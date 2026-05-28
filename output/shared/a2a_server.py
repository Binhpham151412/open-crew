from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

A2A_PROTOCOL = "a2a/1.0"
VALID_MESSAGE_TYPES: Set[str] = {
    "task",
    "challenge",
    "response",
    "final_position",
    "escalate",
    "decision",
    "result",
}

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class Payload(BaseModel):
    """Payload carried inside an A2A message."""

    claim: str = Field(..., description="Description of the problem or result")
    evidence: str = Field(default="", description="File, line number, or concrete data")
    suggestion: str = Field(default="", description="Proposed action")
    artifacts: List[Dict[str, Any]] = Field(
        default_factory=list,
        description='Artifact references, e.g. [{"name": "spec.yaml", "content": "..."}]',
    )

    class Config:
        extra = "allow"


class A2AMessage(BaseModel):
    """Schema for an A2A protocol message (v1.0)."""

    protocol: str = Field(..., description="Protocol identifier, must be 'a2a/1.0'")
    type: str = Field(..., description="Message type: task | challenge | response | ...")
    from_: str = Field(..., alias="from", description="Sender agent name")
    to: str = Field(..., description="Recipient agent name")
    task_id: str = Field(..., description="UUID identifying the task/conversation")
    round: int = Field(default=1, ge=1, le=10, description="Debate round number")
    payload: Payload = Field(default_factory=Payload)
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp")

    @field_validator("protocol")
    @classmethod
    def check_protocol(cls, v: str) -> str:
        if v != A2A_PROTOCOL:
            raise ValueError(f"Unsupported protocol: {v!r}. Expected {A2A_PROTOCOL!r}")
        return v

    @field_validator("type")
    @classmethod
    def check_message_type(cls, v: str) -> str:
        if v not in VALID_MESSAGE_TYPES:
            raise ValueError(f"Invalid message type: {v!r}. Must be one of {VALID_MESSAGE_TYPES}")
        return v

    @field_validator("task_id")
    @classmethod
    def check_task_id(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(f"task_id must be a valid UUID: {v!r}") from exc
        return v

    class Config:
        populate_by_name = True
        extra = "allow"


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

# A handler receives a validated A2AMessage and returns a dict response.
A2AHandler = Callable[[A2AMessage], Awaitable[Dict[str, Any]]]


class AgentCard(BaseModel):
    """Agent Card served at /.well-known/agent.json"""

    name: str
    display_name: str
    url: str
    version: str = "1.0.0"
    capabilities: List[str] = Field(default_factory=list)
    input_types: List[str] = Field(default_factory=list)
    output_types: List[str] = Field(default_factory=list)
    protocol: str = A2A_PROTOCOL


# ---------------------------------------------------------------------------
# A2A Server
# ---------------------------------------------------------------------------


class A2AServer:
    """Base class for the A2A (Agent-to-Agent) HTTP server.

    Each agent in the OpenCrew system creates an ``A2AServer`` instance,
    registers one or more message handlers, and mounts the generated
    :class:`fastapi.APIRouter` on its own FastAPI application.

    Usage::

        a2a = A2AServer(agent_name="backend-dev", port=8005)

        async def handle_task(msg: A2AMessage) -> dict:
            ...

        a2a.register_handler("task", handle_task)

        app.include_router(a2a.router)

    Parameters
    ----------
    agent_name:
        Lowercase hyphenated identifier (e.g. ``"backend-dev"``).
    port:
        Port the agent listens on (e.g. ``8005``).
    display_name:
        Human-readable name.  Defaults to a title-cased version of
        *agent_name*.
    version:
        Semantic version string for the agent card.
    capabilities:
        List of capability identifiers this agent provides.
    input_types:
        Kinds of input the agent can consume.
    output_types:
        Kinds of output the agent can produce.
    base_url:
        Public base URL.  Defaults to ``http://<agent_name>:<port>``.
    """

    def __init__(
        self,
        agent_name: str,
        port: int,
        *,
        display_name: Optional[str] = None,
        version: str = "1.0.0",
        capabilities: Optional[List[str]] = None,
        input_types: Optional[List[str]] = None,
        output_types: Optional[List[str]] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.agent_name: str = agent_name
        self.port: int = port
        self.display_name: str = display_name or agent_name.replace("-", " ").replace("_", " ").title()
        self.version: str = version
        self.capabilities: List[str] = capabilities or []
        self.input_types: List[str] = input_types or []
        self.output_types: List[str] = output_types or []
        self.base_url: str = base_url or f"http://{agent_name}:{port}"

        self._handlers: Dict[str, A2AHandler] = {}

        # Build the FastAPI router ----------------------------------------
        self._router: APIRouter = APIRouter()
        self._register_routes()

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def get_card(self) -> Dict[str, Any]:
        """Return the Agent Card as a JSON-serialisable dict.

        The card is served at ``/.well-known/agent.json`` and allows other
        agents to discover this agent's capabilities.
        """
        card = AgentCard(
            name=self.agent_name,
            display_name=self.display_name,
            url=self.base_url,
            version=self.version,
            capabilities=self.capabilities,
            input_types=self.input_types,
            output_types=self.output_types,
            protocol=A2A_PROTOCOL,
        )
        return card.model_dump()

    def validate_message(self, msg: Dict[str, Any]) -> A2AMessage:
        """Validate a raw message dict against the A2A protocol schema.

        Returns a parsed :class:`A2AMessage` on success.

        Raises
        ------
        ValueError
            If the message is malformed or fails validation.
        """
        return A2AMessage.model_validate(msg)

    def register_handler(self, msg_type: str, handler: A2AHandler) -> None:
        """Register an async handler for a given message type.

        Parameters
        ----------
        msg_type:
            One of ``task``, ``challenge``, ``response``, ``final_position``,
            ``escalate``, ``decision``, ``result``.
        handler:
            An async callable that receives an :class:`A2AMessage` and
            returns a JSON-serialisable ``dict`` response.

        Raises
        ------
        ValueError
            If *msg_type* is not a recognised A2A message type.
        """
        if msg_type not in VALID_MESSAGE_TYPES:
            raise ValueError(
                f"Cannot register handler for unknown type {msg_type!r}. "
                f"Valid types: {sorted(VALID_MESSAGE_TYPES)}"
            )
        self._handlers[msg_type] = handler
        logger.info(
            "Registered handler for type=%r on agent=%s",
            msg_type,
            self.agent_name,
        )

    @property
    def router(self) -> APIRouter:
        """The :class:`fastapi.APIRouter` to include in the agent's app."""
        return self._router

    # -------------------------------------------------------------------
    # Internal — route wiring
    # -------------------------------------------------------------------

    def _register_routes(self) -> None:
        """Wire up the standard A2A endpoints on the internal router."""

        @self._router.get(
            "/.well-known/agent.json",
            summary="Agent Card — auto-discovery",
            tags=["a2a"],
        )
        async def agent_card_endpoint() -> Dict[str, Any]:
            return self.get_card()

        @self._router.get("/health", summary="Health check", tags=["a2a"])
        async def health_endpoint() -> Dict[str, Any]:
            return {
                "status": "ok",
                "agent": self.agent_name,
                "registered_handlers": sorted(self._handlers.keys()),
            }

        @self._router.post(
            "/a2a",
            summary="Receive an A2A message",
            tags=["a2a"],
            status_code=202,
        )
        async def receive_message(request: Request) -> JSONResponse:
            # ---- 1. Parse body ------------------------------------------------
            try:
                body: Dict[str, Any] = await request.json()
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

            # ---- 2. Validate against A2A schema -------------------------------
            try:
                message: A2AMessage = self.validate_message(body)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"A2A validation error: {exc}",
                ) from exc

            # ---- 3. Ensure a handler exists for this type ---------------------
            handler = self._handlers.get(message.type)
            if handler is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"No handler registered for message type {message.type!r}. "
                        f"Registered types: {sorted(self._handlers.keys())}"
                    ),
                )

            logger.info(
                "A2A %s received: type=%s from=%s task_id=%s round=%s",
                self.agent_name,
                message.type,
                message.from_,
                message.task_id,
                message.round,
            )

            # ---- 4. Dispatch to handler ---------------------------------------
            try:
                result: Dict[str, Any] = await handler(message)
            except Exception as exc:
                logger.exception(
                    "Handler for type=%r on agent=%s raised an exception",
                    message.type,
                    self.agent_name,
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Internal handler error: {exc}",
                ) from exc

            return JSONResponse(
                status_code=202,
                content={
                    "status": "accepted",
                    "task_id": message.task_id,
                    "agent": self.agent_name,
                    "handled_type": message.type,
                    **(result if isinstance(result, dict) else {}),
                },
            )

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def create_response(
        self,
        *,
        msg_type: str,
        from_agent: Optional[str] = None,
        to_agent: str,
        task_id: str,
        round: int = 1,
        claim: str = "",
        evidence: str = "",
        suggestion: str = "",
        artifacts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Build an A2A message dict ready to be sent to another agent.

        This is a convenience factory — agents can use it when they need to
        craft a response / challenge / escalate message.

        Returns
        -------
        dict
            A JSON-serialisable dict conforming to the A2A message schema.
        """
        return {
            "protocol": A2A_PROTOCOL,
            "type": msg_type,
            "from": from_agent or self.agent_name,
            "to": to_agent,
            "task_id": task_id,
            "round": round,
            "payload": {
                "claim": claim,
                "evidence": evidence,
                "suggestion": suggestion,
                "artifacts": artifacts or [],
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_registered_types(self) -> List[str]:
        """Return a sorted list of message types that have handlers."""
        return sorted(self._handlers.keys())

    def has_handler(self, msg_type: str) -> bool:
        """Check whether a handler is registered for *msg_type*."""
        return msg_type in self._handlers

    def __repr__(self) -> str:
        return (
            f"A2AServer(agent={self.agent_name!r}, port={self.port}, "
            f"handlers={self.get_registered_types()})"
        )