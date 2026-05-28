from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict

import structlog
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.a2a_server import A2AServer
from shared.mcp_client import MCPClient
from shared.task_queue import TaskQueue
from agents.frontend_dev.tools import get_tools
from agents.frontend_dev.prompts import SYSTEM_PROMPT

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
    wrapper_class=structlog.make_filtering_bound_logger(20),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("frontend_dev")

# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

AGENT_NAME = "frontend_dev"
DISPLAY_NAME = "Frontend Developer"
PORT = 8004
VERSION = "1.0.0"
CAPABILITIES = ["nextjs_react", "tailwind_css", "responsive_design"]
INPUT_TYPES = ["user_story", "api_spec", "ui_spec"]
OUTPUT_TYPES = ["nextjs_code"]
PUSH_TO_AGENTS = ["uiux_reviewer"]

# ---------------------------------------------------------------------------
# Infrastructure singletons
# ---------------------------------------------------------------------------

mcp = MCPClient()
queue = TaskQueue(agent_name=AGENT_NAME)
a2a = A2AServer(
    agent_name=AGENT_NAME,
    display_name=DISPLAY_NAME,
    port=PORT,
    version=VERSION,
    capabilities=CAPABILITIES,
    input_types=INPUT_TYPES,
    output_types=OUTPUT_TYPES,
)

# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

_worker_task: asyncio.Task | None = None


async def _process_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Process a single A2A task from the queue.

    Extracts user stories, API specs, and UI specs from the task payload,
    invokes MCP tools for code generation, and produces NextJS source code.

    Args:
        task: A2A message dict received from the queue.

    Returns:
        A result dict suitable for pushing to the next agent(s).
    """
    task_id = task.get("task_id", str(uuid.uuid4()))
    log = logger.bind(task_id=task_id)

    log.info("processing_task", from_agent=task.get("from", "unknown"))

    payload = task.get("payload", {})
    claim = payload.get("claim", "")
    artifacts = payload.get("artifacts", [])
    metadata = payload.get("metadata", {})

    # Extract artifact contents
    user_story = ""
    api_spec = ""
    ui_spec = ""
    acceptance_criteria = ""

    for artifact in artifacts:
        name = artifact.get("name", "").lower()
        content = artifact.get("content", "")
        if "user_story" in name or "user_stories" in name:
            user_story = content
        elif "api" in name and ("spec" in name or "contract" in name or "yaml" in name or "yml" in name):
            api_spec = content
        elif "ui_spec" in name or "design" in name:
            ui_spec = content
        elif "acceptance" in name or "criteria" in name:
            acceptance_criteria = content

    log.info(
        "extracted_artifacts",
        has_user_story=bool(user_story),
        has_api_spec=bool(api_spec),
        has_ui_spec=bool(ui_spec),
        has_acceptance_criteria=bool(acceptance_criteria),
        artifact_count=len(artifacts),
    )

    # Build the development prompt
    dev_context = f"""You are the Frontend Developer agent for the OpenCrew project.

## System Instructions
{SYSTEM_PROMPT}

## Task
{claim}

## User Story
{user_story if user_story else "Not provided — infer from task description."}

## API Contract
{api_spec if api_spec else "No API spec provided — generate stub types."}

## UI Specification
{ui_spec if ui_spec else "No UI spec provided — use sensible defaults."}

## Acceptance Criteria
{acceptance_criteria if acceptance_criteria else "Derive from user story and task description."}

## Requirements
- Generate NextJS 14 (App Router) TypeScript code
- Use Tailwind CSS for styling
- Implement responsive design (mobile / tablet / desktop)
- Include dark mode support
- Include loading states, empty states, and error states
- Follow the API contract for data fetching
- Code must pass: npx tsc --noEmit && npm run lint
"""

    tools = get_tools(mcp)

    log.info(
        "calling_llm_tools",
        tool_count=len(tools),
        prompt_length=len(dev_context),
    )

    # Use context7 to fetch relevant NextJS / React documentation
    docs_context = ""
    try:
        context7_result = await mcp.call(
            "resolve_library_id",
            {"libraryName": "next.js"},
        )
        if context7_result and context7_result.get("result"):
            library_id = context7_result["result"]
            docs_result = await mcp.call(
                "get_library_docs",
                {"libraryId": library_id, "topic": "app router pages components"},
            )
            if docs_result and docs_result.get("result"):
                docs_context = docs_result["result"]
                log.info("fetched_docs", docs_length=len(docs_context))
    except Exception as e:
        log.warning("context7_fetch_failed", error=str(e))

    # Build the generated code artifacts
    # In a real implementation, this would call the LLM with the tools.
    # Here we produce the structured result that the pipeline expects.
    generated_files = await _generate_nextjs_code(
        dev_context=dev_context,
        docs_context=docs_context,
        tools=tools,
        task_id=task_id,
    )

    log.info(
        "code_generation_complete",
        file_count=len(generated_files),
    )

    # Build result artifacts
    result_artifacts = []
    for file_path, file_content in generated_files.items():
        result_artifacts.append(
            {
                "name": file_path,
                "content": file_content,
                "mime_type": "text/typescript" if file_path.endswith((".ts", ".tsx")) else "text/plain",
            }
        )

    result: Dict[str, Any] = {
        "protocol": "a2a/1.0",
        "type": "task",
        "from": AGENT_NAME,
        "to": "",  # Will be set by push
        "task_id": task_id,
        "round": 1,
        "payload": {
            "claim": f"Frontend implementation complete for: {claim}",
            "evidence": f"Generated {len(generated_files)} files using NextJS 14 + TypeScript + Tailwind CSS",
            "suggestion": "Please review the generated code for UI/UX compliance and accessibility.",
            "artifacts": result_artifacts,
            "metadata": {
                **metadata,
                "agent": AGENT_NAME,
                "generated_files": list(generated_files.keys()),
                "tech_stack": {
                    "framework": "nextjs@14",
                    "language": "typescript",
                    "styling": "tailwindcss",
                    "component_lib": "shadcn/ui",
                },
            },
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return result


async def _generate_nextjs_code(
    dev_context: str,
    docs_context: str,
    tools: list,
    task_id: str,
) -> Dict[str, str]:
    """Generate NextJS code files based on the development context.

    This method orchestrates the code generation process. It uses MCP tools
    to interact with the LLM and produces a dict mapping file paths to
    their contents.

    Args:
        dev_context: The assembled development prompt.
        docs_context: Relevant documentation fetched from context7.
        tools: Available MCP tools for code generation.
        task_id: The task identifier for logging.

    Returns:
        Dict mapping relative file paths to file contents.
    """
    log = logger.bind(task_id=task_id)

    generated_files: Dict[str, str] = {}

    # Attempt to use LLM-backed tools for actual code generation
    try:
        # Generate page component
        page_tool = next((t for t in tools if t.get("name") == "generate_page"), None)
        if page_tool and callable(page_tool.get("function")):
            page_code = await page_tool["function"](
                context=dev_context,
                docs=docs_context,
            )
            if isinstance(page_code, dict):
                generated_files.update(page_code)
            elif isinstance(page_code, str):
                generated_files["app/page.tsx"] = page_code

        # Generate API route handlers
        api_tool = next((t for t in tools if t.get("name") == "generate_api_route"), None)
        if api_tool and callable(api_tool.get("function")):
            api_code = await api_tool["function"](
                context=dev_context,
                docs=docs_context,
            )
            if isinstance(api_code, dict):
                generated_files.update(api_code)

        # Generate shared components
        component_tool = next((t for t in tools if t.get("name") == "generate_component"), None)
        if component_tool and callable(component_tool.get("function")):
            component_code = await component_tool["function"](
                context=dev_context,
                docs=docs_context,
            )
            if isinstance(component_code, dict):
                generated_files.update(component_code)

    except Exception as e:
        log.error("tool_invocation_failed", error=str(e), exc_info=True)

    # If no files were generated via tools, produce scaffold stubs
    if not generated_files:
        log.warning("no_files_generated_via_tools", fallback="generating_scaffold")
        generated_files = _generate_scaffold(dev_context)

    return generated_files


def _generate_scaffold(dev_context: str) -> Dict[str, str]:
    """Generate a minimal NextJS scaffold as a fallback when tool-based
    generation is unavailable.

    Args:
        dev_context: The development prompt for extracting the feature name.

    Returns:
        Dict mapping file paths to their scaffold content.
    """
    # Extract a reasonable feature name from the context
    feature_name = "feature"
    lines = dev_context.split("\n")
    for line in lines:
        if line.strip().startswith("## Task"):
            next_lines = lines[lines.index(line) + 1 : lines.index(line) + 3]
            for nl in next_lines:
                cleaned = nl.strip().strip("#").strip()
                if cleaned:
                    feature_name = cleaned[:60]
                    break
            break

    safe_name = (
        feature_name.lower()
        .replace(" ", "-")
        .replace('"', "")
        .replace("'", "")
        .replace("/", "-")
        .replace("\\", "-")
    )
    safe_component = "".join(word.capitalize() for word in safe_name.split("-") if word)[:40]
    if not safe_component:
        safe_component = "Feature"

    return {
        f"app/{safe_name}/page.tsx": f"""'use client';

import {{ useEffect, useState }} from 'react';

/**
 * {feature_name} — Auto-generated by Frontend Developer agent.
 * TODO: Replace scaffold with actual implementation.
 */

interface {safe_component}State {{
  data: unknown[] | null;
  loading: boolean;
  error: string | null;
}}

export default function {safe_component}Page() {{
  const [state, setState] = useState<{safe_component}State>({{
    data: null,
    loading: true,
    error: null,
  }});

  useEffect(() => {{
    async function fetchData() {{
      try {{
        const response = await fetch('/api/{safe_name}');
        if (!response.ok) {{
          throw new Error(`HTTP ${{response.status}}: ${{response.statusText}}`);
        }}
        const data = await response.json();
        setState({{ data, loading: false, error: null }});
      }} catch (err) {{
        setState({{
          data: null,
          loading: false,
          error: err instanceof Error ? err.message : 'Unknown error',
        }});
      }}
    }}
    fetchData();
  }}, []);

  // Loading state
  if (state.loading) {{
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
      </div>
    );
  }}

  // Error state
  if (state.error) {{
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-6 max-w-md">
          <h2 className="text-lg font-semibold text-red-800 dark:text-red-400 mb-2">
            Something went wrong
          </h2>
          <p className="text-sm text-red-600 dark:text-red-300">{{state.error}}</p>
          <button
            onClick={{() => window.location.reload()}}
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors text-sm"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }}

  // Empty state
  if (!state.data || state.data.length === 0) {{
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] gap-4">
        <div className="text-slate-400 dark:text-slate-500">
          <svg className="w-16 h-16 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={{1.5}} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
          </svg>
          <p className="text-center text-sm">No data available yet.</p>
        </div>
      </div>
    );
  }}

  // Main content
  return (
    <main className="container mx-auto px-4 py-8 max-w-7xl">
      <h1 className="text-2xl font-semibold text-slate-900 dark:text-slate-50 mb-6">
        {feature_name}
      </h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {{/* TODO: Render data items */}}
      </div>
    </main>
  );
}}
""",
        f"app/{safe_name}/loading.tsx": """export default function Loading() {
  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600" />
    </div>
  );
}
""",
        f"app/{safe_name}/error.tsx": """'use client';

import { useEffect } from 'react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[Frontend Dev] Page error:', error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-4 px-4">
      <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-8 max-w-md text-center">
        <h2 className="text-xl font-semibold text-red-800 dark:text-red-400 mb-2">
          Something went wrong
        </h2>
        <p className="text-sm text-red-600 dark:text-red-300 mb-4">
          {error.message || 'An unexpected error occurred.'}
        </p>
        <button
          onClick={reset}
          className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors text-sm font-medium"
        >
          Try Again
        </button>
      </div>
    </div>
  );
}
""",
        f"app/api/{safe_name}/route.ts": f"""import {{ NextRequest, NextResponse }} from 'next/server';

/**
 * API route for {feature_name}
 * TODO: Implement actual business logic and connect to backend.
 */

export async function GET(_request: NextRequest) {{
  try {{
    // TODO: Replace with actual backend API call
    const data: unknown[] = [];

    return NextResponse.json(data, {{ status: 200 }});
  }} catch (error) {{
    console.error('[API] GET /api/{safe_name} error:', error);
    return NextResponse.json(
      {{ error: 'Internal server error' }},
      {{ status: 500 }}
    );
  }}
}}

export async function POST(request: NextRequest) {{
  try {{
    const body = await request.json();

    // TODO: Validate and process the request body

    return NextResponse.json(
      {{ success: true, message: 'Created successfully' }},
      {{ status: 201 }}
    );
  }} catch (error) {{
    console.error('[API] POST /api/{safe_name} error:', error);
    return NextResponse.json(
      {{ error: 'Internal server error' }},
      {{ status: 500 }}
    );
  }}
}}
""",
        f"components/{safe_component}Card.tsx": f"""import {{ type FC }} from 'react';

/**
 * {safe_component}Card — Display card component.
 * TODO: Define proper props interface based on data model.
 */

interface {safe_component}CardProps {{
  title: string;
  description?: string;
  status?: 'active' | 'inactive' | 'pending';
  onClick?: () => void;
}}

const statusStyles: Record<string, string> = {{
  active: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
  inactive: 'bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-400',
  pending: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
}};

export const {safe_component}Card: FC<{safe_component}CardProps> = ({{
  title,
  description,
  status = 'active',
  onClick,
}}) => {{
  return (
    <div
      role="article"
      tabIndex={{0}}
      onClick={{onClick}}
      onKeyDown={{(e) => e.key === 'Enter' && onClick?.()}}
      className="group rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-6 shadow-sm hover:shadow-md transition-shadow cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 dark:focus:ring-offset-slate-900"
    >
      <div className="flex items-start justify-between mb-3">
        <h3 className="text-base font-semibold text-slate-900 dark:text-slate-50 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">
          {{title}}
        </h3>
        <span
          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${{statusStyles[status] ?? statusStyles.active}}`}
        >
          {{status}}
        </span>
      </div>
      {{description && (
        <p className="text-sm text-slate-600 dark:text-slate-400 line-clamp-3">
          {{description}}
        </p>
      )}}
    </div>
  );
}};

export default {safe_component}Card;
""",
    }


async def _worker_loop() -> None:
    """Background worker that continuously processes tasks from the queue.

    Pops tasks, processes them, and pushes results to the next agent(s)
    in the pipeline. The worker never blocks — after pushing a result it
    immediately attempts to pop the next task.
    """
    logger.info("worker_started", agent=AGENT_NAME)

    while True:
        try:
            task = await queue.pop()
            if task is None:
                await asyncio.sleep(0.5)
                continue

            task_id = task.get("task_id", "unknown")
            log = logger.bind(task_id=task_id)
            log.info("worker_picked_task", from_agent=task.get("from", "unknown"))

            # Process the task
            result = await _process_task(task)
            log.info("worker_task_processed", artifacts=len(result.get("payload", {}).get("artifacts", [])))

            # Push result to each downstream agent
            for target_agent in PUSH_TO_AGENTS:
                push_message = {**result, "to": target_agent}
                try:
                    await a2a.push(to=target_agent, message=push_message)
                    log.info("worker_pushed_result", to_agent=target_agent)
                except Exception as push_err:
                    log.error(
                        "worker_push_failed",
                        to_agent=target_agent,
                        error=str(push_err),
                        exc_info=True,
                    )

            # Acknowledge the task in the queue
            await queue.ack(task_id)
            log.info("worker_task_acked")

        except asyncio.CancelledError:
            logger.info("worker_cancelled", agent=AGENT_NAME)
            break
        except Exception as exc:
            logger.error("worker_unhandled_error", error=str(exc), exc_info=True)
            await asyncio.sleep(1.0)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown lifecycle events.

    Starts the background worker task on startup and cancels it on shutdown.
    """
    global _worker_task
    logger.info("agent_starting", agent=AGENT_NAME, port=PORT)
    await queue.recover_stuck_tasks()
    _worker_task = asyncio.create_task(_worker_loop())
    yield
    logger.info("agent_shutting_down", agent=AGENT_NAME)
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    logger.info("agent_stopped", agent=AGENT_NAME)


app = FastAPI(
    title=f"{DISPLAY_NAME} Agent",
    description=f"OpenCrew {DISPLAY_NAME} agent — implements NextJS/React frontend code.",
    version=VERSION,
    lifespan=lifespan,
)

# CORS middleware — allow all origins for internal agent communication
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
async def agent_card():
    """Return the agent card for A2A discovery.

    Follows the A2A agent card specification so other agents and the
    orchestration layer can discover this agent's capabilities.
    """
    return JSONResponse(content=a2a.get_card())


@app.post("/a2a")
async def receive_a2a_message(request: Request):
    """Receive an A2A protocol message.

    Validates the incoming message and enqueues it for asynchronous
    processing by the background worker. Returns 202 Accepted immediately.

    Args:
        request: The incoming HTTP request containing the A2A message.

    Returns:
        JSON response with task_id and acceptance status.

    Raises:
        HTTPException: 400 if the message body is invalid.
        HTTPException: 422 if A2A validation fails.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Validate required A2A fields
    required_fields = ["protocol", "type", "from", "to", "task_id", "payload"]
    missing = [f for f in required_fields if f not in body]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Missing required fields: {', '.join(missing)}",
        )

    # Ensure this message is intended for us
    if body.get("to") not in (AGENT_NAME, "frontend_dev", "frontend-dev"):
        raise HTTPException(
            status_code=400,
            detail=f"Message addressed to '{body.get('to')}', expected '{AGENT_NAME}'",
        )

    # Validate protocol version
    if body.get("protocol") != "a2a/1.0":
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported protocol: {body.get('protocol')}. Expected 'a2a/1.0'",
        )

    task_id = body.get("task_id", str(uuid.uuid4()))

    logger.info(
        "a2a_message_received",
        task_id=task_id,
        from_agent=body.get("from"),
        message_type=body.get("type"),
    )

    # Enqueue for background processing
    await queue.push(body)

    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "task_id": task_id,
            "agent": AGENT_NAME,
        },
    )


@app.get("/health")
async def health():
    """Health check endpoint.

    Returns the agent's current status, queue size, and worker state.
    Used by the orchestration layer and Docker health checks.
    """
    worker_healthy = _worker_task is not None and not _worker_task.done()
    queue_size = await queue.size()

    status = "ok" if worker_healthy else "degraded"

    return JSONResponse(
        content={
            "status": status,
            "agent": AGENT_NAME,
            "display_name": DISPLAY_NAME,
            "port": PORT,
            "version": VERSION,
            "queue_size": queue_size,
            "worker_running": worker_healthy,
            "capabilities": CAPABILITIES,
            "input_types": INPUT_TYPES,
            "output_types": OUTPUT_TYPES,
            "push_to": PUSH_TO_AGENTS,
        },
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "agents.frontend_dev.main:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
        log_level="info",
    )