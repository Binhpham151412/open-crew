"""MCP tool implementations for the Project Manager agent.

Provides tools that wrap Linear MCP and GitHub MCP client calls, plus local
logic helpers for breaking down PRDs into stories, estimating effort, and
building sprint plans.

Usage::

    from .tools import get_tools

    tools = get_tools()
    result = await tools["linear_create_sprint"](name="Sprint 1", goal="MVP")
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

import structlog

from shared.mcp_client import MCPClient

logger = structlog.get_logger("pm.tools")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_NAME = "pm"

# Effort heuristics — keywords that hint at complexity
_COMPLEXITY_SIGNALS: dict[str, list[str]] = {
    "XL": [
        "authentication", "authorization", "oauth", "sso", "rbac",
        "payment", "billing", "subscription", "checkout",
        "real-time", "websocket", "sse", "streaming",
        "migration", "data migration", "schema change",
        "third-party integration", "external api", "webhook",
        "machine learning", "ml model", "recommendation",
        "file upload", "s3", "storage", "media processing",
        "search engine", "elasticsearch", "full-text search",
        "caching layer", "redis cache", "distributed cache",
    ],
    "L": [
        "crud", "rest api", "endpoint", "database", "query",
        "form", "validation", "pagination", "filtering",
        "notification", "email", "sms", "push notification",
        "dashboard", "chart", "graph", "visualization",
        "export", "import", "csv", "pdf generation",
        "permission", "role", "access control",
        "settings", "configuration", "admin panel",
    ],
    "M": [
        "page", "component", "modal", "dialog",
        "list", "table", "card", "grid",
        "search", "sort", "select", "dropdown",
        "profile", "avatar", "display",
        "error handling", "loading state", "empty state",
        "responsive", "mobile", "tablet",
    ],
    "S": [
        "button", "link", "icon", "badge",
        "tooltip", "label", "text",
        "fix", "bug", "typo", "style",
        "rename", "refactor", "cleanup",
        "readme", "documentation", "comment",
    ],
}

# Priority mapping for must/should/nice-to-have keywords
_PRIORITY_KEYWORDS: dict[str, list[str]] = {
    "must_have": [
        "must", "required", "critical", "essential", "core",
        "blocker", "p0", "must have", "mandatory",
    ],
    "should_have": [
        "should", "important", "recommended", "needed",
        "significant", "p1", "should have",
    ],
    "nice_to_have": [
        "nice to have", "optional", "could", "p2", "p3",
        "future", "enhancement", "stretch", "wishlist",
    ],
}


# ---------------------------------------------------------------------------
# Effort / priority enums (mirror shared.models.EffortSize)
# ---------------------------------------------------------------------------

class EffortSize(str, Enum):
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class Priority(str, Enum):
    MUST_HAVE = "must_have"
    SHOULD_HAVE = "should_have"
    NICE_TO_HAVE = "nice_to_have"


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

def get_tools(mcp_client: Optional[MCPClient] = None) -> Dict[str, Callable]:
    """Return all PM tools as a name → callable mapping.

    Each callable accepts keyword arguments and returns a serializable dict
    with at least a ``success`` key.  When *mcp_client* is ``None`` the
    returned tools will still be invokable but MCP-backed operations will
    return an error payload.

    Args:
        mcp_client: Optional MCP client instance.  If not provided, MCP
            tools will report that the client is unavailable.

    Returns:
        Dictionary mapping tool names to async callables.
    """

    # --- Linear MCP wrappers -----------------------------------------------

    async def linear_create_sprint(
        *,
        name: str,
        goal: str = "",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new sprint on Linear.

        Args:
            name: Human-readable sprint name (e.g. "Sprint 1").
            goal: Sprint goal or objective.
            start_date: ISO-8601 date string for sprint start.
            end_date: ISO-8601 date string for sprint end.
            team_id: Optional Linear team identifier.

        Returns:
            Dict with ``success`` flag and either ``sprint`` data or ``error``.
        """
        args: dict[str, Any] = {"name": name, "goal": goal}
        if start_date:
            args["startDate"] = start_date
        if end_date:
            args["endDate"] = end_date
        if team_id:
            args["teamId"] = team_id

        logger.info("linear.create_sprint", name=name, goal=goal)
        return await _linear_call(mcp_client, "create_sprint", args)

    async def linear_create_story(
        *,
        title: str,
        description: str = "",
        sprint_id: Optional[str] = None,
        priority: int = 0,
        estimate: Optional[int] = None,
        labels: Optional[List[str]] = None,
        project_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a new story / issue on Linear.

        Args:
            title: Story title.
            description: Detailed description (Markdown supported).
            sprint_id: Linear cycle / sprint identifier.
            priority: 0 = No priority, 1 = Urgent, 2 = High, 3 = Medium, 4 = Low.
            estimate: Story points (Fibonacci: 1, 2, 3, 5, 8, 13).
            labels: List of label names to attach.
            project_id: Optional Linear project identifier.

        Returns:
            Dict with ``success`` flag and either ``story`` data or ``error``.
        """
        args: dict[str, Any] = {
            "title": title,
            "description": description,
            "priority": priority,
        }
        if sprint_id:
            args["cycleId"] = sprint_id
        if estimate is not None:
            args["estimate"] = estimate
        if labels:
            args["labelNames"] = labels
        if project_id:
            args["projectId"] = project_id

        logger.info("linear.create_story", title=title)
        return await _linear_call(mcp_client, "create_story", args)

    async def linear_update_story(
        *,
        story_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[int] = None,
        estimate: Optional[int] = None,
        labels: Optional[List[str]] = None,
    ) -> dict[str, Any]:
        """Update an existing story on Linear.

        Args:
            story_id: Linear issue identifier.
            title: New title (if changing).
            description: New description (if changing).
            status: New status (e.g. "In Progress", "Done").
            priority: New priority level.
            estimate: New story points.
            labels: New label list.

        Returns:
            Dict with ``success`` flag and either ``story`` data or ``error``.
        """
        args: dict[str, Any] = {"id": story_id}
        if title is not None:
            args["title"] = title
        if description is not None:
            args["description"] = description
        if status is not None:
            args["state"] = status
        if priority is not None:
            args["priority"] = priority
        if estimate is not None:
            args["estimate"] = estimate
        if labels is not None:
            args["labelNames"] = labels

        logger.info("linear.update_story", story_id=story_id)
        return await _linear_call(mcp_client, "update_story", args)

    async def linear_assign_story(
        *,
        story_id: str,
        assignee_id: str,
    ) -> dict[str, Any]:
        """Assign a story to a team member on Linear.

        Args:
            story_id: Linear issue identifier.
            assignee_id: Linear user identifier.

        Returns:
            Dict with ``success`` flag and either ``story`` data or ``error``.
        """
        args = {"id": story_id, "assigneeId": assignee_id}

        logger.info("linear.assign_story", story_id=story_id, assignee=assignee_id)
        return await _linear_call(mcp_client, "assign_story", args)

    # --- GitHub MCP wrappers -----------------------------------------------

    async def github_create_milestone(
        *,
        owner: str,
        repo: str,
        title: str,
        description: str = "",
        due_on: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create a milestone on a GitHub repository.

        Args:
            owner: Repository owner (user or org).
            repo: Repository name.
            title: Milestone title (typically matches sprint name).
            description: Milestone description.
            due_on: ISO-8601 due date string.

        Returns:
            Dict with ``success`` flag and either ``milestone`` data or ``error``.
        """
        args: dict[str, Any] = {
            "owner": owner,
            "repo": repo,
            "title": title,
            "description": description,
        }
        if due_on:
            args["due_on"] = due_on

        logger.info("github.create_milestone", owner=owner, repo=repo, title=title)
        return await _github_call(mcp_client, "create_milestone", args)

    async def github_create_label(
        *,
        owner: str,
        repo: str,
        name: str,
        color: str = "0366d6",
        description: str = "",
    ) -> dict[str, Any]:
        """Create a label on a GitHub repository.

        Args:
            owner: Repository owner.
            repo: Repository name.
            name: Label name.
            color: Hex colour code (without ``#``).
            description: Short label description.

        Returns:
            Dict with ``success`` flag and either ``label`` data or ``error``.
        """
        args = {
            "owner": owner,
            "repo": repo,
            "name": name,
            "color": color.lstrip("#"),
            "description": description,
        }

        logger.info("github.create_label", owner=owner, repo=repo, name=name)
        return await _github_call(mcp_client, "create_label", args)

    async def github_create_issue(
        *,
        owner: str,
        repo: str,
        title: str,
        body: str = "",
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
        milestone: Optional[int] = None,
    ) -> dict[str, Any]:
        """Create an issue on a GitHub repository.

        Args:
            owner: Repository owner.
            repo: Repository name.
            title: Issue title.
            body: Issue body (Markdown).
            labels: List of label names.
            assignees: List of GitHub usernames.
            milestone: Milestone number.

        Returns:
            Dict with ``success`` flag and either ``issue`` data or ``error``.
        """
        args: dict[str, Any] = {
            "owner": owner,
            "repo": repo,
            "title": title,
            "body": body,
        }
        if labels:
            args["labels"] = labels
        if assignees:
            args["assignees"] = assignees
        if milestone is not None:
            args["milestone"] = milestone

        logger.info("github.create_issue", owner=owner, repo=repo, title=title)
        return await _github_call(mcp_client, "create_issue", args)

    async def github_add_issue_to_milestone(
        *,
        owner: str,
        repo: str,
        issue_number: int,
        milestone_number: int,
    ) -> dict[str, Any]:
        """Assign an existing issue to a milestone.

        Args:
            owner: Repository owner.
            repo: Repository name.
            issue_number: Issue number.
            milestone_number: Milestone number.

        Returns:
            Dict with ``success`` flag and either ``issue`` data or ``error``.
        """
        args = {
            "owner": owner,
            "repo": repo,
            "issue_number": issue_number,
            "milestone": milestone_number,
        }

        logger.info(
            "github.add_issue_to_milestone",
            issue=issue_number,
            milestone=milestone_number,
        )
        return await _github_call(mcp_client, "update_issue", args)

    # --- Local logic tools -------------------------------------------------

    async def break_down_prd(
        *,
        prd_content: str,
        title: str = "",
    ) -> dict[str, Any]:
        """Break a Product Requirements Document into individual stories.

        Parses the PRD text, identifies discrete features or requirements,
        estimates effort for each, and assigns priority based on keyword
        analysis.  This is a *local* tool — no MCP call is made.

        Args:
            prd_content: Raw PRD text (Markdown or plain text).
            title: Optional title for the overall product / feature.

        Returns:
            Dict with ``success`` flag and ``stories`` list.
        """
        logger.info("break_down_prd", content_length=len(prd_content))

        try:
            stories = _parse_prd_into_stories(prd_content)
            return {
                "success": True,
                "title": title,
                "story_count": len(stories),
                "stories": stories,
            }
        except Exception as exc:
            logger.error("break_down_prd.failed", error=str(exc))
            return {"success": False, "error": f"Failed to parse PRD: {exc}"}

    async def estimate_effort(
        *,
        title: str,
        description: str = "",
    ) -> dict[str, Any]:
        """Estimate effort size for a single story.

        Uses keyword heuristics on the title and description to assign an
        ``S`` / ``M`` / ``L`` / ``XL`` estimate.  This is a *local* tool.

        Args:
            title: Story title.
            description: Story description.

        Returns:
            Dict with ``success``, ``effort`` (EffortSize value), and
            ``reasoning`` explaining the estimate.
        """
        effort, reasoning = _estimate_single_effort(title, description)
        logger.info("estimate_effort", title=title, effort=effort)
        return {
            "success": True,
            "effort": effort,
            "reasoning": reasoning,
        }

    async def build_sprint_plan(
        *,
        stories: List[dict[str, Any]],
        sprint_name: str = "Sprint 1",
        sprint_goal: str = "",
        capacity: int = 40,
        team_members: Optional[List[dict[str, str]]] = None,
    ) -> dict[str, Any]:
        """Build a sprint plan from a list of stories.

        Sorts stories by priority, fills the sprint up to *capacity* story
        points, and assigns stories to *team_members* in round-robin fashion.
        Remaining stories are flagged for the backlog.  This is a *local* tool.

        Args:
            stories: List of story dicts with keys ``title``, ``description``,
                ``effort``, ``priority``, ``story_id``.
            sprint_name: Name for the sprint.
            sprint_goal: Sprint goal.
            capacity: Total story-point capacity for the sprint.
            team_members: List of dicts with ``id`` and ``name``.

        Returns:
            Dict with ``success``, ``sprint_plan``, and ``backlog_stories``.
        """
        logger.info(
            "build_sprint_plan",
            story_count=len(stories),
            capacity=capacity,
        )

        try:
            plan = _build_sprint_plan(
                stories=stories,
                sprint_name=sprint_name,
                sprint_goal=sprint_goal,
                capacity=capacity,
                team_members=team_members or [],
            )
            return {"success": True, **plan}
        except Exception as exc:
            logger.error("build_sprint_plan.failed", error=str(exc))
            return {"success": False, "error": f"Failed to build sprint plan: {exc}"}

    async def create_full_sprint(
        *,
        prd_content: str,
        sprint_name: str = "Sprint 1",
        sprint_goal: str = "",
        capacity: int = 40,
        team_members: Optional[List[dict[str, str]]] = None,
        repo_owner: Optional[str] = None,
        repo_name: Optional[str] = None,
        title: str = "",
    ) -> dict[str, Any]:
        """End-to-end sprint creation: PRD → stories → sprint plan → Linear + GitHub.

        This is the primary orchestration tool for the PM agent.  It:

        1. Breaks down the PRD into stories (local logic).
        2. Creates a sprint on Linear.
        3. Creates each story on Linear.
        4. Optionally creates a GitHub milestone and labels.
        5. Assigns stories to team members.

        Args:
            prd_content: Raw PRD text.
            sprint_name: Name for the sprint.
            sprint_goal: Sprint goal.
            capacity: Story-point capacity.
            team_members: List of dicts with ``id``, ``name``, ``github_username``.
            repo_owner: GitHub repo owner (enables GitHub milestone creation).
            repo_name: GitHub repo name.
            title: Product/feature title.

        Returns:
            Dict with ``success``, ``sprint``, ``stories``, and ``github_milestone``.
        """
        logger.info("create_full_sprint", sprint_name=sprint_name)

        results: dict[str, Any] = {
            "sprint": None,
            "stories": [],
            "github_milestone": None,
            "assignments": [],
            "backlog": [],
        }

        # Step 1 — break down PRD
        breakdown = await break_down_prd(prd_content=prd_content, title=title)
        if not breakdown.get("success"):
            return {"success": False, "error": breakdown.get("error"), **results}

        parsed_stories: list[dict[str, Any]] = breakdown.get("stories", [])

        # Step 2 — build sprint plan
        plan = await build_sprint_plan(
            stories=parsed_stories,
            sprint_name=sprint_name,
            sprint_goal=sprint_goal,
            capacity=capacity,
            team_members=team_members,
        )
        if not plan.get("success"):
            return {"success": False, "error": plan.get("error"), **results}

        sprint_stories = plan.get("sprint_plan", {}).get("stories", [])
        backlog_stories = plan.get("backlog_stories", [])
        results["backlog"] = backlog_stories

        # Step 3 — create sprint on Linear
        now = datetime.now(timezone.utc)
        sprint_result = await linear_create_sprint(
            name=sprint_name,
            goal=sprint_goal,
            start_date=now.isoformat(),
        )
        if not sprint_result.get("success"):
            return {
                "success": False,
                "error": f"Failed to create sprint: {sprint_result.get('error')}",
                **results,
            }
        results["sprint"] = sprint_result.get("sprint")
        sprint_id = (
            results["sprint"].get("id") if isinstance(results["sprint"], dict) else None
        )

        # Step 4 — optionally create GitHub milestone
        milestone_number: Optional[int] = None
        if repo_owner and repo_name:
            gh_result = await github_create_milestone(
                owner=repo_owner,
                repo=repo_name,
                title=sprint_name,
                description=sprint_goal,
            )
            if gh_result.get("success"):
                milestone_data = gh_result.get("milestone", {})
                milestone_number = milestone_data.get("number")
                results["github_milestone"] = milestone_data
            else:
                logger.warning(
                    "create_full_sprint.github_milestone_failed",
                    error=gh_result.get("error"),
                )

        # Step 5 — create stories on Linear and optionally on GitHub
        effort_to_points: dict[str, int] = {"S": 1, "M": 3, "L": 5, "XL": 8}

        for story in sprint_stories:
            effort = story.get("effort", "M")
            points = effort_to_points.get(effort, 3)
            priority = _priority_to_linear(story.get("priority", "should_have"))

            # Create on Linear
            linear_result = await linear_create_story(
                title=story.get("title", "Untitled"),
                description=story.get("description", ""),
                sprint_id=sprint_id,
                priority=priority,
                estimate=points,
                labels=story.get("labels", []),
            )

            linear_story_id: str | None = None
            if linear_result.get("success"):
                linear_story_data = linear_result.get("story", {})
                linear_story_id = linear_story_data.get("id")
            else:
                logger.warning(
                    "create_full_sprint.story_failed",
                    title=story.get("title"),
                    error=linear_result.get("error"),
                )

            # Assign to team member
            assignee = story.get("assigned_to")
            if assignee and linear_story_id:
                assign_result = await linear_assign_story(
                    story_id=linear_story_id,
                    assignee_id=assignee,
                )
                results["assignments"].append(
                    {
                        "story_id": linear_story_id,
                        "assignee_id": assignee,
                        "success": assign_result.get("success", False),
                    }
                )

            # Create GitHub issue and link to milestone
            gh_issue_number: int | None = None
            if repo_owner and repo_name:
                assignee_gh = story.get("assigned_to_github", "")
                gh_issue = await github_create_issue(
                    owner=repo_owner,
                    repo=repo_name,
                    title=f"[{sprint_name}] {story.get('title', 'Untitled')}",
                    body=story.get("description", ""),
                    labels=[effort, story.get("priority", "should_have")],
                    assignees=[assignee_gh] if assignee_gh else None,
                    milestone=milestone_number,
                )
                if gh_issue.get("success"):
                    gh_issue_number = gh_issue.get("issue", {}).get("number")

            results["stories"].append(
                {
                    "title": story.get("title"),
                    "effort": effort,
                    "points": points,
                    "priority": story.get("priority"),
                    "linear_id": linear_story_id,
                    "github_issue": gh_issue_number,
                    "assigned_to": assignee,
                }
            )

        # Step 6 — create backlog stories on Linear (no sprint)
        for story in backlog_stories:
            effort = story.get("effort", "M")
            points = effort_to_points.get(effort, 3)
            priority = _priority_to_linear(story.get("priority", "nice_to_have"))

            await linear_create_story(
                title=story.get("title", "Untitled"),
                description=story.get("description", ""),
                priority=priority,
                estimate=points,
                labels=[*story.get("labels", []), "backlog"],
            )

        logger.info(
            "create_full_sprint.complete",
            sprint_name=sprint_name,
            story_count=len(results["stories"]),
            backlog_count=len(results["backlog"]),
        )

        return {"success": True, **results}

    async def update_progress(
        *,
        sprint_id: str,
        story_updates: List[dict[str, Any]],
    ) -> dict[str, Any]:
        """Batch-update story statuses for progress tracking.

        Args:
            sprint_id: Linear sprint / cycle identifier.
            story_updates: List of dicts with ``story_id`` and ``status``.

        Returns:
            Dict with ``success``, ``updated_count``, and any ``errors``.
        """
        logger.info(
            "update_progress",
            sprint_id=sprint_id,
            update_count=len(story_updates),
        )

        updated = 0
        errors: list[dict[str, str]] = []

        for update in story_updates:
            story_id = update.get("story_id", "")
            status = update.get("status", "")

            if not story_id or not status:
                errors.append(
                    {"story_id": story_id, "error": "Missing story_id or status"}
                )
                continue

            result = await linear_update_story(story_id=story_id, status=status)
            if result.get("success"):
                updated += 1
            else:
                errors.append(
                    {"story_id": story_id, "error": result.get("error", "Unknown error")}
                )

        return {
            "success": len(errors) == 0,
            "updated_count": updated,
            "errors": errors,
        }

    # --- Register all tools -----------------------------------------------

    return {
        # Linear MCP tools
        "linear_create_sprint": linear_create_sprint,
        "linear_create_story": linear_create_story,
        "linear_update_story": linear_update_story,
        "linear_assign_story": linear_assign_story,
        # GitHub MCP tools
        "github_create_milestone": github_create_milestone,
        "github_create_label": github_create_label,
        "github_create_issue": github_create_issue,
        "github_add_issue_to_milestone": github_add_issue_to_milestone,
        # Local logic tools
        "break_down_prd": break_down_prd,
        "estimate_effort": estimate_effort,
        "build_sprint_plan": build_sprint_plan,
        "create_full_sprint": create_full_sprint,
        "update_progress": update_progress,
    }


# ---------------------------------------------------------------------------
# MCP client helpers
# ---------------------------------------------------------------------------

async def _linear_call(
    mcp_client: Optional[MCPClient],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a call to the Linear MCP server.

    Args:
        mcp_client: MCP client instance (may be ``None``).
        tool_name: Tool name without the ``linear_`` prefix — the prefix is
            added automatically.
        arguments: Tool arguments.

    Returns:
        MCP response dict or an error payload.
    """
    if mcp_client is None:
        return {"success": False, "error": "MCP client not initialised"}

    full_tool_name = f"linear_{tool_name}"

    try:
        result = await mcp_client.call(
            server="linear_mcp",
            tool=full_tool_name,
            arguments=arguments,
        )
        return result
    except Exception as exc:
        logger.error("mcp.linear_call.failed", tool=full_tool_name, error=str(exc))
        return {"success": False, "error": f"Linear MCP call failed: {exc}"}


async def _github_call(
    mcp_client: Optional[MCPClient],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch a call to the GitHub MCP server.

    Args:
        mcp_client: MCP client instance (may be ``None``).
        tool_name: Tool name without the ``github_`` prefix.
        arguments: Tool arguments.

    Returns:
        MCP response dict or an error payload.
    """
    if mcp_client is None:
        return {"success": False, "error": "MCP client not initialised"}

    full_tool_name = f"github_{tool_name}"

    try:
        result = await mcp_client.call(
            server="github_mcp",
            tool=full_tool_name,
            arguments=arguments,
        )
        return result
    except Exception as exc:
        logger.error("mcp.github_call.failed", tool=full_tool_name, error=str(exc))
        return {"success": False, "error": f"GitHub MCP call failed: {exc}"}


# ---------------------------------------------------------------------------
# PRD parsing logic
# ---------------------------------------------------------------------------

def _parse_prd_into_stories(prd_content: str) -> list[dict[str, Any]]:
    """Parse a PRD document into a list of story dicts.

    The parser looks for:

    * Markdown headings (``#``, ``##``, ``###``) as feature boundaries.
    * Bullet points (``-``, ``*``, ``1.``) as individual requirements.
    * Sub-sections titled "Acceptance Criteria", "User Story", etc.
    * Priority keywords (must/should/nice-to-have).
    * Complexity keywords for effort estimation.

    Args:
        prd_content: Raw PRD text.

    Returns:
        List of story dicts.
    """
    stories: list[dict[str, Any]] = []

    # Split into sections by markdown headings
    sections = re.split(r"\n(?=#{1,3}\s)", prd_content)

    story_index = 0

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Extract heading
        heading_match = re.match(r"^#{1,3}\s+(.+)", section)
        if not heading_match:
            # Treat the whole block as a single story if no heading
            if len(section) > 20:
                story_index += 1
                effort, _ = _estimate_single_effort("", section)
                priority = _detect_priority(section)
                stories.append(
                    _make_story_dict(
                        index=story_index,
                        title=f"Requirement {story_index}",
                        description=section,
                        effort=effort,
                        priority=priority,
                    )
                )
            continue

        heading = heading_match.group(1).strip()
        body = section[heading_match.end() :].strip()

        # Skip metadata sections that aren't features
        skip_headings = {
            "overview", "introduction", "background", "glossary",
            "table of contents", "references", "appendix", "revision history",
            "non-functional requirements", "constraints", "assumptions",
        }
        if heading.lower() in skip_headings:
            continue

        # Check for bullet-point sub-items
        bullet_pattern = re.compile(
            r"^\s*[-*]\s+(.+)$|^\s*\d+\.\s+(.+)$", re.MULTILINE
        )
        bullets = bullet_pattern.findall(body)

        if bullets:
            for bullet_match in bullets:
                bullet_text = (bullet_match[0] or bullet_match[1]).strip()
                if not bullet_text or len(bullet_text) < 10:
                    continue

                story_index += 1
                effort, _ = _estimate_single_effort(bullet_text, "")
                priority = _detect_priority(bullet_text)

                stories.append(
                    _make_story_dict(
                        index=story_index,
                        title=bullet_text[:120],
                        description=f"**{heading}**\n\n{bullet_text}",
                        effort=effort,
                        priority=priority,
                    )
                )
        else:
            # Whole section as one story
            description = f"## {heading}\n\n{body}" if body else heading
            story_index += 1
            effort, _ = _estimate_single_effort(heading, body)
            priority = _detect_priority(section)

            stories.append(
                _make_story_dict(
                    index=story_index,
                    title=heading[:120],
                    description=description,
                    effort=effort,
                    priority=priority,
                )
            )

    # Fallback — if no stories were extracted, create one from the whole PRD
    if not stories:
        stories.append(
            _make_story_dict(
                index=1,
                title="Implement PRD requirements",
                description=prd_content[:2000],
                effort="L",
                priority="must_have",
            )
        )

    return stories


def _make_story_dict(
    *,
    index: int,
    title: str,
    description: str,
    effort: str,
    priority: str,
) -> dict[str, Any]:
    """Construct a normalised story dict.

    Args:
        index: Sequence number.
        title: Story title.
        description: Full description.
        effort: Effort size (S/M/L/XL).
        priority: Priority level.

    Returns:
        Story dict with all required fields.
    """
    return {
        "story_id": f"STORY-{uuid4().hex[:8].upper()}",
        "index": index,
        "title": title,
        "description": description,
        "effort": effort,
        "priority": priority,
        "labels": [effort.lower(), priority],
        "assigned_to": None,
        "assigned_to_github": None,
    }


# ---------------------------------------------------------------------------
# Effort estimation
# ---------------------------------------------------------------------------

def _estimate_single_effort(title: str, description: str) -> Tuple[str, str]:
    """Estimate effort for a single story using keyword heuristics.

    Scans *title* and *description* for complexity signals and returns the
    highest-matching effort size along with a human-readable explanation.

    Args:
        title: Story title.
        description: Story description.

    Returns:
        Tuple of (effort_size, reasoning).
    """
    text = f"{title} {description}".lower()
    scores: dict[str, int] = {"S": 0, "M": 0, "L": 0, "XL": 0}
    matched_keywords: dict[str, list[str]] = {"S": [], "M": [], "L": [], "XL": []}

    for effort_size, keywords in _COMPLEXITY_SIGNALS.items():
        for keyword in keywords:
            if keyword in text:
                scores[effort_size] += 1
                matched_keywords[effort_size].append(keyword)

    # Determine the winner — prefer higher complexity
    if scores["XL"] > 0:
        effort = "XL"
    elif scores["L"] > 0:
        effort = "L"
    elif scores["M"] > 0:
        effort = "M"
    else:
        effort = "S"

    reasoning_parts = []
    for size in ["XL", "L", "M", "S"]:
        if matched_keywords[size]:
            reasoning_parts.append(
                f"{size}: matched [{', '.join(matched_keywords[size])}]"
            )

    reasoning = "; ".join(reasoning_parts) if reasoning_parts else "No complexity signals — defaulting to S"

    return effort, reasoning


def _detect_priority(text: str) -> str:
    """Detect priority from keyword analysis.

    Args:
        text: Text to analyse.

    Returns:
        Priority level string.
    """
    lower = text.lower()

    for priority, keywords in _PRIORITY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in lower:
                return priority

    return "should_have"


def _priority_to_linear(priority: str) -> int:
    """Convert our priority enum to Linear's numeric priority.

    Linear priorities: 0 = No priority, 1 = Urgent, 2 = High, 3 = Medium, 4 = Low.

    Args:
        priority: Priority string.

    Returns:
        Linear priority integer.
    """
    mapping = {
        "must_have": 2,
        "should_have": 3,
        "nice_to_have": 4,
    }
    return mapping.get(priority, 3)


# ---------------------------------------------------------------------------
# Sprint planning logic
# ---------------------------------------------------------------------------

def _build_sprint_plan(
    *,
    stories: list[dict[str, Any]],
    sprint_name: str,
    sprint_goal: str,
    capacity: int,
    team_members: list[dict[str, str]],
) -> dict[str, Any]:
    """Build a sprint plan from stories.

    Stories are sorted by priority (must → should → nice) then by effort
    (smallest first) to maximise throughput.  Stories are added until the
    sprint capacity is reached; the remainder go to the backlog.

    Team members are assigned in round-robin order based on effort size
    (larger stories to more senior members if indicated by ordering).

    Args:
        stories: List of story dicts.
        sprint_name: Sprint name.
        sprint_goal: Sprint goal.
        capacity: Total story-point capacity.
        team_members: List of member dicts with ``id`` and ``name``.

    Returns:
        Dict with ``sprint_plan`` and ``backlog_stories``.
    """
    effort_to_points: dict[str, int] = {"S": 1, "M": 3, "L": 5, "XL": 8}
    priority_order: dict[str, int] = {
        "must_have": 0,
        "should_have": 1,
        "nice_to_have": 2,
    }

    # Sort: must_have first, then smallest effort first within same priority
    sorted_stories = sorted(
        stories,
        key=lambda s: (
            priority_order.get(s.get("priority", "should_have"), 1),
            effort_to_points.get(s.get("effort", "M"), 3),
        ),
    )

    sprint_stories: list[dict[str, Any]] = []
    backlog_stories: list[dict[str, Any]] = []
    used_points = 0

    for story in sorted_stories:
        effort = story.get("effort", "M")
        points = effort_to_points.get(effort, 3)

        if used_points + points <= capacity:
            sprint_stories.append(story)
            used_points += points
        else:
            backlog_stories.append(story)

    # Assign team members in round-robin
    if team_members:
        for i, story in enumerate(sprint_stories):
            member = team_members[i % len(team_members)]
            story["assigned_to"] = member.get("id", "")
            story["assigned_to_github"] = member.get("github_username", "")
            story["assigned_to_name"] = member.get("name", "")

    return {
        "sprint_plan": {
            "name": sprint_name,
            "goal": sprint_goal,
            "capacity": capacity,
            "used_points": used_points,
            "remaining_points": capacity - used_points,
            "story_count": len(sprint_stories),
            "stories": sprint_stories,
            "team_size": len(team_members),
        },
        "backlog_stories": backlog_stories,
        "backlog_count": len(backlog_stories),
    }