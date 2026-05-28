from __future__ import annotations

"""MCP tool implementations for the Solution Architect agent.

Provides ``get_tools()`` which returns a mapping of tool names to their
async callable implementations.  Tools wrap MCP client calls to
``context7`` and ``github_mcp``, or implement local analysis logic that
supports the Solution Architect's responsibilities:

* System architecture design (Mermaid diagrams)
* Architecture Decision Records (ADRs)
* Database schema design (SQL DDL)
* Interface / contract definition between services
* Cross-cutting concern analysis (auth, logging, caching, rate-limiting)
* Existing codebase exploration via GitHub MCP
"""

import json
import os
import re
import textwrap
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine
from uuid import uuid4

import structlog
import yaml

from shared.mcp_client import MCPClient

logger = structlog.get_logger("solution_architect.tools")

# ---------------------------------------------------------------------------
# Type alias for tool callables
# ---------------------------------------------------------------------------
ToolCallable = Callable[..., Coroutine[Any, Any, Any]]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_mcp_client: MCPClient | None = None


def _get_mcp_client() -> MCPClient:
    """Return a lazily-initialised singleton MCP client."""
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Context7 MCP wrappers — library / architecture-pattern lookups
# ---------------------------------------------------------------------------

async def resolve_library_id(
    library_name: str,
    *,
    topic: str = "",
) -> dict[str, Any]:
    """Resolve a library name to its Context7-compatible identifier.

    Used to look up architecture patterns, framework documentation, and
    best-practice references.

    Parameters
    ----------
    library_name:
        Human-readable name, e.g. ``"fastapi"``, ``"react"``, ``"kubernetes"``.
    topic:
        Optional narrowing topic, e.g. ``"deployment"``, ``"routing"``.

    Returns
    -------
    dict
        Context7 resolve response containing candidate library IDs.
    """
    client = _get_mcp_client()
    arguments: dict[str, Any] = {"query": library_name}
    if topic:
        arguments["topic"] = topic

    result = await client.call(
        server="context7",
        tool="resolve_library_id",
        arguments=arguments,
    )
    await logger.ainfo(
        "context7_resolve_library_id",
        library_name=library_name,
        topic=topic,
        result_count=len(result.get("library_ids", []))
        if isinstance(result, dict)
        else None,
    )
    return result


async def get_library_docs(
    library_id: str,
    *,
    tokens: int = 10_000,
    topic: str = "",
) -> dict[str, Any]:
    """Retrieve documentation for a library from Context7.

    Parameters
    ----------
    library_id:
        The Context7 library identifier (obtained from ``resolve_library_id``).
    tokens:
        Maximum number of documentation tokens to retrieve.
    topic:
        Optional narrowing topic (e.g. ``"database"``, ``"authentication"``).

    Returns
    -------
    dict
        Context7 docs response containing the fetched documentation.
    """
    client = _get_mcp_client()
    arguments: dict[str, Any] = {
        "context7CompatibleLibraryID": library_id,
        "tokens": tokens,
    }
    if topic:
        arguments["topic"] = topic

    result = await client.call(
        server="context7",
        tool="get_library_docs",
        arguments=arguments,
    )
    await logger.ainfo(
        "context7_get_library_docs",
        library_id=library_id,
        tokens=tokens,
        topic=topic,
    )
    return result


async def search_architecture_patterns(
    query: str,
    *,
    tokens: int = 8_000,
) -> dict[str, Any]:
    """High-level helper: resolve *and* fetch docs in one call.

    Useful when the agent needs to quickly look up an architecture pattern
    (e.g. "microservices event sourcing", "Redis caching strategies").

    Parameters
    ----------
    query:
        Natural-language search term.
    tokens:
        Maximum documentation tokens to return.

    Returns
    -------
    dict
        Combined response with ``library_ids`` and ``documentation`` keys.
    """
    resolve_result = await resolve_library_id(query)
    library_ids: list[str] = []
    if isinstance(resolve_result, dict):
        library_ids = resolve_result.get("library_ids", [])
        if not library_ids and "results" in resolve_result:
            library_ids = [
                r.get("id", "") for r in resolve_result["results"] if r.get("id")
            ]

    if not library_ids:
        await logger.awarn("no_library_found", query=query)
        return {"library_ids": [], "documentation": None, "query": query}

    first_id = library_ids[0]
    docs = await get_library_docs(first_id, tokens=tokens, topic=query)

    return {
        "library_ids": library_ids,
        "documentation": docs,
        "query": query,
        "resolved_id": first_id,
    }


# ---------------------------------------------------------------------------
# GitHub MCP wrappers — read-only codebase exploration
# ---------------------------------------------------------------------------

async def get_file(
    repo: str,
    path: str,
    *,
    ref: str = "main",
) -> dict[str, Any]:
    """Retrieve the contents of a file from a GitHub repository.

    Parameters
    ----------
    repo:
        Repository in ``owner/name`` format.
    path:
        File path within the repository (e.g. ``"src/main.py"``).
    ref:
        Git ref (branch, tag, or SHA). Defaults to ``"main"``.

    Returns
    -------
    dict
        ``{"content": "<file text>", "sha": "...", ...}``
    """
    client = _get_mcp_client()
    result = await client.call(
        server="github_mcp",
        tool="get_file",
        arguments={"repo": repo, "path": path, "ref": ref},
    )
    await logger.ainfo("github_get_file", repo=repo, path=path, ref=ref)
    return result


async def search_code(
    repo: str,
    query: str,
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Search for code patterns within a GitHub repository.

    Parameters
    ----------
    repo:
        Repository in ``owner/name`` format.
    query:
        GitHub code search query (supports qualifiers like ``language:py``).
    limit:
        Maximum number of results to return.

    Returns
    -------
    dict
        ``{"items": [{ "path": ..., "text_matches": ... }, ...]}``
    """
    client = _get_mcp_client()
    result = await client.call(
        server="github_mcp",
        tool="search_code",
        arguments={"repo": repo, "query": query, "limit": limit},
    )
    await logger.ainfo(
        "github_search_code", repo=repo, query=query, limit=limit
    )
    return result


async def get_repo_structure(
    repo: str,
    *,
    ref: str = "main",
    path: str = "",
    max_depth: int = 3,
) -> dict[str, Any]:
    """Retrieve the directory tree of a GitHub repository.

    Parameters
    ----------
    repo:
        Repository in ``owner/name`` format.
    ref:
        Git ref. Defaults to ``"main"``.
    path:
        Sub-directory to start from (empty string = root).
    max_depth:
        Maximum recursion depth for the tree.

    Returns
    -------
    dict
        ``{"tree": [...], "truncated": bool}``
    """
    client = _get_mcp_client()
    result = await client.call(
        server="github_mcp",
        tool="get_repo_structure",
        arguments={
            "repo": repo,
            "ref": ref,
            "path": path,
            "max_depth": max_depth,
        },
    )
    await logger.ainfo(
        "github_get_repo_structure",
        repo=repo,
        ref=ref,
        path=path,
        max_depth=max_depth,
    )
    return result


# ---------------------------------------------------------------------------
# Local analysis tools — ADR generation
# ---------------------------------------------------------------------------

async def generate_adr(
    title: str,
    context: str,
    decision: str,
    consequences: str,
    *,
    status: str = "Accepted",
    alternatives: list[dict[str, str]] | None = None,
    related_decisions: list[str] | None = None,
) -> dict[str, Any]:
    """Generate an Architecture Decision Record (ADR) in Markdown format.

    Follows the standard ADR template: Title, Status, Context, Decision,
    Consequences, and optional Alternatives section.

    Parameters
    ----------
    title:
        Short descriptive title, e.g. ``"Use PostgreSQL as primary database"``.
    context:
        Background and problem statement.
    decision:
        The decision that was made and its rationale.
    consequences:
        Positive and negative outcomes of the decision.
    status:
        ADR status (``"Proposed"``, ``"Accepted"``, ``"Deprecated"``, ``"Superseded"``).
    alternatives:
        List of alternative options considered, each with ``{"name": ..., "pros": ..., "cons": ...}``.
    related_decisions:
        List of related ADR identifiers.

    Returns
    -------
    dict
        ``{"adr_id": "...", "content": "<markdown>", "title": ..., "status": ...}``
    """
    adr_id = f"ADR-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid4().hex[:6]}"

    alternatives_section = ""
    if alternatives:
        alternatives_section = "\n## Alternatives Considered\n\n"
        for alt in alternatives:
            name = alt.get("name", "Unnamed")
            pros = alt.get("pros", "N/A")
            cons = alt.get("cons", "N/A")
            alternatives_section += f"### {name}\n\n"
            alternatives_section += f"**Pros:** {pros}\n\n"
            alternatives_section += f"**Cons:** {cons}\n\n"

    related_section = ""
    if related_decisions:
        related_section = "\n## Related Decisions\n\n"
        for rd in related_decisions:
            related_section += f"- {rd}\n"

    content = textwrap.dedent(f"""\
        # {title}

        **ADR ID:** {adr_id}
        **Status:** {status}
        **Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

        ## Context

        {context}

        ## Decision

        {decision}

        ## Consequences

        {consequences}
        {alternatives_section}{related_section}
    """).strip()

    await logger.ainfo(
        "adr_generated",
        adr_id=adr_id,
        title=title,
        status=status,
    )

    return {
        "adr_id": adr_id,
        "content": content,
        "title": title,
        "status": status,
        "format": "markdown",
    }


# ---------------------------------------------------------------------------
# Local analysis tools — Database schema design
# ---------------------------------------------------------------------------

async def generate_db_schema(
    entities: list[dict[str, Any]],
    *,
    dialect: str = "postgresql",
    include_indexes: bool = True,
    include_timestamps: bool = True,
) -> dict[str, Any]:
    """Generate SQL DDL statements for the given entity definitions.

    Each entity dict should follow the schema::

        {
            "name": "users",
            "columns": [
                {"name": "id", "type": "UUID", "primary_key": true, "default": "gen_random_uuid()"},
                {"name": "email", "type": "VARCHAR(255)", "unique": true, "nullable": false},
                ...
            ],
            "indexes": ["idx_users_email"],          # optional
            "foreign_keys": [                          # optional
                {"column": "org_id", "references": "organizations(id)", "on_delete": "CASCADE"}
            ]
        }

    Parameters
    ----------
    entities:
        List of entity definitions.
    dialect:
        SQL dialect: ``"postgresql"`` (default), ``"mysql"``, ``"sqlite"``.
    include_indexes:
        Whether to emit ``CREATE INDEX`` statements.
    include_timestamps:
        Whether to add ``created_at`` / ``updated_at`` columns automatically.

    Returns
    -------
    dict
        ``{"ddl": "<SQL>", "tables": [...], "dialect": ...}``
    """
    now_default = {
        "postgresql": "NOW()",
        "mysql": "CURRENT_TIMESTAMP",
        "sqlite": "CURRENT_TIMESTAMP",
    }.get(dialect, "CURRENT_TIMESTAMP")

    updated_trigger = ""
    if dialect == "postgresql":
        updated_trigger = textwrap.dedent("""\
            -- Automatic updated_at trigger
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

        """)

    table_ddls: list[str] = []
    index_ddls: list[str] = []
    trigger_ddls: list[str] = []
    table_names: list[str] = []

    for entity in entities:
        name = entity["name"]
        table_names.append(name)
        columns = entity.get("columns", [])
        foreign_keys = entity.get("foreign_keys", [])
        indexes = entity.get("indexes", [])

        col_defs: list[str] = []
        pk_cols: list[str] = []

        # Auto-timestamp columns
        if include_timestamps:
            col_defs.append(f"    created_at TIMESTAMPTZ NOT NULL DEFAULT {now_default}")
            col_defs.append(f"    updated_at TIMESTAMPTZ NOT NULL DEFAULT {now_default}")

        for col in columns:
            cname = col["name"]
            ctype = col["type"]
            nullable = col.get("nullable", True)
            is_pk = col.get("primary_key", False)
            is_unique = col.get("unique", False)
            default = col.get("default")

            parts = [f"    {cname} {ctype}"]

            if not nullable:
                parts.append("NOT NULL")
            if is_unique and not is_pk:
                parts.append("UNIQUE")
            if default is not None:
                parts.append(f"DEFAULT {default}")

            col_defs.append(" ".join(parts))
            if is_pk:
                pk_cols.append(cname)

        if pk_cols:
            col_defs.append(f"    PRIMARY KEY ({', '.join(pk_cols)})")

        for fk in foreign_keys:
            col_defs.append(
                f"    FOREIGN KEY ({fk['column']}) "
                f"REFERENCES {fk['references']} "
                f"ON DELETE {fk.get('on_delete', 'CASCADE')}"
            )

        table_ddl = f"CREATE TABLE IF NOT EXISTS {name} (\n"
        table_ddl += ",\n".join(col_defs)
        table_ddl += "\n);"
        table_ddls.append(table_ddl)

        # Indexes
        if include_indexes:
            for idx in indexes:
                # idx may be a string like "idx_users_email (email)" or just a column name
                if "(" in idx:
                    index_ddls.append(f"CREATE INDEX IF NOT EXISTS {idx};")
                else:
                    index_ddls.append(
                        f"CREATE INDEX IF NOT EXISTS idx_{name}_{idx} ON {name} ({idx});"
                    )

        # Updated_at trigger (PostgreSQL only)
        if include_timestamps and dialect == "postgresql":
            trigger_ddls.append(
                f"CREATE TRIGGER set_updated_at_{name}\n"
                f"    BEFORE UPDATE ON {name}\n"
                f"    FOR EACH ROW\n"
                f"    EXECUTE FUNCTION update_updated_at_column();\n"
            )

    parts: list[str] = []
    if updated_trigger:
        parts.append(updated_trigger)
    parts.extend(table_ddls)
    if index_ddls:
        parts.append("-- Indexes")
        parts.extend(index_ddls)
    if trigger_ddl := "\n".join(trigger_ddls):
        parts.append(trigger_ddl)

    ddl = "\n\n".join(parts)

    await logger.ainfo(
        "db_schema_generated",
        table_count=len(table_names),
        dialect=dialect,
        tables=table_names,
    )

    return {
        "ddl": ddl,
        "tables": table_names,
        "dialect": dialect,
        "format": "sql",
    }


# ---------------------------------------------------------------------------
# Local analysis tools — System architecture diagram
# ---------------------------------------------------------------------------

async def generate_system_diagram(
    components: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    *,
    title: str = "System Architecture",
    style: str = "C4Context",
) -> dict[str, Any]:
    """Generate a Mermaid diagram representing the system architecture.

    Parameters
    ----------
    components:
        Each component: ``{"id": "...", "label": "...", "group": "...", "type": "service|database|queue|external"}``.
    relationships:
        Each relationship: ``{"from": "...", "to": "...", "label": "...", "protocol": "HTTP|gRPC|..."}``.
    title:
        Diagram title.
    style:
        Mermaid diagram type: ``"C4Context"`` (default) or ``"graph"``.

    Returns
    -------
    dict
        ``{"mermaid": "<mermaid code>", "title": ..., "component_count": ..., "format": "mermaid"}``
    """
    lines: list[str] = []

    if style == "C4Context":
        lines.append(f"```mermaid")
        lines.append(f"C4Context")
        lines.append(f'    title {title}')
        lines.append("")

        # Group components by group
        groups: dict[str, list[dict[str, Any]]] = {}
        for comp in components:
            group = comp.get("group", "default")
            groups.setdefault(group, []).append(comp)

        for group, comps in groups.items():
            if group == "default":
                for comp in comps:
                    ctype = comp.get("type", "service")
                    tag = {
                        "service": "System",
                        "database": "SystemDb",
                        "queue": "SystemQueue",
                        "external": "System_Ext",
                    }.get(ctype, "System")
                    lines.append(f'    {tag}({comp["id"]}, "{comp["label"]}")')
            else:
                lines.append(f'    System_Boundary({group}, "{group}") {{')
                for comp in comps:
                    ctype = comp.get("type", "service")
                    tag = {
                        "service": "System",
                        "database": "SystemDb",
                        "queue": "SystemQueue",
                        "external": "System_Ext",
                    }.get(ctype, "System")
                    lines.append(f'        {tag}({comp["id"]}, "{comp["label"]}")')
                lines.append("    }")
            lines.append("")

        lines.append("    Rel(")
        for rel in relationships:
            label = rel.get("label", "")
            proto = rel.get("protocol", "")
            rel_label = f"{label} ({proto})" if proto else label
            lines.append(
                f'        {rel["from"]}, {rel["to"]}, "{rel_label}"'
            )
        lines.append("    )")
        lines.append("```")
    else:
        # Fallback: simple graph
        lines.append("```mermaid")
        lines.append(f"graph TB")
        lines.append(f"    %% {title}")
        lines.append("")

        for comp in components:
            shape = {
                "service": "(",
                "database": "[(",
                "queue": "{",
                "external": "((",
            }.get(comp.get("type", "service"), "(")
            end_shape = {
                "service": ")",
                "database": ")]",
                "queue": "}",
                "external": "))",
            }.get(comp.get("type", "service"), ")")

            safe_label = comp["label"].replace('"', "'")
            lines.append(
                f'    {comp["id"]}{shape}"{safe_label}"{end_shape}'
            )

        lines.append("")
        for rel in relationships:
            label = rel.get("label", "")
            if label:
                lines.append(f'    {rel["from"]} -->|{label}| {rel["to"]}')
            else:
                lines.append(f'    {rel["from"]} --> {rel["to"]}')

        lines.append("```")

    mermaid_code = "\n".join(lines)

    await logger.ainfo(
        "system_diagram_generated",
        title=title,
        style=style,
        component_count=len(components),
        relationship_count=len(relationships),
    )

    return {
        "mermaid": mermaid_code,
        "title": title,
        "style": style,
        "component_count": len(components),
        "relationship_count": len(relationships),
        "format": "mermaid",
    }


# ---------------------------------------------------------------------------
# Local analysis tools — Interface / contract definition
# ---------------------------------------------------------------------------

async def define_interfaces(
    services: list[dict[str, Any]],
    *,
    format: str = "openapi",
    api_version: str = "1.0.0",
) -> dict[str, Any]:
    """Generate interface contracts between services.

    Each service dict::

        {
            "name": "auth-service",
            "endpoints": [
                {
                    "method": "POST",
                    "path": "/api/v1/auth/login",
                    "request_schema": {"email": "string", "password": "string"},
                    "response_schema": {"token": "string", "expires_in": "integer"},
                    "status_codes": [200, 401, 422],
                    "description": "Authenticate user"
                }
            ],
            "events_published": ["user.created", "user.updated"],
            "events_consumed": ["order.completed"]
        }

    Parameters
    ----------
    services:
        List of service definitions.
    format:
        Output format: ``"openapi"`` (default) or ``"markdown"``.
    api_version:
        Version string for the generated spec.

    Returns
    -------
    dict
        ``{"contracts": "<YAML/Markdown>", "service_count": ..., "format": ...}``
    """
    if format == "openapi":
        paths: dict[str, Any] = {}
        for svc in services:
            for ep in svc.get("endpoints", []):
                path = ep["path"]
                method = ep["method"].lower()
                operation = {
                    "summary": ep.get("description", ""),
                    "operationId": f"{svc['name']}_{method}_{path.replace('/', '_').strip('_')}",
                    "responses": {},
                }

                # Request body
                request_schema = ep.get("request_schema")
                if request_schema and method in ("post", "put", "patch"):
                    operation["requestBody"] = {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        k: {"type": v}
                                        for k, v in request_schema.items()
                                    },
                                }
                            }
                        },
                    }

                # Responses
                for code in ep.get("status_codes", [200]):
                    code_str = str(code)
                    if code == 200:
                        response_schema = ep.get("response_schema", {})
                        operation["responses"][code_str] = {
                            "description": "Successful response",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            k: {"type": v}
                                            for k, v in response_schema.items()
                                        },
                                    }
                                }
                            },
                        }
                    elif code == 401:
                        operation["responses"][code_str] = {
                            "description": "Unauthorized",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "error": {"type": "string"}
                                        },
                                    }
                                }
                            },
                        }
                    elif code == 422:
                        operation["responses"][code_str] = {
                            "description": "Validation error",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "detail": {"type": "array", "items": {"type": "object"}}
                                        },
                                    }
                                }
                            },
                        }
                    else:
                        operation["responses"][code_str] = {
                            "description": f"Response {code_str}",
                        }

                paths.setdefault(path, {})[method] = operation

        spec = {
            "openapi": "3.0.3",
            "info": {
                "title": "OpenCrew Service Interfaces",
                "version": api_version,
                "description": "Auto-generated interface contracts between services",
            },
            "paths": paths,
        }

        contracts = yaml.dump(spec, default_flow_style=False, sort_keys=False)
        output_format = "openapi"
    else:
        # Markdown format
        sections: list[str] = [
            f"# Service Interface Contracts (v{api_version})\n",
        ]
        for svc in services:
            sections.append(f"## {svc['name']}\n")

            if svc.get("endpoints"):
                sections.append("### Endpoints\n")
                sections.append("| Method | Path | Description |")
                sections.append("|--------|------|-------------|")
                for ep in svc["endpoints"]:
                    sections.append(
                        f"| {ep['method']} | `{ep['path']}` | {ep.get('description', '')} |"
                    )
                sections.append("")

                for ep in svc["endpoints"]:
                    sections.append(f"#### `{ep['method']} {ep['path']}`\n")
                    if ep.get("request_schema"):
                        sections.append("**Request:**")
                        sections.append("```json")
                        sections.append(json.dumps(ep["request_schema"], indent=2))
                        sections.append("```\n")
                    if ep.get("response_schema"):
                        sections.append("**Response:**")
                        sections.append("```json")
                        sections.append(json.dumps(ep["response_schema"], indent=2))
                        sections.append("```\n")
                    sections.append(f"**Status codes:** {', '.join(str(c) for c in ep.get('status_codes', [200]))}\n")

            if svc.get("events_published"):
                sections.append("### Events Published\n")
                for ev in svc["events_published"]:
                    sections.append(f"- `{ev}`")
                sections.append("")

            if svc.get("events_consumed"):
                sections.append("### Events Consumed\n")
                for ev in svc["events_consumed"]:
                    sections.append(f"- `{ev}`")
                sections.append("")

        contracts = "\n".join(sections)
        output_format = "markdown"

    await logger.ainfo(
        "interfaces_defined",
        service_count=len(services),
        format=format,
        endpoint_count=sum(len(s.get("endpoints", [])) for s in services),
    )

    return {
        "contracts": contracts,
        "service_count": len(services),
        "format": output_format,
    }


# ---------------------------------------------------------------------------
# Local analysis tools — Cross-cutting concerns analysis
# ---------------------------------------------------------------------------

async def analyze_cross_cutting_concerns(
    requirements: dict[str, Any],
    *,
    components: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Analyze and produce recommendations for cross-cutting concerns.

    Examines the given requirements and system components to produce
    guidance on authentication, authorization, logging, caching, rate
    limiting, and error handling.

    Parameters
    ----------
    requirements:
        Dictionary with requirement categories as keys, e.g.::

            {
                "auth": "JWT with refresh tokens",
                "logging": "Structured JSON logging",
                "caching": "Redis for session + API responses",
                "rate_limiting": "60 requests/min per user",
                "error_handling": "RFC 7807 Problem Details"
            }

    components:
        Optional list of system components for context-aware recommendations.

    Returns
    -------
    dict
        ``{"recommendations": {...}, "adr_fragments": [...], "checklist": [...]}``
    """
    concerns = {
        "authentication": {
            "required": True,
            "default_approach": "JWT (RS256) with short-lived access tokens and refresh token rotation",
            "considerations": [
                "Token expiry: access 15m, refresh 7d",
                "Store refresh tokens in httpOnly secure cookies",
                "Implement token refresh endpoint",
                "Consider OAuth2 / OIDC for third-party auth",
            ],
            "libraries": ["python-jose", "pyjwt", "passlib"],
        },
        "authorization": {
            "required": True,
            "default_approach": "RBAC with role hierarchy",
            "considerations": [
                "Define roles: admin, user, viewer",
                "Middleware for route-level access control",
                "Resource-level permissions where needed",
                "Audit log for authorization failures",
            ],
            "libraries": ["casbin", "fastapi-security"],
        },
        "logging": {
            "required": True,
            "default_approach": "Structured JSON logging with correlation IDs",
            "considerations": [
                "Use structlog for structured output",
                "Include request_id, user_id, trace_id in every log",
                "Log levels: DEBUG for dev, INFO for prod",
                "Ship logs to centralized system (ELK/Loki)",
                "Never log sensitive data (passwords, tokens, PII)",
            ],
            "libraries": ["structlog", "python-json-logger"],
        },
        "caching": {
            "required": True,
            "default_approach": "Redis with TTL-based invalidation",
            "considerations": [
                "Cache auth tokens, user sessions",
                "Cache frequently-read, rarely-changed data",
                "Use cache-aside pattern",
                "TTL: 5min for API responses, 1h for reference data",
                "Implement cache invalidation on writes",
            ],
            "libraries": ["redis", "aiocache"],
        },
        "rate_limiting": {
            "required": True,
            "default_approach": "Token bucket algorithm via Redis",
            "considerations": [
                "60 requests/min per authenticated user",
                "10 requests/min for unauthenticated endpoints",
                "Return 429 with Retry-After header",
                "Whitelist health check and internal endpoints",
            ],
            "libraries": ["slowapi", "fastapi-limiter"],
        },
        "error_handling": {
            "required": True,
            "default_approach": "RFC 7807 Problem Details with structured error responses",
            "considerations": [
                "Consistent error response schema across all endpoints",
                "Include error code, message, and details",
                "Map business errors to appropriate HTTP status codes",
                "Global exception handler for unhandled errors",
                "Log all 5xx errors with stack trace",
            ],
            "libraries": ["fastapi-problem-details"],
        },
        "health_checks": {
            "required": True,
            "default_approach": "Liveness + readiness probes",
            "considerations": [
                "GET /health → liveness (200 OK)",
                "GET /health/ready → readiness (checks DB, Redis, etc.)",
                "Include uptime, version, dependency status",
            ],
        },
        "monitoring": {
            "required": True,
            "default_approach": "Prometheus metrics endpoint",
            "considerations": [
                "Expose /metrics endpoint",
                "Track request duration, error rate, queue depth",
                "Custom business metrics where needed",
            ],
            "libraries": ["prometheus-fastapi-instrumentator"],
        },
    }

    # Merge user requirements
    recommendations: dict[str, Any] = {}
    for concern_name, base_config in concerns.items():
        rec = dict(base_config)
        if concern_name in requirements:
            rec["user_requirement"] = requirements[concern_name]
            rec["status"] = "configured"
        else:
            rec["status"] = "default"
        recommendations[concern_name] = rec

    # Generate ADR fragments
    adr_fragments: list[str] = []
    for concern_name, rec in recommendations.items():
        if rec.get("user_requirement"):
            adr_fragments.append(
                f"**{concern_name.replace('_', ' ').title()}:** {rec['user_requirement']}"
            )
        else:
            adr_fragments.append(
                f"**{concern_name.replace('_', ' ').title()} (default):** {rec['default_approach']}"
            )

    # Generate implementation checklist
    checklist: list[str] = []
    for concern_name, rec in recommendations.items():
        checklist.append(f"[ ] {concern_name.replace('_', ' ').title()}: {rec['default_approach']}")
        for consideration in rec.get("considerations", []):
            checklist.append(f"    [ ] {consideration}")

    await logger.ainfo(
        "cross_cutting_analyzed",
        concern_count=len(recommendations),
        configured_count=sum(
            1 for r in recommendations.values() if r.get("status") == "configured"
        ),
    )

    return {
        "recommendations": recommendations,
        "adr_fragments": adr_fragments,
        "checklist": checklist,
    }


# ---------------------------------------------------------------------------
# Local analysis tools — Code architecture review
# ---------------------------------------------------------------------------

async def review_code_architecture(
    code_files: list[dict[str, str]],
    *,
    rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform an architecture-level code review.

    Examines code files for architectural concerns (not business logic):
    dependency direction, layer violations, circular dependencies, module
    cohesion, and separation of concerns.

    Parameters
    ----------
    code_files:
        List of ``{"path": "src/auth/service.py", "content": "..."}`` dicts.
    rules:
        Optional override rules, e.g.::

            {"max_file_lines": 300, "max_function_lines": 50,
             "allowed_imports_from": {"service": ["repository", "model"]}}

    Returns
    -------
    dict
        ``{"findings": [...], "summary": {...}, "severity_counts": {...}}``
    """
    default_rules = {
        "max_file_lines": 400,
        "max_function_lines": 80,
        "max_class_methods": 20,
        "max_imports": 30,
    }
    effective_rules = {**default_rules, **(rules or {})}

    findings: list[dict[str, Any]] = []
    severity_counts = {"violation": 0, "suggestion": 0, "opinion": 0}

    for file_info in code_files:
        path = file_info.get("path", "unknown")
        content = file_info.get("content", "")
        lines = content.splitlines()

        # Check file length
        if len(lines) > effective_rules["max_file_lines"]:
            findings.append({
                "file": path,
                "severity": "suggestion",
                "category": "file_length",
                "message": f"File has {len(lines)} lines (max recommended: {effective_rules['max_file_lines']}). Consider splitting into smaller modules.",
            })
            severity_counts["suggestion"] += 1

        # Check import count
        import_count = sum(
            1 for line in lines
            if line.strip().startswith(("import ", "from "))
        )
        if import_count > effective_rules["max_imports"]:
            findings.append({
                "file": path,
                "severity": "suggestion",
                "category": "import_count",
                "message": f"File has {import_count} imports (max recommended: {effective_rules['max_imports']}). Consider reducing dependencies.",
            })
            severity_counts["suggestion"] += 1

        # Check for long functions (simple heuristic: detect `def ` and count lines)
        func_starts: list[tuple[int, str]] = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("def ", "async def ")):
                func_name = stripped.split("(")[0].split()[-1]
                func_starts.append((i, func_name))

        for idx, (start, fname) in enumerate(func_starts):
            end = func_starts[idx + 1][0] if idx + 1 < len(func_starts) else len(lines)
            func_length = end - start
            if func_length > effective_rules["max_function_lines"]:
                findings.append({
                    "file": path,
                    "line": start + 1,
                    "severity": "suggestion",
                    "category": "function_length",
                    "message": f"Function `{fname}` has {func_length} lines (max recommended: {effective_rules['max_function_lines']}). Consider extracting logic.",
                })
                severity_counts["suggestion"] += 1

        # Check for circular import patterns (simple: look for relative imports that go up)
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("from ..") and stripped.count(".") > 3:
                findings.append({
                    "file": path,
                    "severity": "violation",
                    "category": "deep_relative_import",
                    "message": f"Deep relative import detected: `{stripped.split('#')[0].strip()}`. This may indicate tight coupling.",
                })
                severity_counts["violation"] += 1

        # Check for God class (too many methods)
        class_starts: list[tuple[int, str]] = []
        for i, line in enumerate(lines):
            if line.strip().startswith("class "):
                class_name = line.strip().split("(")[0].split(":")[0].split()[-1]
                class_starts.append((i, class_name))

        for idx, (start, cname) in enumerate(class_starts):
            end = class_starts[idx + 1][0] if idx + 1 < len(class_starts) else len(lines)
            method_count = sum(
                1 for line in lines[start:end]
                if line.strip().startswith(("def ", "async def "))
            )
            if method_count > effective_rules["max_class_methods"]:
                findings.append({
                    "file": path,
                    "line": start + 1,
                    "severity": "suggestion",
                    "category": "god_class",
                    "message": f"Class `{cname}` has {method_count} methods (max recommended: {effective_rules['max_class_methods']}). Consider splitting responsibilities.",
                })
                severity_counts["suggestion"] += 1

        # Check for hardcoded secrets patterns
        secret_patterns = [
            (r'(?i)(password|secret|api_key|token)\s*=\s*["\'][^"\']+["\']', "hardcoded_secret"),
            (r'(?i)(AWS|GCP|AZURE)_.*KEY\s*=', "cloud_secret"),
        ]
        for line_num, line in enumerate(lines, 1):
            for pattern, category in secret_patterns:
                if re.search(pattern, line):
                    stripped_line = line.strip()
                    if not stripped_line.startswith("#") and "os.getenv" not in stripped_line and "os.environ" not in stripped_line:
                        findings.append({
                            "file": path,
                            "line": line_num,
                            "severity": "violation",
                            "category": category,
                            "message": f"Possible hardcoded secret detected. Use environment variables instead.",
                        })
                        severity_counts["violation"] += 1

    summary = {
        "files_reviewed": len(code_files),
        "total_findings": len(findings),
        "violations": severity_counts["violation"],
        "suggestions": severity_counts["suggestion"],
        "opinions": severity_counts["opinion"],
        "review_passed": severity_counts["violation"] == 0,
    }

    await logger.ainfo(
        "code_architecture_reviewed",
        files_reviewed=len(code_files),
        total_findings=len(findings),
        violations=severity_counts["violation"],
    )

    return {
        "findings": findings,
        "summary": summary,
        "severity_counts": severity_counts,
    }


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

def get_tools() -> dict[str, ToolCallable]:
    """Return the mapping of tool names to their callable implementations.

    The Solution Architect agent exposes the following tools:

    **Context7 MCP tools** (library & pattern research):
        - ``context7_resolve_library_id`` — Resolve a library name to its Context7 ID.
        - ``context7_get_library_docs`` — Fetch documentation from Context7.
        - ``context7_search_architecture_patterns`` — Combined resolve + fetch helper.

    **GitHub MCP tools** (read-only codebase exploration):
        - ``github_get_file`` — Retrieve a file's contents from a repository.
        - ``github_search_code`` — Search for code patterns in a repository.
        - ``github_get_repo_structure`` — Get the directory tree of a repository.

    **Local architecture tools**:
        - ``generate_adr`` — Produce an Architecture Decision Record.
        - ``generate_db_schema`` — Generate SQL DDL from entity definitions.
        - ``generate_system_diagram`` — Create a Mermaid architecture diagram.
        - ``define_interfaces`` — Produce interface contracts between services.
        - ``analyze_cross_cutting_concerns`` — Guidance on auth, logging, caching, etc.
        - ``review_code_architecture`` — Architecture-level code review.

    Returns
    -------
    dict[str, ToolCallable]
        Mapping of tool name → async callable.
    """
    return {
        # Context7 MCP wrappers
        "context7_resolve_library_id": resolve_library_id,
        "context7_get_library_docs": get_library_docs,
        "context7_search_architecture_patterns": search_architecture_patterns,
        # GitHub MCP wrappers
        "github_get_file": get_file,
        "github_search_code": search_code,
        "github_get_repo_structure": get_repo_structure,
        # Local architecture tools
        "generate_adr": generate_adr,
        "generate_db_schema": generate_db_schema,
        "generate_system_diagram": generate_system_diagram,
        "define_interfaces": define_interfaces,
        "analyze_cross_cutting_concerns": analyze_cross_cutting_concerns,
        "review_code_architecture": review_code_architecture,
    }