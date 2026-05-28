"""UIUX Reviewer Agent — FastAPI server on port 8006.

Reviews frontend code for WCAG 2.1 AA accessibility, UX best practices,
and design compliance against UI_SPEC.md. Pushes to QA on pass or back
to Frontend Dev on violation.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from shared.a2a_server import A2AMessage, A2AServer
from shared.mcp_client import MCPClient
from shared.task_queue import TaskQueue

from prompts import SYSTEM_PROMPT
from tools import get_tools

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AGENT_NAME = "uiux_reviewer"
AGENT_DISPLAY_NAME = "UIUX Reviewer"
PORT = 8006
VERSION = "1.0.0"

CAPABILITIES: List[str] = ["accessibility_review", "ux_validation", "design_compliance"]
INPUT_TYPES: List[str] = ["frontend_code", "ui_spec"]
OUTPUT_TYPES: List[str] = ["review_report"]
PUSH_TO_PASS: str = "qa"
PUSH_TO_FAIL: str = "frontend_dev"

# ---------------------------------------------------------------------------
# Structured logger
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
    wrapper_class=structlog.make_filtering_bound_logger(20),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger(AGENT_NAME)

# ---------------------------------------------------------------------------
# Shared services
# ---------------------------------------------------------------------------

a2a = A2AServer(agent_name=AGENT_NAME, port=PORT)
mcp = MCPClient()
queue = TaskQueue(agent_name=AGENT_NAME)

# ---------------------------------------------------------------------------
# Lifespan & background worker
# ---------------------------------------------------------------------------

_worker_task: Optional[asyncio.Task] = None


async def _classify_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run the UIUX review using MCP tools and the system prompt.

    Returns a structured review result containing severity-classified
    findings (VIOLATION / SUGGESTION / OPINION) and an overall pass/fail
    determination.
    """
    tools = get_tools(mcp)
    claim = payload.get("claim", "")
    evidence = payload.get("evidence", "")
    artifacts = payload.get("artifacts", [])
    metadata = payload.get("metadata", {})

    logger = log.bind(
        task_claim=claim,
        artifact_count=len(artifacts),
    )
    logger.info("starting_uiux_review")

    # Build the review context from artifacts
    frontend_code = ""
    ui_spec = ""
    for artifact in artifacts:
        name = artifact.get("name", "")
        content = artifact.get("content", "")
        if "spec" in name.lower() or "ui_spec" in name.lower():
            ui_spec = content
        else:
            # Treat other artifacts as frontend code to review
            if frontend_code:
                frontend_code += "\n\n---\n\n"
            frontend_code += f"// File: {name}\n{content}"

    if not frontend_code and not ui_spec:
        frontend_code = claim + "\n" + evidence

    # Gather MCP tool data for the review
    mcp_findings: List[Dict[str, Any]] = []
    for tool in tools:
        tool_name = tool.get("name", "")
        try:
            if tool_name == "check_accessibility":
                result = await mcp.call(tool_name, {"code": frontend_code})
                mcp_findings.append({"source": tool_name, "data": result})
            elif tool_name == "check_color_contrast":
                result = await mcp.call(tool_name, {"code": frontend_code})
                mcp_findings.append({"source": tool_name, "data": result})
            elif tool_name == "check_responsive":
                result = await mcp.call(tool_name, {"code": frontend_code})
                mcp_findings.append({"source": tool_name, "data": result})
            elif tool_name == "compare_design_spec" and ui_spec:
                result = await mcp.call(
                    tool_name, {"code": frontend_code, "spec": ui_spec}
                )
                mcp_findings.append({"source": tool_name, "data": result})
        except Exception as exc:
            logger.warning("mcp_tool_error", tool=tool_name, error=str(exc))

    # Classify findings into severity buckets
    violations: List[Dict[str, str]] = []
    suggestions: List[Dict[str, str]] = []
    opinions: List[Dict[str, str]] = []

    for finding in mcp_findings:
        data = finding.get("data", {})
        if isinstance(data, dict):
            items = data.get("issues", data.get("findings", []))
            if isinstance(items, list):
                for item in items:
                    severity = str(item.get("severity", "opinion")).lower()
                    entry = {
                        "source": finding["source"],
                        "description": item.get("description", str(item)),
                        "file": item.get("file", ""),
                        "line": str(item.get("line", "")),
                        "suggestion": item.get("suggestion", ""),
                    }
                    if severity in ("violation", "critical", "high"):
                        violations.append(entry)
                    elif severity in ("suggestion", "medium"):
                        suggestions.append(entry)
                    else:
                        opinions.append(entry)

    # Determine overall pass/fail
    passed = len(violations) == 0

    review_report = {
        "agent": AGENT_NAME,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "verdict": "PASS" if passed else "FAIL",
        "summary": (
            "UIUX review passed — no accessibility or layout violations found."
            if passed
            else f"UIUX review failed — {len(violations)} violation(s) must be fixed before merge."
        ),
        "violations": violations,
        "suggestions": suggestions,
        "opinions": opinions,
        "mcp_findings_count": len(mcp_findings),
        "system_prompt_context": SYSTEM_PROMPT[:500],
    }

    logger.info(
        "review_complete",
        verdict=review_report["verdict"],
        violations=len(violations),
        suggestions=len(suggestions),
        opinions=len(opinions),
    )

    return review_report


async def _process_task(message: Dict[str, Any]) -> None:
    """Process a single A2A message from the queue."""
    task_id = message.get("task_id", "unknown")
    msg_from = message.get("from", "unknown")
    payload = message.get("payload", {})

    logger = log.bind(task_id=task_id, from_agent=msg_from)
    logger.info("processing_task", message_type=message.get("type"))

    try:
        review_report = await _classify_review(payload)

        passed = review_report["verdict"] == "PASS"
        next_agent = PUSH_TO_PASS if passed else PUSH_TO_FAIL

        result_message = {
            "protocol": "a2a/1.0",
            "type": "result",
            "from": AGENT_NAME,
            "to": next_agent,
            "task_id": task_id,
            "round": message.get("round", 1),
            "payload": {
                "claim": review_report["summary"],
                "evidence": (
                    f"Violations: {len(review_report['violations'])}, "
                    f"Suggestions: {len(review_report['suggestions'])}, "
                    f"Opinions: {len(review_report['opinions'])}"
                ),
                "suggestion": (
                    "Merge is approved from UIUX perspective."
                    if passed
                    else "Fix violations listed in artifacts before resubmitting."
                ),
                "artifacts": [
                    {
                        "name": "uiux_review_report.json",
                        "content": __import__("json").dumps(
                            review_report, indent=2, ensure_ascii=False
                        ),
                    }
                ],
                "metadata": {
                    "verdict": review_report["verdict"],
                    "violations_count": len(review_report["violations"]),
                    "suggestions_count": len(review_report["suggestions"]),
                },
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        await a2a.push(to=next_agent, message=result_message)
        logger.info(
            "pushed_result",
            to_agent=next_agent,
            verdict=review_report["verdict"],
        )

    except Exception as exc:
        logger.error("task_processing_failed", error=str(exc), exc_info=True)
        # Push error result back to the sender so the pipeline doesn't stall
        error_message = {
            "protocol": "a2a/1.0",
            "type": "result",
            "from": AGENT_NAME,
            "to": msg_from,
            "task_id": task_id,
            "round": message.get("round", 1),
            "payload": {
                "claim": f"UIUX review encountered an internal error: {exc}",
                "evidence": str(exc),
                "suggestion": "Resubmit the task or check the UIUX Reviewer agent logs.",
                "artifacts": [],
                "metadata": {"verdict": "ERROR", "error": str(exc)},
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await a2a.push(to=msg_from, message=error_message)
        except Exception:
            logger.critical("failed_to_push_error_result", exc_info=True)

    finally:
        await queue.ack(task_id)


async def _worker() -> None:
    """Background worker loop — pops tasks from the queue and processes them."""
    log.info("worker_started", agent=AGENT_NAME)
    while True:
        try:
            task = await queue.pop()
            if task is not None:
                await _process_task(task)
            else:
                # Nothing in queue — brief sleep to avoid busy-spinning
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            log.info("worker_cancelled")
            break
        except Exception as exc:
            log.error("worker_error", error=str(exc), exc_info=True)
            await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Manage startup/shutdown lifecycle."""
    global _worker_task
    log.info(
        "agent_starting",
        agent=AGENT_NAME,
        port=PORT,
        capabilities=CAPABILITIES,
    )
    await queue.recover_stuck_tasks()
    await queue.recover_stuck_tasks()
    worker_task = asyncio.create_task(_worker())
    yield
    log.info("agent_shutting_down", agent=AGENT_NAME)
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    await mcp.close()
    log.info("agent_stopped", agent=AGENT_NAME)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=AGENT_DISPLAY_NAME,
    version=VERSION,
    lifespan=lifespan,
)

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
async def agent_card() -> Dict[str, Any]:
    """Return the A2A agent card for discovery."""
    return {
        "name": AGENT_NAME,
        "display_name": AGENT_DISPLAY_NAME,
        "url": f"http://{AGENT_NAME}:{PORT}",
        "version": VERSION,
        "capabilities": CAPABILITIES,
        "input_types": INPUT_TYPES,
        "output_types": OUTPUT_TYPES,
        "protocol": "a2a/1.0",
        "push_to": [PUSH_TO_PASS, PUSH_TO_FAIL],
        "description": (
            "Reviews frontend code for WCAG 2.1 AA accessibility, "
            "UX validation, and design compliance. Classifies findings as "
            "VIOLATION (blocks merge), SUGGESTION (should fix), or OPINION (nice-to-have)."
        ),
    }


@app.post("/a2a")
async def receive_task(message: Dict[str, Any]) -> Dict[str, Any]:
    """Receive an A2A message and enqueue it for background processing.

    Returns 202 Accepted immediately — the worker processes the task
    asynchronously.
    """
    # Validate basic A2A structure
    protocol = message.get("protocol")
    if protocol != "a2a/1.0":
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported protocol: {protocol!r}. Expected 'a2a/1.0'.",
        )

    task_id = message.get("task_id")
    if not task_id:
        raise HTTPException(status_code=422, detail="Missing required field: task_id")

    log.info(
        "task_received",
        task_id=task_id,
        from_agent=message.get("from", "unknown"),
        message_type=message.get("type", "unknown"),
    )

    await queue.push(message)
    return {"status": "accepted", "task_id": task_id, "agent": AGENT_NAME}


@app.get("/health")
async def health() -> Dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "agent": AGENT_NAME,
        "port": PORT,
        "queue_size": await queue.size(),
        "version": VERSION,
        "capabilities": CAPABILITIES,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "agents.uiux_reviewer.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
    )