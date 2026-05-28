"""Backend Developer Agent — FastAPI main.py (port 8005).

Implements the Backend Developer agent for the OpenCrew pipeline.
Receives API specs, DB schemas, and user stories via A2A protocol,
generates FastAPI implementation code, and pushes results to the
Security Reviewer for review.

Endpoints:
    GET  /.well-known/agent.json  — Agent card (A2A discovery)
    POST /a2a                     — Receive A2A messages
    GET  /health                  — Health check
"""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
import logging
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.a2a_server import A2AServer
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
        min_level=logging.INFO
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("backend_dev")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_NAME = "backend_dev"
AGENT_DISPLAY_NAME = "Backend Developer"
AGENT_PORT = int(os.environ.get("BACKEND_DEV_PORT", "8005"))
MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
MIMO_BASE_URL = os.environ.get("MIMO_BASE_URL", "https://api.xiaomi.com/v1")
MIMO_MODEL = os.environ.get("MIMO_MODEL", "mimo-v2.5-pro")
PUSH_TO_AGENTS = ["security_reviewer"]

# ---------------------------------------------------------------------------
# Shared services
# ---------------------------------------------------------------------------

a2a_server = A2AServer(agent_name=AGENT_NAME, port=AGENT_PORT)
mcp_client = MCPClient(timeout=120.0, max_retries=2)
task_queue = TaskQueue(agent_name=AGENT_NAME)

# Background worker task handle
_worker_task: asyncio.Task | None = None


# ---------------------------------------------------------------------------
# LLM integration
# ---------------------------------------------------------------------------


async def call_llm(prompt: str, tools: list[dict[str, Any]]) -> str:
    """Call the MiMo LLM with system prompt, user prompt, and tool definitions.

    Args:
        prompt: The user-facing prompt containing the task details.
        tools: List of tool definitions in OpenAI-compatible format.

    Returns:
        The assistant's text response content.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    headers = {
        "Authorization": f"Bearer {MIMO_API_KEY}",
        "Content-Type": "application/json",
    }

    body: dict[str, Any] = {
        "model": MIMO_MODEL,
        "messages": messages,
        "temperature": float(os.environ.get("MIMO_TEMPERATURE", "0.2")),
        "max_tokens": int(os.environ.get("MIMO_MAX_TOKENS", "8192")),
    }

    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            f"{MIMO_BASE_URL}/chat/completions",
            headers=headers,
            json=body,
        )
        response.raise_for_status()
        data = response.json()

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("LLM returned no choices")

    message = choices[0].get("message", {})
    content = message.get("content", "")

    # Handle tool calls if present
    tool_calls = message.get("tool_calls", [])
    if tool_calls:
        tool_results = await _execute_tool_calls(tool_calls)
        # Append tool call and results, then call LLM again for final response
        messages.append(message)
        for tool_result in tool_results:
            messages.append({
                "role": "tool",
                "tool_call_id": tool_result["tool_call_id"],
                "content": tool_result["content"],
            })
        body["messages"] = messages
        body.pop("tools", None)
        body.pop("tool_choice", None)

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{MIMO_BASE_URL}/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")

    return content


async def _execute_tool_calls(
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Execute MCP tool calls returned by the LLM.

    Args:
        tool_calls: List of tool call objects from the LLM response.

    Returns:
        List of tool result dicts with 'tool_call_id' and 'content'.
    """
    results = []
    for tc in tool_calls:
        function = tc.get("function", {})
        tool_name = function.get("name", "")
        arguments_str = function.get("arguments", "{}")

        import json as _json

        try:
            arguments = _json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except _json.JSONDecodeError:
            arguments = {}

        logger.info("executing_tool", tool_name=tool_name, call_id=tc.get("id"))

        try:
            result = await mcp_client.call(tool_name, arguments)
            content = _json.dumps(result, indent=2) if not isinstance(result, str) else result
        except Exception as exc:
            logger.error("tool_call_failed", tool_name=tool_name, error=str(exc))
            content = f"Error calling tool '{tool_name}': {exc}"

        results.append({
            "tool_call_id": tc.get("id", str(uuid4())),
            "content": content,
        })

    return results


# ---------------------------------------------------------------------------
# Task processing
# ---------------------------------------------------------------------------


def _build_task_prompt(task: dict[str, Any]) -> str:
    """Build the LLM prompt from an incoming A2A task message.

    Args:
        task: The full A2A message dict.

    Returns:
        A formatted prompt string for the LLM.
    """
    payload = task.get("payload", {})
    claim = payload.get("claim", "")
    evidence = payload.get("evidence", "")
    suggestion = payload.get("suggestion", "")
    artifacts = payload.get("artifacts", [])
    metadata = payload.get("metadata", {})
    from_agent = task.get("from", "unknown")
    task_id = task.get("task_id", "unknown")

    parts = [
        f"## Incoming Task (from {from_agent})",
        f"Task ID: {task_id}",
        "",
        f"## Description",
        claim,
    ]

    if evidence:
        parts.extend(["", "## Evidence", evidence])

    if suggestion:
        parts.extend(["", "## Suggested Action", suggestion])

    if artifacts:
        parts.extend(["", "## Attached Artifacts"])
        for art in artifacts:
            name = art.get("name", "unnamed")
            content = art.get("content", "")
            mime = art.get("mime_type", "text/plain")
            parts.append(f"### {name} ({mime})")
            parts.append(f"```")
            parts.append(content)
            parts.append(f"```")
            parts.append("")

    if metadata:
        parts.extend(["", "## Metadata"])
        for key, value in metadata.items():
            parts.append(f"- **{key}**: {value}")

    parts.extend([
        "",
        "## Your Task",
        "Based on the above API specification, database schema, and user stories, "
        "implement the FastAPI endpoints with:",
        "- Complete endpoint implementations with proper routing",
        "- Pydantic request/response models with validation",
        "- SQLAlchemy ORM models and database access layer",
        "- Proper error handling with appropriate HTTP status codes",
        "- Inline docstrings for all functions",
        "- No hardcoded secrets — use environment variables",
        "",
        "Return the implementation code organized by file path.",
    ])

    return "\n".join(parts)


async def process_task(task: dict[str, Any]) -> dict[str, Any]:
    """Process an incoming A2A task and generate backend code.

    Args:
        task: The A2A message dict from the task queue.

    Returns:
        The A2A result message to push to the next agent.
    """
    task_id = task.get("task_id", str(uuid4()))
    from_agent = task.get("from", "unknown")

    logger.info(
        "processing_task",
        task_id=task_id,
        from_agent=from_agent,
    )

    start_time = time.monotonic()

    try:
        # Build prompt and get tools
        prompt = _build_task_prompt(task)
        tools = get_tools()

        # Call the LLM to generate implementation
        response_text = await call_llm(prompt, tools)

        elapsed = time.monotonic() - start_time
        logger.info(
            "task_completed",
            task_id=task_id,
            elapsed_seconds=round(elapsed, 2),
            response_length=len(response_text),
        )

        # Build result artifact
        result_artifact = {
            "name": "fastapi_implementation.md",
            "content": response_text,
            "mime_type": "text/markdown",
        }

        # Build A2A result message for Security Reviewer
        result_message = {
            "protocol": "a2a/1.0",
            "type": "task",
            "from": AGENT_NAME,
            "to": PUSH_TO_AGENTS[0],
            "task_id": task_id,
            "round": 1,
            "payload": {
                "claim": (
                    f"FastAPI implementation generated for task from {from_agent}. "
                    f"Please review for security issues, OWASP Top 10 compliance, "
                    f"and code quality."
                ),
                "evidence": (
                    f"Implementation generated in {elapsed:.1f}s. "
                    f"Response length: {len(response_text)} chars. "
                    f"Original request from: {from_agent}"
                ),
                "suggestion": (
                    "Review for: SQL injection, input validation, authentication, "
                    "authorization, secrets exposure, error handling, and OWASP Top 10."
                ),
                "artifacts": [result_artifact],
                "metadata": {
                    "source_agent": AGENT_NAME,
                    "original_from": from_agent,
                    "generation_time_seconds": round(elapsed, 2),
                    "model": MIMO_MODEL,
                },
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return result_message

    except Exception as exc:
        elapsed = time.monotonic() - start_time
        logger.error(
            "task_processing_failed",
            task_id=task_id,
            error=str(exc),
            elapsed_seconds=round(elapsed, 2),
        )

        # Return an error result so the pipeline doesn't stall
        error_message = {
            "protocol": "a2a/1.0",
            "type": "result",
            "from": AGENT_NAME,
            "to": PUSH_TO_AGENTS[0],
            "task_id": task_id,
            "round": 1,
            "payload": {
                "claim": f"Backend implementation FAILED for task from {from_agent}.",
                "evidence": f"Error after {elapsed:.1f}s: {exc}",
                "suggestion": (
                    "The backend developer encountered an error during code generation. "
                    "The task may need to be retried or the input clarified."
                ),
                "artifacts": [],
                "metadata": {
                    "source_agent": AGENT_NAME,
                    "error": str(exc),
                    "original_from": from_agent,
                },
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return error_message


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


async def worker_loop() -> None:
    """Background worker that continuously dequeues and processes tasks.

    After processing a task, the result is pushed to the next agent
    (security_reviewer) and the worker immediately picks the next task.
    """
    logger.info("worker_started", agent=AGENT_NAME)

    while True:
        try:
            task = await task_queue.pop()

            if task is None:
                # No task available — brief sleep to avoid tight loop
                await asyncio.sleep(0.5)
                continue

            task_id = task.get("task_id", "unknown")
            logger.info("worker_picked_task", task_id=task_id)

            # Process the task
            result = await process_task(task)

            # Push result to next agent(s)
            for target_agent in PUSH_TO_AGENTS:
                try:
                    result["to"] = target_agent
                    await a2a_server.push(to=target_agent, message=result)
                    logger.info(
                        "worker_pushed_result",
                        task_id=task_id,
                        target=target_agent,
                    )
                except Exception as push_exc:
                    logger.error(
                        "worker_push_failed",
                        task_id=task_id,
                        target=target_agent,
                        error=str(push_exc),
                    )

            # Acknowledge task completion in queue
            await task_queue.ack(task_id)

            logger.info("worker_task_done", task_id=task_id)

        except asyncio.CancelledError:
            logger.info("worker_cancelled")
            break

        except Exception as exc:
            logger.error("worker_unhandled_error", error=str(exc))
            await asyncio.sleep(1.0)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Manage startup and shutdown lifecycle events."""
    global _worker_task

    logger.info(
        "agent_starting",
        agent=AGENT_NAME,
        display_name=AGENT_DISPLAY_NAME,
        port=AGENT_PORT,
    )

    # Start background worker
    await task_queue.recover_stuck_tasks()
    _worker_task = asyncio.create_task(worker_loop())
    logger.info("background_worker_launched")

    yield

    # Shutdown
    logger.info("agent_shutting_down", agent=AGENT_NAME)

    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        logger.info("background_worker_stopped")

    # Close MCP client
    try:
        await mcp_client.close()
    except Exception as exc:
        logger.warning("mcp_client_close_error", error=str(exc))

    logger.info("agent_stopped", agent=AGENT_NAME)


app = FastAPI(
    title=f"{AGENT_DISPLAY_NAME} Agent",
    description=(
        "Backend Developer agent for the OpenCrew pipeline. "
        "Implements FastAPI endpoints from API specs and DB schemas."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

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
async def agent_card():
    """Return the A2A agent card for discovery.

    Describes this agent's capabilities, supported input/output types,
    and connection details so other agents can discover and interact
    with it via the A2A protocol.
    """
    card = {
        "name": AGENT_NAME,
        "display_name": AGENT_DISPLAY_NAME,
        "url": f"http://backend_dev:{AGENT_PORT}",
        "version": "1.0.0",
        "capabilities": [
            "fastapi",
            "sqlalchemy",
            "pydantic",
            "api_implementation",
        ],
        "input_types": ["api_spec", "db_schema", "user_story"],
        "output_types": ["fastapi_code"],
        "push_to": PUSH_TO_AGENTS,
        "protocol": "a2a/1.0",
        "mcp_tools": ["github_mcp", "context7"],
    }
    logger.info("agent_card_requested")
    return card


@app.post("/a2a")
async def receive_a2a_message(request: Request):
    """Receive an A2A protocol message and enqueue it for processing.

    Validates the incoming message structure, adds it to the task queue,
    and returns 202 Accepted immediately (non-blocking).

    Args:
        request: The incoming FastAPI request.

    Returns:
        JSON response with status and task_id.
    """
    try:
        body = await request.json()
    except Exception as exc:
        logger.warning("a2a_invalid_json", error=str(exc))
        return JSONResponse(
            status_code=400,
            content={"status": "error", "detail": "Invalid JSON body"},
        )

    # Validate required A2A fields
    required_fields = ["protocol", "type", "from", "to", "task_id", "payload"]
    missing = [f for f in required_fields if f not in body]
    if missing:
        logger.warning("a2a_missing_fields", fields=missing)
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "detail": f"Missing required fields: {', '.join(missing)}",
            },
        )

    # Validate protocol version
    if body.get("protocol") != "a2a/1.0":
        logger.warning("a2a_invalid_protocol", protocol=body.get("protocol"))
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "detail": "Unsupported protocol version. Expected 'a2a/1.0'",
            },
        )

    # Add timestamp if not present
    if "timestamp" not in body:
        body["timestamp"] = datetime.now(timezone.utc).isoformat()

    task_id = body["task_id"]
    from_agent = body.get("from", "unknown")

    logger.info(
        "a2a_message_received",
        task_id=task_id,
        from_agent=from_agent,
        message_type=body.get("type"),
    )

    # Enqueue for async processing
    await task_queue.push(body)

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "task_id": task_id,
            "agent": AGENT_NAME,
            "message": "Task queued for processing",
        },
    )


@app.get("/health")
async def health_check():
    """Return agent health status and queue information.

    Used by the orchestration layer and monitoring to verify
    the agent is running and responsive.
    """
    queue_size = await task_queue.size()

    return {
        "status": "ok",
        "agent": AGENT_NAME,
        "display_name": AGENT_DISPLAY_NAME,
        "port": AGENT_PORT,
        "queue_size": queue_size,
        "worker_running": _worker_task is not None and not _worker_task.done(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }