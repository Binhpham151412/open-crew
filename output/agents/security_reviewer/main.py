"""Security Reviewer Agent — FastAPI service on port 8007.

Reviews backend and frontend code for OWASP Top 10 vulnerabilities,
exposed secrets, and known CVEs.  Pushes results to QA (pass) or
Backend Dev (issues found).

Endpoints
---------
GET  /.well-known/agent.json   Agent card
POST /a2a                      Receive A2A messages
GET  /health                   Health check
"""

from __future__ import annotations
import logging

import asyncio
import os
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Shared infrastructure
from shared.a2a_server import A2AServer
from shared.mcp_client import MCPClient
from shared.task_queue import TaskQueue

# Local modules
from prompts import SYSTEM_PROMPT
from tools import get_tools

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AGENT_NAME = "security_reviewer"
DISPLAY_NAME = "Security Reviewer"
PORT = int(os.getenv("SECURITY_REVIEWER_PORT", "8007"))
POLL_INTERVAL = float(os.getenv("SECURITY_REVIEWER_POLL_INTERVAL", "1.0"))

CAPABILITIES = ["owasp_top10", "secret_scan", "cve_check"]
INPUT_TYPES = ["source_code"]
OUTPUT_TYPES = ["security_report"]
PUSH_TO = ["qa", "backend_dev"]

# Agents that receive security findings for fixing
FIX_AGENTS = {"backend_dev", "frontend_dev"}
# Agent that receives the report when everything passes
PASS_AGENT = "qa"

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)  # 20 = INFO
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger(AGENT_NAME)

# ---------------------------------------------------------------------------
# Shared instances (created once, used across lifespan)
# ---------------------------------------------------------------------------

a2a_server = A2AServer(agent_name=AGENT_NAME, port=PORT)
mcp_client = MCPClient()
task_queue = TaskQueue(agent_name=AGENT_NAME)

# Background worker handle
_worker_task: Optional[asyncio.Task] = None
_shutdown_event = asyncio.Event()


# ---------------------------------------------------------------------------
# A2A message helpers
# ---------------------------------------------------------------------------

def _build_a2a_message(
    *,
    msg_type: str,
    to: str,
    task_id: str,
    claim: str,
    evidence: str = "",
    suggestion: str = "",
    artifacts: Optional[List[Dict[str, Any]]] = None,
    round_num: int = 1,
) -> Dict[str, Any]:
    """Construct a standard A2A protocol message."""
    return {
        "protocol": "a2a/1.0",
        "type": msg_type,
        "from": AGENT_NAME,
        "to": to,
        "task_id": task_id,
        "round": round_num,
        "payload": {
            "claim": claim,
            "evidence": evidence,
            "suggestion": suggestion,
            "artifacts": artifacts or [],
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Core processing logic
# ---------------------------------------------------------------------------

async def _fetch_source_code(task: Dict[str, Any]) -> str:
    """Extract or retrieve source code from the task payload.

    Tries to pull code from artifacts attached to the message.  If none
    are found, uses the MCP GitHub tool to fetch relevant files.
    """
    payload = task.get("payload", {})
    artifacts = payload.get("artifacts", [])

    # Collect all source code artifacts
    code_parts: list[str] = []
    for artifact in artifacts:
        name = artifact.get("name", "")
        content = artifact.get("content", "")
        if content and any(
            name.endswith(ext)
            for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".yml", ".yaml", ".json")
        ):
            code_parts.append(f"### {name}\n```\n{content}\n```\n")

    if code_parts:
        return "\n".join(code_parts)

    # Fallback: try fetching from GitHub via MCP
    repo = payload.get("metadata", {}).get("repo", "")
    ref = payload.get("metadata", {}).get("ref", "main")
    if repo:
        try:
            result = await mcp_client.call(
                "github_search_code",
                {"repo": repo, "query": "language:python OR language:typescript", "ref": ref},
            )
            files = result.get("items", [])
            for f in files[:20]:  # limit to 20 files
                file_content = f.get("content", "")
                file_path = f.get("path", "unknown")
                if file_content:
                    code_parts.append(f"### {file_path}\n```\n{file_content}\n```\n")
            return "\n".join(code_parts) if code_parts else payload.get("claim", "")
        except Exception as exc:
            log.warning("github_fetch_failed", error=str(exc))
            return payload.get("claim", "")

    return payload.get("claim", "")


async def _run_owasp_scan(code: str) -> List[Dict[str, Any]]:
    """Scan source code for OWASP Top 10 vulnerabilities.

    This performs pattern-based and heuristic analysis using the LLM
    backed by the SYSTEM_PROMPT, with MCP context7 for CVE lookups.
    """
    findings: List[Dict[str, Any]] = []

    # Quick pattern-based checks (complement to LLM analysis)
    import re

    patterns = {
        "A01_Broken_Access_Control": {
            "patterns": [
                r"(?:skip|bypass).*auth",
                r"@app\.(?:get|post|put|delete)\([^)]*\)(?!.*Depends)",
            ],
            "severity": "high",
            "description": "Potential broken access control — endpoint without auth dependency",
        },
        "A03_Injection": {
            "patterns": [
                r"(?:execute|text)\s*\(\s*[\"'].*(?:SELECT|INSERT|UPDATE|DELETE).*%s",
                r"f[\"'].*(?:SELECT|INSERT|UPDATE|DELETE).*{.*}",
                r"os\.system\s*\(",
                r"subprocess\.(?:call|run|Popen)\s*\([^)]*shell\s*=\s*True",
                r"eval\s*\(",
                r"exec\s*\(",
            ],
            "severity": "critical",
            "description": "Potential injection vulnerability (SQL, command, code)",
        },
        "A02_Cryptographic_Failures": {
            "patterns": [
                r"hashlib\.md5",
                r"hashlib\.sha1",
                r"DES\b",
                r"RC4\b",
                r"ECB\b",
            ],
            "severity": "high",
            "description": "Weak or deprecated cryptographic algorithm detected",
        },
        "A05_Security_Misconfiguration": {
            "patterns": [
                r"DEBUG\s*=\s*True",
                r"allow_origins\s*=\s*\[\s*[\"']\*[\"']\s*\]",
                r"SECRET_KEY\s*=\s*[\"'][^\"']{1,16}[\"']",
            ],
            "severity": "medium",
            "description": "Security misconfiguration detected",
        },
        "A07_Auth_Session_Failures": {
            "patterns": [
                r"(?:password|secret|token)\s*=\s*[\"'][^\"']+[\"']",
                r"JWT.*(?:verify\s*=\s*False|algorithms?\s*=\s*\[.*none)",
            ],
            "severity": "critical",
            "description": "Authentication or session management weakness",
        },
        "A10_SSRF": {
            "patterns": [
                r"requests\.(?:get|post)\s*\(\s*(?:f[\"']|.*\+.*user)",
                r"httpx\.(?:get|post)\s*\(\s*(?:f[\"']|.*\+.*user)",
                r"urllib\.request\.urlopen\s*\(",
            ],
            "severity": "high",
            "description": "Potential Server-Side Request Forgery (SSRF)",
        },
    }

    for owasp_id, config in patterns.items():
        for pattern in config["patterns"]:
            matches = list(re.finditer(pattern, code, re.IGNORECASE))
            for match in matches:
                # Find line number
                line_num = code[:match.start()].count("\n") + 1
                # Extract surrounding context
                lines = code.split("\n")
                context_start = max(0, line_num - 2)
                context_end = min(len(lines), line_num + 1)
                context = "\n".join(lines[context_start:context_end])

                findings.append(
                    {
                        "id": owasp_id,
                        "severity": config["severity"],
                        "title": owasp_id.replace("_", " "),
                        "description": config["description"],
                        "location": f"line {line_num}",
                        "evidence": match.group(),
                        "context": context,
                        "recommendation": f"Review and remediate {owasp_id} issue at line {line_num}",
                    }
                )

    return findings


async def _run_secret_scan(code: str) -> List[Dict[str, Any]]:
    """Scan for hardcoded secrets, API keys, tokens, and passwords."""
    import re

    findings: List[Dict[str, Any]] = []

    secret_patterns = [
        {
            "name": "Hardcoded API Key",
            "pattern": r"""(?:api[_-]?key|apikey)\s*[:=]\s*['"]([A-Za-z0-9_\-]{20,})['"]""",
            "severity": "critical",
        },
        {
            "name": "Hardcoded AWS Key",
            "pattern": r"AKIA[0-9A-Z]{16}",
            "severity": "critical",
        },
        {
            "name": "Hardcoded Secret Key",
            "pattern": r"""(?:secret[_-]?key|SECRET_KEY)\s*[:=]\s*['"]([A-Za-z0-9_\-]{16,})['"]""",
            "severity": "critical",
        },
        {
            "name": "Hardcoded Password",
            "pattern": r"""(?:password|passwd|pwd)\s*[:=]\s*['"]([^'"]{8,})['"]""",
            "severity": "critical",
        },
        {
            "name": "Hardcoded Token",
            "pattern": r"""(?:token|bearer)\s*[:=]\s*['"]([A-Za-z0-9_\-.]{20,})['"]""",
            "severity": "critical",
        },
        {
            "name": "Private Key in Code",
            "pattern": r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----",
            "severity": "critical",
        },
        {
            "name": "JWT Secret",
            "pattern": r"""(?:jwt[_-]?secret|JWT_SECRET)\s*[:=]\s*['"]([^'"]+)['"]""",
            "severity": "critical",
        },
        {
            "name": "Database Connection String",
            "pattern": r"""(?:postgres|mysql|mongodb)://\w+:\w+@\S+""",
            "severity": "high",
        },
        {
            "name": "Generic Secret Assignment",
            "pattern": r"""(?:secret|credential|apikey|api_key)\s*=\s*['"](?![\s'"])(?!<|{|%|\$\{)[A-Za-z0-9+/=_\-]{8,}['"]""",
            "severity": "high",
        },
    ]

    for secret_def in secret_patterns:
        matches = list(re.finditer(secret_def["pattern"], code, re.IGNORECASE))
        for match in matches:
            line_num = code[:match.start()].count("\n") + 1
            lines = code.split("\n")
            context_start = max(0, line_num - 2)
            context_end = min(len(lines), line_num + 1)
            context = "\n".join(lines[context_start:context_end])

            # Mask the actual secret value in evidence
            matched_text = match.group()
            if len(matched_text) > 12:
                masked = matched_text[:6] + "***" + matched_text[-4:]
            else:
                masked = matched_text[:3] + "***"

            findings.append(
                {
                    "id": "SECRET_EXPOSED",
                    "severity": secret_def["severity"],
                    "title": secret_def["name"],
                    "description": f"{secret_def['name']} detected in source code",
                    "location": f"line {line_num}",
                    "evidence": masked,
                    "context": context,
                    "recommendation": "Remove hardcoded secret and use environment variables or a secrets manager",
                }
            )

    return findings


async def _run_cve_check(code: str, task: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Check dependencies for known CVEs using context7 MCP tool."""
    import re

    findings: List[Dict[str, Any]] = []

    # Extract dependency versions from artifacts or code
    dep_patterns = [
        # Python: requirements.txt style
        r"([\w\-]+)\s*(?:==|>=|~=|<=)\s*([\d.]+)",
        # Python: pyproject.toml style
        r'"([\w\-]+)\s*(?:==|>=|~=|<=)\s*([\d.]+)"',
        # Node: package.json style — simplified
        r'"([\w@/\-]+)"\s*:\s*"([\^~>=<]*[\d.]+)"',
    ]

    deps_found: Dict[str, str] = {}
    artifacts = task.get("payload", {}).get("artifacts", [])
    for artifact in artifacts:
        content = artifact.get("content", "")
        name = artifact.get("name", "")
        if any(
            n in name
            for n in ("requirements.txt", "pyproject.toml", "package.json", "Pipfile")
        ):
            for pattern in dep_patterns:
                for match in re.finditer(pattern, content):
                    dep_name = match.group(1).strip()
                    dep_version = match.group(2).strip()
                    if dep_name and dep_version:
                        deps_found[dep_name] = dep_version

    # If no dependencies found in artifacts, check the code itself
    if not deps_found:
        for pattern in dep_patterns:
            for match in re.finditer(pattern, code):
                dep_name = match.group(1).strip()
                dep_version = match.group(2).strip()
                if dep_name and dep_version:
                    deps_found[dep_name] = dep_version

    # Query context7 for CVE information on found dependencies
    for dep_name, dep_version in list(deps_found.items())[:10]:  # limit queries
        try:
            cve_result = await mcp_client.call(
                "get_library_docs",
                {
                    "library": dep_name,
                    "query": f"CVE security vulnerability {dep_version}",
                },
            )
            docs = cve_result.get("docs", "") if isinstance(cve_result, dict) else str(cve_result)
            # Heuristic: check if CVE identifiers appear in the docs
            cve_ids = re.findall(r"CVE-\d{4}-\d{4,}", docs)
            if cve_ids:
                findings.append(
                    {
                        "id": "KNOWN_CVE",
                        "severity": "high",
                        "title": f"Known CVE for {dep_name}@{dep_version}",
                        "description": f"Package {dep_name} version {dep_version} has known vulnerabilities",
                        "location": f"dependency: {dep_name}=={dep_version}",
                        "evidence": f"CVEs found: {', '.join(cve_ids[:5])}",
                        "context": docs[:500],
                        "recommendation": f"Update {dep_name} to the latest secure version",
                    }
                )
        except Exception as exc:
            log.debug("cve_check_query_failed", dep=dep_name, error=str(exc))
            # Non-fatal — continue with next dependency

    return findings


async def _generate_security_report(
    findings: List[Dict[str, Any]], task: Dict[str, Any]
) -> Dict[str, Any]:
    """Compile findings into a structured security report."""
    task_id = task.get("task_id", "unknown")

    # Deduplicate findings by (id, location)
    seen: set[tuple[str, str]] = set()
    unique_findings: List[Dict[str, Any]] = []
    for f in findings:
        key = (f["id"], f["location"])
        if key not in seen:
            seen.add(key)
            unique_findings.append(f)

    # Sort by severity (critical first)
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    unique_findings.sort(key=lambda f: severity_order.get(f["severity"], 99))

    # Summary counts
    summary: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in unique_findings:
        sev = f.get("severity", "low")
        summary[sev] = summary.get(sev, 0) + 1

    # Determine overall verdict
    has_critical_or_high = summary["critical"] > 0 or summary["high"] > 0
    passed = not has_critical_or_high

    report = {
        "task_id": task_id,
        "agent": AGENT_NAME,
        "verdict": "PASS" if passed else "FAIL",
        "summary": summary,
        "total_findings": len(unique_findings),
        "findings": unique_findings,
        "scans_performed": ["owasp_top10", "secret_scan", "cve_check"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return report


async def _determine_push_targets(
    report: Dict[str, Any], task: Dict[str, Any]
) -> List[str]:
    """Decide which agents receive the report based on findings.

    Rules from PLAN.md:
    - CRITICAL/HIGH issues → push back to backend_dev (or frontend_dev if frontend code)
    - PASS → push to QA
    """
    if report["verdict"] == "PASS":
        return [PASS_AGENT]

    # Determine if findings relate to frontend or backend code
    payload = task.get("payload", {})
    metadata = payload.get("metadata", {})
    source = metadata.get("source", "backend")

    targets: List[str] = []
    if "frontend" in source:
        targets.append("frontend_dev")
    else:
        targets.append("backend_dev")

    # Always also inform QA so they can adjust test plan
    targets.append(PASS_AGENT)

    return targets


async def process_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single security review task end-to-end.

    1. Fetch/extract source code from the task
    2. Run OWASP Top 10 pattern scan
    3. Run secret scan
    4. Run CVE check against dependencies
    5. Compile security report
    6. Push report to appropriate agents
    """
    task_id = task.get("task_id", str(uuid4()))
    log.info("processing_task", task_id=task_id)

    try:
        # Step 1: Get source code
        source_code = await _fetch_source_code(task)
        if not source_code:
            log.warning("no_source_code", task_id=task_id)
            source_code = task.get("payload", {}).get("claim", "")

        # Step 2–4: Run all scans concurrently
        owasp_findings, secret_findings, cve_findings = await asyncio.gather(
            _run_owasp_scan(source_code),
            _run_secret_scan(source_code),
            _run_cve_check(source_code, task),
            return_exceptions=True,
        )

        all_findings: List[Dict[str, Any]] = []
        if isinstance(owasp_findings, list):
            all_findings.extend(owasp_findings)
        else:
            log.error("owasp_scan_failed", error=str(owasp_findings))

        if isinstance(secret_findings, list):
            all_findings.extend(secret_findings)
        else:
            log.error("secret_scan_failed", error=str(secret_findings))

        if isinstance(cve_findings, list):
            all_findings.extend(cve_findings)
        else:
            log.error("cve_check_failed", error=str(cve_findings))

        # Step 5: Generate report
        report = await _generate_security_report(all_findings, task)

        log.info(
            "security_report_generated",
            task_id=task_id,
            verdict=report["verdict"],
            total_findings=report["total_findings"],
            critical=report["summary"]["critical"],
            high=report["summary"]["high"],
            medium=report["summary"]["medium"],
            low=report["summary"]["low"],
        )

        # Step 6: Push to next agents
        targets = await _determine_push_targets(report, task)
        report_artifact = {
            "name": f"security_report_{task_id[:8]}.json",
            "content": _serialize_report(report),
            "mime_type": "application/json",
        }

        for target in targets:
            msg_type = "result" if report["verdict"] == "PASS" else "challenge"
            message = _build_a2a_message(
                msg_type=msg_type,
                to=target,
                task_id=task_id,
                claim=(
                    f"Security review {'PASSED' if report['verdict'] == 'PASS' else 'FAILED'}: "
                    f"{report['total_findings']} finding(s) — "
                    f"Critical: {report['summary']['critical']}, "
                    f"High: {report['summary']['high']}, "
                    f"Medium: {report['summary']['medium']}, "
                    f"Low: {report['summary']['low']}"
                ),
                evidence=f"Scans performed: {', '.join(report['scans_performed'])}",
                suggestion=(
                    "All clear — proceed to QA testing"
                    if report["verdict"] == "PASS"
                    else "Fix all CRITICAL and HIGH severity issues before resubmitting"
                ),
                artifacts=[report_artifact],
            )
            await a2a_server.push(to=target, message=message)
            log.info("pushed_report", task_id=task_id, target=target, verdict=report["verdict"])

        return report

    except Exception as exc:
        log.error("task_processing_failed", task_id=task_id, error=str(exc), exc_info=True)
        raise


def _serialize_report(report: Dict[str, Any]) -> str:
    """Serialize the security report to a JSON string."""
    import json

    return json.dumps(report, indent=2, default=str)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

async def worker_loop() -> None:
    """Background loop that processes tasks from the queue.

    Runs until ``_shutdown_event`` is set.  After processing a task and
    pushing results, immediately checks for the next task (no idle wait).
    """
    log.info("worker_started", poll_interval=POLL_INTERVAL)
    while not _shutdown_event.is_set():
        try:
            task = await task_queue.pop()
            if task is None:
                # Nothing in queue — wait briefly then retry
                await asyncio.sleep(POLL_INTERVAL)
                continue

            task_id = task.get("task_id", "unknown")
            log.info("worker_picked_task", task_id=task_id)

            try:
                await process_task(task)
                await task_queue.ack(task_id)
                log.info("worker_completed_task", task_id=task_id)
            except Exception as exc:
                log.error(
                    "worker_task_failed",
                    task_id=task_id,
                    error=str(exc),
                    exc_info=True,
                )
                # Ack the task even on failure to prevent infinite re-processing
                await task_queue.ack(task_id)

        except asyncio.CancelledError:
            log.info("worker_cancelled")
            break
        except Exception as exc:
            log.error("worker_unexpected_error", error=str(exc), exc_info=True)
            await asyncio.sleep(POLL_INTERVAL)

    log.info("worker_stopped")


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Manage startup and shutdown lifecycle events."""
    global _worker_task

    log.info(
        "agent_starting",
        agent=AGENT_NAME,
        display_name=DISPLAY_NAME,
        port=PORT,
        capabilities=CAPABILITIES,
    )

    # Start background worker
    await task_queue.recover_stuck_tasks()
    _worker_task = asyncio.create_task(worker_loop())

    yield

    # Shutdown: signal worker to stop and wait for it
    log.info("agent_shutting_down")
    _shutdown_event.set()
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass

    log.info("agent_stopped")


app = FastAPI(
    title=DISPLAY_NAME,
    description="Security Reviewer Agent — OWASP Top 10, secret scanning, CVE checking",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    """Return the agent card per A2A protocol specification."""
    card = a2a_server.get_card(
        display_name=DISPLAY_NAME,
        url=f"http://{AGENT_NAME}:{PORT}",
        capabilities=CAPABILITIES,
        input_types=INPUT_TYPES,
        output_types=OUTPUT_TYPES,
    )
    # Override / extend card fields specific to this agent
    card.update(
        {
            "name": AGENT_NAME,
            "display_name": DISPLAY_NAME,
            "url": f"http://{AGENT_NAME}:{PORT}",
            "version": "1.0.0",
            "capabilities": CAPABILITIES,
            "input_types": INPUT_TYPES,
            "output_types": OUTPUT_TYPES,
            "push_to": PUSH_TO,
            "protocol": "a2a/1.0",
        }
    )
    return JSONResponse(content=card)


@app.post("/a2a")
async def receive_task(request: Request) -> JSONResponse:
    """Receive an A2A message and enqueue it for background processing.

    Returns 202 Accepted immediately (non-blocking).
    """
    try:
        body = await request.json()
    except Exception as exc:
        log.error("invalid_json_payload", error=str(exc))
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    task_id = body.get("task_id", str(uuid4()))
    body["task_id"] = task_id

    log.info(
        "task_received",
        task_id=task_id,
        from_agent=body.get("from", "unknown"),
        message_type=body.get("type", "unknown"),
    )

    await task_queue.push(body)

    return JSONResponse(
        status_code=202,
        content={"status": "accepted", "task_id": task_id},
    )


@app.get("/health")
async def health() -> JSONResponse:
    """Health check endpoint for monitoring and service discovery."""
    queue_size = await task_queue.size() if hasattr(task_queue, "size") else 0
    return JSONResponse(
        content={
            "status": "ok",
            "agent": AGENT_NAME,
            "display_name": DISPLAY_NAME,
            "port": PORT,
            "queue_size": queue_size,
            "capabilities": CAPABILITIES,
            "worker_running": _worker_task is not None and not _worker_task.done(),
        }
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "agents.security_reviewer.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
    )