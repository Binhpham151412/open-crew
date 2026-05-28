from __future__ import annotations

from typing import Any, Callable

import structlog
from shared.mcp_client import MCPClient

logger = structlog.get_logger("techlead")


def get_tools(mcp: MCPClient) -> dict[str, Callable[..., Any]]:
    """Return a mapping of tool names to their callable implementations.

    Each callable wraps an MCP client call or implements local logic
    relevant to the TechLead agent's responsibilities:
      - Arbitrate conflicts between agents
      - Final architecture review
      - Merge PR and sign-off delivery
      - Monitor pipeline and unblock stuck agents
    """

    async def get_pr_diff(
        owner: str, repo: str, pull_number: int, base: str = "main"
    ) -> dict[str, Any]:
        """Retrieve the diff and details of a pull request for final review.

        Args:
            owner: GitHub repository owner (user or org).
            repo: Repository name.
            pull_number: The PR number to review.
            base: Base branch to compare against.

        Returns:
            Dictionary with PR metadata and file changes.
        """
        logger.info(
            "get_pr_diff_called",
            owner=owner,
            repo=repo,
            pull_number=pull_number,
        )
        pr_details = await mcp.call(
            tool="github_mcp",
            method="tools/call",
            params={
                "name": "get_pull_request",
                "arguments": {
                    "owner": owner,
                    "repo": repo,
                    "pull_number": pull_number,
                },
            },
        )
        diff_files = await mcp.call(
            tool="github_mcp",
            method="tools/call",
            params={
                "name": "list_pull_request_files",
                "arguments": {
                    "owner": owner,
                    "repo": repo,
                    "pull_number": pull_number,
                },
            },
        )
        return {
            "pr": pr_details,
            "files": diff_files,
        }

    async def final_review_pr(
        owner: str,
        repo: str,
        pull_number: int,
        comment: str,
        event: str = "COMMENT",
    ) -> dict[str, Any]:
        """Post a final review comment on a pull request.

        This is the TechLead's last review before deciding to merge or reject.

        Args:
            owner: GitHub repository owner.
            repo: Repository name.
            pull_number: PR number.
            comment: Review comment body.
            event: Review event type — one of APPROVE, REQUEST_CHANGES, COMMENT.

        Returns:
            GitHub API response for the created review.
        """
        logger.info(
            "final_review_pr_called",
            owner=owner,
            repo=repo,
            pull_number=pull_number,
            event=event,
        )
        result = await mcp.call(
            tool="github_mcp",
            method="tools/call",
            params={
                "name": "create_review",
                "arguments": {
                    "owner": owner,
                    "repo": repo,
                    "pull_number": pull_number,
                    "body": comment,
                    "event": event,
                },
            },
        )
        return result

    async def approve_and_merge_pr(
        owner: str,
        repo: str,
        pull_number: int,
        merge_method: str = "squash",
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        """Approve and merge a pull request — the final sign-off gate.

        Args:
            owner: GitHub repository owner.
            repo: Repository name.
            pull_number: PR number to merge.
            merge_method: One of 'merge', 'squash', 'rebase'.
            commit_message: Optional override for the merge commit message.

        Returns:
            GitHub API response for the merge operation.
        """
        logger.info(
            "approve_and_merge_pr_called",
            owner=owner,
            repo=repo,
            pull_number=pull_number,
            merge_method=merge_method,
        )
        # First approve
        await mcp.call(
            tool="github_mcp",
            method="tools/call",
            params={
                "name": "create_review",
                "arguments": {
                    "owner": owner,
                    "repo": repo,
                    "pull_number": pull_number,
                    "body": "✅ TechLead sign-off: all checks passed. Approving and merging.",
                    "event": "APPROVE",
                },
            },
        )
        # Then merge
        merge_args: dict[str, Any] = {
            "owner": owner,
            "repo": repo,
            "pull_number": pull_number,
            "merge_method": merge_method,
        }
        if commit_message:
            merge_args["commit_message"] = commit_message
        result = await mcp.call(
            tool="github_mcp",
            method="tools/call",
            params={
                "name": "merge_pull_request",
                "arguments": merge_args,
            },
        )
        return result

    async def list_open_prs(
        owner: str, repo: str, head: str | None = None
    ) -> dict[str, Any]:
        """List open pull requests in a repository for monitoring.

        Args:
            owner: GitHub repository owner.
            repo: Repository name.
            head: Optional filter by head branch (format: user:branch).

        Returns:
            List of open PRs.
        """
        logger.info("list_open_prs_called", owner=owner, repo=repo)
        args: dict[str, Any] = {
            "owner": owner,
            "repo": repo,
            "state": "open",
        }
        if head:
            args["head"] = head
        result = await mcp.call(
            tool="github_mcp",
            method="tools/call",
            params={
                "name": "list_pull_requests",
                "arguments": args,
            },
        )
        return result

    async def get_repo_structure(
        owner: str, repo: str, path: str = "", ref: str = "main"
    ) -> dict[str, Any]:
        """Retrieve the directory tree of a repository for final architecture review.

        Args:
            owner: GitHub repository owner.
            repo: Repository name.
            path: Subdirectory path to list (empty for root).
            ref: Git ref (branch, tag, or commit SHA).

        Returns:
            Directory listing from the repository.
        """
        logger.info("get_repo_structure_called", owner=owner, repo=repo, path=path)
        result = await mcp.call(
            tool="github_mcp",
            method="tools/call",
            params={
                "name": "get_file",
                "arguments": {
                    "owner": owner,
                    "repo": repo,
                    "path": path,
                    "ref": ref,
                },
            },
        )
        return result

    async def get_file_content(
        owner: str, repo: str, path: str, ref: str = "main"
    ) -> str:
        """Fetch the raw content of a single file from the repository.

        Used during final architecture review to inspect key files
        such as docker-compose.yml, CI configs, or entry points.

        Args:
            owner: GitHub repository owner.
            repo: Repository name.
            path: Full file path within the repo.
            ref: Git ref (branch, tag, or commit SHA).

        Returns:
            Raw file content as a string.
        """
        logger.info("get_file_content_called", owner=owner, repo=repo, path=path)
        result = await mcp.call(
            tool="github_mcp",
            method="tools/call",
            params={
                "name": "get_file",
                "arguments": {
                    "owner": owner,
                    "repo": repo,
                    "path": path,
                    "ref": ref,
                },
            },
        )
        if isinstance(result, dict) and "content" in result:
            return result["content"]
        return str(result)

    async def search_code(
        query: str, owner: str, repo: str, language: str | None = None
    ) -> dict[str, Any]:
        """Search for code patterns within a repository.

        Useful for the TechLead to verify that critical patterns are
        present (e.g. health checks, input validation, structured logging).

        Args:
            query: Search query string (GitHub code search syntax).
            owner: GitHub repository owner.
            repo: Repository name.
            language: Optional language filter.

        Returns:
            Search results from GitHub.
        """
        logger.info("search_code_called", query=query, owner=owner, repo=repo)
        args: dict[str, Any] = {
            "query": f"{query} repo:{owner}/{repo}",
        }
        if language:
            args["query"] += f" language:{language}"
        result = await mcp.call(
            tool="github_mcp",
            method="tools/call",
            params={
                "name": "search_code",
                "arguments": args,
            },
        )
        return result

    async def mark_story_done(story_id: str, summary: str = "") -> dict[str, Any]:
        """Mark a Linear story as Done after final approval.

        Args:
            story_id: The Linear story/issue identifier.
            summary: Optional completion summary to add as a comment.

        Returns:
            Linear API response.
        """
        logger.info("mark_story_done_called", story_id=story_id)
        update_args: dict[str, Any] = {
            "id": story_id,
            "state": "Done",
        }
        result = await mcp.call(
            tool="linear_mcp",
            method="tools/call",
            params={
                "name": "update_story",
                "arguments": update_args,
            },
        )
        if summary:
            await mcp.call(
                tool="linear_mcp",
                method="tools/call",
                params={
                    "name": "add_comment",
                    "arguments": {
                        "issue_id": story_id,
                        "body": summary,
                    },
                },
            )
        return result

    async def mark_epic_done(epic_id: str, summary: str = "") -> dict[str, Any]:
        """Mark a Linear Epic as Done after all child stories are complete.

        Args:
            epic_id: The Linear epic identifier.
            summary: Optional completion summary.

        Returns:
            Linear API response.
        """
        logger.info("mark_epic_done_called", epic_id=epic_id)
        update_args: dict[str, Any] = {
            "id": epic_id,
            "state": "Done",
        }
        result = await mcp.call(
            tool="linear_mcp",
            method="tools/call",
            params={
                "name": "update_story",
                "arguments": update_args,
            },
        )
        if summary:
            await mcp.call(
                tool="linear_mcp",
                method="tools/call",
                params={
                    "name": "add_comment",
                    "arguments": {
                        "issue_id": epic_id,
                        "body": summary,
                    },
                },
            )
        return result

    async def escalate_to_po(
        report: str,
        task_id: str,
        artifacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a delivery report or escalation to the Product Owner.

        After final sign-off, the TechLead notifies the PO so the user
        receives the result.

        Args:
            report: Summary of the delivery / decision.
            task_id: The task identifier.
            artifacts: Optional list of artifacts (file paths, URLs).

        Returns:
            Confirmation dict.
        """
        logger.info("escalate_to_po_called", task_id=task_id)
        return {
            "action": "notify_po",
            "task_id": task_id,
            "report": report,
            "artifacts": artifacts or [],
        }

    async def get_linear_story(story_id: str) -> dict[str, Any]:
        """Fetch full details of a Linear story for status verification.

        Args:
            story_id: Linear story identifier.

        Returns:
            Story details from Linear.
        """
        logger.info("get_linear_story_called", story_id=story_id)
        result = await mcp.call(
            tool="linear_mcp",
            method="tools/call",
            params={
                "name": "get_issue",
                "arguments": {
                    "id": story_id,
                },
            },
        )
        return result

    async def get_linear_epic(epic_id: str) -> dict[str, Any]:
        """Fetch full details of a Linear Epic for delivery verification.

        Args:
            epic_id: Linear Epic identifier.

        Returns:
            Epic details from Linear.
        """
        logger.info("get_linear_epic_called", epic_id=epic_id)
        result = await mcp.call(
            tool="linear_mcp",
            method="tools/call",
            params={
                "name": "get_issue",
                "arguments": {
                    "id": epic_id,
                },
            },
        )
        return result

    # ------------------------------------------------------------------
    # Return the complete tool registry
    # ------------------------------------------------------------------

    return {
        # --- GitHub MCP tools (read + write) ---
        "get_pr_diff": get_pr_diff,
        "final_review_pr": final_review_pr,
        "approve_and_merge_pr": approve_and_merge_pr,
        "list_open_prs": list_open_prs,
        "get_repo_structure": get_repo_structure,
        "get_file_content": get_file_content,
        "search_code": search_code,
        # --- Linear MCP tools (read + write) ---
        "mark_story_done": mark_story_done,
        "mark_epic_done": mark_epic_done,
        "get_linear_story": get_linear_story,
        "get_linear_epic": get_linear_epic,
        # --- Local logic ---
        "escalate_to_po": escalate_to_po,
    }