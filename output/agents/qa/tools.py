"""MCP tool implementations for QA / Tester agent.

Each tool wraps an MCP client call (github_mcp, context7) or implements
local testing logic.  Tools cover the full QA lifecycle: reading source
code, generating test cases from acceptance criteria, running automated
tests (pytest / Playwright), committing test code, filing bug reports,
and consulting documentation.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4

import structlog

from shared.mcp_client import MCPClient

log = structlog.get_logger(agent="qa")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_mcp: Optional[MCPClient] = None


def _get_mcp() -> MCPClient:
    """Return (and lazily initialise) the shared MCP client."""
    global _mcp
    if _mcp is None:
        _mcp = MCPClient()
    return _mcp


def _run_cmd(
    cmd: List[str],
    cwd: str | None = None,
    timeout: int = 300,
) -> Tuple[int, str, str]:
    """Run a subprocess command synchronously.

    Returns (returncode, stdout, stderr).
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"


def _parse_pytest_output(raw: str) -> Dict[str, Any]:
    """Parse pytest output into a structured report."""
    lines = raw.strip().splitlines()
    summary: Dict[str, Any] = {
        "raw_output": raw,
        "total": 0,
        "passed": 0,
        "failed": 0,
        "error": 0,
        "skipped": 0,
        "duration_seconds": 0.0,
        "pass_rate": 0.0,
        "failures": [],
    }

    # Parse summary line  e.g. "===== 5 passed, 2 failed in 3.45s ====="
    summary_re = re.compile(
        r"=+\s+"
        r"(?:(\d+)\s+failed,\s+)?"
        r"(?:(\d+)\s+passed,\s+)?"
        r"(?:(\d+)\s+error,\s+)?"
        r"(?:(\d+)\s+skipped,\s+)?"
        r"in\s+([\d.]+)s"
    )
    for line in reversed(lines):
        m = summary_re.search(line)
        if m:
            summary["failed"] = int(m.group(1) or 0)
            summary["passed"] = int(m.group(2) or 0)
            summary["error"] = int(m.group(3) or 0)
            summary["skipped"] = int(m.group(4) or 0)
            summary["duration_seconds"] = float(m.group(5) or 0)
            summary["total"] = (
                summary["passed"]
                + summary["failed"]
                + summary["error"]
                + summary["skipped"]
            )
            break

    if summary["total"] > 0:
        summary["pass_rate"] = round(summary["passed"] / summary["total"], 4)

    # Capture FAILURES section
    in_failures = False
    failure_lines: List[str] = []
    for line in lines:
        if line.startswith("FAILURES") or line.startswith("== FAILURES"):
            in_failures = True
            continue
        if in_failures and line.startswith("="):
            in_failures = False
        if in_failures:
            failure_lines.append(line)

    if failure_lines:
        summary["failure_details"] = "\n".join(failure_lines)

    return summary


def _parse_playwright_output(raw: str) -> Dict[str, Any]:
    """Parse Playwright test runner output into a structured report."""
    lines = raw.strip().splitlines()
    summary: Dict[str, Any] = {
        "raw_output": raw,
        "total": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "flaky": 0,
        "duration_seconds": 0.0,
        "pass_rate": 0.0,
        "failures": [],
    }

    # Playwright summary: "X passed (Yms)" / "X failed" / "X skipped"
    passed_re = re.compile(r"(\d+)\s+passed")
    failed_re = re.compile(r"(\d+)\s+failed")
    skipped_re = re.compile(r"(\d+)\s+skipped")
    duration_re = re.compile(r"\((\d+\.?\d*)[ms]")

    for line in lines:
        if m := passed_re.search(line):
            summary["passed"] = int(m.group(1))
        if m := failed_re.search(line):
            summary["failed"] = int(m.group(1))
        if m := skipped_re.search(line):
            summary["skipped"] = int(m.group(1))
        if m := duration_re.search(line):
            summary["duration_seconds"] = float(m.group(1)) / 1000

    summary["total"] = summary["passed"] + summary["failed"] + summary["skipped"]
    if summary["total"] > 0:
        summary["pass_rate"] = round(summary["passed"] / summary["total"], 4)

    # Capture failure lines (Playwright marks with ✘ or ×)
    for i, line in enumerate(lines):
        if any(sym in line for sym in ("✘", "×", "FAILED")):
            context = "\n".join(lines[max(0, i - 1) : min(len(lines), i + 4)])
            summary["failures"].append(context)

    return summary


def _extract_test_functions(content: str) -> List[str]:
    """Extract test function names from a Python test file."""
    return re.findall(r"(def (test_\w+)\s*\()", content)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def get_file(repo: str, path: str, ref: str = "main") -> Dict[str, Any]:
    """Retrieve a file's content from a GitHub repository via GitHub MCP.

    Parameters
    ----------
    repo:
        Repository in ``owner/name`` format.
    path:
        Path to the file inside the repo.
    ref:
        Branch, tag, or commit SHA (default ``main``).

    Returns
    -------
    dict
        ``{"path": ..., "content": ..., "sha": ...}``
    """
    mcp = _get_mcp()
    log.info("mcp_call", tool="github_get_file", repo=repo, path=path, ref=ref)
    result = await mcp.call(
        server="github_mcp",
        tool="get_file",
        arguments={"repo": repo, "path": path, "ref": ref},
    )
    return result  # type: ignore[return-value]


async def search_code(
    repo: str,
    query: str,
    path: str = "",
) -> Dict[str, Any]:
    """Search for code patterns in a repository via GitHub MCP.

    Useful for locating existing tests, source modules, or specific
    patterns that need test coverage.

    Parameters
    ----------
    repo:
        ``owner/name`` format.
    query:
        Search query / pattern.
    path:
        Optional path filter.

    Returns
    -------
    dict
        Search results with file matches.
    """
    mcp = _get_mcp()
    log.info("mcp_call", tool="github_search_code", repo=repo, query=query)
    result = await mcp.call(
        server="github_mcp",
        tool="search_code",
        arguments={"repo": repo, "query": query, "path": path},
    )
    return result  # type: ignore[return-value]


async def commit_files(
    repo: str,
    branch: str,
    files: List[Dict[str, str]],
    message: str,
) -> Dict[str, Any]:
    """Commit one or more files to a branch via GitHub MCP.

    Parameters
    ----------
    repo:
        ``owner/name`` format.
    branch:
        Target branch name.
    files:
        List of ``{"path": ..., "content": ...}`` dicts.
    message:
        Commit message.

    Returns
    -------
    dict
        Commit information (sha, url, etc.).
    """
    mcp = _get_mcp()
    log.info(
        "mcp_call",
        tool="github_commit_files",
        repo=repo,
        branch=branch,
        file_count=len(files),
    )
    result = await mcp.call(
        server="github_mcp",
        tool="commit_files",
        arguments={
            "repo": repo,
            "branch": branch,
            "files": files,
            "message": message,
        },
    )
    return result  # type: ignore[return-value]


async def create_branch(
    repo: str,
    branch_name: str,
    base_ref: str = "main",
) -> Dict[str, Any]:
    """Create a new branch in a repository via GitHub MCP.

    Parameters
    ----------
    repo:
        ``owner/name`` format.
    branch_name:
        Name of the new branch.
    base_ref:
        Branch or SHA to base from (default ``main``).

    Returns
    -------
    dict
        Created branch information.
    """
    mcp = _get_mcp()
    log.info("mcp_call", tool="github_create_branch", repo=repo, branch=branch_name)
    result = await mcp.call(
        server="github_mcp",
        tool="create_branch",
        arguments={
            "repo": repo,
            "branch": branch_name,
            "base": base_ref,
        },
    )
    return result  # type: ignore[return-value]


async def create_pull_request(
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
) -> Dict[str, Any]:
    """Create a pull request via GitHub MCP.

    Parameters
    ----------
    repo:
        ``owner/name`` format.
    title:
        PR title.
    body:
        PR body / description (Markdown).
    head:
        Source branch.
    base:
        Target branch (default ``main``).

    Returns
    -------
    dict
        Pull request details (number, url, etc.).
    """
    mcp = _get_mcp()
    log.info("mcp_call", tool="github_create_pr", repo=repo, title=title)
    result = await mcp.call(
        server="github_mcp",
        tool="create_pr",
        arguments={
            "repo": repo,
            "title": title,
            "body": body,
            "head": head,
            "base": base,
        },
    )
    return result  # type: ignore[return-value]


async def create_issue(
    repo: str,
    title: str,
    body: str,
    labels: List[str] | None = None,
) -> Dict[str, Any]:
    """Create a GitHub issue — used for filing bug reports.

    Parameters
    ----------
    repo:
        ``owner/name`` format.
    title:
        Issue title (should include P-level prefix).
    body:
        Issue body in Markdown — must contain Steps to Reproduce,
        Expected Result, Actual Result, Severity.
    labels:
        Optional labels (e.g. ``["bug", "P0"]``).

    Returns
    -------
    dict
        Issue details (number, url, etc.).
    """
    mcp = _get_mcp()
    log.info("mcp_call", tool="github_create_issue", repo=repo, title=title)
    args: Dict[str, Any] = {
        "repo": repo,
        "title": title,
        "body": body,
    }
    if labels:
        args["labels"] = labels
    result = await mcp.call(
        server="github_mcp",
        tool="create_issue",
        arguments=args,
    )
    return result  # type: ignore[return-value]


async def resolve_library_id(library_name: str) -> Dict[str, Any]:
    """Resolve a library name to a Context7 identifier.

    Used to look up documentation for testing frameworks (pytest,
    playwright, httpx, etc.).

    Parameters
    ----------
    library_name:
        Name of the library (e.g. ``"pytest"``, ``"playwright"``).

    Returns
    -------
    dict
        Context7 library resolution result.
    """
    mcp = _get_mcp()
    log.info("mcp_call", tool="context7_resolve_library_id", library=library_name)
    result = await mcp.call(
        server="context7",
        tool="resolve_library_id",
        arguments={"libraryName": library_name},
    )
    return result  # type: ignore[return-value]


async def get_library_docs(
    library_id: str,
    topic: str = "",
    tokens: int = 5000,
) -> Dict[str, Any]:
    """Retrieve documentation for a library from Context7.

    Parameters
    ----------
    library_id:
        Context7 library identifier.
    topic:
        Optional topic filter (e.g. ``"parametrize"``, ``"fixtures"``).
    tokens:
        Maximum tokens to return (default 5000).

    Returns
    -------
    dict
        Documentation content.
    """
    mcp = _get_mcp()
    log.info("mcp_call", tool="context7_get_library_docs", library_id=library_id, topic=topic)
    args: Dict[str, Any] = {"libraryId": library_id, "tokens": tokens}
    if topic:
        args["topic"] = topic
    result = await mcp.call(
        server="context7",
        tool="get_library_docs",
        arguments=args,
    )
    return result  # type: ignore[return-value]


async def generate_test_cases(
    acceptance_criteria: str,
    source_code: str = "",
    test_type: str = "backend",
) -> Dict[str, Any]:
    """Generate test cases from acceptance criteria.

    Applies the QA distribution rule: 40 % happy path, 35 % edge cases,
    25 % error cases.  Returns structured test case descriptions that
    can later be converted to pytest or Playwright code.

    Parameters
    ----------
    acceptance_criteria:
        Gherkin-style acceptance criteria (Given / When / Then).
    source_code:
        Optional source code context for more targeted tests.
    test_type:
        ``"backend"`` for API tests (pytest), ``"frontend"`` for E2E
        (Playwright).

    Returns
    -------
    dict
        ``{"test_cases": [...], "distribution": {...}, "estimated_coverage": float}``
    """
    log.info(
        "generate_test_cases",
        test_type=test_type,
        criteria_length=len(acceptance_criteria),
    )

    # Parse Gherkin scenarios from acceptance criteria
    scenarios = re.findall(
        r"(?:Given|When|Then|And|But)\s+(.+?)(?:\n|$)",
        acceptance_criteria,
        re.IGNORECASE,
    )

    # Parse full scenario blocks
    scenario_blocks = re.findall(
        r"Scenario:\s*(.+?)(?=\n\s*(?:Scenario:|Given|\Z))",
        acceptance_criteria,
        re.DOTALL | re.IGNORECASE,
    )

    all_criteria = [s.strip() for s in scenarios if s.strip()]

    # If no Gherkin found, split by line
    if not all_criteria:
        all_criteria = [
            line.strip()
            for line in acceptance_criteria.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    total_criteria = max(len(all_criteria), 1)

    # Calculate distribution
    happy_count = max(1, round(total_criteria * 0.40))
    edge_count = max(1, round(total_criteria * 0.35))
    error_count = max(1, round(total_criteria * 0.25))

    test_cases: List[Dict[str, Any]] = []

    # Happy path tests
    for i, criterion in enumerate(all_criteria[:happy_count]):
        test_cases.append({
            "id": f"TC-HP-{i + 1:03d}",
            "category": "happy_path",
            "description": f"Verify: {criterion}",
            "priority": "P1",
            "automated": True,
            "test_type": test_type,
            "status": "pending",
        })

    # Edge case tests
    edge_scenarios = [
        "empty input handling",
        "boundary value (min/max)",
        "special characters in input",
        "concurrent access / race conditions",
        "large payload handling",
        "pagination boundaries (first/last page)",
        "unicode / international characters",
        "null / undefined optional fields",
        "maximum string length",
        "timezone edge cases",
    ]
    for i in range(edge_count):
        scenario = edge_scenarios[i % len(edge_scenarios)]
        test_cases.append({
            "id": f"TC-EC-{i + 1:03d}",
            "category": "edge_case",
            "description": f"Edge case: {scenario}",
            "priority": "P2",
            "automated": True,
            "test_type": test_type,
            "status": "pending",
        })

    # Error case tests
    error_scenarios = [
        "invalid input format",
        "unauthorized / missing auth token",
        "forbidden access to resource",
        "resource not found (404)",
        "method not allowed (405)",
        "request timeout",
        "payload too large (413)",
        "unsupported media type (415)",
        "server internal error (500)",
        "service unavailable (503)",
        "rate limit exceeded (429)",
    ]
    for i in range(error_count):
        scenario = error_scenarios[i % len(error_scenarios)]
        test_cases.append({
            "id": f"TC-ER-{i + 1:03d}",
            "category": "error_case",
            "description": f"Error case: {scenario}",
            "priority": "P2",
            "automated": True,
            "test_type": test_type,
            "status": "pending",
        })

    result: Dict[str, Any] = {
        "test_cases": test_cases,
        "distribution": {
            "happy_path": happy_count,
            "edge_cases": edge_count,
            "error_cases": error_count,
            "total": len(test_cases),
        },
        "estimated_coverage": round(min(0.85, len(test_cases) * 0.05), 2),
        "test_type": test_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    log.info(
        "test_cases_generated",
        total=len(test_cases),
        happy=happy_count,
        edge=edge_count,
        error=error_count,
    )

    return result


async def run_pytest(
    test_path: str,
    repo_path: str = ".",
    extra_args: List[str] | None = None,
    timeout: int = 300,
) -> Dict[str, Any]:
    """Execute pytest on the specified test path.

    Parameters
    ----------
    test_path:
        Path to the test file or directory.
    repo_path:
        Working directory (repo root).
    extra_args:
        Additional pytest CLI arguments (e.g. ``["-k", "test_auth"]``).
    timeout:
        Subprocess timeout in seconds (default 300).

    Returns
    -------
    dict
        Structured test report with pass/fail counts, duration, and
        failure details.
    """
    cmd = [
        "python", "-m", "pytest",
        test_path,
        "-v",
        "--tb=short",
        "--no-header",
        "-q",
    ]
    if extra_args:
        cmd.extend(extra_args)

    log.info("run_pytest", test_path=test_path, repo_path=repo_path)

    returncode, stdout, stderr = _run_cmd(cmd, cwd=repo_path, timeout=timeout)

    report = _parse_pytest_output(stdout + "\n" + stderr)
    report["returncode"] = returncode
    report["success"] = returncode == 0

    log.info(
        "pytest_complete",
        total=report["total"],
        passed=report["passed"],
        failed=report["failed"],
        success=report["success"],
    )

    return report


async def run_playwright(
    test_path: str,
    repo_path: str = ".",
    extra_args: List[str] | None = None,
    timeout: int = 600,
) -> Dict[str, Any]:
    """Execute Playwright E2E tests.

    Parameters
    ----------
    test_path:
        Path to the Playwright test file or directory.
    repo_path:
        Working directory (repo root).
    extra_args:
        Additional Playwright CLI arguments.
    timeout:
        Subprocess timeout in seconds (default 600).

    Returns
    -------
    dict
        Structured test report with pass/fail counts, duration, and
        failure details.
    """
    cmd = [
        "npx", "playwright", "test",
        test_path,
        "--reporter=line",
    ]
    if extra_args:
        cmd.extend(extra_args)

    log.info("run_playwright", test_path=test_path, repo_path=repo_path)

    returncode, stdout, stderr = _run_cmd(cmd, cwd=repo_path, timeout=timeout)

    report = _parse_playwright_output(stdout + "\n" + stderr)
    report["returncode"] = returncode
    report["success"] = returncode == 0

    log.info(
        "playwright_complete",
        total=report["total"],
        passed=report["passed"],
        failed=report["failed"],
        success=report["success"],
    )

    return report


async def run_coverage(
    test_path: str,
    source_path: str = "src",
    repo_path: str = ".",
    timeout: int = 300,
) -> Dict[str, Any]:
    """Run pytest with coverage and return the report.

    Parameters
    ----------
    test_path:
        Test file or directory to run.
    source_path:
        Source directory to measure coverage against.
    repo_path:
        Working directory (repo root).
    timeout:
        Subprocess timeout in seconds.

    Returns
    -------
    dict
        ``{"coverage_percent": float, "missing_lines": [...], "report": str}``
    """
    cmd = [
        "python", "-m", "pytest",
        test_path,
        f"--cov={source_path}",
        "--cov-report=term-missing",
        "--cov-report=json:coverage.json",
        "-q",
        "--no-header",
    ]

    log.info("run_coverage", test_path=test_path, source_path=source_path)

    returncode, stdout, stderr = _run_cmd(cmd, cwd=repo_path, timeout=timeout)

    coverage_percent = 0.0
    missing_lines: List[str] = []

    # Try to parse the JSON coverage report
    coverage_json_path = Path(repo_path) / "coverage.json"
    if coverage_json_path.exists():
        try:
            cov_data = json.loads(coverage_json_path.read_text())
            coverage_percent = cov_data.get("totals", {}).get("percent_covered", 0.0)
            for fname, file_data in cov_data.get("files", {}).items():
                missing = file_data.get("missing_lines", [])
                if missing:
                    missing_lines.append(f"{fname}: lines {missing}")
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: parse text output for coverage percentage
    if coverage_percent == 0.0:
        cov_match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", stdout + stderr)
        if cov_match:
            coverage_percent = float(cov_match.group(1))

    result: Dict[str, Any] = {
        "coverage_percent": round(coverage_percent, 2),
        "meets_target": coverage_percent >= 80.0,
        "target": 80.0,
        "missing_lines": missing_lines,
        "raw_output": stdout,
        "returncode": returncode,
        "success": returncode == 0,
    }

    log.info(
        "coverage_complete",
        coverage_percent=coverage_percent,
        meets_target=result["meets_target"],
    )

    return result


async def generate_bug_report(
    test_name: str,
    expected: str,
    actual: str,
    steps: List[str],
    severity: str = "P2",
    screen_capture: str = "",
) -> Dict[str, Any]:
    """Generate a structured bug report.

    The report follows the mandatory format: Steps to Reproduce,
    Expected Result, Actual Result, Severity, Screen capture.

    Parameters
    ----------
    test_name:
        Name of the failing test.
    expected:
        What the expected behaviour was.
    actual:
        What actually happened.
    steps:
        Steps to reproduce the bug.
    severity:
        ``P0`` (critical), ``P1`` (high), ``P2`` (medium), ``P3`` (low).
    screen_capture:
        Text representation of the screen state at failure.

    Returns
    -------
    dict
        Structured bug report ready for GitHub issue creation.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    bug_id = f"BUG-{uuid4().hex[:8].upper()}"

    steps_text = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(steps))

    body = textwrap.dedent(f"""\
    ## Bug Report: {bug_id}

    **Test:** `{test_name}`
    **Severity:** {severity}
    **Reported:** {timestamp}

    ### Steps to Reproduce

    {steps_text}

    ### Expected Result

    {expected}

    ### Actual Result

    {actual}
    """)

    if screen_capture:
        body += textwrap.dedent(f"""\
    ### Screen Capture (text representation)

    ```
    {screen_capture}
    ```
    """)

    result: Dict[str, Any] = {
        "bug_id": bug_id,
        "title": f"[{severity}] {test_name}: {actual[:80]}",
        "body": body,
        "severity": severity,
        "labels": ["bug", severity.lower()],
        "test_name": test_name,
        "timestamp": timestamp,
    }

    log.info("bug_report_generated", bug_id=bug_id, severity=severity, test=test_name)
    return result


async def file_bug_as_issue(
    repo: str,
    bug_report: Dict[str, Any],
) -> Dict[str, Any]:
    """File a bug report as a GitHub issue.

    Parameters
    ----------
    repo:
        ``owner/name`` format.
    bug_report:
        Output of :func:`generate_bug_report`.

    Returns
    -------
    dict
        Created issue details.
    """
    log.info("file_bug", bug_id=bug_report.get("bug_id"), repo=repo)
    return await create_issue(
        repo=repo,
        title=bug_report["title"],
        body=bug_report["body"],
        labels=bug_report.get("labels", ["bug"]),
    )


async def commit_test_code(
    repo: str,
    branch: str,
    test_files: List[Dict[str, str]],
    message: str,
) -> Dict[str, Any]:
    """Commit generated test files to a branch.

    Parameters
    ----------
    repo:
        ``owner/name`` format.
    branch:
        Target branch (typically a feature or fix branch).
    test_files:
        List of ``{"path": ..., "content": ...}`` dicts for test files.
    message:
        Commit message.

    Returns
    -------
    dict
        Commit details.
    """
    log.info(
        "commit_test_code",
        repo=repo,
        branch=branch,
        file_count=len(test_files),
    )
    return await commit_files(
        repo=repo,
        branch=branch,
        files=test_files,
        message=message,
    )


async def create_test_pr(
    repo: str,
    branch: str,
    base: str = "main",
    test_summary: str = "",
    coverage: float = 0.0,
) -> Dict[str, Any]:
    """Create a pull request for a test branch.

    Parameters
    ----------
    repo:
        ``owner/name`` format.
    branch:
        Head branch containing test code.
    base:
        Target branch.
    test_summary:
        Summary of tests added / modified.
    coverage:
        Current coverage percentage.

    Returns
    -------
    dict
        Pull request details.
    """
    title = f"test: add automated tests — {coverage:.1f}% coverage"
    body = textwrap.dedent(f"""\
    ## Automated Test Suite

    ### Coverage
    - **{coverage:.1f}%** (target: ≥ 80%)

    ### Summary
    {test_summary}

    ### Distribution
    - Happy path: 40%
    - Edge cases: 35%
    - Error cases: 25%

    ---
    *Auto-generated by QA / Tester agent*
    """)

    log.info("create_test_pr", repo=repo, branch=branch, coverage=coverage)
    return await create_pull_request(
        repo=repo,
        title=title,
        body=body,
        head=branch,
        base=base,
    )


async def get_testing_docs(
    framework: str = "pytest",
    topic: str = "",
) -> Dict[str, Any]:
    """Look up testing framework documentation via Context7.

    Parameters
    ----------
    framework:
        Library name (``"pytest"``, ``"playwright"``, ``"httpx"``, etc.).
    topic:
        Optional topic filter (``"parametrize"``, ``"fixtures"``, etc.).

    Returns
    -------
    dict
        Documentation content from Context7.
    """
    log.info("get_testing_docs", framework=framework, topic=topic)
    lib_result = await resolve_library_id(framework)
    library_id = lib_result.get("library_id") or lib_result.get("id", "")
    if not library_id:
        return {"error": f"Could not resolve library: {framework}", "docs": ""}
    return await get_library_docs(library_id=library_id, topic=topic)


async def read_source_code(repo: str, path: str, ref: str = "main") -> str:
    """Convenience wrapper: return raw file content as a string.

    Parameters
    ----------
    repo:
        ``owner/name`` format.
    path:
        File path inside the repo.
    ref:
        Branch / tag / SHA.

    Returns
    -------
    str
        File content, or empty string on error.
    """
    result = await get_file(repo=repo, path=path, ref=ref)
    return result.get("content", "")


async def collect_source_context(
    repo: str,
    paths: List[str],
    ref: str = "main",
) -> Dict[str, str]:
    """Fetch multiple source files in parallel and return as a dict.

    Parameters
    ----------
    repo:
        ``owner/name`` format.
    paths:
        List of file paths to fetch.
    ref:
        Branch / tag / SHA.

    Returns
    -------
    dict
        ``{path: content}`` mapping.
    """
    tasks = [get_file(repo=repo, path=p, ref=ref) for p in paths]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    context: Dict[str, str] = {}
    for path, result in zip(paths, results):
        if isinstance(result, Exception):
            log.warning("fetch_failed", path=path, error=str(result))
            context[path] = ""
        elif isinstance(result, dict):
            context[path] = result.get("content", "")
        else:
            context[path] = str(result)

    return context


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_tools(mcp=None) -> Dict[str, Callable]:
    """Return the QA / Tester agent's tool registry.

    Each key is a tool name (used in MCP-style calls or local invocation)
    and each value is the corresponding async callable.

    Returns
    -------
    dict
        ``{tool_name: callable}`` mapping.
    """
    return {
        # GitHub MCP wrappers
        "get_file": get_file,
        "search_code": search_code,
        "commit_files": commit_files,
        "create_branch": create_branch,
        "create_pull_request": create_pull_request,
        "create_issue": create_issue,
        # Context7 MCP wrappers
        "resolve_library_id": resolve_library_id,
        "get_library_docs": get_library_docs,
        "get_testing_docs": get_testing_docs,
        # Test generation
        "generate_test_cases": generate_test_cases,
        # Test execution
        "run_pytest": run_pytest,
        "run_playwright": run_playwright,
        "run_coverage": run_coverage,
        # Bug reporting
        "generate_bug_report": generate_bug_report,
        "file_bug_as_issue": file_bug_as_issue,
        # Convenience
        "commit_test_code": commit_test_code,
        "create_test_pr": create_test_pr,
        "read_source_code": read_source_code,
        "collect_source_context": collect_source_context,
    }