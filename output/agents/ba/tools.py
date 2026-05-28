"""MCP tool implementations for the Business Analyst agent.

Provides a :func:`get_tools` factory that returns a dictionary mapping tool
names to callables.  Each callable either wraps an MCP client invocation
(``context7``, ``linear_mcp``) or implements purely local analysis logic.

Design notes:
    * ``get_tools(mcp_client)`` binds the shared :class:`MCPClient` instance
      to every tool that needs it, returning self-contained callables whose
      signature is ``(task_context: dict) -> dict``.
    * All tools return a plain ``dict`` with at least ``"success"`` and
      ``"result"`` keys so callers can handle failures uniformly.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Callable, Dict, List, Optional

import structlog
import yaml

log = structlog.get_logger("ba.tools")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_STORY_PATTERN = re.compile(
    r"as\s+a\s+.+?,\s*i\s+want\s+.+?,\s*so\s+that\s+.+",
    re.IGNORECASE,
)

_GHERKIN_STEPS = {"given", "when", "then", "and", "but"}

_OPENAPI_REQUIRED_KEYS = {"openapi", "info", "paths"}
_OPENAPI_INFO_REQUIRED = {"title", "version"}

_CONTEXT7_TOOL_RESOLVE = "resolve-library-id"
_CONTEXT7_TOOL_DOCS = "get-library-docs"
_LINEAR_TOOL_UPDATE = "update_story"
_LINEAR_TOOL_SUBTASK = "create_subtask"


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def get_tools(mcp_client: Any) -> Dict[str, Callable[..., Any]]:
    """Return a dictionary of tool-name → callable for the BA agent.

    Args:
        mcp_client: An initialised :class:`shared.mcp_client.MCPClient`
            instance pre-configured with ``context7`` and ``linear_mcp``
            server connections.

    Returns:
        Mapping of tool names to async (or sync) callables that accept a
        single ``task_context: dict`` argument and return a ``dict`` with
        ``"success"`` and ``"result"`` keys.
    """

    # -- MCP-backed tools ---------------------------------------------------

    async def context7_resolve_library(task_context: dict) -> dict:
        """Resolve a library or framework identifier via Context7.

        Args:
            task_context: Must contain ``"library_name"`` (str) and may
                contain ``"topic"`` (str, optional).

        Returns:
            ``{"success": True, "result": {"library_id": ..., "topic": ...}}``
            on success, or an error dict.
        """
        library_name: str = task_context.get("library_name", "")
        if not library_name:
            return {"success": False, "error": "library_name is required"}

        topic: str = task_context.get("topic", "")

        try:
            result = await mcp_client.call(
                tool=_CONTEXT7_TOOL_RESOLVE,
                arguments={"query": library_name},
            )
            log.info(
                "context7_resolve_library",
                library_name=library_name,
                topic=topic,
            )
            return {
                "success": True,
                "result": {"library_id": result, "topic": topic},
            }
        except Exception as exc:
            log.error("context7_resolve_library_failed", error=str(exc))
            return {"success": False, "error": str(exc)}

    async def context7_get_docs(task_context: dict) -> dict:
        """Retrieve documentation snippets from Context7.

        Args:
            task_context: Must contain ``"library_id"`` (str) and may
                contain ``"topic"`` (str) and ``"tokens"`` (int).

        Returns:
            ``{"success": True, "result": {"docs": ...}}`` on success.
        """
        library_id: str = task_context.get("library_id", "")
        if not library_id:
            return {"success": False, "error": "library_id is required"}

        topic: str = task_context.get("topic", "general")
        tokens: int = task_context.get("tokens", 8000)

        arguments: dict[str, Any] = {
            "library_id": library_id,
            "tokens": tokens,
        }
        if topic:
            arguments["topic"] = topic

        try:
            result = await mcp_client.call(
                tool=_CONTEXT7_TOOL_DOCS,
                arguments=arguments,
            )
            log.info("context7_get_docs", library_id=library_id, topic=topic)
            return {"success": True, "result": {"docs": result}}
        except Exception as exc:
            log.error("context7_get_docs_failed", error=str(exc))
            return {"success": False, "error": str(exc)}

    async def linear_update_story(task_context: dict) -> dict:
        """Update a Linear Story with BA artifacts.

        Merges the current description with user stories, acceptance criteria,
        API spec summary, and data-model overview.

        Args:
            task_context: Must contain ``"story_id"`` (str) and at least one
                of ``"user_stories"``, ``"acceptance_criteria"``,
                ``"api_spec_summary"``, ``"data_model_summary"`` (all str).

        Returns:
            ``{"success": True, "result": {...}}`` with the Linear update
            response.
        """
        story_id: str = task_context.get("story_id", "")
        if not story_id:
            return {"success": False, "error": "story_id is required"}

        # Build a rich description block from whatever BA outputs are present.
        sections: list[str] = []
        if task_context.get("user_stories"):
            sections.append(f"## User Stories\n\n{task_context['user_stories']}")
        if task_context.get("acceptance_criteria"):
            sections.append(
                f"## Acceptance Criteria\n\n{task_context['acceptance_criteria']}"
            )
        if task_context.get("api_spec_summary"):
            sections.append(
                f"## API Contract Summary\n\n{task_context['api_spec_summary']}"
            )
        if task_context.get("data_model_summary"):
            sections.append(
                f"## Data Model\n\n{task_context['data_model_summary']}"
            )

        if not sections:
            return {"success": False, "error": "No BA content to update"}

        description = "\n\n---\n\n".join(sections)

        arguments: dict[str, Any] = {"id": story_id, "description": description}
        if task_context.get("labels"):
            arguments["labelIds"] = task_context["labels"]

        try:
            result = await mcp_client.call(
                tool=_LINEAR_TOOL_UPDATE,
                arguments=arguments,
            )
            log.info("linear_update_story", story_id=story_id)
            return {"success": True, "result": result}
        except Exception as exc:
            log.error("linear_update_story_failed", story_id=story_id, error=str(exc))
            return {"success": False, "error": str(exc)}

    async def linear_create_subtask(task_context: dict) -> dict:
        """Create a sub-task on a Linear Story.

        Args:
            task_context: Must contain ``"parent_story_id"`` (str) and
                ``"title"`` (str).  Optional: ``"description"`` (str).

        Returns:
            ``{"success": True, "result": {"subtask_id": ...}}`` on success.
        """
        parent_story_id: str = task_context.get("parent_story_id", "")
        title: str = task_context.get("title", "")
        if not parent_story_id or not title:
            return {
                "success": False,
                "error": "parent_story_id and title are required",
            }

        arguments: dict[str, Any] = {
            "parentId": parent_story_id,
            "title": title,
        }
        if task_context.get("description"):
            arguments["description"] = task_context["description"]

        try:
            result = await mcp_client.call(
                tool=_LINEAR_TOOL_SUBTASK,
                arguments=arguments,
            )
            log.info("linear_create_subtask", parent_story_id=parent_story_id, title=title)
            return {"success": True, "result": result}
        except Exception as exc:
            log.error("linear_create_subtask_failed", error=str(exc))
            return {"success": False, "error": str(exc)}

    # -- Local logic tools --------------------------------------------------

    def write_user_stories(task_context: dict) -> dict:
        """Generate structured User Stories from a PM Story.

        Args:
            task_context: Must contain ``"story_description"`` (str).
                Optional: ``"roles"`` (list[str]), ``"prd_context"`` (str).

        Returns:
            ``{"success": True, "result": {"user_stories": [...]}}``
            where each element has ``role``, ``goal``, ``benefit``,
            ``acceptance_criteria``, and ``raw`` keys.
        """
        story_description: str = task_context.get("story_description", "")
        if not story_description:
            return {"success": False, "error": "story_description is required"}

        roles: list[str] = task_context.get("roles", ["user"])
        prd_context: str = task_context.get("prd_context", "")

        user_stories: list[dict[str, str]] = []
        for role in roles:
            user_stories.append(
                {
                    "role": role,
                    "goal": story_description,
                    "benefit": f"achieve the expected outcome described in: {story_description[:120]}",
                    "acceptance_criteria": "",
                    "raw": (
                        f"As a {role}, I want {story_description}, "
                        f"so that I can achieve the described outcome."
                    ),
                }
            )

        log.info("write_user_stories", count=len(user_stories), roles=roles)
        return {"success": True, "result": {"user_stories": user_stories}}

    def write_acceptance_criteria(task_context: dict) -> dict:
        """Generate Gherkin-style Acceptance Criteria.

        Args:
            task_context: Must contain ``"story_description"`` (str).
                Optional: ``"happy_paths"`` (list[str]),
                ``"edge_cases"`` (list[str]),
                ``"error_cases"`` (list[str]).

        Returns:
            ``{"success": True, "result": {"acceptance_criteria": "<Gherkin>"}}``
        """
        story_description: str = task_context.get("story_description", "")
        if not story_description:
            return {"success": False, "error": "story_description is required"}

        happy_paths: list[str] = task_context.get("happy_paths", [])
        edge_cases: list[str] = task_context.get("edge_cases", [])
        error_cases: list[str] = task_context.get("error_cases", [])

        # Fallback defaults when the caller supplies no specifics.
        if not happy_paths:
            happy_paths = [
                f"User successfully completes the action: {story_description[:80]}",
            ]
        if not edge_cases:
            edge_cases = [
                "User submits with all optional fields empty",
                "User submits with maximum-length input values",
            ]
        if not error_cases:
            error_cases = [
                "User submits with invalid/missing required fields",
                "Backend service is temporarily unavailable",
            ]

        scenarios: list[str] = []

        # Happy-path scenarios (≈40 %)
        for idx, path in enumerate(happy_paths, start=1):
            scenarios.append(
                f"  Scenario: Happy path #{idx} — {path}\n"
                f"    Given the user is authenticated\n"
                f"    And the system is ready to process the request\n"
                f"    When the user performs: {path}\n"
                f"    Then the operation succeeds\n"
                f"    And the user receives a confirmation response"
            )

        # Edge-case scenarios (≈35 %)
        for idx, edge in enumerate(edge_cases, start=1):
            scenarios.append(
                f"  Scenario: Edge case #{idx} — {edge}\n"
                f"    Given the user is authenticated\n"
                f"    And {edge.lower()}\n"
                f"    When the user submits the request\n"
                f"    Then the system handles the input gracefully\n"
                f"    And no unexpected errors are raised"
            )

        # Error-case scenarios (≈25 %)
        for idx, err in enumerate(error_cases, start=1):
            scenarios.append(
                f"  Scenario: Error case #{idx} — {err}\n"
                f"    Given the user is on the relevant page\n"
                f"    And {err.lower()}\n"
                f"    When the user attempts the action\n"
                f"    Then the system returns an appropriate error message\n"
                f"    And no partial data is persisted"
            )

        gherkin = f"Feature: {story_description[:100]}\n\n" + "\n\n".join(scenarios)
        total = len(happy_paths) + len(edge_cases) + len(error_cases)

        log.info(
            "write_acceptance_criteria",
            total_scenarios=total,
            happy=len(happy_paths),
            edge=len(edge_cases),
            error=len(error_cases),
        )
        return {"success": True, "result": {"acceptance_criteria": gherkin}}

    def write_api_spec(task_context: dict) -> dict:
        """Generate an OpenAPI 3.0 YAML specification.

        Args:
            task_context: Must contain ``"endpoints"`` (list[dict]).
                Each endpoint dict should have: ``"path"`` (str),
                ``"method"`` (str), ``"summary"`` (str).
                Optional per endpoint: ``"request_schema"`` (dict),
                ``"response_schema"`` (dict),
                ``"error_codes"`` (list[int]).

        Returns:
            ``{"success": True, "result": {"api_spec": "<YAML string>"}}``
        """
        endpoints: list[dict[str, Any]] = task_context.get("endpoints", [])
        if not endpoints:
            return {"success": False, "error": "endpoints list is required"}

        spec: dict[str, Any] = {
            "openapi": "3.0.3",
            "info": {
                "title": task_context.get("title", "BA Generated API"),
                "version": task_context.get("version", "1.0.0"),
                "description": task_context.get(
                    "description", "API contract generated by OpenCrew BA agent"
                ),
            },
            "paths": {},
        }

        for ep in endpoints:
            path: str = ep.get("path", "/")
            method: str = ep.get("method", "get").lower()
            summary: str = ep.get("summary", "")

            path_item: dict[str, Any] = {
                "summary": summary,
                "responses": {},
            }

            # Request body
            request_schema = ep.get("request_schema")
            if request_schema and method in {"post", "put", "patch"}:
                path_item["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {"schema": request_schema}
                    },
                }

            # Success response
            response_schema = ep.get("response_schema", {"type": "object"})
            path_item["responses"]["200"] = {
                "description": "Successful response",
                "content": {
                    "application/json": {"schema": response_schema}
                },
            }

            # Error responses
            error_codes: list[int] = ep.get("error_codes", [400, 401, 404, 500])
            for code in error_codes:
                path_item["responses"][str(code)] = {
                    "description": f"Error {code}",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "error": {"type": "string"},
                                    "detail": {"type": "string"},
                                },
                                "required": ["error"],
                            }
                        }
                    },
                }

            spec["paths"].setdefault(path, {})[method] = path_item

        api_spec_yaml: str = yaml.dump(spec, default_flow_style=False, sort_keys=False, allow_unicode=True)
        log.info("write_api_spec", endpoints_count=len(endpoints))
        return {"success": True, "result": {"api_spec": api_spec_yaml}}

    def write_data_model(task_context: dict) -> dict:
        """Generate a data model with entities, relations, and constraints.

        Args:
            task_context: Must contain ``"entities"`` (list[dict]).
                Each entity: ``"name"`` (str), ``"fields"`` (list[dict]).
                Each field: ``"name"`` (str), ``"type"`` (str),
                ``"nullable"`` (bool, default False),
                ``"primary_key"`` (bool, default False).
                Optional: ``"relationships"`` (list[dict]) with ``"from"``,
                ``"to"``, ``"type"`` (one_to_many | many_to_one | many_to_many),
                ``"foreign_key"``.

        Returns:
            ``{"success": True, "result": {"data_model": {...}}}``
        """
        entities_raw: list[dict[str, Any]] = task_context.get("entities", [])
        if not entities_raw:
            return {"success": False, "error": "entities list is required"}

        relationships_raw: list[dict[str, Any]] = task_context.get("relationships", [])

        entities: list[dict[str, Any]] = []
        for ent in entities_raw:
            entity_name: str = ent.get("name", "unnamed_entity")
            fields_raw: list[dict[str, Any]] = ent.get("fields", [])

            fields: list[dict[str, Any]] = []
            primary_keys: list[str] = []

            for f in fields_raw:
                fname: str = f.get("name", "id")
                ftype: str = f.get("type", "string")
                nullable: bool = f.get("nullable", False)
                is_pk: bool = f.get("primary_key", False)

                field_entry: dict[str, Any] = {
                    "name": fname,
                    "type": ftype,
                    "nullable": nullable,
                    "primary_key": is_pk,
                }
                if f.get("unique"):
                    field_entry["unique"] = True
                if f.get("default") is not None:
                    field_entry["default"] = f["default"]
                if f.get("max_length"):
                    field_entry["max_length"] = f["max_length"]

                fields.append(field_entry)
                if is_pk:
                    primary_keys.append(fname)

            # Ensure every entity has at least a default `id` primary key.
            if not primary_keys:
                fields.insert(
                    0,
                    {
                        "name": "id",
                        "type": "uuid",
                        "nullable": False,
                        "primary_key": True,
                    },
                )
                primary_keys = ["id"]

            entities.append(
                {
                    "name": entity_name,
                    "fields": fields,
                    "primary_keys": primary_keys,
                }
            )

        # Normalise relationships.
        relationships: list[dict[str, Any]] = []
        for rel in relationships_raw:
            relationships.append(
                {
                    "from": rel.get("from", ""),
                    "to": rel.get("to", ""),
                    "type": rel.get("type", "one_to_many"),
                    "foreign_key": rel.get("foreign_key", ""),
                }
            )

        data_model: dict[str, Any] = {
            "entities": entities,
            "relationships": relationships,
            "constraints": task_context.get("constraints", []),
        }

        log.info(
            "write_data_model",
            entities_count=len(entities),
            relationships_count=len(relationships),
        )
        return {"success": True, "result": {"data_model": data_model}}

    # -- Validation tools ---------------------------------------------------

    def validate_user_stories(task_context: dict) -> dict:
        """Validate that user stories follow the standard format.

        Expected format: ``As a [role], I want [goal], so that [benefit]``

        Args:
            task_context: Must contain ``"user_stories"`` (list of str).

        Returns:
            ``{"success": True, "result": {"valid": bool, "issues": [...]}}``
        """
        user_stories: list[str] = task_context.get("user_stories", [])
        if not user_stories:
            return {"success": False, "error": "user_stories list is required"}

        issues: list[str] = []
        for idx, story in enumerate(user_stories, start=1):
            if not _USER_STORY_PATTERN.search(story):
                issues.append(
                    f"Story #{idx} does not follow 'As a [role], I want [goal], "
                    f"so that [benefit]' format: '{story[:100]}…'"
                )

        valid = len(issues) == 0
        log.info("validate_user_stories", total=len(user_stories), valid=valid, issues_count=len(issues))
        return {"success": True, "result": {"valid": valid, "issues": issues}}

    def validate_acceptance_criteria(task_context: dict) -> dict:
        """Validate that acceptance criteria use proper Gherkin syntax.

        Each scenario must contain at least Given, When, Then steps.

        Args:
            task_context: Must contain ``"acceptance_criteria"`` (str).

        Returns:
            ``{"success": True, "result": {"valid": bool, "issues": [...]}}``
        """
        acceptance_criteria: str = task_context.get("acceptance_criteria", "")
        if not acceptance_criteria:
            return {"success": False, "error": "acceptance_criteria is required"}

        issues: list[str] = []
        scenarios = [
            s.strip()
            for s in re.split(r"\n\s*Scenario:", acceptance_criteria)
            if s.strip()
        ]

        # The first chunk before the first "Scenario:" is the feature header.
        if scenarios and "Scenario:" not in acceptance_criteria.split("\n")[0]:
            scenarios = scenarios[1:]  # drop the feature preamble

        for idx, scenario in enumerate(scenarios, start=1):
            steps_found: set[str] = set()
            for line in scenario.split("\n"):
                stripped = line.strip().lower()
                for keyword in _GHERKIN_STEPS:
                    if stripped.startswith(keyword):
                        steps_found.add(keyword)

            missing_steps = {"given", "when", "then"} - steps_found
            if missing_steps:
                issues.append(
                    f"Scenario #{idx} is missing required steps: "
                    f"{', '.join(sorted(missing_steps))}"
                )

        valid = len(issues) == 0
        log.info(
            "validate_acceptance_criteria",
            scenarios_count=len(scenarios),
            valid=valid,
            issues_count=len(issues),
        )
        return {"success": True, "result": {"valid": valid, "issues": issues}}

    def validate_api_spec(task_context: dict) -> dict:
        """Validate an OpenAPI specification string.

        Args:
            task_context: Must contain ``"api_spec"`` (str, YAML).

        Returns:
            ``{"success": True, "result": {"valid": bool, "issues": [...]}}``
        """
        api_spec_str: str = task_context.get("api_spec", "")
        if not api_spec_str:
            return {"success": False, "error": "api_spec is required"}

        issues: list[str] = []

        # Parse YAML.
        try:
            spec = yaml.safe_load(api_spec_str)
        except yaml.YAMLError as exc:
            return {
                "success": True,
                "result": {"valid": False, "issues": [f"YAML parse error: {exc}"]},
            }

        if not isinstance(spec, dict):
            return {
                "success": True,
                "result": {"valid": False, "issues": ["Spec is not a YAML mapping"]},
            }

        # Top-level required keys.
        missing_top = _OPENAPI_REQUIRED_KEYS - spec.keys()
        if missing_top:
            issues.append(f"Missing top-level keys: {', '.join(sorted(missing_top))}")

        # Info block.
        info = spec.get("info", {})
        if isinstance(info, dict):
            missing_info = _OPENAPI_INFO_REQUIRED - info.keys()
            if missing_info:
                issues.append(f"Missing info keys: {', '.join(sorted(missing_info))}")

        # Paths validation.
        paths = spec.get("paths", {})
        if not paths:
            issues.append("No paths defined")
        else:
            for path, methods in paths.items():
                if not isinstance(methods, dict):
                    issues.append(f"Path '{path}' is not a mapping")
                    continue
                for method, details in methods.items():
                    if method not in {
                        "get", "post", "put", "patch", "delete",
                        "head", "options", "trace",
                    }:
                        continue  # skip non-HTTP keys like "parameters"
                    if not isinstance(details, dict):
                        issues.append(f"{method.upper()} {path} — not a mapping")
                        continue
                    if "responses" not in details:
                        issues.append(
                            f"{method.upper()} {path} — missing 'responses'"
                        )

        valid = len(issues) == 0
        log.info("validate_api_spec", valid=valid, issues_count=len(issues))
        return {"success": True, "result": {"valid": valid, "issues": issues}}

    # -- Cross-system sync tool ---------------------------------------------

    async def sync_ba_output_to_linear(task_context: dict) -> dict:
        """Convenience wrapper: validate all BA artifacts then update Linear.

        Args:
            task_context: Must contain ``"story_id"`` (str) and one or more of:
                ``"user_stories"`` (list[str]), ``"acceptance_criteria"`` (str),
                ``"api_spec"`` (str, YAML).

        Returns:
            ``{"success": True, "result": {"validation": {...}, "linear_update": {...}}}``
        """
        story_id: str = task_context.get("story_id", "")
        if not story_id:
            return {"success": False, "error": "story_id is required"}

        validation_results: dict[str, Any] = {}

        # Validate user stories.
        if task_context.get("user_stories"):
            validation_results["user_stories"] = validate_user_stories(
                {"user_stories": task_context["user_stories"]}
            )

        # Validate acceptance criteria.
        if task_context.get("acceptance_criteria"):
            validation_results["acceptance_criteria"] = validate_acceptance_criteria(
                {"acceptance_criteria": task_context["acceptance_criteria"]}
            )

        # Validate API spec.
        if task_context.get("api_spec"):
            validation_results["api_spec"] = validate_api_spec(
                {"api_spec": task_context["api_spec"]}
            )

        # Block sync if any validation failed.
        all_valid = all(
            v.get("result", {}).get("valid", False) for v in validation_results.values()
        )
        if not all_valid:
            return {
                "success": False,
                "error": "Validation failed — fix issues before syncing to Linear",
                "result": {"validation": validation_results},
            }

        # Build summary strings for the Linear description.
        ac_text: str = task_context.get("acceptance_criteria", "")
        api_spec_text: str = task_context.get("api_spec", "")
        us_lines: list[str] = task_context.get("user_stories", [])

        linear_update = await linear_update_story(
            {
                "story_id": story_id,
                "user_stories": "\n".join(f"- {s}" for s in us_lines),
                "acceptance_criteria": ac_text,
                "api_spec_summary": (
                    f"```yaml\n{api_spec_text[:2000]}\n```"
                    if api_spec_text
                    else ""
                ),
                "data_model_summary": task_context.get("data_model_summary", ""),
            }
        )

        return {
            "success": linear_update.get("success", False),
            "result": {
                "validation": validation_results,
                "linear_update": linear_update,
            },
        }

    # -- Assemble tool registry ---------------------------------------------

    tools: Dict[str, Callable[..., Any]] = {
        # MCP — Context7
        "context7_resolve_library": context7_resolve_library,
        "context7_get_docs": context7_get_docs,
        # MCP — Linear
        "linear_update_story": linear_update_story,
        "linear_create_subtask": linear_create_subtask,
        # Local generation
        "write_user_stories": write_user_stories,
        "write_acceptance_criteria": write_acceptance_criteria,
        "write_api_spec": write_api_spec,
        "write_data_model": write_data_model,
        # Validation
        "validate_user_stories": validate_user_stories,
        "validate_acceptance_criteria": validate_acceptance_criteria,
        "validate_api_spec": validate_api_spec,
        # Orchestration
        "sync_ba_output_to_linear": sync_ba_output_to_linear,
    }

    log.info("tools_registered", tool_names=list(tools.keys()), count=len(tools))
    return tools