"""MCP tool implementations for Security Reviewer agent.

Provides functions that wrap MCP client calls (GitHub, Context7) and local
security analysis logic for OWASP Top 10 checks, secret scanning, and CVE
lookups.

Usage::

    from agents.security_reviewer.tools import get_tools

    tools = get_tools()
    result = await tools["get_file_content"]("backend/app/auth.py")
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

import structlog

from shared.mcp_client import MCPClient
from shared.models import Severity

log = structlog.get_logger("security_reviewer.tools")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex patterns that indicate a hardcoded secret.
SECRET_PATTERNS: list[re.Pattern[str]] = [
    # AWS keys
    re.compile(r"(?i)(?:aws[_\-]?access[_\-]?key[_\-]?id|aws[_\-]?secret)\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{20,})", re.IGNORECASE),
    # Generic API keys / tokens
    re.compile(r"(?i)(?:api[_\-]?key|api[_\-]?secret|auth[_\-]?token|access[_\-]?token|secret[_\-]?key)\s*[:=]\s*['\"]([A-Za-z0-9_\-]{16,})['\"]", re.IGNORECASE),
    # Private keys
    re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----", re.IGNORECASE),
    # Bearer tokens in code
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\._\-]{20,}", re.IGNORECASE),
    # Connection strings with passwords
    re.compile(r"(?i)(?:postgres|mysql|mongodb|redis):\/\/[^:]+:[^@]+@", re.IGNORECASE),
    # JWT secrets
    re.compile(r"(?i)(?:jwt[_\-]?secret|signing[_\-]?key)\s*[:=]\s*['\"]([^'\"]{8,})['\"]", re.IGNORECASE),
    # Password assignments
    re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"]([^'\"]{4,})['\"]", re.IGNORECASE),
]

# File extensions to skip during secret scanning
SECRET_SCAN_SKIP_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
    ".ttf", ".eot", ".map", ".min.js", ".min.css", ".lock",
}

# Files / directories that are exempt from secret scanning
SECRET_SCAN_EXEMPT_PATHS: set[str] = {
    ".env.example",
    "requirements.txt",
    "package-lock.json",
    "yarn.lock",
    "Pipfile.lock",
    ".gitignore",
}

# OWASP Top 10 (2021) category identifiers
OWASP_CATEGORIES: dict[str, str] = {
    "A01": "Broken Access Control",
    "A02": "Cryptographic Failures",
    "A03": "Injection",
    "A04": "Insecure Design",
    "A05": "Security Misconfiguration",
    "A06": "Vulnerable and Outdated Components",
    "A07": "Identification and Authentication Failures",
    "A08": "Software and Data Integrity Failures",
    "A09": "Security Logging and Monitoring Failures",
    "A10": "Server-Side Request Forgery (SSRF)",
}

# Patterns per OWASP category for static analysis
OWASP_PATTERNS: dict[str, list[dict[str, Any]]] = {
    "A03": [
        {
            "pattern": re.compile(r"(?i)\.(?:execute|raw|text)\s*\(\s*['\"].*(?:%s|%d|\{|\+)", re.DOTALL),
            "message": "Possible SQL/NoSQL injection — string formatting in query execution",
            "severity": Severity.CRITICAL,
        },
        {
            "pattern": re.compile(r"(?i)f['\"].*(?:SELECT|INSERT|UPDATE|DELETE|DROP)\s", re.DOTALL),
            "message": "f-string used in SQL statement — use parameterized queries instead",
            "severity": Severity.CRITICAL,
        },
        {
            "pattern": re.compile(r"(?i)os\.(?:system|popen|exec)\s*\(\s*(?!.*subprocess)"),
            "message": "Direct OS command execution — potential command injection",
            "severity": Severity.CRITICAL,
        },
        {
            "pattern": re.compile(r"(?i)subprocess\.(?:call|run|Popen)\s*\(.*shell\s*=\s*True"),
            "message": "subprocess with shell=True — potential command injection",
            "severity": Severity.HIGH,
        },
    ],
    "A01": [
        {
            "pattern": re.compile(r"(?i)@app\.(?:get|post|put|delete|patch)\s*\(.*\)\s*\nasync\s+def\s+\w+\s*\([^)]*\)\s*:(?:(?!\bDepends\b).)*$"),
            "message": "Endpoint may be missing authentication/authorization (no Depends)",
            "severity": Severity.HIGH,
        },
    ],
    "A02": [
        {
            "pattern": re.compile(r"(?i)(?:md5|sha1)\s*\("),
            "message": "Weak hash algorithm (MD5/SHA1) — use bcrypt, argon2, or SHA-256+",
            "severity": Severity.HIGH,
        },
        {
            "pattern": re.compile(r"(?i)(?:DES|3DES|RC4|Blowfish)\b"),
            "message": "Weak or deprecated cipher — use AES-256-GCM or ChaCha20",
            "severity": Severity.HIGH,
        },
    ],
    "A05": [
        {
            "pattern": re.compile(r"(?i)debug\s*[:=]\s*True"),
            "message": "Debug mode enabled — must be False in production",
            "severity": Severity.MEDIUM,
        },
        {
            "pattern": re.compile(r"(?i)CORS\s*\(\s*app.*allow_origins\s*=\s*\[\s*['\"]\\*['\"]"),
            "message": "CORS allows all origins — restrict to trusted domains",
            "severity": Severity.HIGH,
        },
    ],
    "A07": [
        {
            "pattern": re.compile(r"(?i)session.*(?:secure\s*=\s*False|httponly\s*=\s*False)"),
            "message": "Session cookie flags insecure — set Secure and HttpOnly",
            "severity": Severity.MEDIUM,
        },
    ],
    "A09": [
        {
            "pattern": re.compile(r"(?i)except\s+\w+\s*:\s*(?:pass|\.\.\.)\s*$", re.MULTILINE),
            "message": "Silent exception swallowing — log all errors",
            "severity": Severity.MEDIUM,
        },
    ],
    "A10": [
        {
            "pattern": re.compile(r"(?i)(?:requests\.(?:get|post)|httpx\.(?:get|post)|aiohttp\.ClientSession).*user.*input"),
            "message": "Possible SSRF — user input used in outbound request URL",
            "severity": Severity.HIGH,
        },
    ],
}


# ---------------------------------------------------------------------------
# Dataclasses for structured findings
# ---------------------------------------------------------------------------


@dataclass
class SecurityFinding:
    """A single security finding discovered during review."""

    id: str
    category: str
    title: str
    description: str
    severity: Severity
    file_path: str
    line_number: int | None = None
    evidence: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "id": self.id,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "severity": self.severity.value,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass
class SecurityReport:
    """Aggregated security report from one or more scans."""

    findings: list[SecurityFinding] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.findings)

    @property
    def has_high(self) -> bool:
        return any(f.severity == Severity.HIGH for f in self.findings)

    @property
    def passed(self) -> bool:
        """True when no CRITICAL or HIGH findings exist."""
        return not self.has_critical and not self.has_high

    def summary(self) -> dict[str, Any]:
        counts = {s.value: 0 for s in Severity}
        for f in self.findings:
            counts[f.severity.value] += 1
        return {
            "total": len(self.findings),
            "counts": counts,
            "passed": self.passed,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def get_tools() -> dict[str, Callable[..., Any]]:
    """Return the mapping of tool names to their callable implementations.

    Each callable is either an ``async`` function or returns a coroutine so
    that the caller can ``await`` it uniformly.
    """

    mcp = MCPClient()

    tools: dict[str, Callable[..., Any]] = {
        "get_file_content": _make_get_file_content(mcp),
        "list_repository_files": _make_list_repository_files(mcp),
        "search_code": _make_search_code(mcp),
        "create_pr_review_comment": _make_create_pr_review_comment(mcp),
        "request_changes": _make_request_changes(mcp),
        "search_cve": _make_search_cve(mcp),
        "get_security_docs": _make_get_security_docs(mcp),
        "scan_for_secrets": scan_for_secrets,
        "check_owasp_patterns": check_owasp_patterns,
        "analyze_code": analyze_code,
        "generate_report": generate_report,
    }

    return tools


# ---------------------------------------------------------------------------
# GitHub MCP wrappers
# ---------------------------------------------------------------------------


def _make_get_file_content(mcp: MCPClient) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Fetch the contents of a single file from the GitHub repository.

    Parameters
    ----------
    mcp : MCPClient
        Shared MCP client instance.

    Returns
    -------
    async callable
        ``get_file_content(file_path: str, ref: str = "main") -> str``
    """

    async def get_file_content(file_path: str, ref: str = "main") -> str:
        """Retrieve raw file content from the repository.

        Parameters
        ----------
        file_path : str
            Path relative to the repository root (e.g. ``backend/app/auth.py``).
        ref : str
            Git reference — branch name, tag, or commit SHA.

        Returns
        -------
        str
            The raw text content of the file.
        """
        log.info("github.get_file", file_path=file_path, ref=ref)
        result = await mcp.call(
            server="github_mcp",
            tool="get_file",
            arguments={"file_path": file_path, "ref": ref},
        )
        content = result.get("content", "")
        log.info("github.get_file.done", file_path=file_path, length=len(content))
        return content

    return get_file_content


def _make_list_repository_files(mcp: MCPClient) -> Callable[..., Coroutine[Any, Any, Any]]:
    """List files in the repository tree for a given ref.

    Returns
    -------
    async callable
        ``list_repository_files(ref: str = "main") -> list[dict]``
    """

    async def list_repository_files(ref: str = "main") -> list[dict[str, Any]]:
        """List all files in the repository tree.

        Parameters
        ----------
        ref : str
            Git reference.

        Returns
        -------
        list[dict]
            Each dict has ``path``, ``type`` (blob/tree), and ``size`` keys.
        """
        log.info("github.list_files", ref=ref)
        result = await mcp.call(
            server="github_mcp",
            tool="list_files",
            arguments={"ref": ref},
        )
        files = result.get("files", [])
        log.info("github.list_files.done", count=len(files))
        return files

    return list_repository_files


def _make_search_code(mcp: MCPClient) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Search for code patterns across the repository.

    Returns
    -------
    async callable
        ``search_code(query: str, ref: str = "main") -> list[dict]``
    """

    async def search_code(query: str, ref: str = "main") -> list[dict[str, Any]]:
        """Search code in the repository matching *query*.

        Parameters
        ----------
        query : str
            Search query string (GitHub code search syntax).
        ref : str
            Git reference to search within.

        Returns
        -------
        list[dict]
            Each dict has ``file_path``, ``line_number``, ``line_content`` keys.
        """
        log.info("github.search_code", query=query, ref=ref)
        result = await mcp.call(
            server="github_mcp",
            tool="search_code",
            arguments={"query": query, "ref": ref},
        )
        matches = result.get("matches", [])
        log.info("github.search_code.done", query=query, matches=len(matches))
        return matches

    return search_code


def _make_create_pr_review_comment(
    mcp: MCPClient,
) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Post a review comment on a pull request.

    Returns
    -------
    async callable
        ``create_pr_review_comment(pr_number: int, body: str, ...) -> dict``
    """

    async def create_pr_review_comment(
        pr_number: int,
        body: str,
        commit_sha: str | None = None,
        file_path: str | None = None,
        line: int | None = None,
    ) -> dict[str, Any]:
        """Create a review comment on the given PR.

        Parameters
        ----------
        pr_number : int
            Pull request number.
        body : str
            Markdown body of the comment.
        commit_sha : str, optional
            The commit SHA to anchor the comment to.
        file_path : str, optional
            File path for inline comments.
        line : int, optional
            Line number for inline comments.

        Returns
        -------
        dict
            The created comment object from GitHub.
        """
        arguments: dict[str, Any] = {"pr_number": pr_number, "body": body}
        if commit_sha:
            arguments["commit_sha"] = commit_sha
        if file_path:
            arguments["file_path"] = file_path
        if line:
            arguments["line"] = line

        log.info(
            "github.create_comment",
            pr_number=pr_number,
            file_path=file_path,
            line=line,
        )
        result = await mcp.call(
            server="github_mcp",
            tool="create_review_comment",
            arguments=arguments,
        )
        log.info("github.create_comment.done", pr_number=pr_number)
        return result

    return create_pr_review_comment


def _make_request_changes(mcp: MCPClient) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Submit a ``REQUEST_CHANGES`` review on a PR.

    Returns
    -------
    async callable
        ``request_changes(pr_number: int, body: str) -> dict``
    """

    async def request_changes(pr_number: int, body: str) -> dict[str, Any]:
        """Request changes on a pull request, blocking merge.

        Parameters
        ----------
        pr_number : int
            Pull request number.
        body : str
            Summary of the security issues that must be addressed.

        Returns
        -------
        dict
            The review object returned by GitHub.
        """
        log.info("github.request_changes", pr_number=pr_number)
        result = await mcp.call(
            server="github_mcp",
            tool="create_review",
            arguments={
                "pr_number": pr_number,
                "event": "REQUEST_CHANGES",
                "body": body,
            },
        )
        log.info("github.request_changes.done", pr_number=pr_number)
        return result

    return request_changes


# ---------------------------------------------------------------------------
# Context7 MCP wrappers
# ---------------------------------------------------------------------------


def _make_search_cve(mcp: MCPClient) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Look up known CVEs for a dependency via Context7.

    Returns
    -------
    async callable
        ``search_cve(library: str, version: str | None = None) -> list[dict]``
    """

    async def search_cve(
        library: str, version: str | None = None
    ) -> list[dict[str, Any]]:
        """Search for known CVEs affecting the given library.

        Parameters
        ----------
        library : str
            Library or package name (e.g. ``fastapi``, ``lodash``).
        version : str, optional
            Specific version to check.  If *None*, returns advisories for
            all recent versions.

        Returns
        -------
        list[dict]
            Each dict contains ``cve_id``, ``severity``, ``description``,
            ``affected_versions``, ``fixed_version`` keys.
        """
        log.info("context7.search_cve", library=library, version=version)
        # First resolve the library identifier in Context7
        lib_result = await mcp.call(
            server="context7",
            tool="resolve_library_id",
            arguments={"query": library},
        )
        library_id = lib_result.get("library_id", library)

        # Then search for security advisories / CVE docs
        docs_result = await mcp.call(
            server="context7",
            tool="get_library_docs",
            arguments={
                "library_id": library_id,
                "query": f"CVE security vulnerability {version or ''}".strip(),
            },
        )
        cves = docs_result.get("cves", [])
        log.info("context7.search_cve.done", library=library, cves_found=len(cves))
        return cves

    return search_cve


def _make_get_security_docs(mcp: MCPClient) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Retrieve security best-practice documentation from Context7.

    Returns
    -------
    async callable
        ``get_security_docs(topic: str) -> str``
    """

    async def get_security_docs(topic: str) -> str:
        """Get security-related documentation or best practices.

        Parameters
        ----------
        topic : str
            The security topic to look up (e.g. ``"FastAPI authentication"``,
            ``"SQLAlchemy SQL injection prevention"``,
            ``"OWASP session management"``).

        Returns
        -------
        str
            Relevant documentation text.
        """
        log.info("context7.get_security_docs", topic=topic)

        # Resolve a relevant library based on the topic keywords
        lib_result = await mcp.call(
            server="context7",
            tool="resolve_library_id",
            arguments={"query": topic},
        )
        library_id = lib_result.get("library_id", topic)

        docs_result = await mcp.call(
            server="context7",
            tool="get_library_docs",
            arguments={
                "library_id": library_id,
                "query": f"security best practices {topic}",
            },
        )
        text = docs_result.get("documentation", "")
        log.info("context7.get_security_docs.done", topic=topic, length=len(text))
        return text

    return get_security_docs


# ---------------------------------------------------------------------------
# Local security analysis logic
# ---------------------------------------------------------------------------


def scan_for_secrets(
    file_path: str,
    content: str,
) -> list[SecurityFinding]:
    """Scan source code for hardcoded secrets, tokens, and credentials.

    Parameters
    ----------
    file_path : str
        Path of the file being scanned (used in the finding report).
    content : str
        Raw source code content.

    Returns
    -------
    list[SecurityFinding]
        Findings for every secret pattern match.
    """
    # Skip binary / exempt files
    if any(file_path.endswith(ext) for ext in SECRET_SCAN_SKIP_EXTENSIONS):
        return []
    if os.path.basename(file_path) in SECRET_SCAN_EXEMPT_PATHS:
        return []

    findings: list[SecurityFinding] = []
    lines = content.splitlines()

    for line_num, line in enumerate(lines, start=1):
        # Skip comments that look like examples
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            # Allow scanning comments too — secrets sometimes end up there
            pass

        for pattern in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                # Redact the actual secret value for the report
                redacted_line = _redact_secret(line)
                finding_id = f"SEC-SECRET-{len(findings) + 1:03d}"
                findings.append(
                    SecurityFinding(
                        id=finding_id,
                        category="A05",
                        title="Hardcoded secret detected",
                        description=(
                            "A potential secret, token, or credential was found "
                            "hardcoded in the source file.  Secrets must be loaded "
                            "from environment variables or a secrets manager."
                        ),
                        severity=Severity.CRITICAL,
                        file_path=file_path,
                        line_number=line_num,
                        evidence=redacted_line,
                        recommendation=(
                            "Move the secret to an environment variable or a "
                            "dedicated secrets manager (e.g. HashiCorp Vault, "
                            "AWS Secrets Manager).  Rotate the exposed credential "
                            "immediately."
                        ),
                    )
                )
                # One finding per line is enough — break to avoid duplicates
                break

    return findings


def check_owasp_patterns(
    file_path: str,
    content: str,
) -> list[SecurityFinding]:
    """Run static OWASP pattern checks against source code.

    Parameters
    ----------
    file_path : str
        Path of the file being scanned.
    content : str
        Raw source code content.

    Returns
    -------
    list[SecurityFinding]
        Findings for every OWASP pattern match.
    """
    findings: list[SecurityFinding] = []
    lines = content.splitlines()

    for category, patterns in OWASP_PATTERNS.items():
        category_name = OWASP_CATEGORIES.get(category, category)
        for rule in patterns:
            pattern: re.Pattern[str] = rule["pattern"]
            for line_num, line in enumerate(lines, start=1):
                if pattern.search(line):
                    finding_id = (
                        f"SEC-{category}-{len(findings) + 1:03d}"
                    )
                    findings.append(
                        SecurityFinding(
                            id=finding_id,
                            category=category,
                            title=f"{category_name} — {rule['message'].split('—')[0].strip()}",
                            description=rule["message"],
                            severity=rule["severity"],
                            file_path=file_path,
                            line_number=line_num,
                            evidence=line.strip()[:200],
                            recommendation=_recommendation_for_category(category),
                        )
                    )

    return findings


async def analyze_code(
    file_path: str,
    content: str,
) -> SecurityFinding:
    """Run a single security analysis — this is never used directly; it exists
    as a convenience wrapper for external callers.

    Parameters
    ----------
    file_path : str
        Path of the file.
    content : str
        Source code content.

    Returns
    -------
    SecurityFinding
        The most severe finding, or a clean-finding sentinel.
    """
    all_findings: list[SecurityFinding] = []
    all_findings.extend(scan_for_secrets(file_path, content))
    all_findings.extend(check_owasp_patterns(file_path, content))

    if not all_findings:
        return SecurityFinding(
            id="SEC-CLEAN-001",
            category="PASS",
            title="No issues found",
            description="No security issues detected in this file.",
            severity=Severity.LOW,
            file_path=file_path,
        )

    # Return the most severe finding
    severity_order = {
        Severity.CRITICAL: 0,
        Severity.HIGH: 1,
        Severity.MEDIUM: 2,
        Severity.LOW: 3,
    }
    all_findings.sort(key=lambda f: severity_order[f.severity])
    return all_findings[0]


def generate_report(
    findings: list[SecurityFinding],
) -> dict[str, Any]:
    """Generate a structured security report from accumulated findings.

    Parameters
    ----------
    findings : list[SecurityFinding]
        All findings collected during the review.

    Returns
    -------
    dict
        A JSON-serializable report with summary, findings list, and
        a verdict (``"pass"`` or ``"fail"``).
    """
    report = SecurityReport(findings=findings)
    report_dict = report.to_dict()
    report_dict["verdict"] = "pass" if report.passed else "fail"
    report_dict["owasp_coverage"] = _owasp_coverage(findings)
    return report_dict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _redact_secret(line: str) -> str:
    """Replace the secret value portion of a line with ``****REDACTED****``."""
    for pattern in SECRET_PATTERNS:
        match = pattern.search(line)
        if match:
            # Replace the captured group (the secret) with redacted marker
            secret_value = match.group(1) if match.lastindex else match.group(0)
            redacted = line.replace(secret_value, "****REDACTED****", 1)
            return redacted[:200]
    return line[:200]


def _recommendation_for_category(category: str) -> str:
    """Return a static recommendation string for a given OWASP category."""
    recommendations: dict[str, str] = {
        "A01": (
            "Enforce authorization checks on every endpoint.  Use a centralized "
            "middleware or dependency injection (e.g. FastAPI Depends) to verify "
            "permissions before reaching the handler."
        ),
        "A02": (
            "Use strong, modern algorithms: bcrypt/argon2 for password hashing, "
            "AES-256-GCM for encryption.  Never use MD5, SHA1, DES, or RC4."
        ),
        "A03": (
            "Use parameterized queries or an ORM (SQLAlchemy) for all database "
            "operations.  Never interpolate user input into query strings."
        ),
        "A04": (
            "Adopt threat modeling during design.  Validate assumptions about "
            "trust boundaries and data flow."
        ),
        "A05": (
            "Disable debug mode in production.  Restrict CORS origins.  Use "
            "security headers (CSP, HSTS, X-Frame-Options)."
        ),
        "A06": (
            "Regularly audit dependencies with safety / pip-audit / npm audit.  "
            "Pin versions and update when CVEs are disclosed."
        ),
        "A07": (
            "Implement multi-factor authentication where possible.  Use secure, "
            "HttpOnly, SameSite cookies.  Enforce strong password policies."
        ),
        "A08": (
            "Verify integrity of CI/CD pipelines.  Use signed commits and "
            "dependency lock files."
        ),
        "A09": (
            "Log all authentication events, authorization failures, and input "
            "validation failures.  Forward logs to a SIEM or monitoring stack."
        ),
        "A10": (
            "Validate and sanitize all user-supplied URLs before making outbound "
            "requests.  Use allow-lists for permitted domains."
        ),
    }
    return recommendations.get(category, "Consult OWASP guidelines for remediation.")


def _owasp_coverage(findings: list[SecurityFinding]) -> dict[str, int]:
    """Return a mapping of OWASP category → number of findings."""
    coverage: dict[str, int] = {cat: 0 for cat in OWASP_CATEGORIES}
    for finding in findings:
        if finding.category in coverage:
            coverage[finding.category] += 1
    return coverage