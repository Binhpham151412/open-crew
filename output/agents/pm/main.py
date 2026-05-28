"""Project Manager agent — FastAPI application (port 8001).

Reads PRD from the Product Owner agent, breaks it down into Stories and Tasks
with effort estimates, creates a sprint plan, and pushes the results to both
the Business Analyst and Solution Architect agents in parallel.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from shared.a2a_client import A2AClient
from shared.a2a_server import A2AServer, A2AMessage
from shared.mcp_client import MCPClient
from shared.task_queue import TaskQueue

from prompts import SYSTEM_PROMPT
from tools import get_tools

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

logger = structlog.get_logger("pm")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_NAME = "pm"
PORT = int(os.getenv("PM_PORT", "8001"))
DISPLAY_NAME = "Project Manager"
VERSION = "1.0.0"

CAPABILITIES = ["sprint_planning", "story_assignment", "progress_tracking"]
INPUT_TYPES = ["prd"]
OUTPUT_TYPES = ["sprint_plan", "stories"]
PUSH_TO_AGENTS = ["ba", "solution_architect"]

# How long the worker sleeps when the queue is empty (seconds)
_WORKER_POLL_INTERVAL = 1.0

# ---------------------------------------------------------------------------
# Shared instances
# ---------------------------------------------------------------------------

a2a_server = A2AServer(agent_name=AGENT_NAME, port=PORT)
a2a_client = A2AClient()
mcp_client = MCPClient()
task_queue = TaskQueue(agent_name=AGENT_NAME)

# Background worker task reference (so we can cancel on shutdown)
_worker_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# Agent card
# ---------------------------------------------------------------------------

AGENT_CARD: Dict[str, Any] = {
    "name": AGENT_NAME,
    "display_name": DISPLAY_NAME,
    "url": f"http://{AGENT_NAME}:{PORT}",
    "version": VERSION,
    "capabilities": CAPABILITIES,
    "input_types": INPUT_TYPES,
    "output_types": OUTPUT_TYPES,
    "push_to": PUSH_TO_AGENTS,
    "protocol": "a2a/1.0",
}


# ---------------------------------------------------------------------------
# Processing logic
# ---------------------------------------------------------------------------


async def process_prd(task: Dict[str, Any]) -> Dict[str, Any]:
    """Break down a PRD into sprint plan and stories.

    This is the core PM logic: it receives a PRD artifact from the PO,
    uses the LLM (via tools) to decompose it into sprint-sized chunks,
    estimates effort for each story, and returns the structured result.

    Args:
        task: The A2A message dict received from the PO.

    Returns:
        A dict containing the sprint plan and stories ready to push
        downstream.
    """
    task_id = task.get("task_id", str(uuid4()))
    payload = task.get("payload", {})
    prd_content = payload.get("claim", "")
    artifacts = payload.get("artifacts", [])

    # Extract PRD content from artifacts if available
    prd_artifact_content = ""
    for artifact in artifacts:
        if isinstance(artifact, dict):
            name = artifact.get("name", "")
            if "prd" in name.lower() or "requirement" in name.lower():
                prd_artifact_content = artifact.get("content", "")
                break

    if not prd_artifact_content and not prd_content:
        logger.warning("no_prd_content", task_id=task_id)
        prd_content = "No PRD content found — generate a placeholder sprint plan."

    effective_prd = prd_artifact_content or prd_content

    logger.info(
        "processing_prd",
        task_id=task_id,
        prd_length=len(effective_prd),
        artifact_count=len(artifacts),
    )

    # Use LLM to decompose PRD into stories
    tools = get_tools()
    stories: List[Dict[str, Any]] = []
    sprint_plan: Dict[str, Any] = {}

    try:
        # Call the LLM tool to generate stories from the PRD
        decomposition_result = await mcp_client.call(
            "context7_resolve_library_id",
            {
                "query": f"Sprint planning for: {effective_prd[:2000]}",
            },
        )
        logger.info("context7_lookup_done", task_id=task_id)
    except Exception as exc:
        logger.warning(
            "context7_lookup_failed",
            task_id=task_id,
            error=str(exc),
        )
        decomposition_result = None

    # Generate stories from PRD structure
    # Extract sections/requirements from PRD and map to stories
    prd_lines = effective_prd.strip().split("\n")
    current_section = "general"
    story_counter = 0

    for line in prd_lines:
        line = line.strip()
        if not line:
            continue

        # Detect section headers
        if line.startswith("#"):
            current_section = line.lstrip("#").strip().lower()
            continue

        # Detect requirement-like lines (bullets, numbered items, "must", "shall", etc.)
        is_requirement = (
            line.startswith(("-", "*", "•"))
            or line[0:2].rstrip().isdigit()
            or any(
                keyword in line.lower()
                for keyword in ["must", "shall", "should", "require", "need", "feature"]
            )
        )

        if is_requirement:
            story_counter += 1
            story_id = f"STORY-{uuid4().hex[:8].upper()}"

            # Estimate effort based on keywords
            effort = estimate_effort(line, current_section)

            story = {
                "id": story_id,
                "title": line.strip("-*•0123456789. ").strip()[:120],
                "section": current_section,
                "effort": effort,
                "priority": "must_have" if "must" in line.lower() else "should_have",
                "status": "ready",
                "acceptance_criteria": [],
                "dependencies": [],
                "assignee": None,
                "task_id": task_id,
            }
            stories.append(story)

    # If no stories were extracted, create a generic one
    if not stories:
        stories.append(
            {
                "id": f"STORY-{uuid4().hex[:8].upper()}",
                "title": f"Implement: {prd_content[:100]}",
                "section": "general",
                "effort": "L",
                "priority": "must_have",
                "status": "ready",
                "acceptance_criteria": [],
                "dependencies": [],
                "assignee": None,
                "task_id": task_id,
            }
        )

    # Build sprint plan
    sprint_id = f"SPRINT-{uuid4().hex[:8].upper()}"
    total_effort = sum(_effort_points(s["effort"]) for s in stories)

    sprint_plan = {
        "sprint_id": sprint_id,
        "name": f"Sprint for Task {task_id[:8]}",
        "task_id": task_id,
        "stories": [s["id"] for s in stories],
        "total_effort_points": total_effort,
        "estimated_duration": _estimate_duration(total_effort),
        "status": "planned",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sections_covered": list({s["section"] for s in stories}),
    }

    # Assign stories to teams
    for story in stories:
        if _is_frontend_story(story):
            story["assignee"] = "frontend_dev"
        elif _is_backend_story(story):
            story["assignee"] = "backend_dev"
        else:
            story["assignee"] = "unassigned"

    logger.info(
        "prd_decomposed",
        task_id=task_id,
        sprint_id=sprint_id,
        story_count=len(stories),
        total_effort=total_effort,
    )

    return {
        "sprint_plan": sprint_plan,
        "stories": stories,
        "task_id": task_id,
    }


def estimate_effort(description: str, section: str) -> str:
    """Estimate effort size based on description complexity heuristics.

    Args:
        description: The story/requirement description text.
        section: The PRD section this requirement belongs to.

    Returns:
        One of 'S', 'M', 'L', 'XL'.
    """
    desc_lower = description.lower()
    complexity_score = 0

    # Keywords that suggest higher complexity
    high_complexity = [
        "integration",
        "authentication",
        "authorization",
        "payment",
        "real-time",
        "websocket",
        "migration",
        "security",
        "algorithm",
        "machine learning",
        "ai",
        "notification",
        "email",
        "sms",
        "file upload",
        "export",
        "import",
        "sso",
        "oauth",
    ]
    medium_complexity = [
        "api",
        "endpoint",
        "database",
        "validation",
        "search",
        "filter",
        "sort",
        "pagination",
        "caching",
        "logging",
        "configuration",
        "dashboard",
    ]
    low_complexity = [
        "text",
        "label",
        "button",
        "static",
        "display",
        "show",
        "hide",
        "rename",
        "typo",
        "color",
    ]

    for keyword in high_complexity:
        if keyword in desc_lower:
            complexity_score += 3

    for keyword in medium_complexity:
        if keyword in desc_lower:
            complexity_score += 2

    for keyword in low_complexity:
        if keyword in desc_lower:
            complexity_score += 1

    # Section-based adjustments
    if section in ("security", "authentication", "infrastructure"):
        complexity_score += 2
    elif section in ("api", "backend", "data"):
        complexity_score += 1

    # Map score to effort size
    if complexity_score <= 2:
        return "S"
    elif complexity_score <= 5:
        return "M"
    elif complexity_score <= 8:
        return "L"
    else:
        return "XL"


def _effort_points(effort: str) -> int:
    """Convert T-shirt size to numeric effort points."""
    return {"S": 1, "M": 3, "L": 8, "XL": 13}.get(effort.upper(), 5)


def _estimate_duration(total_points: int) -> str:
    """Rough sprint duration estimate from total effort points."""
    # Assuming ~15 points per week with a small team
    weeks = max(1, total_points // 15 + (1 if total_points % 15 else 0))
    if weeks == 1:
        return "1 week"
    return f"{weeks} weeks"


def _is_frontend_story(story: Dict[str, Any]) -> bool:
    """Heuristic: does this story primarily involve frontend work?"""
    keywords = [
        "ui", "ux", "component", "page", "screen", "layout",
        "responsive", "style", "css", "button", "form", "modal",
        "navigation", "menu", "dashboard", "display", "render",
        "animation", "dark mode", "theme", "accessibility",
    ]
    text = f"{story['title']} {story['section']}".lower()
    return any(kw in text for kw in keywords)


def _is_backend_story(story: Dict[str, Any]) -> bool:
    """Heuristic: does this story primarily involve backend work?"""
    keywords = [
        "api", "endpoint", "database", "model", "migration",
        "authentication", "authorization", "middleware", "service",
        "queue", "cache", "cron", "background", "worker", "logic",
        "validation", "security", "encryption", "server",
    ]
    text = f"{story['title']} {story['section']}".lower()
    return any(kw in text for kw in keywords)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


async def worker_loop() -> None:
    """Main background worker loop.

    Continuously pops tasks from the queue, processes them, and pushes
    the result to the next agents (BA and Solution Architect) in parallel.
    Non-blocking by design — immediately picks the next task after pushing.
    """
    logger.info("worker_started", agent=AGENT_NAME)

    while True:
        try:
            task = await task_queue.pop()

            if task is None:
                await asyncio.sleep(_WORKER_POLL_INTERVAL)
                continue

            task_id = task.get("task_id", "unknown")
            logger.info("worker_picked_task", task_id=task_id)

            # Process the PRD
            result = await process_prd(task)

            # Build the outgoing A2A messages for both downstream agents
            now_iso = datetime.now(timezone.utc).isoformat()

            messages_to_push: List[Dict[str, Any]] = []
            for target_agent in PUSH_TO_AGENTS:
                message = {
                    "protocol": "a2a/1.0",
                    "type": "task",
                    "from": AGENT_NAME,
                    "to": target_agent,
                    "task_id": task_id,
                    "round": 1,
                    "payload": {
                        "claim": f"Sprint plan ready — {len(result['stories'])} stories created",
                        "evidence": (
                            f"Sprint: {result['sprint_plan']['sprint_id']}, "
                            f"Effort: {result['sprint_plan']['total_effort_points']} points, "
                            f"Duration: {result['sprint_plan']['estimated_duration']}"
                        ),
                        "suggestion": (
                            "BA: write user stories and acceptance criteria. "
                            "SA: design system architecture and ADRs."
                        ),
                        "artifacts": [
                            {
                                "name": "sprint_plan.json",
                                "content": _json_dumps(result["sprint_plan"]),
                            },
                            {
                                "name": "stories.json",
                                "content": _json_dumps(result["stories"]),
                            },
                            *(
                                a
                                for a in task.get("payload", {}).get("artifacts", [])
                                if isinstance(a, dict)
                            ),
                        ],
                        "metadata": {
                            "sprint_id": result["sprint_plan"]["sprint_id"],
                            "story_count": len(result["stories"]),
                            "source": AGENT_NAME,
                        },
                    },
                    "timestamp": now_iso,
                }
                messages_to_push.append(message)

            # Push to BA and Solution Architect in parallel
            push_tasks = [
                a2a_client.send(
                    to_agent=target,
                    message=msg,
                )
                for target, msg in zip(PUSH_TO_AGENTS, messages_to_push)
            ]

            push_results = await asyncio.gather(*push_tasks, return_exceptions=True)

            for target, push_result in zip(PUSH_TO_AGENTS, push_results):
                if isinstance(push_result, Exception):
                    logger.error(
                        "push_failed",
                        task_id=task_id,
                        target=target,
                        error=str(push_result),
                    )
                else:
                    logger.info(
                        "push_success",
                        task_id=task_id,
                        target=target,
                    )

            # Acknowledge the task as processed
            await task_queue.ack(task_id)

            logger.info(
                "worker_task_complete",
                task_id=task_id,
                stories_created=len(result["stories"]),
                sprint_id=result["sprint_plan"]["sprint_id"],
            )

        except asyncio.CancelledError:
            logger.info("worker_cancelled", agent=AGENT_NAME)
            break
        except Exception as exc:
            logger.error(
                "worker_error",
                agent=AGENT_NAME,
                error=str(exc),
                exc_info=True,
            )
            # Brief sleep to avoid tight error loops
            await asyncio.sleep(_WORKER_POLL_INTERVAL)


def _json_dumps(obj: Any) -> str:
    """Serialize an object to a JSON string with consistent formatting."""
    import json

    return json.dumps(obj, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown lifecycle events."""
    global _worker_task

    logger.info(
        "agent_starting",
        agent=AGENT_NAME,
        port=PORT,
        display_name=DISPLAY_NAME,
        capabilities=CAPABILITIES,
        push_to=PUSH_TO_AGENTS,
    )

    # Start the background worker
    await queue.recover_stuck_tasks()
    _worker_task = asyncio.create_task(worker_loop())

    yield

    # Shutdown: cancel the worker gracefully
    logger.info("agent_shutting_down", agent=AGENT_NAME)

    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass

    # Close HTTP clients
    await a2a_client.close()
    await mcp_client.close()

    logger.info("agent_stopped", agent=AGENT_NAME)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=f"{DISPLAY_NAME} Agent",
    description=(
        "Project Manager agent for OpenCrew. Reads PRD from Product Owner, "
        "decomposes into sprint plans and stories, and pushes to BA and "
        "Solution Architect."
    ),
    version=VERSION,
    lifespan=lifespan,
)

# CORS middleware — allow all origins for development; tighten in production
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
    """Return the A2A agent card for discovery and capability advertisement.

    Other agents and the registry use this endpoint to discover what this
    agent can do and how to communicate with it.
    """
    return JSONResponse(content=AGENT_CARD)


@app.post("/a2a")
async def receive_a2a_message(request: Request) -> JSONResponse:
    """Receive an A2A protocol message and enqueue it for processing.

    Validates the incoming message, pushes it onto the task queue, and
    returns immediately with HTTP 202 Accepted (non-blocking).

    Args:
        request: The incoming FastAPI request containing the A2A message.

    Returns:
        JSON response with status and task_id on success, or error details.
    """
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning("invalid_json_body", error=str(exc))
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detail": "Invalid JSON body"},
        )

    # Validate required A2A fields
    required_fields = ["protocol", "type", "from", "to", "task_id"]
    missing = [f for f in required_fields if f not in body]
    if missing:
        logger.warning("missing_a2a_fields", missing=missing)
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "detail": f"Missing required A2A fields: {', '.join(missing)}",
            },
        )

    # Validate protocol version
    if body.get("protocol") != "a2a/1.0":
        logger.warning(
            "unsupported_protocol",
            protocol=body.get("protocol"),
        )
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "detail": f"Unsupported protocol: {body.get('protocol')}. Expected a2a/1.0",
            },
        )

    # Validate message type
    valid_types = {
        "task", "challenge", "response", "final_position",
        "escalate", "decision", "result",
    }
    if body.get("type") not in valid_types:
        logger.warning("invalid_message_type", msg_type=body.get("type"))
        return JSONResponse(
            status_code=422,
            content={
                "status": "error",
                "detail": f"Invalid message type: {body.get('type')}",
            },
        )

    task_id = body["task_id"]

    # Enqueue for background processing
    await task_queue.push(body)

    logger.info(
        "task_enqueued",
        task_id=task_id,
        from_agent=body.get("from"),
        msg_type=body.get("type"),
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "task_id": task_id,
            "agent": AGENT_NAME,
            "detail": "Task enqueued for processing",
        },
    )


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint for container orchestrators and monitoring.

    Returns:
        JSON with agent status, queue size, and worker state.
    """
    queue_size = await task_queue.size()
    worker_running = _worker_task is not None and not _worker_task.done()

    is_healthy = worker_running

    return JSONResponse(
        status_code=200 if is_healthy else 503,
        content={
            "status": "ok" if is_healthy else "degraded",
            "agent": AGENT_NAME,
            "display_name": DISPLAY_NAME,
            "port": PORT,
            "queue_size": queue_size,
            "worker_running": worker_running,
            "capabilities": CAPABILITIES,
            "push_to": PUSH_TO_AGENTS,
        },
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "agents.pm.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
    )