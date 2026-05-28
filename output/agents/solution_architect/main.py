"""Solution Architect Agent — FastAPI server (port 8003).

Handles system design, Architecture Decision Records (ADRs), database
schema design, and interface contracts.  Receives PRDs and Stories from
PM, produces architecture artifacts, and pushes results to Backend Dev
and DevOps via the A2A protocol.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------
from shared.a2a_server import A2AServer
from shared.mcp_client import MCPClient
from shared.task_queue import TaskQueue

# ---------------------------------------------------------------------------
# Local modules
# ---------------------------------------------------------------------------
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
        min_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("solution_architect")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_NAME = "solution_architect"
DISPLAY_NAME = "Solution Architect"
PORT = int(os.getenv("SOLUTION_ARCHITECT_PORT", "8003"))
VERSION = "1.0.0"

CAPABILITIES: list[str] = ["system_design", "adr", "db_schema", "interface_design"]
INPUT_TYPES: list[str] = ["prd", "story"]
OUTPUT_TYPES: list[str] = ["adr", "system_diagram", "db_schema"]
PUSH_TO_AGENTS: list[str] = ["backend_dev", "devops"]

# Worker polling interval (seconds) when the queue is empty
_WORKER_POLL_INTERVAL = float(os.getenv("WORKER_POLL_INTERVAL", "1.0"))
# Maximum processing time per task before giving up (seconds)
_TASK_TIMEOUT = float(os.getenv("TASK_TIMEOUT", "600"))

# ---------------------------------------------------------------------------
# Instantiate shared components
# ---------------------------------------------------------------------------

a2a = A2AServer(agent_name=AGENT_NAME, port=PORT)
mcp = MCPClient()
queue = TaskQueue(agent_name=AGENT_NAME)

# ---------------------------------------------------------------------------
# Background worker state
# ---------------------------------------------------------------------------

_worker_task: Optional[asyncio.Task] = None
_shutdown_event = asyncio.Event()


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

def _build_agent_card() -> Dict[str, Any]:
    """Return the A2A agent descriptor card."""
    return {
        "name": AGENT_NAME,
        "display_name": DISPLAY_NAME,
        "url": f"http://{AGENT_NAME}:{PORT}",
        "version": VERSION,
        "capabilities": CAPABILITIES,
        "input_types": INPUT_TYPES,
        "output_types": OUTPUT_TYPES,
        "protocol": "a2a/1.0",
    }


# ---------------------------------------------------------------------------
# Processing helpers
# ---------------------------------------------------------------------------

async def _call_llm(prompt: str, system_prompt: str) -> str:
    """Call the LLM (MiMo) via MCP or direct HTTP to generate architecture artifacts.

    This tries the ``context7`` tool first for library/pattern lookups that
    inform the architecture decisions, then uses the MiMo API for synthesis.

    Args:
        prompt: The user-facing prompt describing the work to do.
        system_prompt: The system prompt for the LLM.

    Returns:
        The LLM response text.
    """
    import httpx

    api_key = os.getenv("MIMO_API_KEY", "")
    base_url = os.getenv("MIMO_BASE_URL", "https://api.xiaomi.com/v1")
    model = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")

    if not api_key:
        logger.warning("mimo_api_key_missing", msg="MIMO_API_KEY not set — using mock response")
        return "[MOCK] Architecture design output — MIMO_API_KEY not configured."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 8192,
    }

    async with httpx.AsyncClient(timeout=_TASK_TIMEOUT) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _extract_artifacts(llm_output: str) -> List[Dict[str, str]]:
    """Parse the LLM output into structured artifacts.

    The LLM is instructed to return sections delimited by markers like
    ``### FILE: <path>``.  This function splits on those markers and
    returns a list of ``{"name": path, "content": body}`` dicts.

    Args:
        llm_output: Raw text returned by the LLM.

    Returns:
        List of artifact dicts with ``name`` and ``content`` keys.
    """
    artifacts: List[Dict[str, str]] = []
    sections = llm_output.split("### FILE:")
    for section in sections[1:]:
        lines = section.strip().split("\n", 1)
        if len(lines) >= 2:
            name = lines[0].strip()
            content = lines[1].strip()
            artifacts.append({"name": name, "content": content})
        elif lines:
            # Single-line section — treat entire remainder as content
            artifacts.append({"name": "artifact.md", "content": lines[0].strip()})

    # If no structured sections found, treat the entire output as one artifact
    if not artifacts:
        artifacts.append({"name": "architecture_output.md", "content": llm_output})

    return artifacts


def _collect_input_artifacts(task_message: Dict[str, Any]) -> str:
    """Build a context string from the incoming message payload and artifacts.

    Args:
        task_message: The full A2A message dict.

    Returns:
        A formatted string with all relevant context for the LLM.
    """
    payload = task_message.get("payload", {})
    parts: List[str] = []

    claim = payload.get("claim", "")
    if claim:
        parts.append(f"## Task\n{claim}")

    evidence = payload.get("evidence", "")
    if evidence:
        parts.append(f"## Evidence / Context\n{evidence}")

    suggestion = payload.get("suggestion", "")
    if suggestion:
        parts.append(f"## Suggestion\n{suggestion}")

    artifacts = payload.get("artifacts", [])
    for art in artifacts:
        name = art.get("name", "unknown")
        content = art.get("content", "")
        parts.append(f"## Artifact: {name}\n```\n{content}\n```")

    metadata = payload.get("metadata", {})
    if metadata:
        parts.append(f"## Metadata\n```json\n{json.dumps(metadata, indent=2)}\n```")

    return "\n\n".join(parts) if parts else "(no input provided)"


def _determine_next_agents(task_message: Dict[str, Any]) -> List[str]:
    """Decide which downstream agents should receive the result.

    The Solution Architect pushes to both ``backend_dev`` and ``devops``
    by default.  If the task metadata suggests a specific routing, it
    can be overridden.

    Args:
        task_message: The incoming A2A message.

    Returns:
        List of agent names to push to.
    """
    metadata = task_message.get("payload", {}).get("metadata", {})
    override = metadata.get("push_to")
    if override and isinstance(override, list):
        return [a for a in override if a in PUSH_TO_AGENTS]
    return list(PUSH_TO_AGENTS)


# ---------------------------------------------------------------------------
# Core task processor
# ---------------------------------------------------------------------------

async def _process_task(task_message: Dict[str, Any]) -> Dict[str, Any]:
    """Run the Solution Architect pipeline on a single task.

    Steps:
        1. Extract context from the incoming A2A message.
        2. Look up relevant architecture patterns via context7 (MCP).
        3. Call the LLM with the system prompt and assembled context.
        4. Parse the LLM output into structured artifacts.
        5. Build the result A2A message.

    Args:
        task_message: Validated A2A message dict.

    Returns:
        A2A result message dict ready to be pushed downstream.
    """
    task_id = task_message.get("task_id", str(uuid4()))
    sender = task_message.get("from", "unknown")

    log = logger.bind(task_id=task_id, sender=sender)
    log.info("task_processing_start")

    start_time = time.monotonic()

    try:
        # -- 1. Assemble context ------------------------------------------
        context = _collect_input_artifacts(task_message)
        log.info("context_assembled", context_length=len(context))

        # -- 2. MCP enrichment: fetch architecture patterns ----------------
        enrichment_notes = ""
        try:
            mcp_result = await mcp.call(
                "context7_resolve_library_id",
                {"libraryName": "fastapi"},
            )
            if mcp_result:
                lib_id = mcp_result.get("libraryId") or mcp_result.get("id", "")
                if lib_id:
                    docs = await mcp.call(
                        "context7_get_library_docs",
                        {"libraryId": lib_id, "topic": "architecture patterns"},
                    )
                    if docs:
                        enrichment_notes = f"\n\n## Reference: FastAPI Architecture Patterns\n{docs}"
                        log.info("mcp_enrichment_success", lib=lib_id)
        except Exception as exc:
            log.warning("mcp_enrichment_failed", error=str(exc))

        # -- 3. Call LLM --------------------------------------------------
        full_prompt = (
            f"You are the Solution Architect for the OpenCrew project.\n\n"
            f"{context}{enrichment_notes}\n\n"
            f"Please produce the following outputs:\n"
            f"1. **Architecture Decision Records (ADR)** — one per major decision.\n"
            f"2. **System Diagram** — Mermaid diagram showing service interactions.\n"
            f"3. **Database Schema** — SQL DDL for all entities.\n"
            f"4. **Interface Contracts** — API interfaces between services.\n\n"
            f"For each output, use the format:\n"
            f"### FILE: <path/to/file>\n<content>\n"
        )

        llm_output = await _call_llm(full_prompt, SYSTEM_PROMPT)
        log.info("llm_call_completed", output_length=len(llm_output))

        # -- 4. Parse artifacts -------------------------------------------
        artifacts = _extract_artifacts(llm_output)
        log.info("artifacts_extracted", count=len(artifacts))

        elapsed = time.monotonic() - start_time
        log.info("task_processing_done", elapsed_seconds=round(elapsed, 2))

        # -- 5. Build result message --------------------------------------
        result_message = {
            "protocol": "a2a/1.0",
            "type": "result",
            "from": AGENT_NAME,
            "to": sender,
            "task_id": task_id,
            "round": task_message.get("round", 1),
            "payload": {
                "claim": f"Solution architecture artifacts produced for task {task_id}",
                "evidence": f"Processed in {elapsed:.1f}s. {len(artifacts)} artifact(s) generated.",
                "suggestion": "Review ADR, system diagram, DB schema, and interface contracts.",
                "artifacts": artifacts,
                "metadata": {
                    "agent": AGENT_NAME,
                    "elapsed_seconds": round(elapsed, 2),
                    "artifact_count": len(artifacts),
                },
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return result_message

    except Exception as exc:
        elapsed = time.monotonic() - start_time
        log.error(
            "task_processing_failed",
            error=str(exc),
            elapsed_seconds=round(elapsed, 2),
            exc_info=True,
        )
        # Return an error result so downstream agents know something went wrong
        return {
            "protocol": "a2a/1.0",
            "type": "result",
            "from": AGENT_NAME,
            "to": sender,
            "task_id": task_id,
            "round": task_message.get("round", 1),
            "payload": {
                "claim": f"Solution architecture processing FAILED for task {task_id}",
                "evidence": f"Error after {elapsed:.1f}s: {exc}",
                "suggestion": "Investigate the error and retry or escalate to TechLead.",
                "artifacts": [],
                "metadata": {
                    "agent": AGENT_NAME,
                    "error": str(exc),
                    "elapsed_seconds": round(elapsed, 2),
                },
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

async def _worker_loop() -> None:
    """Continuously pop tasks from the queue, process them, and push results.

    Follows the OpenCrew async rule: after pushing the result to downstream
    agents, immediately pick the next task — no idle waiting.
    """
    logger.info("worker_started", agent=AGENT_NAME)

    while not _shutdown_event.is_set():
        try:
            task = await queue.pop()
            if task is None:
                # Nothing in queue — brief sleep then retry
                try:
                    await asyncio.wait_for(
                        _shutdown_event.wait(),
                        timeout=_WORKER_POLL_INTERVAL,
                    )
                except asyncio.TimeoutError:
                    pass
                continue

            task_id = task.get("task_id", "unknown")
            log = logger.bind(task_id=task_id)
            log.info("worker_picked_task")

            # Process the task (with timeout)
            try:
                result = await asyncio.wait_for(
                    _process_task(task),
                    timeout=_TASK_TIMEOUT,
                )
            except asyncio.TimeoutError:
                log.error("task_timeout", timeout=_TASK_TIMEOUT)
                result = {
                    "protocol": "a2a/1.0",
                    "type": "result",
                    "from": AGENT_NAME,
                    "to": task.get("from", "unknown"),
                    "task_id": task_id,
                    "round": task.get("round", 1),
                    "payload": {
                        "claim": f"Task {task_id} timed out after {_TASK_TIMEOUT}s",
                        "evidence": "Processing exceeded maximum allowed time.",
                        "suggestion": "Escalate to TechLead.",
                        "artifacts": [],
                        "metadata": {"agent": AGENT_NAME, "error": "timeout"},
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

            # Push result to each downstream agent
            next_agents = _determine_next_agents(task)
            for agent in next_agents:
                try:
                    # Override the "to" field for each recipient
                    push_msg = {**result, "to": agent}
                    await a2a.push(to=agent, message=push_msg)
                    log.info("result_pushed", target=agent)
                except Exception as push_exc:
                    log.error("push_failed", target=agent, error=str(push_exc))

            # Acknowledge the task in the queue
            try:
                await queue.ack(task_id)
            except Exception:
                pass  # ack is best-effort for in-memory queue

            log.info("worker_task_complete", targets=next_agents)

        except asyncio.CancelledError:
            logger.info("worker_cancelled")
            break
        except Exception as exc:
            logger.error("worker_unhandled_error", error=str(exc), exc_info=True)
            # Brief backoff to prevent tight error loops
            await asyncio.sleep(2.0)

    logger.info("worker_stopped")


# ---------------------------------------------------------------------------
# FastAPI lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Manage startup/shutdown of the background worker and shared resources."""
    global _worker_task

    logger.info(
        "agent_starting",
        agent=AGENT_NAME,
        port=PORT,
        capabilities=CAPABILITIES,
    )

    # Start the background worker
    await queue.recover_stuck_tasks()
    _worker_task = asyncio.create_task(_worker_loop(), name=f"{AGENT_NAME}-worker")

    yield

    # Shutdown
    logger.info("agent_shutting_down", agent=AGENT_NAME)
    _shutdown_event.set()

    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass

    # Close MCP client
    try:
        await mcp.close()
    except Exception:
        pass

    logger.info("agent_stopped", agent=AGENT_NAME)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=f"{DISPLAY_NAME} Agent",
    description=(
        "Solution Architect agent for the OpenCrew system. "
        "Produces architecture decision records, system diagrams, "
        "database schemas, and interface contracts."
    ),
    version=VERSION,
    lifespan=_lifespan,
)

# CORS — allow all origins for development; tighten in production
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
    """Return the A2A agent descriptor card.

    Other agents and the registry discover this agent by fetching
    ``/.well-known/agent.json``.
    """
    return JSONResponse(content=_build_agent_card())


@app.post("/a2a")
async def receive_a2a_message(request: Request) -> JSONResponse:
    """Receive an A2A protocol message and enqueue it for processing.

    The message is validated, pushed onto the local task queue, and an
    immediate ``202 Accepted`` is returned so the sender is not blocked.
    The background worker will pick up and process the task asynchronously.
    """
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning("invalid_json_body", error=str(exc))
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid JSON body", "detail": str(exc)},
        )

    # Basic validation
    task_id = body.get("task_id")
    if not task_id:
        task_id = str(uuid4())
        body["task_id"] = task_id

    protocol = body.get("protocol")
    if protocol != "a2a/1.0":
        logger.warning("unsupported_protocol", protocol=protocol, task_id=task_id)
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Unsupported protocol: {protocol!r}",
                "expected": "a2a/1.0",
            },
        )

    msg_type = body.get("type")
    if msg_type not in {"task", "challenge", "result"}:
        # We accept task, challenge, and result messages
        # Other types (response, escalate, decision) are handled differently
        if msg_type not in {"task", "challenge"}:
            logger.info("message_type_info", type=msg_type, task_id=task_id)

    # Push to the async queue
    await queue.push(body)
    queue_size = await queue.size()

    logger.info(
        "task_enqueued",
        task_id=task_id,
        msg_type=msg_type,
        sender=body.get("from", "unknown"),
        queue_size=queue_size,
    )

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "task_id": task_id,
            "agent": AGENT_NAME,
            "queue_size": queue_size,
        },
    )


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health-check endpoint for monitoring and docker-compose healthcheck.

    Returns agent status, queue depth, and uptime information.
    """
    try:
        queue_size = await queue.size()
    except Exception:
        queue_size = -1

    worker_status = "running" if (_worker_task and not _worker_task.done()) else "stopped"

    return JSONResponse(
        content={
            "status": "ok",
            "agent": AGENT_NAME,
            "display_name": DISPLAY_NAME,
            "port": PORT,
            "version": VERSION,
            "capabilities": CAPABILITIES,
            "queue_size": queue_size,
            "worker": worker_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "agents.solution_architect.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=os.getenv("RELOAD", "false").lower() == "true",
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )