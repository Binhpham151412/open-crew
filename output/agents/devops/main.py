from __future__ import annotations
import logging

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("devops")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_NAME = "devops"
DISPLAY_NAME = "DevOps / SRE"
PORT = 8009
VERSION = "1.0.0"
CAPABILITIES = ["docker", "cicd", "deployment", "monitoring"]
INPUT_TYPES = ["merged_code", "architecture"]
OUTPUT_TYPES = ["dockerfile", "cicd_config"]
PUSH_TO_AGENTS = ["techlead"]

# Worker polling interval in seconds
WORKER_POLL_INTERVAL = 0.5

# ---------------------------------------------------------------------------
# Shared components
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
    description=f"OpenCrew {DISPLAY_NAME} agent — handles Docker, CI/CD, deployment, and monitoring.",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Agent card — /.well-known/agent.json
# ---------------------------------------------------------------------------


@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    """Return the agent card following the A2A discovery protocol."""
    card = {
        "name": AGENT_NAME,
        "display_name": DISPLAY_NAME,
        "url": f"http://{AGENT_NAME}:{PORT}",
        "version": VERSION,
        "capabilities": CAPABILITIES,
        "input_types": INPUT_TYPES,
        "output_types": OUTPUT_TYPES,
        "protocol": "a2a/1.0",
        "system_prompt_preview": SYSTEM_PROMPT[:200] + "..." if len(SYSTEM_PROMPT) > 200 else SYSTEM_PROMPT,
    }
    return JSONResponse(content=card)


# ---------------------------------------------------------------------------
# A2A endpoint — POST /a2a
# ---------------------------------------------------------------------------


@app.post("/a2a")
async def receive_a2a(request: Request) -> JSONResponse:
    """Receive an A2A message and enqueue it for background processing.

    Validates the message, pushes it onto the local task queue, and
    returns 202 Accepted immediately (non-blocking).
    """
    body = await request.json()

    # Validate A2A message structure
    try:
        message = A2AMessage(**body)
    except Exception as exc:
        logger.error("invalid_a2a_message", error=str(exc), body=body)
        raise HTTPException(status_code=422, detail=f"Invalid A2A message: {exc}")

    task_id = message.task_id or str(uuid4())
    logger.info(
        "a2a_message_received",
        task_id=task_id,
        message_type=message.type,
        sender=message.from_,
        round=message.round,
    )

    # Enqueue for async processing
    message_dict = body if isinstance(body, dict) else message.model_dump(by_alias=True)
    if "task_id" not in message_dict or not message_dict["task_id"]:
        message_dict["task_id"] = task_id

    await queue.push(message_dict)

    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "task_id": task_id},
    )


# ---------------------------------------------------------------------------
# Health check — GET /health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> JSONResponse:
    """Return agent health status and queue depth."""
    return JSONResponse(
        content={
            "status": "ok",
            "agent": AGENT_NAME,
            "display_name": DISPLAY_NAME,
            "port": PORT,
            "queue_size": await queue.size(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


# ---------------------------------------------------------------------------
# Core processing logic
# ---------------------------------------------------------------------------


async def _process_task(message: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single A2A message.

    Depending on the message type and payload, this delegates to the
    appropriate tool function.  For ``task`` messages containing merged code
    and architecture artifacts, it generates Docker and CI/CD configs.

    Args:
        message: The validated A2A message dictionary.

    Returns:
        An A2A result message to push downstream.
    """
    task_id = message.get("task_id", "unknown")
    message_type = message.get("type", "task")
    payload = message.get("payload", {})
    claim = payload.get("claim", "")
    artifacts = payload.get("artifacts", [])
    metadata = payload.get("metadata", {})

    logger.info(
        "processing_task",
        task_id=task_id,
        message_type=message_type,
        claim=claim[:120],
    )

    # Extract artifacts content for processing
    artifact_map: Dict[str, str] = {}
    for artifact in artifacts:
        if isinstance(artifact, dict):
            artifact_map[artifact.get("name", "unnamed")] = artifact.get("content", "")
        elif hasattr(artifact, "name"):
            artifact_map[artifact.name] = artifact.content

    # Route based on available content
    has_merged_code = "merged_code" in artifact_map or any(
        k in artifact_map for k in ("backend_code", "frontend_code", "source_code")
    )
    has_architecture = "architecture" in artifact_map or any(
        k in artifact_map for k in ("adr", "system_diagram", "db_schema", "interface_contracts")
    )

    result_artifacts: list[Dict[str, Any]] = []

    try:
        # Generate Dockerfile(s)
        if has_merged_code:
            logger.info("generating_dockerfiles", task_id=task_id)
            dockerfiles = await tools.generate_dockerfiles(
                code_artifacts=artifact_map,
                metadata=metadata,
            )
            if isinstance(dockerfiles, list):
                result_artifacts.extend(dockerfiles)
            elif isinstance(dockerfiles, dict):
                result_artifacts.append(dockerfiles)

            # Generate docker-compose.yml
            logger.info("generating_docker_compose", task_id=task_id)
            compose = await tools.generate_docker_compose(
                code_artifacts=artifact_map,
                metadata=metadata,
            )
            if isinstance(compose, dict):
                result_artifacts.append(compose)
            elif isinstance(compose, str):
                result_artifacts.append({
                    "name": "docker-compose.yml",
                    "content": compose,
                    "mime_type": "application/yaml",
                })

        # Generate CI/CD config
        if has_merged_code or has_architecture:
            logger.info("generating_cicd_config", task_id=task_id)
            cicd = await tools.generate_cicd_config(
                code_artifacts=artifact_map,
                architecture_artifacts={
                    k: v for k, v in artifact_map.items()
                    if k in ("architecture", "adr", "system_diagram", "db_schema", "interface_contracts")
                },
                metadata=metadata,
            )
            if isinstance(cicd, list):
                result_artifacts.extend(cicd)
            elif isinstance(cicd, dict):
                result_artifacts.append(cicd)

        # Generate deployment documentation
        logger.info("generating_deployment_docs", task_id=task_id)
        deploy_doc = await tools.generate_deployment_documentation(
            artifacts=result_artifacts,
            metadata=metadata,
        )
        if isinstance(deploy_doc, dict):
            result_artifacts.append(deploy_doc)

    except Exception as exc:
        logger.error(
            "task_processing_failed",
            task_id=task_id,
            error=str(exc),
            exc_info=True,
        )
        return _build_result_message(
            task_id=task_id,
            claim=f"DevOps processing failed: {exc}",
            evidence=str(exc),
            suggestion="Review error and retry. If persistent, escalate to TechLead.",
            artifacts=[],
        )

    # Build success result message
    result_message = _build_result_message(
        task_id=task_id,
        claim=(
            f"DevOps deliverables generated successfully. "
            f"Created {len(result_artifacts)} artifact(s): "
            + ", ".join(a.get("name", "unnamed") for a in result_artifacts)
        ),
        evidence=(
            "Generated artifacts follow production best practices: "
            "non-root containers, multi-stage builds, pinned versions, "
            "health checks, resource limits, structured JSON logging."
        ),
        suggestion=(
            "All services include health check endpoints. "
            "Run 'docker-compose up' to verify. "
            "Review CI/CD workflows for any environment-specific adjustments."
        ),
        artifacts=result_artifacts,
    )

    logger.info(
        "task_processing_complete",
        task_id=task_id,
        artifact_count=len(result_artifacts),
    )

    return result_message


def _build_result_message(
    task_id: str,
    claim: str,
    evidence: str,
    suggestion: str,
    artifacts: list[Dict[str, Any]],
) -> Dict[str, Any]:
    """Construct a well-formed A2A result message."""
    return {
        "protocol": "a2a/1.0",
        "type": "result",
        "from": AGENT_NAME,
        "to": PUSH_TO_AGENTS[0],
        "task_id": task_id,
        "round": 1,
        "payload": {
            "claim": claim,
            "evidence": evidence,
            "suggestion": suggestion,
            "artifacts": artifacts,
            "metadata": {
                "agent": AGENT_NAME,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "output_types": OUTPUT_TYPES,
            },
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Push result to downstream agent(s)
# ---------------------------------------------------------------------------


async def _push_to_downstream(result_message: Dict[str, Any]) -> None:
    """Push the result message to all downstream agents via A2A.

    For each agent in PUSH_TO_AGENTS, send the result message.
    """
    import httpx

    # Agent service discovery: derive URL from agent name
    agent_port_map = {
        "po": 8000,
        "pm": 8001,
        "ba": 8002,
        "solution_architect": 8003,
        "frontend_dev": 8004,
        "backend_dev": 8005,
        "uiux_reviewer": 8006,
        "security_reviewer": 8007,
        "qa": 8008,
        "devops": 8009,
        "techlead": 8010,
    }

    task_id = result_message.get("task_id", "unknown")

    for target_agent in PUSH_TO_AGENTS:
        target_port = agent_port_map.get(target_agent, 8010)
        target_url = os.getenv(
            f"{target_agent.upper()}_URL",
            f"http://{target_agent}:{target_port}",
        )

        logger.info(
            "pushing_result_to_downstream",
            task_id=task_id,
            target_agent=target_agent,
            target_url=target_url,
        )

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{target_url}/a2a",
                    json=result_message,
                )
                if response.status_code in (200, 202):
                    logger.info(
                        "push_success",
                        task_id=task_id,
                        target=target_agent,
                        status=response.status_code,
                    )
                else:
                    logger.warning(
                        "push_unexpected_status",
                        task_id=task_id,
                        target=target_agent,
                        status=response.status_code,
                        body=response.text[:500],
                    )
        except Exception as exc:
            logger.error(
                "push_failed",
                task_id=task_id,
                target=target_agent,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------


async def worker_loop() -> None:
    """Background worker that processes queued A2A messages.

    Continuously pops messages from the task queue, processes them,
    and pushes results to downstream agents.  After pushing, it
    immediately picks the next task — no idle waiting.
    """
    logger.info("worker_started", agent=AGENT_NAME)

    while True:
        try:
            task = await queue.pop()
            if task is None:
                await asyncio.sleep(WORKER_POLL_INTERVAL)
                continue

            task_id = task.get("task_id", "unknown")
            logger.info("worker_picked_task", task_id=task_id)

            # Process the task
            result = await _process_task(task)

            # Push result to downstream agents
            await _push_to_downstream(result)

            # Acknowledge completion
            if hasattr(queue, "ack"):
                await queue.ack(task_id)

            logger.info("worker_task_done", task_id=task_id)

        except asyncio.CancelledError:
            logger.info("worker_cancelled", agent=AGENT_NAME)
            break
        except Exception as exc:
            logger.error("worker_error", error=str(exc), exc_info=True)
            await asyncio.sleep(WORKER_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Lifecycle events
# ---------------------------------------------------------------------------

_worker_task: Optional[asyncio.Task] = None


@app.on_event("startup")
async def on_startup() -> None:
    """Start the background worker task on application startup."""
    global _worker_task
    logger.info(
        "agent_starting",
        agent=AGENT_NAME,
        display_name=DISPLAY_NAME,
        port=PORT,
        capabilities=CAPABILITIES,
    )
    await queue.recover_stuck_tasks()
    _worker_task = asyncio.create_task(worker_loop())
    logger.info("background_worker_launched", agent=AGENT_NAME)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Gracefully cancel the background worker on application shutdown."""
    global _worker_task
    logger.info("agent_shutting_down", agent=AGENT_NAME)
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    logger.info("agent_stopped", agent=AGENT_NAME)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "agents.devops.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=bool(os.getenv("RELOAD", "")),
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
    )