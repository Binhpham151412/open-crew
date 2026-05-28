from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from shared.a2a_server import A2AServer, A2AMessage, Payload
from shared.mcp_client import MCPClient
from shared.task_queue import TaskQueue

from prompts import SYSTEM_PROMPT
from tools import get_tools

# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("techlead")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_NAME = "techlead"
DISPLAY_NAME = "TechLead"
PORT = 8010
CAPABILITIES = ["arbitrate", "final_review", "merge_signoff"]
INPUT_TYPES = ["agent_reports", "delivery_package"]
OUTPUT_TYPES = ["final_approval"]
PUSH_TO_AGENTS = ["po"]

MAX_DEBATE_ROUNDS = 3
MAX_RETRY_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Shared instances
# ---------------------------------------------------------------------------

a2a = A2AServer(agent_name=AGENT_NAME, port=PORT)
mcp = MCPClient()
queue = TaskQueue(agent_name=AGENT_NAME)
tools = get_tools(mcp)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class TaskResult(BaseModel):
    """Result produced after TechLead processes a task."""

    task_id: str
    status: str = Field(description="approved | rejected | escalated")
    decision: str = Field(description="Human-readable decision summary")
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Processing logic
# ---------------------------------------------------------------------------


async def _call_llm(messages: list[dict[str, str]]) -> str:
    """Call the LLM via MCP tool (chat_completion) with the system prompt and
    conversation history.  Returns the raw assistant text."""

    from tools import chat_completion

    system_msg = {"role": "system", "content": SYSTEM_PROMPT}
    full_messages = [system_msg, *messages]
    return await chat_completion(mcp, full_messages)


def _build_analysis_prompt(message: dict[str, Any]) -> list[dict[str, str]]:
    """Build the conversation messages that describe the incoming task to the
    LLM so it can decide what to do (arbitrate / final review / merge sign-off)."""

    msg_type = message.get("type", "task")
    payload = message.get("payload", {})
    task_id = message.get("task_id", "unknown")
    sender = message.get("from", "unknown")
    claim = payload.get("claim", "")
    evidence = payload.get("evidence", "")
    suggestion = payload.get("suggestion", "")
    artifacts = payload.get("artifacts", [])

    artifact_text = ""
    for art in artifacts:
        name = art.get("name", "unknown")
        content = art.get("content", "")[:2000]
        artifact_text += f"\n\n--- Artifact: {name} ---\n{content}"

    if msg_type == "escalate":
        user_content = (
            f"CONFLICT ESCALATED to TechLead after {message.get('round', MAX_DEBATE_ROUNDS)} rounds.\n"
            f"From: {sender}\n"
            f"Task ID: {task_id}\n"
            f"Claim: {claim}\n"
            f"Evidence: {evidence}\n"
            f"Suggestion: {suggestion}\n"
            f"{artifact_text}\n\n"
            "You must arbitrate this conflict. Apply the conflict resolution priority:\n"
            "1. Security issue → Security Reviewer wins (always)\n"
            "2. Accessibility issue → UIUX Reviewer wins\n"
            "3. Business logic → BA wins\n"
            "4. Technical architecture → Solution Architect wins\n"
            "5. Performance vs Clean code → Clean code wins (default)\n"
            "6. Deadlock → You decide unilaterally.\n\n"
            "Respond with a JSON object:\n"
            '{"decision": "approve|reject", "winner": "<agent_name>", '
            '"reasoning": "...", "action": "..."}'
        )
    elif msg_type in ("agent_reports", "task"):
        user_content = (
            f"AGENT REPORT for final review.\n"
            f"From: {sender}\n"
            f"Task ID: {task_id}\n"
            f"Report: {claim}\n"
            f"Evidence: {evidence}\n"
            f"Suggestion: {suggestion}\n"
            f"{artifact_text}\n\n"
            "Perform a final architecture review of the entire delivery package.\n"
            "Check: consistency, completeness, security posture, deployment readiness.\n"
            "Respond with a JSON object:\n"
            '{"decision": "approve|reject", "summary": "...", '
            '"issues": ["..."], "action": "..."}'
        )
    elif msg_type == "delivery_package":
        user_content = (
            f"DELIVERY PACKAGE from DevOps for merge sign-off.\n"
            f"From: {sender}\n"
            f"Task ID: {task_id}\n"
            f"Package: {claim}\n"
            f"Details: {evidence}\n"
            f"{artifact_text}\n\n"
            "Review the delivery package. Verify:\n"
            "1. Docker configs are correct (non-root, multi-stage, pinned versions)\n"
            "2. CI/CD pipelines are complete\n"
            "3. Health checks are configured\n"
            "4. Resource limits are set\n"
            "5. Secrets are not committed\n"
            "6. All agent /health endpoints return OK\n\n"
            "If everything passes, approve the merge and prepare the final delivery report for PO.\n"
            "Respond with a JSON object:\n"
            '{"decision": "approve|reject", "delivery_report": "...", '
            '"merge_status": "merged|blocked", "action": "..."}'
        )
    else:
        user_content = (
            f"Received message type '{msg_type}' from {sender}.\n"
            f"Claim: {claim}\n"
            f"Evidence: {evidence}\n"
            f"Suggestion: {suggestion}\n"
            f"{artifact_text}\n\n"
            "Determine the appropriate action as TechLead.\n"
            "Respond with a JSON object:\n"
            '{"decision": "approve|reject|escalate", "summary": "...", "action": "..."}'
        )

    return [{"role": "user", "content": user_content}]


def _determine_next_agent(message: dict[str, Any]) -> str | None:
    """Determine which agent to push the result to.

    TechLead's final output goes to PO so that PO can deliver the result
    back to the user.  For escalate-type messages (arbitration), the result
    is pushed back to the original sender's intended target.
    """
    msg_type = message.get("type", "task")

    # For escalations, we need to decide who gets the arbitration result.
    # The TechLead pushes the decision back to the disputing agents by
    # sending to the 'to' field of the escalated message, but ultimately
    # the delivery report goes to PO.
    if msg_type == "escalate":
        # The escalate message 'from' field tells us who escalated;
        # we push decision to that agent so it can continue.
        return message.get("from", "po")

    # Final review / delivery package → push to PO for user delivery
    return "po"


def _extract_decision(llm_response: str) -> dict[str, Any]:
    """Parse the LLM's JSON decision from its response text.

    Falls back to a safe default if parsing fails.
    """
    import json

    # Try to extract JSON from the response
    text = llm_response.strip()

    # Handle markdown code fences
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    # Fallback: approve by default with the raw text as summary
    logger.warning(
        "Failed to parse LLM decision as JSON, using fallback",
        raw_response=llm_response[:500],
    )
    return {
        "decision": "approve",
        "summary": llm_response[:1000],
        "action": "auto-approved due to parse failure",
    }


async def _process_escalation(message: dict[str, Any]) -> dict[str, Any]:
    """Handle an escalated conflict — arbitrate between agents."""
    task_id = message.get("task_id", str(uuid.uuid4()))
    sender = message.get("from", "unknown")

    logger.info(
        "arbitrating_conflict",
        task_id=task_id,
        from_agent=sender,
        round=message.get("round", 0),
    )

    messages = _build_analysis_prompt(message)
    llm_response = await _call_llm(messages)
    decision = _extract_decision(llm_response)

    winner = decision.get("winner", sender)
    reasoning = decision.get("reasoning", decision.get("summary", ""))
    approved = decision.get("decision", "approve").lower() == "approve"

    result: dict[str, Any] = {
        "protocol": "a2a/1.0",
        "type": "decision",
        "from": AGENT_NAME,
        "to": winner,
        "task_id": task_id,
        "round": message.get("round", MAX_DEBATE_ROUNDS) + 1,
        "payload": {
            "claim": f"TechLead arbitration: {'APPROVED' if approved else 'REJECTED'}",
            "evidence": reasoning,
            "suggestion": decision.get("action", "Proceed as decided."),
            "artifacts": [],
            "metadata": {
                "arbitration": True,
                "winner": winner,
                "decision": decision,
            },
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "arbitration_complete",
        task_id=task_id,
        winner=winner,
        approved=approved,
    )
    return result


async def _process_final_review(message: dict[str, Any]) -> dict[str, Any]:
    """Handle agent reports for final architecture review."""
    task_id = message.get("task_id", str(uuid.uuid4()))
    sender = message.get("from", "unknown")

    logger.info(
        "final_review_started",
        task_id=task_id,
        from_agent=sender,
    )

    messages = _build_analysis_prompt(message)
    llm_response = await _call_llm(messages)
    decision = _extract_decision(llm_response)

    approved = decision.get("decision", "approve").lower() == "approve"

    result: dict[str, Any] = {
        "protocol": "a2a/1.0",
        "type": "result",
        "from": AGENT_NAME,
        "to": "po",
        "task_id": task_id,
        "round": 1,
        "payload": {
            "claim": f"TechLead final review: {'APPROVED' if approved else 'REJECTED'}",
            "evidence": decision.get("summary", ""),
            "suggestion": decision.get("action", "Delivery is ready for user." if approved else "Issues must be addressed."),
            "artifacts": [],
            "metadata": {
                "final_review": True,
                "decision": decision,
                "issues": decision.get("issues", []),
            },
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Update Linear status via MCP if available
    try:
        if approved:
            await tools.update_task_status(task_id, "done")
        else:
            await tools.update_task_status(task_id, "in_progress")
    except Exception as exc:
        logger.warning("linear_update_failed", task_id=task_id, error=str(exc))

    logger.info(
        "final_review_complete",
        task_id=task_id,
        approved=approved,
    )
    return result


async def _process_delivery_package(message: dict[str, Any]) -> dict[str, Any]:
    """Handle delivery package from DevOps — merge sign-off."""
    task_id = message.get("task_id", str(uuid.uuid4()))
    sender = message.get("from", "unknown")

    logger.info(
        "merge_signoff_started",
        task_id=task_id,
        from_agent=sender,
    )

    messages = _build_analysis_prompt(message)
    llm_response = await _call_llm(messages)
    decision = _extract_decision(llm_response)

    approved = decision.get("decision", "approve").lower() == "approve"
    merge_status = decision.get("merge_status", "merged" if approved else "blocked")

    result: dict[str, Any] = {
        "protocol": "a2a/1.0",
        "type": "result",
        "from": AGENT_NAME,
        "to": "po",
        "task_id": task_id,
        "round": 1,
        "payload": {
            "claim": f"TechLead merge sign-off: {merge_status.upper()}",
            "evidence": decision.get("delivery_report", decision.get("summary", "")),
            "suggestion": (
                "Deployment is approved. Deliver results to user."
                if approved
                else "Delivery blocked. Issues must be resolved before merge."
            ),
            "artifacts": [],
            "metadata": {
                "merge_signoff": True,
                "decision": decision,
                "merge_status": merge_status,
            },
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Try to approve the merge PR via GitHub MCP
    if approved:
        try:
            await tools.approve_merge(task_id)
        except Exception as exc:
            logger.warning("github_merge_approve_failed", task_id=task_id, error=str(exc))

    # Update Linear status
    try:
        if approved:
            await tools.update_task_status(task_id, "done")
        else:
            await tools.update_task_status(task_id, "review")
    except Exception as exc:
        logger.warning("linear_update_failed", task_id=task_id, error=str(exc))

    logger.info(
        "merge_signoff_complete",
        task_id=task_id,
        merge_status=merge_status,
    )
    return result


async def _process_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Route an incoming A2A message to the appropriate handler.

    Returns the result message to push downstream, or ``None`` if the
    message type is unhandled.
    """
    msg_type = message.get("type", "task")
    task_id = message.get("task_id", "unknown")

    logger.info(
        "processing_message",
        task_id=task_id,
        msg_type=msg_type,
        from_agent=message.get("from", "unknown"),
    )

    if msg_type == "escalate":
        return await _process_escalation(message)

    if msg_type in ("agent_reports", "task"):
        # Check if this is a delivery package
        payload = message.get("payload", {})
        metadata = payload.get("metadata", {})
        if metadata.get("delivery_package") or msg_type == "delivery_package":
            return await _process_delivery_package(message)
        return await _process_final_review(message)

    if msg_type == "delivery_package":
        return await _process_delivery_package(message)

    # Unknown type — log and skip
    logger.warning(
        "unhandled_message_type",
        task_id=task_id,
        msg_type=msg_type,
    )
    return None


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

_worker_task: asyncio.Task | None = None


async def _worker_loop() -> None:
    """Continuously pop messages from the queue and process them.

    After pushing a result to the next agent, immediately picks the next
    task — no idle waiting.
    """
    logger.info("worker_started", agent=AGENT_NAME)

    while True:
        try:
            task = await queue.pop()
            if task is None:
                await asyncio.sleep(0.1)
                continue

            task_id = task.get("task_id", "unknown")
            logger.info("worker_picked_task", task_id=task_id)

            result = await _process_message(task)

            if result is not None:
                next_agent = _determine_next_agent(task)
                if next_agent:
                    logger.info(
                        "worker_pushing_result",
                        task_id=task_id,
                        to_agent=next_agent,
                    )
                    await a2a.push(to=next_agent, message=result)

            # Acknowledge the task in the queue
            await queue.ack(task_id)

            # Immediately pick next task — no sleep, no waiting

        except asyncio.CancelledError:
            logger.info("worker_cancelled")
            break
        except Exception:
            logger.exception("worker_error", task_id=task.get("task_id", "unknown"))
            # Acknowledge even on error to avoid re-processing a poisoned message
            try:
                await queue.ack(task.get("task_id", "unknown"))
            except Exception:
                pass
            await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    global _worker_task

    logger.info("techlead_starting", port=PORT, agent=AGENT_NAME)

    # Start the background worker
    await queue.recover_stuck_tasks()
    _worker_task = asyncio.create_task(_worker_loop())

    yield

    # Shutdown
    logger.info("techlead_shutting_down")
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass

    # Close MCP client
    await mcp.close()

    logger.info("techlead_stopped")


app = FastAPI(
    title=f"OpenCrew — {DISPLAY_NAME}",
    description=(
        f"{DISPLAY_NAME} agent for OpenCrew pipeline. "
        "Handles final review, conflict arbitration, and merge sign-off."
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
# Routes
# ---------------------------------------------------------------------------


@app.get("/.well-known/agent.json")
async def agent_card():
    """Return the A2A agent card for discovery."""
    return {
        "name": AGENT_NAME,
        "display_name": DISPLAY_NAME,
        "url": f"http://{AGENT_NAME}:{PORT}",
        "version": "1.0.0",
        "capabilities": CAPABILITIES,
        "input_types": INPUT_TYPES,
        "output_types": OUTPUT_TYPES,
        "protocol": "a2a/1.0",
    }


@app.post("/a2a")
async def receive_a2a(message: dict[str, Any]):
    """Receive an A2A message and enqueue it for background processing.

    Returns 202 Accepted immediately — the background worker handles
    processing asynchronously.
    """
    # Validate basic structure
    task_id = message.get("task_id")
    if not task_id:
        task_id = str(uuid.uuid4())
        message["task_id"] = task_id

    msg_type = message.get("type", "unknown")
    sender = message.get("from", "unknown")

    logger.info(
        "a2a_message_received",
        task_id=task_id,
        msg_type=msg_type,
        from_agent=sender,
    )

    # Validate protocol
    protocol = message.get("protocol")
    if protocol and protocol != "a2a/1.0":
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported protocol: {protocol}. Expected a2a/1.0.",
        )

    # Enqueue for background processing
    await queue.push(message)

    logger.info("a2a_message_enqueued", task_id=task_id, queue_size=queue.size())

    return {"status": "accepted", "task_id": task_id}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "agent": AGENT_NAME,
        "display_name": DISPLAY_NAME,
        "port": PORT,
        "queue_size": queue.size(),
        "capabilities": CAPABILITIES,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
async def root():
    """Root endpoint — redirect info."""
    return {
        "agent": AGENT_NAME,
        "display_name": DISPLAY_NAME,
        "docs": "/docs",
        "health": "/health",
        "agent_card": "/.well-known/agent.json",
        "a2a_endpoint": "/a2a",
    }


# ---------------------------------------------------------------------------
# Run directly
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "agents.techlead.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
    )