from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class A2AMessageType(str, Enum):
    """Valid message types for the A2A protocol."""
    TASK = "task"
    CHALLENGE = "challenge"
    RESPONSE = "response"
    FINAL_POSITION = "final_position"
    ESCALATE = "escalate"
    DECISION = "decision"
    RESULT = "result"


class AgentStatus(str, Enum):
    """Runtime status of an agent."""
    ONLINE = "online"
    OFFLINE = "offline"
    WORKING = "working"
    ERROR = "error"


class TaskStatus(str, Enum):
    """Lifecycle status of a task."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


class Severity(str, Enum):
    """Severity levels used by Security and QA reviewers."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EffortSize(str, Enum):
    """T-shirt sizing for task estimation."""
    S = "S"      # < 2h
    M = "M"      # 2–8h
    L = "L"      # 1–3 days
    XL = "XL"    # needs further breakdown


class ResponseDisposition(str, Enum):
    """How an agent responds to a challenge."""
    ACCEPT = "accept"
    COUNTER = "counter"


# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------

class Artifact(BaseModel):
    """A file or document attached to an A2A message."""
    name: str = Field(..., description="Filename or identifier of the artifact")
    content: str = Field(..., description="Raw content of the artifact (text, YAML, JSON, etc.)")
    mime_type: str | None = Field(
        default=None,
        description="Optional MIME type, e.g. 'application/yaml', 'text/markdown'",
    )

    model_config = {"frozen": False, "extra": "forbid"}


class TaskPayload(BaseModel):
    """Payload carried inside an A2A message.

    Holds the claim, supporting evidence, an optional suggestion for next
    steps, and any file artifacts the sender wants to attach.
    """
    claim: str = Field(..., description="Description of the issue, task, or result")
    evidence: str = Field(
        default="",
        description="Supporting evidence — file:line, data, reasoning",
    )
    suggestion: str = Field(
        default="",
        description="Proposed action for the recipient",
    )
    artifacts: list[Artifact] = Field(
        default_factory=list,
        description="Files or documents attached to this message",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata (e.g. sprint_id, story_id)",
    )

    model_config = {"frozen": False, "extra": "forbid"}


# ---------------------------------------------------------------------------
# A2A Message
# ---------------------------------------------------------------------------

class A2AMessage(BaseModel):
    """Agent-to-Agent message conforming to ``a2a/1.0`` protocol.

    Every inter-agent communication uses this envelope.  The ``payload``
    carries the semantic content while the outer fields handle routing,
    correlation, and debate tracking.
    """
    protocol: str = Field(
        default="a2a/1.0",
        description="Protocol identifier — must be 'a2a/1.0'",
    )
    type: A2AMessageType = Field(..., description="Message type")
    from_agent: str = Field(
        ...,
        alias="from",
        description="Sender agent name (e.g. 'ba', 'backend-dev')",
    )
    to: str = Field(..., description="Recipient agent name")
    task_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="UUID correlating messages belonging to the same task",
    )
    round: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Debate round number (1-3 normal, 4-5 escalated)",
    )
    payload: TaskPayload = Field(
        default_factory=TaskPayload,
        description="Semantic payload of the message",
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="ISO 8601 UTC timestamp",
    )

    model_config = {
        "populate_by_name": True,
        "frozen": False,
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "protocol": "a2a/1.0",
                    "type": "task",
                    "from": "ba",
                    "to": "backend-dev",
                    "task_id": "550e8400-e29b-41d4-a716-446655440000",
                    "round": 1,
                    "payload": {
                        "claim": "Implement POST /api/v1/users registration endpoint",
                        "evidence": "User Story US-101, Acceptance Criteria AC-1..AC-5",
                        "suggestion": "Use bcrypt for password hashing",
                        "artifacts": [
                            {"name": "api_spec.yaml", "content": "..."},
                        ],
                    },
                    "timestamp": "2026-05-27T10:00:00Z",
                }
            ]
        },
    }

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        if v != "a2a/1.0":
            raise ValueError(f"Unsupported protocol '{v}', expected 'a2a/1.0'")
        return v


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

class AgentCard(BaseModel):
    """Discovery card served at ``/.well-known/agent.json``.

    Used by the agent registry and other agents to discover capabilities,
    endpoints, and supported message types.
    """
    name: str = Field(
        ...,
        description="Unique machine-readable agent identifier (e.g. 'backend-dev')",
    )
    display_name: str = Field(
        ...,
        description="Human-friendly name (e.g. 'Backend Developer')",
    )
    url: str = Field(
        ...,
        description="Base URL where the agent listens (e.g. 'http://backend-dev:8005')",
    )
    version: str = Field(
        default="1.0.0",
        description="Semantic version of the agent",
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="List of capability slugs the agent supports",
    )
    input_types: list[str] = Field(
        default_factory=list,
        description="Types of artifacts the agent can accept",
    )
    output_types: list[str] = Field(
        default_factory=list,
        description="Types of artifacts the agent can produce",
    )
    protocol: str = Field(
        default="a2a/1.0",
        description="A2A protocol version",
    )
    port: int | None = Field(
        default=None,
        description="Listening port (informational)",
    )
    status: AgentStatus = Field(
        default=AgentStatus.ONLINE,
        description="Current runtime status",
    )
    model: str | None = Field(
        default=None,
        description="AI model identifier (e.g. 'mimo-v2.5-pro')",
    )
    mcp_tools: list[str] = Field(
        default_factory=list,
        description="MCP tools this agent is allowed to call",
    )
    mcp_permissions: dict[str, str] = Field(
        default_factory=dict,
        description="MCP tool → permission mapping (e.g. 'github_mcp': 'W')",
    )

    model_config = {
        "frozen": False,
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "name": "backend-dev",
                    "display_name": "Backend Developer",
                    "url": "http://backend-dev:8005",
                    "version": "1.0.0",
                    "capabilities": ["implement_api", "fix_bug", "code_review"],
                    "input_types": ["api_spec", "db_schema", "user_story"],
                    "output_types": ["source_code", "pr_url"],
                    "protocol": "a2a/1.0",
                    "port": 8005,
                    "status": "online",
                    "model": "mimo-v2.5-pro",
                    "mcp_tools": ["github_mcp", "context7"],
                    "mcp_permissions": {"github_mcp": "W", "context7": "R"},
                }
            ]
        },
    }


# ---------------------------------------------------------------------------
# Debate Message
# ---------------------------------------------------------------------------

class DebateMessage(BaseModel):
    """Structured representation of an agent debate exchange.

    Wraps an ``A2AMessage`` with additional debate-specific metadata so the
    frontend ``DebateViewer`` can render the conversation properly.
    """
    debate_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique identifier for the debate session",
    )
    task_id: str = Field(..., description="Task that triggered the debate")
    round: int = Field(..., ge=1, le=5, description="Debate round number")
    message: A2AMessage = Field(..., description="The A2A message in this round")
    disposition: ResponseDisposition | None = Field(
        default=None,
        description="For RESPONSE messages: whether the agent accepted or countered",
    )
    escalated: bool = Field(
        default=False,
        description="Whether this debate has been escalated to TechLead",
    )
    resolved: bool = Field(
        default=False,
        description="Whether the debate has been resolved",
    )
    winner: str | None = Field(
        default=None,
        description="Agent name that won the debate (set after TechLead decision)",
    )
    conflict_priority: str | None = Field(
        default=None,
        description="Type of conflict that determines auto-resolution (e.g. 'security', 'accessibility')",
    )

    model_config = {"frozen": False, "extra": "forbid"}


# ---------------------------------------------------------------------------
# Convenience type aliases
# ---------------------------------------------------------------------------

A2AMessageMap = dict[str, Any]
"""Type alias for raw dict representation of an A2A message (for quick serialization)."""
</s>