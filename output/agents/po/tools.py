"""MCP tool implementations for the Product Owner (PO) agent.

Provides wrappers around the ``context7`` and ``linear_mcp`` MCP servers
that the PO uses to research domain knowledge and manage Linear Epics /
Stories while generating PRDs.

Usage inside ``main.py``::

    from .tools import get_tools
    tools = get_tools()
    # tools["definitions"] → list[dict] for LLM tool-calling
    # tools["handlers"]    → dict[str, Callable] for execution
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Callable

import structlog

from shared.mcp_client import MCPClient, MCPError

log = structlog.get_logger()

# ── MCP server identifiers ──────────────────────────────────────────────

LINEAR_MCP: str = os.getenv("LINEAR_MCP_SERVER", "linear_mcp")
CONTEXT7_MCP: str = os.getenv("CONTEXT7_MCP_SERVER", "context7")

# ── OpenAI-style tool definitions for the LLM ──────────────────────────

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_epic",
            "description": (
                "Create an Epic in Linear that represents a high-level product "
                "initiative derived from the PRD. Returns the created Epic ID "
                "and URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short, descriptive title for the Epic (e.g. 'User Registration System').",
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "Detailed description of the Epic — typically the "
                            "executive summary section of the PRD."
                        ),
                    },
                    "priority": {
                        "type": "integer",
                        "enum": [1, 2, 3, 4],
                        "description": (
                            "Linear priority: 1 = Urgent, 2 = High, 3 = Medium, "
                            "4 = Low."
                        ),
                    },
                    "team_id": {
                        "type": "string",
                        "description": "Optional Linear team ID. Defaults to the configured team.",
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional label names to attach to the Epic.",
                    },
                },
                "required": ["title", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_story",
            "description": (
                "Create an individual Story (issue) in Linear under the "
                "current Epic. Used when the PO needs to break the PRD into "
                "initial, high-level deliverables before handing off to the PM."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Story title.",
                    },
                    "description": {
                        "type": "string",
                        "description": (
                            "Story description including acceptance hints "
                            "and any Definition-of-Done criteria."
                        ),
                    },
                    "epic_id": {
                        "type": "string",
                        "description": "ID of the parent Epic.",
                    },
                    "priority": {
                        "type": "integer",
                        "enum": [1, 2, 3, 4],
                        "description": "Linear priority (1 = Urgent … 4 = Low).",
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional label names.",
                    },
                },
                "required": ["title", "description", "epic_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_epic",
            "description": (
                "Update an existing Linear Epic — e.g. refine description, "
                "change priority, or add labels after PRD iteration."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "epic_id": {
                        "type": "string",
                        "description": "ID of the Epic to update.",
                    },
                    "title": {
                        "type": "string",
                        "description": "New title (omit to keep current).",
                    },
                    "description": {
                        "type": "string",
                        "description": "New description (omit to keep current).",
                    },
                    "priority": {
                        "type": "integer",
                        "enum": [1, 2, 3, 4],
                        "description": "New priority.",
                    },
                    "state": {
                        "type": "string",
                        "description": (
                            "New workflow state name, e.g. 'Done', 'In Progress'."
                        ),
                    },
                },
                "required": ["epic_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_domain_knowledge",
            "description": (
                "Search for domain knowledge, industry standards, or best "
                "practices using Context7. Useful when the PO needs to "
                "understand a technical or business domain before writing the PRD."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "library_name": {
                        "type": "string",
                        "description": (
                            "Name of the library, framework, or topic to look up "
                            "(e.g. 'FastAPI', 'OAuth 2.0', 'SaaS multi-tenancy')."
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Specific question or topic to search for within the "
                            "library / domain docs."
                        ),
                    },
                },
                "required": ["library_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_library_docs",
            "description": (
                "Retrieve documentation pages for a resolved Context7 library "
                "ID. Call ``search_domain_knowledge`` first to obtain the "
                "library ID, then use this tool to fetch detailed docs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "library_id": {
                        "type": "string",
                        "description": "Context7 library ID (returned by resolve_library_id).",
                    },
                    "topic": {
                        "type": "string",
                        "description": (
                            "Optional topic / section to focus on "
                            "(e.g. 'authentication', 'database schema')."
                        ),
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Maximum number of tokens to return (default 5000).",
                    },
                },
                "required": ["library_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "classify_requirements",
            "description": (
                "Classify a list of requirements into Must Have / Should Have / "
                "Nice to Have (MoSCoW). This is a local reasoning tool — no "
                "external call is made."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "requirements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["id", "description"],
                        },
                        "description": "List of requirements to classify.",
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "Additional context about the product or user "
                            "to guide classification."
                        ),
                    },
                },
                "required": ["requirements"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "define_dod",
            "description": (
                "Generate a Definition of Done (DoD) checklist for a given "
                "feature or story. Local reasoning — no external call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "feature_description": {
                        "type": "string",
                        "description": "Description of the feature or story.",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["backend", "frontend", "fullstack", "infra", "data"],
                        "description": "Category of the work to tailor the DoD.",
                    },
                },
                "required": ["feature_description"],
            },
        },
    },
]


# ── Tool handler implementations ────────────────────────────────────────


async def _create_epic(
    mcp: MCPClient,
    *,
    title: str,
    description: str,
    priority: int = 3,
    team_id: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create an Epic on Linear via the ``linear_mcp`` server.

    Parameters
    ----------
    mcp:
        Shared MCP client instance (injected by the caller).
    title:
        Epic title.
    description:
        Epic description.
    priority:
        Linear priority (1-4).
    team_id:
        Optional team identifier.
    labels:
        Optional label names.

    Returns
    -------
    dict
        ``{"epic_id": str, "url": str}`` on success.
    """
    arguments: dict[str, Any] = {
        "title": title,
        "description": description,
        "priority": priority,
    }
    if team_id:
        arguments["teamId"] = team_id
    if labels:
        arguments["labelNames"] = labels

    log.info("linear.create_epic", title=title, priority=priority)
    result = await mcp.call(server=LINEAR_MCP, tool="create_epic", arguments=arguments)

    epic_id: str = result.get("id", "")
    url: str = result.get("url", "")
    log.info("linear.epic_created", epic_id=epic_id, url=url)
    return {"epic_id": epic_id, "url": url}


async def _create_story(
    mcp: MCPClient,
    *,
    title: str,
    description: str,
    epic_id: str,
    priority: int = 3,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a Story in Linear under the given Epic.

    Parameters
    ----------
    mcp:
        Shared MCP client.
    title:
        Story title.
    description:
        Story description (acceptance hints, DoD criteria).
    epic_id:
        Parent Epic ID.
    priority:
        Linear priority (1-4).
    labels:
        Optional label names.

    Returns
    -------
    dict
        ``{"story_id": str, "url": str}`` on success.
    """
    arguments: dict[str, Any] = {
        "title": title,
        "description": description,
        "parentId": epic_id,
        "priority": priority,
    }
    if labels:
        arguments["labelNames"] = labels

    log.info("linear.create_story", title=title, epic_id=epic_id)
    result = await mcp.call(server=LINEAR_MCP, tool="create_story", arguments=arguments)

    story_id: str = result.get("id", "")
    url: str = result.get("url", "")
    log.info("linear.story_created", story_id=story_id, url=url)
    return {"story_id": story_id, "url": url}


async def _update_epic(
    mcp: MCPClient,
    *,
    epic_id: str,
    title: str | None = None,
    description: str | None = None,
    priority: int | None = None,
    state: str | None = None,
) -> dict[str, Any]:
    """Update an existing Epic on Linear.

    Only non-``None`` fields are sent to the server.

    Parameters
    ----------
    mcp:
        Shared MCP client.
    epic_id:
        Target Epic ID.
    title:
        New title (optional).
    description:
        New description (optional).
    priority:
        New priority (optional).
    state:
        New workflow state name (optional).

    Returns
    -------
    dict
        ``{"epic_id": str, "updated_fields": list[str]}``.
    """
    arguments: dict[str, Any] = {"id": epic_id}
    updated: list[str] = []

    if title is not None:
        arguments["title"] = title
        updated.append("title")
    if description is not None:
        arguments["description"] = description
        updated.append("description")
    if priority is not None:
        arguments["priority"] = priority
        updated.append("priority")
    if state is not None:
        arguments["state"] = state
        updated.append("state")

    if not updated:
        log.warn("linear.update_epic_noop", epic_id=epic_id)
        return {"epic_id": epic_id, "updated_fields": []}

    log.info("linear.update_epic", epic_id=epic_id, fields=updated)
    await mcp.call(server=LINEAR_MCP, tool="update_epic", arguments=arguments)
    log.info("linear.epic_updated", epic_id=epic_id, fields=updated)
    return {"epic_id": epic_id, "updated_fields": updated}


async def _search_domain_knowledge(
    mcp: MCPClient,
    *,
    library_name: str,
    query: str = "",
) -> dict[str, Any]:
    """Resolve a library / topic ID via Context7 and optionally search.

    This first calls ``resolve_library_id`` to find the matching library,
    then returns the ID so the caller can follow up with
    ``get_library_docs``.

    Parameters
    ----------
    mcp:
        Shared MCP client.
    library_name:
        Name of the library, framework, or topic.
    query:
        Optional search query to narrow results.

    Returns
    -------
    dict
        ``{"library_id": str, "library_name": str, "query": str}``.
    """
    log.info("context7.resolve_library", library_name=library_name, query=query)

    result = await mcp.call(
        server=CONTEXT7_MCP,
        tool="resolve_library_id",
        arguments={"libraryName": library_name, "query": query} if query else {"libraryName": library_name},
    )

    library_id: str = result.get("id", result.get("library_id", ""))
    resolved_name: str = result.get("name", library_name)

    log.info("context7.library_resolved", library_id=library_id, name=resolved_name)
    return {
        "library_id": library_id,
        "library_name": resolved_name,
        "query": query,
    }


async def _get_library_docs(
    mcp: MCPClient,
    *,
    library_id: str,
    topic: str = "",
    max_tokens: int = 5000,
) -> dict[str, Any]:
    """Fetch documentation pages from Context7 for a resolved library.

    Parameters
    ----------
    mcp:
        Shared MCP client.
    library_id:
        Context7 library identifier (from ``resolve_library_id``).
    topic:
        Optional topic to focus the search.
    max_tokens:
        Maximum token budget for the returned docs.

    Returns
    -------
    dict
        ``{"library_id": str, "topic": str, "content": str, "token_count": int}``.
    """
    arguments: dict[str, Any] = {
        "libraryId": library_id,
        "maxTokens": max_tokens,
    }
    if topic:
        arguments["topic"] = topic

    log.info("context7.get_docs", library_id=library_id, topic=topic, max_tokens=max_tokens)
    result = await mcp.call(server=CONTEXT7_MCP, tool="get_library_docs", arguments=arguments)

    content: str = result.get("content", result.get("text", ""))
    token_count: int = result.get("token_count", len(content.split()))

    log.info("context7.docs_received", library_id=library_id, token_count=token_count)
    return {
        "library_id": library_id,
        "topic": topic,
        "content": content,
        "token_count": token_count,
    }


async def _classify_requirements(
    _mcp: MCPClient,
    *,
    requirements: list[dict[str, str]],
    context: str = "",
) -> dict[str, Any]:
    """Classify requirements into MoSCoW categories.

    This is a **local** reasoning tool — no external MCP call is made.
    The classification is rule-based so that the LLM can use the result as
    a starting scaffold; it may override specific items during PRD writing.

    Parameters
    ----------
    _mcp:
        MCP client (unused — kept for uniform handler signature).
    requirements:
        List of ``{"id": str, "description": str}`` dicts.
    context:
        Additional product / user context.

    Returns
    -------
    dict
        ``{"must_have": [...], "should_have": [...], "nice_to_have": [...]}``.
    """
    log.info("classify_requirements", count=len(requirements), has_context=bool(context))

    # Simple heuristic bucketing — the LLM refines this in the PRD.
    must_have: list[dict[str, str]] = []
    should_have: list[dict[str, str]] = []
    nice_to_have: list[dict[str, str]] = []

    must_keywords = {
        "security", "authentication", "authorization", "critical",
        "required", "must", "compliance", "legal", "core", "essential",
        "mandatory", "data integrity", "encryption",
    }
    should_keywords = {
        "performance", "scalability", "user experience", "important",
        "should", "integration", "monitoring", "logging", "caching",
        "validation",
    }

    for req in requirements:
        desc_lower = req.get("description", "").lower()
        matched_must = any(kw in desc_lower for kw in must_keywords)
        matched_should = any(kw in desc_lower for kw in should_keywords)

        if matched_must:
            must_have.append(req)
        elif matched_should:
            should_have.append(req)
        else:
            nice_to_have.append(req)

    log.info(
        "classify_requirements.result",
        must=len(must_have),
        should=len(should_have),
        nice_to_have=len(nice_to_have),
    )
    return {
        "must_have": must_have,
        "should_have": should_have,
        "nice_to_have": nice_to_have,
    }


async def _define_dod(
    _mcp: MCPClient,
    *,
    feature_description: str,
    category: str = "fullstack",
) -> dict[str, Any]:
    """Generate a Definition of Done checklist for a feature.

    This is a **local** reasoning tool — the checklist is derived from
    the feature category and standard engineering practices. The LLM may
    extend or modify the list.

    Parameters
    ----------
    _mcp:
        MCP client (unused).
    feature_description:
        Description of the feature or story.
    category:
        Work category — one of ``backend``, ``frontend``, ``fullstack``,
        ``infra``, ``data``.

    Returns
    -------
    dict
        ``{"category": str, "checklist": list[str]}``.
    """
    log.info("define_dod", category=category, description_len=len(feature_description))

    # Base checklist applicable to all categories
    base: list[str] = [
        "Code reviewed and approved by at least one peer",
        "All unit tests pass (≥ 80% coverage)",
        "No linting or type-check errors",
        "Documentation updated (inline docstrings + README if needed)",
        "No hardcoded secrets or credentials",
        "Error handling covers all failure modes",
        "Structured logging for key operations",
    ]

    category_extras: dict[str, list[str]] = {
        "backend": [
            "API endpoint returns correct HTTP status codes",
            "Input validation via Pydantic models",
            "Database migrations created and tested",
            "API contract matches the OpenAPI spec",
            "Rate limiting implemented where applicable",
        ],
        "frontend": [
            "Responsive on mobile, tablet, and desktop breakpoints",
            "Dark mode and light mode both functional",
            "Loading, empty, and error states implemented",
            "Accessibility: WCAG 2.1 AA compliance",
            "Touch targets ≥ 44px",
            "Focus states and keyboard navigation work",
        ],
        "fullstack": [
            "API contract matches the OpenAPI spec",
            "Input validation via Pydantic models",
            "Responsive on mobile, tablet, and desktop breakpoints",
            "Loading, empty, and error states implemented",
            "Accessibility: WCAG 2.1 AA compliance",
        ],
        "infra": [
            "Docker image builds successfully (non-root, multi-stage)",
            "Health check endpoint responds 200",
            "Resource limits (CPU/memory) configured",
            "Secrets sourced from environment variables only",
            "CI/CD pipeline green on main branch",
        ],
        "data": [
            "Schema migration reversible",
            "Indexes defined for frequently queried columns",
            "Foreign key constraints enforced",
            "Seed data / fixtures provided for development",
            "Backup and restore procedure documented",
        ],
    }

    checklist = base + category_extras.get(category, category_extras["fullstack"])

    log.info("define_dod.result", category=category, items=len(checklist))
    return {"category": category, "checklist": checklist}


# ── Handler registry ────────────────────────────────────────────────────

def _build_handlers() -> dict[str, Callable[..., Any]]:
    """Build the handler map with a bound MCP client.

    Each handler is a coroutine that accepts only keyword arguments
    matching its OpenAI tool definition.  The ``MCPClient`` instance is
    captured via closure so callers do not need to pass it explicitly.
    """
    mcp_client = MCPClient()

    async def create_epic_handler(**kwargs: Any) -> dict[str, Any]:
        return await _create_epic(mcp_client, **kwargs)

    async def create_story_handler(**kwargs: Any) -> dict[str, Any]:
        return await _create_story(mcp_client, **kwargs)

    async def update_epic_handler(**kwargs: Any) -> dict[str, Any]:
        return await _update_epic(mcp_client, **kwargs)

    async def search_domain_knowledge_handler(**kwargs: Any) -> dict[str, Any]:
        return await _search_domain_knowledge(mcp_client, **kwargs)

    async def get_library_docs_handler(**kwargs: Any) -> dict[str, Any]:
        return await _get_library_docs(mcp_client, **kwargs)

    async def classify_requirements_handler(**kwargs: Any) -> dict[str, Any]:
        return await _classify_requirements(mcp_client, **kwargs)

    async def define_dod_handler(**kwargs: Any) -> dict[str, Any]:
        return await _define_dod(mcp_client, **kwargs)

    return {
        "create_epic": create_epic_handler,
        "create_story": create_story_handler,
        "update_epic": update_epic_handler,
        "search_domain_knowledge": search_domain_knowledge_handler,
        "get_library_docs": get_library_docs_handler,
        "classify_requirements": classify_requirements_handler,
        "define_dod": define_dod_handler,
    }


# ── Public API ──────────────────────────────────────────────────────────

def get_tools() -> dict[str, Any]:
    """Return the PO agent's tool definitions and callable handlers.

    Returns
    -------
    dict
        ``{
            "definitions": list[dict],   # OpenAI function-calling schemas
            "handlers": dict[str, Callable],  # tool_name → async handler
        }``

    Usage::

        tools = get_tools()

        # Feed definitions to the LLM
        response = await call_llm(messages, tools=tools["definitions"])

        # Execute a tool call returned by the LLM
        result = await tools["handlers"][tool_name](**arguments)
    """
    return {
        "definitions": TOOL_DEFINITIONS,
        "handlers": _build_handlers(),
    }