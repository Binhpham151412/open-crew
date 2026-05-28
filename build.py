"""
OpenCrew Build Engine v2
========================
Direct LLM calls (no CrewAI). Per-file generation. Robust retry + resume.
Designed to run for hours continuously with 30B token budget.

Usage:
  python build.py --test          Test MiMo API connection
  python build.py                 Start/resume full build
  python build.py --status        Show build progress
  python build.py --file <path>   Generate a single file
  python build.py --list          List all files to generate
"""

import os
import sys
import json
import time
import signal
import argparse
from pathlib import Path
from datetime import datetime

# Fix Windows console encoding for Unicode
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

console = Console()
ROOT = Path(__file__).parent
OUTPUT = ROOT / "output"
PROGRESS_FILE = ROOT / ".build_progress.json"

# Graceful shutdown flag
_shutdown = False

def _signal_handler(sig, frame):
    global _shutdown
    _shutdown = True
    console.print("\n[yellow]Ctrl+C detected. Finishing current file then stopping...[/yellow]")

signal.signal(signal.SIGINT, _signal_handler)

# ---------------------------------------------------------------------------
# File Manifest — Every file to generate, with metadata
# ---------------------------------------------------------------------------

AGENTS = [
    "po", "pm", "ba", "solution_architect",
    "frontend_dev", "backend_dev", "uiux_reviewer",
    "security_reviewer", "qa", "devops", "techlead",
]

AGENT_PORTS = {
    "po": 8000, "pm": 8001, "ba": 8002, "solution_architect": 8003,
    "frontend_dev": 8004, "backend_dev": 8005, "uiux_reviewer": 8006,
    "security_reviewer": 8007, "qa": 8008, "devops": 8009, "techlead": 8010,
}

AGENT_DISPLAY_NAMES = {
    "po": "Product Owner", "pm": "Project Manager", "ba": "Business Analyst",
    "solution_architect": "Solution Architect", "frontend_dev": "Frontend Developer",
    "backend_dev": "Backend Developer", "uiux_reviewer": "UIUX Reviewer",
    "security_reviewer": "Security Reviewer", "qa": "QA / Tester",
    "devops": "DevOps / SRE", "techlead": "TechLead",
}

AGENT_PUSH_TO = {
    "po": ["pm"], "pm": ["ba", "solution_architect"],
    "ba": ["frontend_dev", "backend_dev"], "solution_architect": ["backend_dev", "devops"],
    "frontend_dev": ["uiux_reviewer"], "backend_dev": ["security_reviewer"],
    "uiux_reviewer": ["qa", "frontend_dev"], "security_reviewer": ["qa", "backend_dev"],
    "qa": ["devops", "backend_dev"], "devops": ["techlead"], "techlead": ["po"],
}

AGENT_CAPABILITIES = {
    "po": ["receive_requirements", "write_prd", "accept_reject"],
    "pm": ["sprint_planning", "story_assignment", "progress_tracking"],
    "ba": ["write_user_stories", "api_contract", "data_model", "acceptance_criteria"],
    "solution_architect": ["system_design", "adr", "db_schema", "interface_design"],
    "frontend_dev": ["nextjs_react", "tailwind_css", "responsive_design"],
    "backend_dev": ["fastapi", "sqlalchemy", "pydantic", "api_implementation"],
    "uiux_reviewer": ["accessibility_review", "ux_validation", "design_compliance"],
    "security_reviewer": ["owasp_top10", "secret_scan", "cve_check"],
    "qa": ["pytest", "playwright", "test_generation", "bug_reporting"],
    "devops": ["docker", "cicd", "deployment", "monitoring"],
    "techlead": ["arbitrate", "final_review", "merge_signoff"],
}

AGENT_INPUT_TYPES = {
    "po": ["user_request"], "pm": ["prd"], "ba": ["story"],
    "solution_architect": ["prd", "story"], "frontend_dev": ["user_story", "api_spec", "ui_spec"],
    "backend_dev": ["api_spec", "db_schema", "user_story"],
    "uiux_reviewer": ["frontend_code", "ui_spec"], "security_reviewer": ["source_code"],
    "qa": ["acceptance_criteria", "source_code"], "devops": ["merged_code", "architecture"],
    "techlead": ["agent_reports", "delivery_package"],
}

AGENT_OUTPUT_TYPES = {
    "po": ["prd"], "pm": ["sprint_plan", "stories"], "ba": ["user_stories", "api_spec", "data_model"],
    "solution_architect": ["adr", "system_diagram", "db_schema"],
    "frontend_dev": ["nextjs_code"], "backend_dev": ["fastapi_code"],
    "uiux_reviewer": ["review_report"], "security_reviewer": ["security_report"],
    "qa": ["test_suite", "bug_reports"], "devops": ["dockerfile", "cicd_config"],
    "techlead": ["final_approval"],
}

AGENT_MCP_TOOLS = {
    "po": ["context7", "linear_mcp"], "pm": ["linear_mcp", "github_mcp"],
    "ba": ["context7", "linear_mcp"], "solution_architect": ["context7", "github_mcp"],
    "frontend_dev": ["github_mcp", "context7"], "backend_dev": ["github_mcp", "context7"],
    "uiux_reviewer": ["github_mcp", "opendesign_mcp"], "security_reviewer": ["github_mcp", "context7"],
    "qa": ["github_mcp", "context7"], "devops": ["github_mcp", "context7"],
    "techlead": ["github_mcp", "linear_mcp"],
}


def build_manifest() -> list[dict]:
    """Build the complete list of files to generate."""
    files = []

    # --- Shared infrastructure ---
    shared_files = [
        ("shared/__init__.py", "Empty init file for shared module"),
        ("shared/models.py", "Pydantic shared models: A2AMessage, TaskPayload, AgentCard, "
         "Artifact, DebateMessage. Use Pydantic v2 BaseModel."),
        ("shared/a2a_client.py", "A2A client: async function push(to_agent, message) that sends "
         "HTTP POST to target agent's /a2a endpoint. Use httpx.AsyncClient. "
         "Support retry with exponential backoff."),
        ("shared/a2a_server.py", "A2A server base class: A2AServer(agent_name, port). "
         "Methods: get_card() returns AgentCard, validate_message(msg), "
         "register_handler(msg_type, handler). Include FastAPI router."),
        ("shared/mcp_client.py", "MCP client: MCPClient class that calls MCP tools via JSON-RPC 2.0. "
         "Method: call(tool_name, arguments) -> result. Use httpx. "
         "Support multiple MCP servers from env config."),
        ("shared/task_queue.py", "Redis-backed async task queue: TaskQueue(agent_name). "
         "Methods: push(message), pop() -> message, size() -> int, ack(task_id). "
         "Use redis.asyncio. Fallback to in-memory queue if Redis unavailable."),
        ("shared/registry.py", "Agent auto-discovery registry: Registry class. "
         "Methods: register(agent_card), discover(agent_name) -> AgentCard, "
         "list_all() -> list[AgentCard]. Poll /.well-known/agent.json endpoints. "
         "Store in Redis or in-memory dict."),
    ]
    for path, desc in shared_files:
        files.append({"path": path, "desc": desc, "group": "shared", "priority": 1})

    # --- Each agent's files ---
    for agent in AGENTS:
        port = AGENT_PORTS[agent]
        display = AGENT_DISPLAY_NAMES[agent]
        push_to = AGENT_PUSH_TO[agent]
        caps = AGENT_CAPABILITIES[agent]
        in_types = AGENT_INPUT_TYPES[agent]
        out_types = AGENT_OUTPUT_TYPES[agent]
        mcp_tools = AGENT_MCP_TOOLS[agent]

        # __init__.py
        files.append({
            "path": f"agents/{agent}/__init__.py",
            "desc": f"Empty init for {agent} agent module",
            "group": f"agent:{agent}", "priority": 2,
        })

        # main.py
        files.append({
            "path": f"agents/{agent}/main.py",
            "desc": (
                f"FastAPI main.py for {display} agent (port {port}).\n"
                f"Endpoints: GET /.well-known/agent.json, POST /a2a, GET /health.\n"
                f"Agent name: '{agent}'. Display name: '{display}'.\n"
                f"Capabilities: {caps}\n"
                f"Input types: {in_types}\n"
                f"Output types: {out_types}\n"
                f"Push to agents: {push_to}\n"
                f"Uses: shared.a2a_server.A2AServer, shared.mcp_client.MCPClient, "
                f"shared.task_queue.TaskQueue\n"
                f"Background worker: asyncio task that pops from queue, processes, "
                f"pushes result to next agent.\n"
                f"Import SYSTEM_PROMPT from .prompts and get_tools from .tools.\n"
                f"Use structlog for logging. Include CORS middleware."
            ),
            "group": f"agent:{agent}", "priority": 2,
        })

        # tools.py
        files.append({
            "path": f"agents/{agent}/tools.py",
            "desc": (
                f"MCP tool implementations for {display} agent.\n"
                f"Function get_tools() -> dict of tool_name: callable.\n"
                f"MCP tools used: {mcp_tools}\n"
                f"Each tool wraps an MCP client call or implements local logic.\n"
                f"Tools should match the agent's responsibilities."
            ),
            "group": f"agent:{agent}", "priority": 2,
        })

        # prompts.py
        files.append({
            "path": f"agents/{agent}/prompts.py",
            "desc": (
                f"System prompt for {display} agent.\n"
                f"SYSTEM_PROMPT = string with role, capabilities, rules.\n"
                f"Agent role: {display}\n"
                f"Must include: output format rules, A2A message format, "
                f"debate protocol, auto-approve rules."
            ),
            "group": f"agent:{agent}", "priority": 2,
        })

        # agent.json (well-known card)
        files.append({
            "path": f"agents/{agent}/agent.json",
            "desc": (
                f"Agent card JSON for {display}.\n"
                f"name: '{agent}', display_name: '{display}', "
                f"url: 'http://{agent}:{port}', version: '1.0.0', "
                f"capabilities: {caps}, input_types: {in_types}, "
                f"output_types: {out_types}, protocol: 'a2a/1.0'"
            ),
            "group": f"agent:{agent}", "priority": 2,
        })

        # Dockerfile
        files.append({
            "path": f"agents/{agent}/Dockerfile",
            "desc": (
                f"Dockerfile for {display} agent.\n"
                f"Python 3.11-slim, non-root user, multi-stage build.\n"
                f"Install requirements.txt, copy shared/ and agent code.\n"
                f"Expose port {port}. CMD: uvicorn main:app --host 0.0.0.0 --port {port}\n"
                f"Health check: curl http://localhost:{port}/health"
            ),
            "group": f"agent:{agent}", "priority": 2,
        })

        # requirements.txt
        files.append({
            "path": f"agents/{agent}/requirements.txt",
            "desc": (
                f"Python dependencies for {display} agent.\n"
                f"Include: fastapi>=0.110.0, uvicorn>=0.27.0, httpx>=0.27.0, "
                f"pydantic>=2.0, python-dotenv>=1.0.0, structlog>=24.0.0, "
                f"redis>=5.0.0"
            ),
            "group": f"agent:{agent}", "priority": 2,
        })

    # --- Web UI ---
    web_files = [
        ("web/package.json", "NextJS 14 package.json with dependencies: next, react, "
         "react-dom, typescript, tailwindcss, @radix-ui/*, recharts, zustand, "
         "lucide-react, clsx, tailwind-merge"),
        ("web/next.config.js", "NextJS config: enable app router, standalone output"),
        ("web/tailwind.config.ts", "Tailwind config: dark mode class, content paths, "
         "extend theme with custom colors from UI_SPEC"),
        ("web/tsconfig.json", "TypeScript config for NextJS 14"),
        ("web/postcss.config.js", "PostCSS config for Tailwind"),
        ("web/app/layout.tsx", "Root layout: dark mode default, Inter font, "
         "Sidebar component, top bar with OpenCrew title + status, footer"),
        ("web/app/page.tsx", "Dashboard page: AgentStatusCard grid, RecentTasks list, "
         "TokenChart 7-day bar chart. Fetch from /api/agents, /api/tasks, /api/stats"),
        ("web/app/globals.css", "Global CSS: Tailwind directives, dark mode variables, "
         "custom scrollbar styles"),
        ("web/app/tasks/page.tsx", "Tasks page: New Task form (textarea + submit), "
         "Task list with expandable timeline showing A2A messages. "
         "Fetch from /api/tasks"),
        ("web/app/agents/page.tsx", "Agents page: Grid of AgentCard components. "
         "Each shows status dot, name, model, tools, settings (model dropdown, "
         "temperature slider, max tokens input, enabled toggle). "
         "Buttons: Test, View Logs, Restart"),
        ("web/app/config/page.tsx", "Config page: API keys form (MiMo, GitHub, MCP servers), "
         "A2A connections grid. Test/Save buttons per field"),
        ("web/app/logs/page.tsx", "Logs page: Filters (agent, level, search), "
         "real-time log stream via SSE from /api/logs. "
         "Monospace font, auto-scroll, color by level (INFO=green, WARN=yellow, ERROR=red)"),
        ("web/app/api/agents/route.ts", "API route GET /api/agents: "
         "Return list of agents with status (poll each agent's /health endpoint)"),
        ("web/app/api/tasks/route.ts", "API route: GET list tasks, POST create new task. "
         "Store tasks in memory or Redis"),
        ("web/app/api/config/route.ts", "API route: GET current config, POST update config. "
         "Read/write .env file or config store"),
        ("web/app/api/logs/route.ts", "SSE endpoint: Stream logs from all agents. "
         "Use ReadableStream, text/event-content-type"),
        ("web/app/api/stats/route.ts", "API route GET /api/stats: "
         "Return token usage, uptime, active agents count"),
        ("web/components/Sidebar.tsx", "Sidebar: collapsible, navigation links "
         "(Dashboard, Tasks, Agents, Config, Logs). Highlight active page. "
         "Dark bg, icons from lucide-react"),
        ("web/components/AgentCard.tsx", "AgentCard: status dot (green/gray/yellow), "
         "agent name, model, tools list, settings panel. "
         "Buttons: Test, View Logs, Restart"),
        ("web/components/TaskTimeline.tsx", "TaskTimeline: vertical timeline of A2A messages "
         "for a task. Show from/to agent, timestamp, message type, payload summary"),
        ("web/components/DebateViewer.tsx", "DebateViewer: show debate rounds between agents. "
         "CHALLENGE → RESPONSE → FINAL_POSITION flow. "
         "Highlight conflict resolution"),
        ("web/components/LogViewer.tsx", "LogViewer: monospace log stream with auto-scroll. "
         "Color by level, filter by agent, search. Pause/resume button"),
        ("web/components/TokenChart.tsx", "TokenChart: 7-day bar chart using recharts. "
         "Stacked by agent. Show total + estimated cost"),
        ("web/components/StatusDot.tsx", "StatusDot component: green circle (online), "
         "gray circle (offline), yellow pulse (working)"),
        ("web/tailwind.config.js", "Tailwind JS config file (alternative to .ts)"),
    ]
    for path, desc in web_files:
        files.append({"path": path, "desc": desc, "group": "web", "priority": 3})

    # --- Integration / Infrastructure ---
    integration_files = [
        ("docker-compose.yml", "Docker Compose for all 11 agent services + Redis + web UI. "
         "Each agent: build from agents/<name>/, port mapping, depends_on redis, "
         "health check. Redis: redis:7-alpine. Web: build from web/, port 3000. "
         "Networks: opencrew-net. Volumes: redis-data."),
        (".env.example", "Example .env file with all required env vars: "
         "MIMO_API_KEY, MIMO_BASE_URL, MIMO_MODEL, GITHUB_TOKEN, "
         "GITHUB_MCP_URL, LINEAR_MCP_URL, OPENDESIGN_MCP_URL, "
         "REDIS_URL, all with placeholder values"),
        (".gitignore", "Gitignore: output/, __pycache__/, .env, node_modules/, "
         ".next/, .build_progress.json, *.pyc"),
        ("README.md", "Project README: OpenCrew multi-agent AI software team. "
         "Quick start (docker-compose up), architecture overview, agent list, "
         "tech stack, development guide"),
        ("tests/test_integration.py", "Integration tests: test all agents /health endpoints, "
         "test A2A message flow PO→PM→BA, test Redis queue, test web UI returns 200"),
        ("tests/__init__.py", "Empty init for tests"),
        ("tests/conftest.py", "Pytest fixtures: httpx.AsyncClient, agent URLs from env, "
         "test Redis connection"),
    ]
    for path, desc in integration_files:
        files.append({"path": path, "desc": desc, "group": "integration", "priority": 4})

    return files


# ---------------------------------------------------------------------------
# Progress tracking (file-level granularity)
# ---------------------------------------------------------------------------

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            pass
    return {
        "started_at": None,
        "completed_files": [],
        "failed_files": {},
        "skipped_files": [],
        "total_tokens": 0,
        "api_calls": 0,
        "last_update": None,
    }


def save_progress(progress: dict):
    progress["last_update"] = datetime.now().isoformat()
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------------------
# LLM interaction (direct, no CrewAI)
# ---------------------------------------------------------------------------

def create_client():
    from openai import OpenAI
    return OpenAI(
        api_key=os.getenv("MIMO_API_KEY"),
        base_url=os.getenv("MIMO_BASE_URL"),
    )


def build_prompt(file_info: dict, context: str, related_files: dict[str, str]) -> str:
    """Build a focused prompt for generating a single file."""
    path = file_info["path"]
    desc = file_info["desc"]

    # Determine language/type
    ext = Path(path).suffix
    lang_map = {
        ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript React",
        ".js": "JavaScript", ".json": "JSON", ".yml": "YAML",
        ".yaml": "YAML", ".css": "CSS", ".md": "Markdown",
    }
    lang = lang_map.get(ext, "text")

    prompt = f"""You are generating a single file for the OpenCrew project.

FILE TO GENERATE: {path}
LANGUAGE: {lang}

FILE DESCRIPTION:
{desc}

PROJECT CONTEXT (specs and architecture):
{context}
"""

    if related_files:
        prompt += "\nRELATED FILES (for reference — use their types/imports):\n"
        for rel_path, rel_content in related_files.items():
            # Truncate related files to save tokens
            truncated = rel_content[:3000] + ("..." if len(rel_content) > 3000 else "")
            prompt += f"\n--- {rel_path} ---\n{truncated}\n"

    prompt += f"""
RULES:
1. Output ONLY the file content — no explanations, no markdown fences
2. Write COMPLETE, production-ready code — no TODOs, no placeholders
3. Follow the project conventions from the context above
4. For Python: use type hints, docstrings, async where appropriate
5. For TypeScript: use strict types, proper imports
6. Start directly with the code — first line should be the first line of the file

Generate the complete content for {path}:"""

    return prompt


def get_related_files(file_info: dict, progress: dict) -> dict[str, str]:
    """Get content of related files that have already been generated."""
    path = file_info["path"]
    related = {}
    completed = set(progress.get("completed_files", []))

    # shared/models.py is related to almost everything
    if "shared/models.py" in completed and not path.startswith("shared/"):
        models_path = OUTPUT / "shared/models.py"
        if models_path.exists():
            related["shared/models.py"] = models_path.read_text(encoding="utf-8")

    # Agent main.py needs shared modules
    if path.startswith("agents/") and path.endswith("main.py"):
        for sfile in ["shared/a2a_server.py", "shared/mcp_client.py", "shared/task_queue.py"]:
            if sfile in completed:
                fpath = OUTPUT / sfile
                if fpath.exists():
                    related[sfile] = fpath.read_text(encoding="utf-8")

    # Agent tools.py needs main.py context
    if path.startswith("agents/") and path.endswith("tools.py"):
        agent = path.split("/")[1]
        main_file = f"agents/{agent}/main.py"
        if main_file in completed:
            fpath = OUTPUT / main_file
            if fpath.exists():
                related[main_file] = fpath.read_text(encoding="utf-8")

    # Agent prompts.py needs main.py context
    if path.startswith("agents/") and path.endswith("prompts.py"):
        agent = path.split("/")[1]
        main_file = f"agents/{agent}/main.py"
        if main_file in completed:
            fpath = OUTPUT / main_file
            if fpath.exists():
                related[main_file] = fpath.read_text(encoding="utf-8")

    # Web components need layout
    if path.startswith("web/components/") or (path.startswith("web/app/") and path != "web/app/layout.tsx"):
        layout = "web/app/layout.tsx"
        if layout in completed:
            fpath = OUTPUT / layout
            if fpath.exists():
                related[layout] = fpath.read_text(encoding="utf-8")

    return related


def generate_file(client, file_info: dict, context: str, progress: dict,
                  max_retries: int = 3) -> tuple[bool, str, int]:
    """Generate a single file. Returns (success, content_or_error, tokens_used)."""
    path = file_info["path"]
    model = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
    max_tokens_env = os.getenv("MAX_TOKENS", "0")
    max_tokens = None if max_tokens_env == "0" else int(max_tokens_env)

    related = get_related_files(file_info, progress)
    prompt = build_prompt(file_info, context, related)

    for attempt in range(max_retries):
        try:
            api_params = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "timeout": 300,  # 5 min timeout per call
            }
            if max_tokens is not None:
                api_params["max_tokens"] = max_tokens
            resp = client.chat.completions.create(**api_params)

            content = resp.choices[0].message.content
            tokens = resp.usage.total_tokens if resp.usage else 0

            if not content or len(content.strip()) < 10:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return False, "Empty response from LLM", tokens

            # Clean up common LLM artifacts
            content = content.strip()
            # Remove markdown code fences if present
            if content.startswith("```"):
                lines = content.split("\n")
                # Remove first line (```python or ```)
                lines = lines[1:]
                # Remove last line (```)
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)

            return True, content, tokens

        except KeyboardInterrupt:
            raise
        except Exception as e:
            error_msg = str(e)
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                console.print(f"  [yellow]Retry {attempt+1}/{max_retries} in {wait}s: {error_msg[:80]}[/yellow]")
                time.sleep(wait)
            else:
                return False, error_msg, 0

    return False, "Max retries exceeded", 0


# ---------------------------------------------------------------------------
# Test endpoint
# ---------------------------------------------------------------------------

def test_endpoint():
    """Quick test: send 1 request to MiMo API."""
    client = create_client()
    model = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
    console.print(f"[yellow]Testing MiMo API ({model})...[/yellow]")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say 'OpenCrew ready' in 3 words."}],
            max_tokens=20,
        )
        msg = resp.choices[0].message.content
        tokens = resp.usage.total_tokens if resp.usage else 0
        console.print(Panel(
            f"[green][OK][/green] Response: {msg}\nTokens: {tokens}",
            title="Test Result"
        ))
        return True
    except Exception as e:
        console.print(Panel(f"[red][FAIL][/red] {e}", title="Test Result"))
        return False


# ---------------------------------------------------------------------------
# Main build loop
# ---------------------------------------------------------------------------

def read_context() -> str:
    """Read all context files."""
    context = ""
    for fname in ["PLAN.md", "docs/REFERENCE.md", "UI_SPEC.md", "OPENHAND_BLUEPRINT.md"]:
        fpath = ROOT / fname
        if fpath.exists():
            context += f"\n\n--- {fname} ---\n{fpath.read_text(encoding='utf-8')}"
    return context


def run_build(files_to_generate: list[dict] | None = None):
    """Main build loop — generates files one by one with resume support."""
    load_dotenv()
    progress = load_progress()
    completed = set(progress.get("completed_files", []))

    if not progress["started_at"]:
        progress["started_at"] = datetime.now().isoformat()
        save_progress(progress)

    manifest = build_manifest()

    # Filter to only uncompleted files
    if files_to_generate:
        pending = [f for f in files_to_generate if f["path"] not in completed]
    else:
        pending = [f for f in manifest if f["path"] not in completed]

    if not pending:
        console.print("[green]All files already generated![/green]")
        show_summary(progress)
        return

    # Sort by priority
    pending.sort(key=lambda f: f["priority"])

    console.print(Panel(
        "[bold]OpenCrew Build Engine v2[/bold]\n"
        f"Total files: {len(manifest)}\n"
        f"Already done: {len(completed)}\n"
        f"To generate: {len(pending)}\n"
        f"Token budget: 30B (unlimited)\n"
        f"Max tokens/request: {'unlimited' if os.getenv('MAX_TOKENS', '0') == '0' else os.getenv('MAX_TOKENS')}\n\n"
        "Auto-resume: ON — Ctrl+C to pause, rerun to continue",
        title="OpenCrew Builder",
    ))

    context = read_context()
    client = create_client()

    total_tokens = progress.get("total_tokens", 0)
    api_calls = progress.get("api_calls", 0)
    generated = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as prog_bar:
        task = prog_bar.add_task("Building...", total=len(pending))

        for file_info in pending:
            if _shutdown:
                console.print("[yellow]Shutdown requested. Stopping after current file.[/yellow]")
                break

            path = file_info["path"]
            desc_short = path

            prog_bar.update(task, description=f"Generating {desc_short}")

            # Create output directory
            out_path = OUTPUT / path
            out_path.parent.mkdir(parents=True, exist_ok=True)

            # Generate
            success, content_or_error, tokens = generate_file(
                client, file_info, context, progress
            )

            total_tokens += tokens
            api_calls += 1

            if success:
                out_path.write_text(content_or_error, encoding="utf-8")
                progress["completed_files"].append(path)
                progress["total_tokens"] = total_tokens
                progress["api_calls"] = api_calls
                save_progress(progress)
                completed.add(path)
                generated += 1
                console.print(f"  [green][OK][/green] {path} ({tokens} tokens)")
            else:
                progress["failed_files"][path] = content_or_error
                progress["total_tokens"] = total_tokens
                progress["api_calls"] = api_calls
                save_progress(progress)
                failed += 1
                console.print(f"  [red][FAIL][/red] {path}: {content_or_error[:60]}")

            prog_bar.advance(task)

            # Small delay to avoid rate limiting
            time.sleep(0.5)

    # Summary
    console.print()
    show_summary(progress, generated, failed)


def show_summary(progress: dict, generated: int = 0, failed: int = 0):
    """Show build summary."""
    completed = progress.get("completed_files", [])
    failed_files = progress.get("failed_files", {})
    total_tokens = progress.get("total_tokens", 0)
    api_calls = progress.get("api_calls", 0)
    manifest = build_manifest()

    table = Table(title="Build Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total files", str(len(manifest)))
    table.add_row("Completed", str(len(completed)))
    table.add_row("Failed", str(len(failed_files)))
    table.add_row("Remaining", str(len(manifest) - len(completed)))
    table.add_row("This run: generated", str(generated))
    table.add_row("This run: failed", str(failed))
    table.add_row("Total API calls", str(api_calls))
    table.add_row("Total tokens", f"{total_tokens:,}")
    table.add_row("Est. cost (if $0.001/1K)", f"${total_tokens / 1000 * 0.001:.2f}")

    console.print(table)

    if failed_files:
        console.print("\n[red]Failed files:[/red]")
        for path, err in failed_files.items():
            console.print(f"  - {path}: {err[:80]}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="OpenCrew Build Engine v2")
    parser.add_argument("--test", action="store_true", help="Test MiMo API connection")
    parser.add_argument("--status", action="store_true", help="Show build progress")
    parser.add_argument("--list", action="store_true", help="List all files to generate")
    parser.add_argument("--file", type=str, help="Generate a single file by path")
    parser.add_argument("--reset", action="store_true", help="Reset progress and start over")
    parser.add_argument("--retry-failed", action="store_true", help="Retry only failed files")
    args = parser.parse_args()

    # Validate env
    required = ["MIMO_API_KEY", "MIMO_BASE_URL"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        console.print(f"[red]Missing env vars: {', '.join(missing)}[/red]")
        console.print("Create .env file — see CONFIG.md")
        sys.exit(1)

    if args.test:
        sys.exit(0 if test_endpoint() else 1)

    if args.reset:
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
        console.print("[yellow]Progress reset.[/yellow]")
        return

    if args.list:
        manifest = build_manifest()
        progress = load_progress()
        completed = set(progress.get("completed_files", []))
        table = Table(title="File Manifest")
        table.add_column("Status", width=4)
        table.add_column("Group", width=20)
        table.add_column("Path")
        for f in manifest:
            status = "[green][OK][/green]" if f["path"] in completed else "[yellow][--][/yellow]"
            table.add_row(status, f["group"], f["path"])
        console.print(table)
        return

    if args.status:
        progress = load_progress()
        show_summary(progress)
        return

    if args.file:
        manifest = build_manifest()
        match = [f for f in manifest if f["path"] == args.file]
        if not match:
            console.print(f"[red]File not in manifest: {args.file}[/red]")
            sys.exit(1)
        run_build(match)
        return

    if args.retry_failed:
        progress = load_progress()
        failed_paths = set(progress.get("failed_files", {}).keys())
        # Clear failed status
        progress["failed_files"] = {}
        save_progress(progress)
        manifest = build_manifest()
        retry = [f for f in manifest if f["path"] in failed_paths]
        if retry:
            run_build(retry)
        else:
            console.print("[green]No failed files to retry.[/green]")
        return

    # Default: full build
    run_build()


if __name__ == "__main__":
    main()
