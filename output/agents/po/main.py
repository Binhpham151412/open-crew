"""Product Owner (PO) agent — FastAPI application.

FastAPI main.py for the Product Owner agent (port 8000).
Receives user requirements, generates PRDs via LLM + MCP tools,
and pushes the result to the PM agent through the A2A protocol.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.a2a_server import A2AServer
from shared.mcp_client import MCPClient, MCPError
from shared.task_queue import TaskQueue

from prompts import SYSTEM_PROMPT
from tools import get_tools

# ── Configuration ────────────────────────────────────────────────────────

AGENT_NAME: str = "po"
PORT: int = 8000
DISPLAY_NAME: str = "Product Owner"
PUSH_TO_AGENTS: list[str] = ["pm"]
CAPABILITIES: list[str] = ["receive_requirements", "write_prd", "accept_reject"]
INPUT_TYPES: list[str] = ["user_request"]
OUTPUT_TYPES: list[str] = ["prd"]

MIMO_BASE_URL: str = os.getenv("MIMO_BASE_URL", "https://api.xiaomi.com/v1")
MIMO_API_KEY: str = os.getenv("MIMO_API_KEY", "")
MIMO_MODEL: str = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "8192"))
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "120.0"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
AGENT_LOOP_MAX_ITERATIONS: int = int(os.getenv("AGENT_LOOP_MAX_ITERATIONS", "10"))

# ── Structured Logging ──────────────────────────────────────────────────

_LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
_LOG_JSON: bool = os.getenv("LOG_JSON", "false").lower() in ("1", "true", "yes")

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        (
            structlog.dev.ConsoleRenderer()
            if not _LOG_JSON
            else structlog.processors.JSONRenderer()
        ),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, _LOG_LEVEL, logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()

# ── Shared Instances ────────────────────────────────────────────────────

a2a = A2AServer(agent_name=AGENT_NAME, port=PORT)
mcp = MCPClient()
queue = TaskQueue(agent_name=AGENT_NAME)


# ── LLM Helpers ─────────────────────────────────────────────────────────


async def _call_llm(
    client: httpx.AsyncClient,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call the MiMo LLM API using OpenAI-compatible chat completions format.

    Retries transient failures with exponential backoff.

    Args:
        client: Shared httpx async client.
        messages: Chat message history for the LLM.
        tools: Optional list of tool definitions for function calling.

    Returns:
        Raw JSON response from the LLM API.

    Raises:
        httpx.HTTPStatusError: On non-retryable HTTP errors.
        httpx.TransportError: After exhausting all retries.
    """
    payload: dict[str, Any] = {
        "model": MIMO_MODEL,
        "messages": messages,
        "temperature": LLM_TEMPERATURE,
        "max_tokens": LLM_MAX_TOKENS,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Authorization": f"Bearer {MIMO_API_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{MIMO_BASE_URL.rstrip('/')}/chat/completions"

    last_exc: Exception | None = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = await client.post(
                url, json=payload, headers=headers
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            last_exc = exc
            wait = min(2 ** attempt, 30)
            log.warning(
                "llm_call_retry",
                attempt=attempt,
                max_retries=LLM_MAX_RETRIES,
                wait_seconds=wait,
                error=str(exc),
            )
            if attempt < LLM_MAX_RETRIES:
                await asyncio.sleep(wait)

    raise last_exc  # type: ignore[misc]


async def _execute_tool_call(tool_call: dict[str, Any]) -> str:
    """Execute a single LLM tool call via the MCP client.

    Args:
        tool_call: The tool_call object from the LLM response.

    Returns:
        JSON-encoded string of the tool result (or error).
    """
    func = tool_call.get("function", {})
    name: str = func.get("name", "")
    raw_args = func.get("arguments", "{}")

    try:
        args: dict[str, Any] = (
            json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        )
    except (json.JSONDecodeError, TypeError):
        args = {}

    log.info("tool_call_start", tool=name, args_keys=list(args.keys()) if isinstance(args, dict) else None)

    try:
        result = await mcp.call(name, args)
        log.info("tool_call_success", tool=name)
        return json.dumps(result, ensure_ascii=False, default=str)
    except MCPError as exc:
        log.error("tool_call_mcp_error", tool=name, error=str(exc))
        return json.dumps({"error": f"MCP error: {exc}"})
    except Exception as exc:
        log.error("tool_call_unexpected_error", tool=name, error=str(exc))
        return json.dumps({"error": f"Unexpected error: {exc}"})


async def _run_agent_loop(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> str:
    """Run the LLM agent loop with tool calling until a final text response.

    Iterates by sending the conversation to the LLM, executing any requested
    tool calls via MCP, appending results, and repeating until the LLM returns
    a content-only message (no tool calls) or the iteration limit is reached.

    Args:
        messages: Mutable list of chat messages (modified in-place).
        tools: Tool definitions to send to the LLM.

    Returns:
        The final text content from the LLM.
    """
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        for iteration in range(1, AGENT_LOOP_MAX_ITERATIONS + 1):
            log.debug("agent_loop_iteration", iteration=iteration)

            llm_response = await _call_llm(client, messages, tools)
            choice = llm_response["choices"][0]
            assistant_msg: dict[str, Any] = choice["message"]
            messages.append(assistant_msg)

            tool_calls = assistant_msg.get("tool_calls")
            if not tool_calls:
                content = assistant_msg.get("content") or ""
                log.info(
                    "agent_loop_finished",
                    iterations=iteration,
                    content_length=len(content),
                )
                return content

            # Execute all tool calls and append results
            for tc in tool_calls:
                tc_id = tc.get("id", str(uuid4()))
                result_content = await _execute_tool_call(tc)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_content,
                    }
                )

    # Exhausted iterations — return last assistant content
    log.warning("agent_loop_max_iterations", max_iter=AGENT_LOOP_MAX_ITERATIONS)
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"]
    return ""


# ── Task Processing ─────────────────────────────────────────────────────


async def _process_task(message: dict[str, Any]) -> None:
    """Process an incoming A2A task: generate a PRD and push it to PM.

    Extracts the user request from the message payload, runs the LLM agent
    loop (with MCP tool access), and pushes the resulting PRD to the PM agent.

    Args:
        message: The inbound A2A message dict.
    """
    task_id: str = message.get("task_id", str(uuid4()))
    payload: dict[str, Any] = message.get("payload", {})
    user_request: str = payload.get("claim", "")

    if not user_request.strip():
        log.warning("empty_user_request", task_id=task_id)
        return

    log.info(
        "processing_task",
        task_id=task_id,
        from_agent=message.get("from", "unknown"),
        request_preview=user_request[:300],
    )

    # Retrieve tool definitions for the PO agent
    tools = get_tools(mcp)

    # Build initial conversation
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_request},
    ]

    # Append any artifacts from the incoming payload as context
    artifacts: list[dict[str, Any]] = payload.get("artifacts", [])
    if artifacts:
        artifact_sections = []
        for art in artifacts:
            name = art.get("name", "attachment")
            content = art.get("content", "")
            artifact_sections.append(f"### {name}\n```\n{content}\n```")
        messages[1]["content"] += (
            "\n\n## Attached Context\n" + "\n\n".join(artifact_sections)
        )

    # Run the agent loop (LLM + tool calls)
    prd_content = await _run_agent_loop(messages, tools)

    if not prd_content.strip():
        log.error("empty_prd_generated", task_id=task_id)
        return

    log.info("prd_generated", task_id=task_id, prd_length=len(prd_content))

    # Push PRD to PM agent
    await _push_to_pm(
        task_id=task_id,
        prd_content=prd_content,
        user_request=user_request,
    )


async def _push_to_pm(
    task_id: str,
    prd_content: str,
    user_request: str,
) -> None:
    """Push the generated PRD to the PM agent via A2A protocol.

    Args:
        task_id: The task UUID (preserved through the pipeline).
        prd_content: The full PRD markdown content.
        user_request: Original user request for traceability.
    """
    a2a_message: dict[str, Any] = {
        "protocol": "a2a/1.0",
        "type": "task",
        "from": AGENT_NAME,
        "to": "pm",
        "task_id": task_id,
        "round": 1,
        "payload": {
            "claim": f"PRD generated for: {user_request[:200]}",
            "evidence": (
                "Product Requirements Document created by Product Owner "
                "based on user requirements analysis."
            ),
            "suggestion": (
                "Break down the PRD into Stories and Tasks, estimate effort, "
                "create a sprint plan, and assign to BA and Solution Architect "
                "in parallel."
            ),
            "artifacts": [
                {
                    "name": "PRD.md",
                    "content": prd_content,
                    "mime_type": "text/markdown",
                }
            ],
            "metadata": {
                "source_agent": AGENT_NAME,
                "original_request": user_request[:500],
            },
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        await a2a.push(to="pm", message=a2a_message)
        log.info("prd_pushed_to_pm", task_id=task_id)
    except Exception as exc:
        log.error("push_to_pm_failed", task_id=task_id, error=str(exc))
        raise


# ── Background Worker ───────────────────────────────────────────────────


async def _worker() -> None:
    """Background worker that dequeues tasks and processes them sequentially.

    Runs for the lifetime of the application. Pops one task at a time from
    the queue, processes it (LLM + tools + push), and immediately picks
    the next task — never idling between tasks per the async pipeline rule.
    """
    log.info("worker_started", agent=AGENT_NAME)
    while True:
        try:
            task = await queue.pop()
            if task is None:
                await asyncio.sleep(0.05)
                continue

            task_id: str = task.get("task_id", "unknown")
            log.info("task_dequeued", task_id=task_id)

            try:
                await _process_task(task)
                log.info("task_completed", task_id=task_id)
            except Exception as exc:
                log.error(
                    "task_processing_failed",
                    task_id=task_id,
                    error=str(exc),
                    exc_info=True,
                )
            finally:
                try:
                    await queue.ack(task_id)
                except Exception as exc:
                    log.warning("task_ack_failed", task_id=task_id, error=str(exc))

        except asyncio.CancelledError:
            log.info("worker_cancelled", agent=AGENT_NAME)
            break
        except Exception as exc:
            log.error("worker_unexpected_error", error=str(exc), exc_info=True)
            await asyncio.sleep(1)


# ── FastAPI Application ─────────────────────────────────────────────────


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    if not MIMO_API_KEY:
        log.warning(
            "mimo_api_key_missing",
            message="LLM calls will fail — set MIMO_API_KEY environment variable",
        )

    await queue.recover_stuck_tasks()
    worker_task = asyncio.create_task(_worker())

    log.info(
        "po_agent_started",
        agent=AGENT_NAME,
        display_name=DISPLAY_NAME,
        port=PORT,
        capabilities=CAPABILITIES,
        push_to=PUSH_TO_AGENTS,
        model=MIMO_MODEL,
    )

    yield

    # Graceful shutdown
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    try:
        await mcp.close()
    except Exception as exc:
        log.warning("mcp_close_error", error=str(exc))

    log.info("po_agent_stopped", agent=AGENT_NAME)


app = FastAPI(
    title="OpenCrew — Product Owner Agent",
    description="Receives user requirements, generates PRDs, and pushes them to PM.",
    version="1.0.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ───────────────────────────────────────────────────────────


@app.get("/.well-known/agent.json")
async def agent_card():
    """Return the Agent Card for A2A protocol discovery.

    Follows the A2A specification so that other agents and the web UI
    can discover this agent's capabilities, input/output types, and URL.
    """
    card = a2a.get_card()
    # Ensure the card reflects PO-specific metadata
    card.setdefault("name", AGENT_NAME)
    card.setdefault("display_name", DISPLAY_NAME)
    card.setdefault("version", "1.0.0")
    card["capabilities"] = CAPABILITIES
    card["input_types"] = INPUT_TYPES
    card["output_types"] = OUTPUT_TYPES
    card["protocol"] = "a2a/1.0"
    return card


@app.post("/a2a")
async def receive_task(message: dict[str, Any]):
    """Receive an A2A protocol message and enqueue it for background processing.

    Returns 202 Accepted immediately — the task is processed asynchronously
    by the background worker so the caller is never blocked.
    """
    task_id: str = message.get("task_id") or str(uuid4())
    if not message.get("task_id"):
        message["task_id"] = task_id

    # Ensure required protocol fields
    message.setdefault("protocol", "a2a/1.0")
    message.setdefault("type", "task")
    message.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

    await queue.push(message)

    log.info(
        "task_enqueued",
        task_id=task_id,
        from_agent=message.get("from", "unknown"),
        msg_type=message.get("type", "task"),
    )

    return {"status": "accepted", "task_id": task_id}


@app.get("/health")
async def health():
    """Health check endpoint for container orchestration and monitoring."""
    try:
        qsize = await queue.size()
    except Exception:
        qsize = -1

    return {
        "status": "ok",
        "agent": AGENT_NAME,
        "display_name": DISPLAY_NAME,
        "port": PORT,
        "queue_size": qsize,
        "capabilities": CAPABILITIES,
        "model": MIMO_MODEL,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Entry Point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "agents.po.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=os.getenv("ENV", "production").lower() == "dev",
        log_level=_LOG_LEVEL.lower(),
        access_log=True,
    )