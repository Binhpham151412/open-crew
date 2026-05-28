"""Business Analyst Agent — FastAPI main entry point (port 8002).

The BA agent reads Stories from PM, writes User Stories with Acceptance
Criteria, API contracts (OpenAPI YAML), and data models (ERD).  Results
are pushed asynchronously to Frontend and Backend developers.

Endpoints:
    GET  /.well-known/agent.json  — A2A agent card
    POST /a2a                     — Receive an A2A message (enqueued for background processing)
    GET  /health                  — Liveness / readiness probe
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import signal
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
import uvicorn
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Path setup — allow importing shared package from project root
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from shared.a2a_server import A2AServer
from shared.mcp_client import MCPClient
from shared.task_queue import TaskQueue

from .prompts import SYSTEM_PROMPT
from .tools import get_tools

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        int(os.getenv("LOG_LEVEL", "20"))  # 20 = INFO
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger("ba")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AGENT_NAME = "ba"
DISPLAY_NAME = "Business Analyst"
PORT = int(os.getenv("BA_PORT", "8002"))
VERSION = "1.0.0"

CAPABILITIES: list[str] = [
    "write_user_stories",
    "api_contract",
    "data_model",
    "acceptance_criteria",
]
INPUT_TYPES: list[str] = ["story"]
OUTPUT_TYPES: list[str] = ["user_stories", "api_spec", "data_model"]
PUSH_TO_AGENTS: list[str] = ["frontend_dev", "backend_dev"]

# ---------------------------------------------------------------------------
# Instantiate shared services
# ---------------------------------------------------------------------------
a2a = A2AServer(agent_name=AGENT_NAME, port=PORT)
mcp = MCPClient()
queue = TaskQueue(agent_name=AGENT_NAME)
tools = get_tools(mcp)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title=f"{DISPLAY_NAME} Agent",
    version=VERSION,
    docs_url="/docs",
    redoc_url=None,
)

# CORS — allow all origins for inter-container communication and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    """Return the A2A agent card describing this agent's capabilities."""
    return JSONResponse(
        content={
            "name": AGENT_NAME,
            "display_name": DISPLAY_NAME,
            "url": f"http://{AGENT_NAME}:{PORT}",
            "version": VERSION,
            "capabilities": CAPABILITIES,
            "input_types": INPUT_TYPES,
            "output_types": OUTPUT_TYPES,
            "protocol": "a2a/1.0",
        }
    )


@app.post("/a2a")
async def receive_a2a(request: Request) -> JSONResponse:
    """Accept an incoming A2A message and enqueue it for async processing.

    Returns 202 Accepted immediately; the background worker will pick up the
    task and process it asynchronously.
    """
    try:
        body = await request.json()
    except Exception as exc:
        log.error("a2a.invalid_json", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Invalid JSON body"},
        )

    task_id = body.get("task_id", "unknown")
    sender = body.get("from", "unknown")

    log.info(
        "a2a.message_received",
        task_id=task_id,
        from_agent=sender,
        msg_type=body.get("type"),
    )

    try:
        await queue.push(body)
    except Exception as exc:
        log.error("a2a.enqueue_failed", task_id=task_id, error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Failed to enqueue task"},
        )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"status": "accepted", "task_id": task_id},
    )


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness and readiness probe."""
    queue_size = 0
    try:
        queue_size = queue.size()
    except Exception:
        pass

    return JSONResponse(
        content={
            "status": "ok",
            "agent": AGENT_NAME,
            "display_name": DISPLAY_NAME,
            "port": PORT,
            "queue_size": queue_size,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# Background worker — core BA processing logic
# ---------------------------------------------------------------------------


async def _process_story(task: Dict[str, Any]) -> Dict[str, Any]:
    """Process a story task from PM and produce BA deliverables.

    This function orchestrates the LLM call via the A2A server's LLM
    integration (or a direct call) and uses MCP tools (context7, linear)
    as needed.

    Returns the result A2A message dict to be pushed to downstream agents.
    """
    task_id = task.get("task_id", "unknown")
    payload = task.get("payload", {})
    story_description = payload.get("claim", "")
    artifacts = payload.get("artifacts", [])
    metadata = payload.get("metadata", {})

    log.info(
        "ba.processing_story",
        task_id=task_id,
        story_description=story_description[:200],
    )

    # ------------------------------------------------------------------
    # Step 1 — Gather context from artifacts (PRD, sprint info, etc.)
    # ------------------------------------------------------------------
    prd_context = ""
    sprint_info = ""
    for artifact in artifacts:
        artifact_name = artifact.get("name", "")
        artifact_content = artifact.get("content", "")
        if "prd" in artifact_name.lower():
            prd_context = artifact_content
        elif "sprint" in artifact_name.lower() or "story" in artifact_name.lower():
            sprint_info = artifact_content

    # ------------------------------------------------------------------
    # Step 2 — Look up domain context via context7 MCP (if available)
    # ------------------------------------------------------------------
    domain_context = ""
    try:
        context_result = await mcp.call(
            "context7_resolve_library_id",
            {"query": story_description[:200]},
        )
        if context_result:
            domain_context = json.dumps(context_result)
            log.info("ba.context7_resolved", task_id=task_id, length=len(domain_context))
    except Exception as exc:
        log.warning("ba.context7_failed", task_id=task_id, error=str(exc))

    # ------------------------------------------------------------------
    # Step 3 — Generate BA deliverables using LLM
    # ------------------------------------------------------------------
    from shared.a2a_server import A2AServer as _A2AServer

    prompt_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"## Story\n{story_description}\n\n"
                f"## PRD Context\n{prd_context}\n\n"
                f"## Sprint Info\n{sprint_info}\n\n"
                f"## Domain Context\n{domain_context}\n\n"
                "Please produce the following deliverables:\n"
                "1. **User Stories** (As a [role], I want [goal], so that [benefit])\n"
                "2. **Acceptance Criteria** (Gherkin format: Given/When/Then)\n"
                "3. **API Contract** (OpenAPI YAML — endpoints, request/response schemas, error codes)\n"
                "4. **Data Model** (entities, relationships, constraints)\n\n"
                "Return your response as a single JSON object with keys: "
                "user_stories, acceptance_criteria, api_spec, data_model. "
                "Each value should be a string containing the formatted content."
            ),
        },
    ]

    # Call LLM via the A2A server helper or direct HTTP
    llm_response_text = await _call_llm(prompt_messages)

    # ------------------------------------------------------------------
    # Step 4 — Parse LLM response into structured deliverables
    # ------------------------------------------------------------------
    deliverables = _parse_deliverables(llm_response_text, task_id)

    user_stories = deliverables.get("user_stories", "")
    acceptance_criteria = deliverables.get("acceptance_criteria", "")
    api_spec = deliverables.get("api_spec", "")
    data_model = deliverables.get("data_model", "")

    # ------------------------------------------------------------------
    # Step 5 — Update story on Linear (best-effort)
    # ------------------------------------------------------------------
    story_id = metadata.get("story_id") or metadata.get("linear_story_id")
    if story_id:
        try:
            update_content = (
                f"## User Stories\n{user_stories}\n\n"
                f"## Acceptance Criteria\n{acceptance_criteria}"
            )
            await mcp.call(
                "linear_update_story",
                {
                    "story_id": story_id,
                    "description": update_content,
                },
            )
            log.info("ba.linear_updated", task_id=task_id, story_id=story_id)
        except Exception as exc:
            log.warning("ba.linear_update_failed", task_id=task_id, error=str(exc))

    # ------------------------------------------------------------------
    # Step 6 — Build result artifacts
    # ------------------------------------------------------------------
    result_artifacts = [
        {"name": "user_stories.md", "content": user_stories},
        {"name": "acceptance_criteria.md", "content": acceptance_criteria},
        {"name": "api_spec.yaml", "content": api_spec},
        {"name": "data_model.md", "content": data_model},
    ]

    # ------------------------------------------------------------------
    # Step 7 — Build A2A result messages for downstream agents
    # ------------------------------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()

    result_messages: List[Dict[str, Any]] = []

    for target_agent in PUSH_TO_AGENTS:
        # Frontend dev needs user stories + API contract (no data model typically)
        # Backend dev needs everything
        if target_agent == "frontend_dev":
            target_artifacts = [
                {"name": "user_stories.md", "content": user_stories},
                {"name": "acceptance_criteria.md", "content": acceptance_criteria},
                {"name": "api_spec.yaml", "content": api_spec},
            ]
        else:
            target_artifacts = result_artifacts

        result_msg = {
            "protocol": "a2a/1.0",
            "type": "task",
            "from": AGENT_NAME,
            "to": target_agent,
            "task_id": task_id,
            "round": 1,
            "payload": {
                "claim": f"BA deliverables for story: {story_description[:120]}",
                "evidence": (
                    "User stories, acceptance criteria, API contract, "
                    "and data model produced by Business Analyst."
                ),
                "suggestion": (
                    f"Implement the story using the provided API contract "
                    f"and data model. Follow acceptance criteria for validation."
                ),
                "artifacts": target_artifacts,
                "metadata": {
                    **metadata,
                    "ba_processed_at": now_iso,
                    "source_story": story_description[:500],
                },
            },
            "timestamp": now_iso,
        }
        result_messages.append(result_msg)

    log.info(
        "ba.story_processed",
        task_id=task_id,
        downstream_agents=PUSH_TO_AGENTS,
        user_stories_length=len(user_stories),
        api_spec_length=len(api_spec),
    )

    return {
        "result_messages": result_messages,
        "task_id": task_id,
    }


async def _call_llm(messages: List[Dict[str, str]]) -> str:
    """Call the LLM (MiMo) to generate BA deliverables.

    Uses the MiMo API via environment variables. Falls back to a structured
    placeholder if the API is unavailable.
    """
    import httpx

    api_key = os.getenv("MIMO_API_KEY", "")
    base_url = os.getenv("MIMO_BASE_URL", "https://api.xiaomi.com/v1")
    model = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")

    if not api_key:
        log.warning("ba.llm.no_api_key", msg="MIMO_API_KEY not set, using fallback generation")
        return _fallback_generate(messages)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 8192,
                },
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            log.info("ba.llm.success", model=model, tokens_used=data.get("usage", {}).get("total_tokens", 0))
            return content
    except Exception as exc:
        log.error("ba.llm.failed", error=str(exc))
        return _fallback_generate(messages)


def _fallback_generate(messages: List[Dict[str, str]]) -> str:
    """Produce a structured fallback response when LLM is unavailable.

    Extracts the story description from the user message and generates
    template deliverables.
    """
    # Extract story from user message
    user_msg = messages[-1]["content"] if len(messages) > 1 else ""
    story_line = ""
    for line in user_msg.split("\n"):
        if line.strip() and "## Story" in user_msg:
            story_section = user_msg.split("## Story")[1].split("##")[0].strip()
            story_line = story_section[:200]
            break
    if not story_line:
        story_line = "the requested feature"

    return json.dumps(
        {
            "user_stories": (
                "## User Stories\n\n"
                f"### US-001\n"
                f"As a user, I want to {story_line}, "
                f"so that I can accomplish my goals efficiently.\n\n"
                f"### US-002\n"
                "As an admin, I want to manage and monitor this feature, "
                "so that I can ensure system reliability.\n"
            ),
            "acceptance_criteria": (
                "## Acceptance Criteria\n\n"
                "### AC-001: Happy path\n"
                f"**Given** a registered user\n"
                f"**When** they interact with the feature: {story_line}\n"
                f"**Then** the system responds with a success result\n\n"
                "### AC-002: Validation\n"
                "**Given** invalid input data\n"
                "**When** the user submits the request\n"
                "**Then** the system returns a 400 error with descriptive message\n\n"
                "### AC-003: Unauthorized access\n"
                "**Given** an unauthenticated request\n"
                "**When** the endpoint is accessed\n"
                "**Then** the system returns 401 Unauthorized\n"
            ),
            "api_spec": (
                "openapi: 3.0.3\n"
                "info:\n"
                f"  title: {story_line[:60]}\n"
                "  version: 1.0.0\n"
                "paths:\n"
                "  /api/v1/resource:\n"
                "    post:\n"
                "      summary: Create resource\n"
                "      requestBody:\n"
                "        required: true\n"
                "        content:\n"
                "          application/json:\n"
                "            schema:\n"
                "              type: object\n"
                "              properties:\n"
                "                name:\n"
                "                  type: string\n"
                "      responses:\n"
                "        '201':\n"
                "          description: Created\n"
                "        '400':\n"
                "          description: Validation error\n"
                "        '401':\n"
                "          description: Unauthorized\n"
            ),
            "data_model": (
                "## Data Model\n\n"
                "### Entity: Resource\n"
                "| Field | Type | Constraints |\n"
                "|-------|------|-------------|\n"
                "| id | UUID | PK, auto-generated |\n"
                "| name | VARCHAR(255) | NOT NULL |\n"
                "| created_at | TIMESTAMP | NOT NULL, default NOW() |\n"
                "| updated_at | TIMESTAMP | NOT NULL, on update NOW() |\n\n"
                "### Relations\n"
                "- Resource belongs to User (user_id FK)\n"
            ),
        },
        indent=2,
    )


def _parse_deliverables(llm_response: str, task_id: str) -> Dict[str, str]:
    """Parse LLM response into structured deliverables dict.

    Attempts JSON parsing first, then falls back to section-based extraction.
    """
    # Try JSON parse
    try:
        parsed = json.loads(llm_response)
        if isinstance(parsed, dict):
            return {
                "user_stories": parsed.get("user_stories", ""),
                "acceptance_criteria": parsed.get("acceptance_criteria", ""),
                "api_spec": parsed.get("api_spec", ""),
                "data_model": parsed.get("data_model", ""),
            }
    except (json.JSONDecodeError, TypeError):
        pass

    # Try extracting JSON from markdown code block
    import re
    json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", llm_response, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            if isinstance(parsed, dict):
                return {
                    "user_stories": parsed.get("user_stories", ""),
                    "acceptance_criteria": parsed.get("acceptance_criteria", ""),
                    "api_spec": parsed.get("api_spec", ""),
                    "data_model": parsed.get("data_model", ""),
                }
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: section-based extraction
    sections = {
        "user_stories": "",
        "acceptance_criteria": "",
        "api_spec": "",
        "data_model": "",
    }

    section_markers = {
        "user_stories": ["user stories", "user story", "## user stories"],
        "acceptance_criteria": ["acceptance criteria", "## acceptance criteria"],
        "api_spec": ["api contract", "api spec", "openapi", "## api"],
        "data_model": ["data model", "erd", "## data model"],
    }

    text_lower = llm_response.lower()
    for key, markers in section_markers.items():
        for marker in markers:
            idx = text_lower.find(marker)
            if idx != -1:
                # Find the next section header or end of text
                rest = llm_response[idx:]
                next_section = len(rest)
                for other_key, other_markers in section_markers.items():
                    if other_key == key:
                        continue
                    for other_marker in other_markers:
                        other_idx = rest.lower().find(other_marker, len(marker))
                        if other_idx != -1 and other_idx < next_section:
                            next_section = other_idx
                sections[key] = rest[:next_section].strip()
                break

    # If nothing was parsed, use the entire response as user stories
    if not any(sections.values()):
        sections["user_stories"] = llm_response

    log.warning(
        "ba.deliverables.json_parse_failed",
        task_id=task_id,
        extracted_sections=[k for k, v in sections.items() if v],
    )

    return sections


async def _push_results(result: Dict[str, Any]) -> None:
    """Push result messages to downstream agents via A2A protocol."""
    result_messages = result.get("result_messages", [])
    task_id = result.get("task_id", "unknown")

    for msg in result_messages:
        target = msg.get("to", "unknown")
        try:
            await a2a.push(to=target, message=msg)
            log.info(
                "ba.pushed_result",
                task_id=task_id,
                target_agent=target,
                artifacts_count=len(msg.get("payload", {}).get("artifacts", [])),
            )
        except Exception as exc:
            log.error(
                "ba.push_failed",
                task_id=task_id,
                target_agent=target,
                error=str(exc),
            )


async def worker() -> None:
    """Background worker loop.

    Continuously pops tasks from the queue, processes them through the BA
    pipeline, and pushes results to downstream agents.  After pushing, the
    worker immediately picks the next task — no idle waiting.
    """
    log.info("ba.worker_started", agent=AGENT_NAME)

    while True:
        try:
            task = await queue.pop()
            if task is None:
                # Nothing in queue — brief sleep to avoid tight-loop CPU spin
                await asyncio.sleep(0.5)
                continue

            task_id = task.get("task_id", "unknown")
            log.info("ba.worker.picked_task", task_id=task_id)

            # Process the story
            result = await _process_story(task)

            # Push to downstream agents (frontend_dev, backend_dev)
            await _push_results(result)

            # Acknowledge task completion in queue
            try:
                await queue.ack(task_id)
            except AttributeError:
                # In-memory queue may not have ack — that's OK
                pass

            log.info("ba.worker.task_completed", task_id=task_id)

        except asyncio.CancelledError:
            log.info("ba.worker.cancelled")
            break
        except Exception as exc:
            log.error(
                "ba.worker.error",
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            # Brief backoff on error before retrying
            await asyncio.sleep(2.0)


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------

_background_task: Optional[asyncio.Task] = None


@app.on_event("startup")
async def on_startup() -> None:
    """Start the background worker task on application startup."""
    global _background_task
    log.info(
        "ba.startup",
        agent=AGENT_NAME,
        display_name=DISPLAY_NAME,
        port=PORT,
        capabilities=CAPABILITIES,
        push_to=PUSH_TO_AGENTS,
    )
    await queue.recover_stuck_tasks()
    _background_task = asyncio.create_task(worker())
    log.info("ba.background_worker_spawned")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Gracefully cancel the background worker on shutdown."""
    global _background_task
    log.info("ba.shutdown", agent=AGENT_NAME)
    if _background_task is not None:
        _background_task.cancel()
        try:
            await _background_task
        except asyncio.CancelledError:
            pass
        _background_task = None
        log.info("ba.background_worker_stopped")

    # Close MCP client HTTP session
    try:
        await mcp.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "agents.ba.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=os.getenv("RELOAD", "false").lower() == "true",
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
        access_log=True,
    )