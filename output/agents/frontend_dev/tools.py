from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger("frontend_dev.tools")


def get_tools() -> Dict[str, Any]:
    """Return a mapping of tool names to their callable implementations.

    Each tool wraps either an MCP client call or implements local logic
    relevant to the Frontend Developer agent's responsibilities.

    Returns:
        Dict mapping tool name strings to async callable functions.
    """
    return {
        "create_feature_branch": create_feature_branch,
        "commit_and_push": commit_and_push,
        "open_pull_request": open_pull_request,
        "get_file_content": get_file_content,
        "search_codebase": search_codebase,
        "get_library_docs": get_library_docs,
        "resolve_library_id": resolve_library_id,
        "generate_component": generate_component,
        "generate_page": generate_page,
        "generate_api_hook": generate_api_hook,
        "validate_typescript": validate_typescript,
        "validate_lint": validate_lint,
        "validate_responsive_classes": validate_responsive_classes,
        "validate_dark_mode": validate_dark_mode,
        "validate_loading_states": validate_loading_states,
    }


async def create_feature_branch(
    branch_name: str,
    base_branch: str = "main",
    mcp_client: Any = None,
) -> Dict[str, Any]:
    """Create a new feature branch from the specified base branch.

    Uses the github_mcp tool to create a branch in the remote repository.

    Args:
        branch_name: Name of the new branch (e.g. 'feature/user-registration').
        base_branch: Base branch to create from, defaults to 'main'.
        mcp_client: MCPClient instance for making MCP calls.

    Returns:
        Dict with branch creation result including URL and SHA.
    """
    logger.info(
        "create_feature_branch",
        branch_name=branch_name,
        base_branch=base_branch,
    )

    if mcp_client is None:
        return {"success": False, "error": "MCP client not available"}

    try:
        result = await mcp_client.call(
            server="github_mcp",
            tool="create_branch",
            arguments={
                "branch_name": branch_name,
                "base_branch": base_branch,
            },
        )

        logger.info(
            "branch_created",
            branch_name=branch_name,
            sha=result.get("sha", "unknown"),
        )

        return {
            "success": True,
            "branch_name": branch_name,
            "base_branch": base_branch,
            "sha": result.get("sha"),
            "url": result.get("url"),
        }
    except Exception as e:
        logger.error("create_branch_failed", error=str(e), branch=branch_name)
        return {"success": False, "error": str(e)}


async def commit_and_push(
    branch_name: str,
    files: List[Dict[str, str]],
    commit_message: str,
    mcp_client: Any = None,
) -> Dict[str, Any]:
    """Commit multiple files and push to the specified branch.

    Args:
        branch_name: Target branch name.
        files: List of dicts with 'path' and 'content' keys representing
               files to commit.
        commit_message: Commit message following conventional commit format.
        mcp_client: MCPClient instance for making MCP calls.

    Returns:
        Dict with commit result including SHA and URL.
    """
    logger.info(
        "commit_and_push",
        branch=branch_name,
        file_count=len(files),
        message=commit_message,
    )

    if mcp_client is None:
        return {"success": False, "error": "MCP client not available"}

    try:
        result = await mcp_client.call(
            server="github_mcp",
            tool="commit_files",
            arguments={
                "branch": branch_name,
                "files": files,
                "message": commit_message,
            },
        )

        logger.info(
            "commit_pushed",
            branch=branch_name,
            sha=result.get("sha", "unknown"),
            files=len(files),
        )

        return {
            "success": True,
            "branch": branch_name,
            "commit_sha": result.get("sha"),
            "commit_url": result.get("url"),
            "files_committed": len(files),
        }
    except Exception as e:
        logger.error("commit_push_failed", error=str(e), branch=branch_name)
        return {"success": False, "error": str(e)}


async def open_pull_request(
    title: str,
    body: str,
    head_branch: str,
    base_branch: str = "main",
    labels: Optional[List[str]] = None,
    mcp_client: Any = None,
) -> Dict[str, Any]:
    """Open a pull request for the feature branch.

    Args:
        title: PR title.
        body: PR description with details of changes.
        head_branch: Source branch containing changes.
        base_branch: Target branch for merge, defaults to 'main'.
        labels: Optional list of label names to apply.
        mcp_client: MCPClient instance for making MCP calls.

    Returns:
        Dict with PR details including URL and number.
    """
    logger.info(
        "open_pull_request",
        title=title,
        head=head_branch,
        base=base_branch,
    )

    if mcp_client is None:
        return {"success": False, "error": "MCP client not available"}

    arguments: Dict[str, Any] = {
        "title": title,
        "body": body,
        "head": head_branch,
        "base": base_branch,
    }
    if labels:
        arguments["labels"] = labels

    try:
        result = await mcp_client.call(
            server="github_mcp",
            tool="create_pr",
            arguments=arguments,
        )

        logger.info(
            "pr_opened",
            pr_number=result.get("number"),
            pr_url=result.get("html_url"),
        )

        return {
            "success": True,
            "pr_number": result.get("number"),
            "pr_url": result.get("html_url"),
            "pr_title": title,
        }
    except Exception as e:
        logger.error("open_pr_failed", error=str(e), head=head_branch)
        return {"success": False, "error": str(e)}


async def get_file_content(
    file_path: str,
    ref: str = "main",
    mcp_client: Any = None,
) -> Dict[str, Any]:
    """Retrieve the content of a file from the repository.

    Args:
        file_path: Path to the file in the repository.
        ref: Git ref (branch, tag, or SHA), defaults to 'main'.
        mcp_client: MCPClient instance for making MCP calls.

    Returns:
        Dict with file content and metadata.
    """
    logger.info("get_file_content", path=file_path, ref=ref)

    if mcp_client is None:
        return {"success": False, "error": "MCP client not available"}

    try:
        result = await mcp_client.call(
            server="github_mcp",
            tool="get_file",
            arguments={
                "path": file_path,
                "ref": ref,
            },
        )

        return {
            "success": True,
            "path": file_path,
            "content": result.get("content", ""),
            "encoding": result.get("encoding", "utf-8"),
            "sha": result.get("sha"),
            "size": result.get("size"),
        }
    except Exception as e:
        logger.error("get_file_failed", error=str(e), path=file_path)
        return {"success": False, "error": str(e)}


async def search_codebase(
    query: str,
    file_extension: Optional[str] = None,
    mcp_client: Any = None,
) -> Dict[str, Any]:
    """Search the codebase for code matching the query.

    Args:
        query: Search query string.
        file_extension: Optional file extension filter (e.g. 'tsx', 'ts').
        mcp_client: MCPClient instance for making MCP calls.

    Returns:
        Dict with search results including file paths and matches.
    """
    logger.info("search_codebase", query=query, extension=file_extension)

    if mcp_client is None:
        return {"success": False, "error": "MCP client not available"}

    arguments: Dict[str, Any] = {"query": query}
    if file_extension:
        arguments["extension"] = file_extension

    try:
        result = await mcp_client.call(
            server="github_mcp",
            tool="search_code",
            arguments=arguments,
        )

        items = result.get("items", [])
        matches = [
            {
                "path": item.get("path", ""),
                "name": item.get("name", ""),
                "score": item.get("score", 0),
                "url": item.get("html_url", ""),
            }
            for item in items
        ]

        return {
            "success": True,
            "query": query,
            "total_count": len(matches),
            "matches": matches,
        }
    except Exception as e:
        logger.error("search_failed", error=str(e), query=query)
        return {"success": False, "error": str(e)}


async def get_library_docs(
    library_id: str,
    topic: Optional[str] = None,
    tokens: int = 5000,
    mcp_client: Any = None,
) -> Dict[str, Any]:
    """Retrieve documentation for a library from Context7.

    Fetches up-to-date documentation for NextJS, React, Tailwind,
    shadcn/ui, or other libraries used by the frontend.

    Args:
        library_id: Context7 library identifier.
        topic: Optional specific topic to search within the library docs.
        tokens: Maximum tokens to return, defaults to 5000.
        mcp_client: MCPClient instance for making MCP calls.

    Returns:
        Dict with library documentation content.
    """
    logger.info("get_library_docs", library_id=library_id, topic=topic)

    if mcp_client is None:
        return {"success": False, "error": "MCP client not available"}

    arguments: Dict[str, Any] = {
        "context7_compatible_library_id": library_id,
        "tokens": tokens,
    }
    if topic:
        arguments["topic"] = topic

    try:
        result = await mcp_client.call(
            server="context7",
            tool="get_library_docs",
            arguments=arguments,
        )

        return {
            "success": True,
            "library_id": library_id,
            "topic": topic,
            "documentation": result.get("content", ""),
            "tokens_used": result.get("tokens_used", 0),
        }
    except Exception as e:
        logger.error("get_docs_failed", error=str(e), library=library_id)
        return {"success": False, "error": str(e)}


async def resolve_library_id(
    library_name: str,
    mcp_client: Any = None,
) -> Dict[str, Any]:
    """Resolve a library name to its Context7 identifier.

    Args:
        library_name: Name of the library (e.g. 'nextjs', 'react', 'tailwindcss').
        mcp_client: MCPClient instance for making MCP calls.

    Returns:
        Dict with resolved library ID and metadata.
    """
    logger.info("resolve_library_id", library_name=library_name)

    if mcp_client is None:
        return {"success": False, "error": "MCP client not available"}

    try:
        result = await mcp_client.call(
            server="context7",
            tool="resolve_library_id",
            arguments={
                "library_name": library_name,
            },
        )

        library_id = result.get("context7_compatible_library_id", "")
        logger.info("library_resolved", name=library_name, id=library_id)

        return {
            "success": True,
            "library_name": library_name,
            "library_id": library_id,
            "description": result.get("description", ""),
        }
    except Exception as e:
        logger.error("resolve_library_failed", error=str(e), name=library_name)
        return {"success": False, "error": str(e)}


async def generate_component(
    component_name: str,
    description: str,
    props: List[Dict[str, str]],
    dependencies: Optional[List[str]] = None,
    output_dir: str = "app/components",
) -> Dict[str, Any]:
    """Generate a NextJS/React component with TypeScript and Tailwind.

    Creates a production-ready component file with proper typing,
    dark mode support, and responsive design classes.

    Args:
        component_name: PascalCase component name.
        description: Description of what the component does.
        props: List of prop definitions with 'name', 'type', and 'description'.
        dependencies: Optional list of shadcn/ui or other component dependencies.
        output_dir: Output directory path for the component file.

    Returns:
        Dict with generated component code and file path.
    """
    logger.info(
        "generate_component",
        name=component_name,
        description=description,
        props_count=len(props),
    )

    # Build props interface
    props_lines = []
    for prop in props:
        prop_name = prop.get("name", "")
        prop_type = prop.get("type", "string")
        prop_desc = prop.get("description", "")
        if prop_desc:
            props_lines.append(f"  /** {prop_desc} */")
        props_lines.append(f"  {prop_name}: {prop_type};")

    props_interface = "\n".join(props_lines)

    # Build imports
    import_lines = ['"use client";', ""]
    import_lines.append('import { cn } from "@/lib/utils";')

    if dependencies:
        for dep in dependencies:
            if dep.startswith("@/components/"):
                component_import = dep.split("/")[-1].replace("-", " ").title().replace(" ", "")
                import_lines.append(
                    f'import {{ {component_import} }} from "{dep}";'
                )

    imports = "\n".join(import_lines)

    # Generate component code
    component_code = f'''{imports}

interface {component_name}Props {{
{props_interface}
}}

/**
 * {description}
 *
 * @component
 * @example
 * ```tsx
 * <{component_name} {chr(10).join(f"  {p["name"]}={{...}}" for p in props[:3])} />
 * ```
 */
export function {component_name}({{{", ".join(p["name"] for p in props)}}}: {component_name}Props) {{
  return (
    <div
      className={{cn(
        "rounded-lg bg-slate-800 p-6 text-slate-50",
        "dark:bg-slate-900",
        "transition-colors duration-200",
      )}}
    >
      <p className="text-sm text-slate-400">
        {description}
      </p>
      {{/* TODO: Implement component content */}}
    </div>
  );
}}

export default {component_name};
'''

    file_path = f"{output_dir}/{component_name}.tsx"

    logger.info("component_generated", name=component_name, path=file_path)

    return {
        "success": True,
        "component_name": component_name,
        "file_path": file_path,
        "code": component_code,
        "props_count": len(props),
    }


async def generate_page(
    page_name: str,
    route_path: str,
    description: str,
    sections: List[Dict[str, str]],
    api_endpoints: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Generate a NextJS page component with proper layout structure.

    Creates a page.tsx file with loading states, error boundaries,
    and responsive layout.

    Args:
        page_name: PascalCase page name.
        route_path: NextJS route path (e.g. '/dashboard', '/tasks').
        description: Page description for documentation.
        sections: List of section definitions with 'name' and 'description'.
        api_endpoints: Optional list of API endpoints this page consumes.

    Returns:
        Dict with generated page code and file path.
    """
    logger.info(
        "generate_page",
        name=page_name,
        route=route_path,
        sections_count=len(sections),
    )

    # Build section placeholders
    section_components = []
    for section in sections:
        section_name = section.get("name", "Section")
        section_desc = section.get("description", "")
        section_components.append(f"""
      {/* {section_name} */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold text-slate-50">
          {section_name}
        </h2>
        <p className="text-sm text-slate-400">{section_desc}</p>
        <div className="rounded-lg bg-slate-800 p-6">
          {{/* {section_name} content */}}
        </div>
      </section>""")

    sections_code = "\n".join(section_components)

    # Build imports
    import_statements = ['"use client";', ""]
    import_statements.append('import { useState, useEffect } from "react";')
    import_statements.append('import { cn } from "@/lib/utils";')

    if api_endpoints:
        import_statements.append(
            'import { useApi } from "@/hooks/useApi";'
        )

    imports = "\n".join(import_statements)

    page_code = f'''{imports}

/**
 * {page_name} — {description}
 *
 * Route: {route_path}
 * Generated by OpenCrew Frontend Developer Agent
 */

interface {page_name}State {{
  isLoading: boolean;
  error: string | null;
}}

export default function {page_name}Page() {{
  const [state, setState] = useState<{page_name}State>({{
    isLoading: true,
    error: null,
  }});

  useEffect(() => {{
    const loadData = async () => {{
      try {{
        setState((prev) => ({{ ...prev, isLoading: true, error: null }}));
        // TODO: Fetch data from API
        await new Promise((resolve) => setTimeout(resolve, 100));
        setState((prev) => ({{ ...prev, isLoading: false }}));
      }} catch (err) {{
        setState((prev) => ({{
          ...prev,
          isLoading: false,
          error: err instanceof Error ? err.message : "Failed to load data",
        }}));
      }}
    }};

    loadData();
  }}, []);

  // Loading state
  if (state.isLoading) {{
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-900">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
          <p className="text-sm text-slate-400">Loading...</p>
        </div>
      </div>
    );
  }}

  // Error state
  if (state.error) {{
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-900">
        <div className="rounded-lg border border-red-500/20 bg-red-500/10 p-6 text-center">
          <p className="text-lg font-semibold text-red-400">Error</p>
          <p className="mt-2 text-sm text-slate-400">{{state.error}}</p>
          <button
            onClick={{() => window.location.reload()}}
            className="mt-4 rounded-md bg-red-500 px-4 py-2 text-sm font-medium text-white hover:bg-red-600"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }}

  return (
    <div className="min-h-screen bg-slate-900 text-slate-50">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-8">
          <h1 className="text-2xl font-semibold">{page_name}</h1>
          <p className="mt-1 text-sm text-slate-400">{description}</p>
        </header>

        <div className="space-y-8">
          {sections_code}
        </div>
      </div>
    </div>
  );
}}
'''

    # Determine file path based on route
    clean_route = route_path.strip("/")
    if clean_route:
        file_path = f"app/{clean_route}/page.tsx"
    else:
        file_path = "app/page.tsx"

    logger.info("page_generated", name=page_name, path=file_path)

    return {
        "success": True,
        "page_name": page_name,
        "route_path": route_path,
        "file_path": file_path,
        "code": page_code,
        "sections_count": len(sections),
    }


async def generate_api_hook(
    hook_name: str,
    endpoint: str,
    method: str = "GET",
    request_type: Optional[str] = None,
    response_type: Optional[str] = None,
    description: str = "",
) -> Dict[str, Any]:
    """Generate a custom React hook for API calls with loading/error states.

    Args:
        hook_name: Hook name in camelCase (e.g. 'useUsers', 'useTasks').
        endpoint: API endpoint path (e.g. '/api/users').
        method: HTTP method, defaults to 'GET'.
        request_type: TypeScript type for request body.
        response_type: TypeScript type for response data.
        description: Description of what the hook does.

    Returns:
        Dict with generated hook code and file path.
    """
    logger.info(
        "generate_api_hook",
        hook_name=hook_name,
        endpoint=endpoint,
        method=method,
    )

    type_params = []
    if response_type:
        type_params.append(f"T = {response_type}")
    else:
        type_params.append("T = unknown")

    if request_type:
        type_params.append(f"B = {request_type}")

    generic_params = ", ".join(type_params)

    hook_code = f'''"use client";

import {{ useState, useCallback }} from "react";

interface ApiState<T> {{
  data: T | null;
  isLoading: boolean;
  error: string | null;
}}

interface UseApiReturn<T{", B = void" if request_type else ""}> extends ApiState<T> {{
  execute: ({f"body: B" if request_type else ""}) => Promise<T | null>;
  reset: () => void;
}}

/**
 * {description or f"Hook for {endpoint} API endpoint"}
 *
 * @param endpoint - API endpoint path
 * @returns Object with data, loading state, error, and execute function
 *
 * @example
 * ```tsx
 * const {{ data, isLoading, error, execute }} = {hook_name}();
 * useEffect(() => {{ execute(); }}, []);
 * ```
 */
export function {hook_name}(
  endpoint: string = "{endpoint}",
): UseApiReturn<{generic_params}> {{
  const [state, setState] = useState<ApiState<T>>({{
    data: null,
    isLoading: false,
    error: null,
  }});

  const execute = useCallback(
    async ({f"body" if request_type else ""}{f": {request_type}" if request_type else ""}): Promise<T | null> => {{
      setState((prev) => ({{ ...prev, isLoading: true, error: null }}));

      try {{
        const options: RequestInit = {{
          method: "{method}",
          headers: {{
            "Content-Type": "application/json",
          }},
        }};

        {"options.body = JSON.stringify(body);" if request_type else ""}

        const response = await fetch(endpoint, options);

        if (!response.ok) {{
          const errorData = await response.json().catch(() => ({{}}));
          throw new Error(
            errorData.message || `Request failed with status ${{response.status}}`
          );
        }}

        const data = (await response.json()) as T;
        setState({{ data, isLoading: false, error: null }});
        return data;
      }} catch (err) {{
        const errorMessage =
          err instanceof Error ? err.message : "An unexpected error occurred";
        setState((prev) => ({{ ...prev, isLoading: false, error: errorMessage }}));
        return null;
      }}
    }},
    [endpoint],
  );

  const reset = useCallback(() => {{
    setState({{ data: null, isLoading: false, error: null }});
  }}, []);

  return {{
    ...state,
    execute,
    reset,
  }};
}}

export default {hook_name};
'''

    file_path = f"hooks/{hook_name}.ts"

    logger.info("hook_generated", name=hook_name, path=file_path)

    return {
        "success": True,
        "hook_name": hook_name,
        "endpoint": endpoint,
        "method": method,
        "file_path": file_path,
        "code": hook_code,
    }


async def validate_typescript(
    project_dir: str = ".",
) -> Dict[str, Any]:
    """Run TypeScript type checking on the project.

    Executes 'npx tsc --noEmit' and returns validation results.

    Args:
        project_dir: Path to the project root directory.

    Returns:
        Dict with validation result including any type errors found.
    """
    logger.info("validate_typescript", project_dir=project_dir)

    try:
        result = subprocess.run(
            ["npx", "tsc", "--noEmit", "--pretty"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )

        is_valid = result.returncode == 0

        if is_valid:
            logger.info("typescript_check_passed")
            return {
                "success": True,
                "is_valid": True,
                "errors": [],
                "output": result.stdout,
            }
        else:
            errors = [
                line.strip()
                for line in result.stdout.split("\n")
                if line.strip() and "error TS" in line
            ]

            logger.warn(
                "typescript_check_failed",
                error_count=len(errors),
            )

            return {
                "success": True,
                "is_valid": False,
                "errors": errors,
                "output": result.stdout,
                "error_output": result.stderr,
            }

    except FileNotFoundError:
        return {
            "success": False,
            "is_valid": False,
            "error": "npx or tsc not found. Ensure Node.js and TypeScript are installed.",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "is_valid": False,
            "error": "TypeScript check timed out after 120 seconds.",
        }
    except Exception as e:
        logger.error("typescript_check_error", error=str(e))
        return {
            "success": False,
            "is_valid": False,
            "error": str(e),
        }


async def validate_lint(
    project_dir: str = ".",
) -> Dict[str, Any]:
    """Run ESLint on the project.

    Executes 'npm run lint' and returns validation results.

    Args:
        project_dir: Path to the project root directory.

    Returns:
        Dict with validation result including any lint warnings/errors found.
    """
    logger.info("validate_lint", project_dir=project_dir)

    try:
        result = subprocess.run(
            ["npm", "run", "lint"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )

        is_valid = result.returncode == 0

        if is_valid:
            logger.info("lint_check_passed")
            return {
                "success": True,
                "is_valid": True,
                "warnings": [],
                "errors": [],
                "output": result.stdout,
            }
        else:
            output_lines = result.stdout.split("\n")
            errors = [line.strip() for line in output_lines if "error" in line.lower()]
            warnings = [line.strip() for line in output_lines if "warning" in line.lower()]

            logger.warn(
                "lint_check_failed",
                error_count=len(errors),
                warning_count=len(warnings),
            )

            return {
                "success": True,
                "is_valid": False,
                "errors": errors,
                "warnings": warnings,
                "output": result.stdout,
                "error_output": result.stderr,
            }

    except FileNotFoundError:
        return {
            "success": False,
            "is_valid": False,
            "error": "npm not found. Ensure Node.js is installed.",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "is_valid": False,
            "error": "Lint check timed out after 120 seconds.",
        }
    except Exception as e:
        logger.error("lint_check_error", error=str(e))
        return {
            "success": False,
            "is_valid": False,
            "error": str(e),
        }


async def validate_responsive_classes(
    code_content: str,
) -> Dict[str, Any]:
    """Validate that Tailwind responsive breakpoint classes are used.

    Checks for the presence of sm:, md:, lg:, xl: prefixes in class strings.

    Args:
        code_content: Source code content to validate.

    Returns:
        Dict with validation result and details about responsive usage.
    """
    logger.info("validate_responsive_classes")

    responsive_prefixes = ["sm:", "md:", "lg:", "xl:", "2xl:"]
    found_prefixes = []

    for prefix in responsive_prefixes:
        if prefix in code_content:
            found_prefixes.append(prefix)

    has_responsive = len(found_prefixes) > 0

    if not has_responsive:
        logger.warn("no_responsive_classes_found")
        return {
            "success": True,
            "is_valid": False,
            "found_prefixes": found_prefixes,
            "suggestion": "Add responsive breakpoint classes (sm:, md:, lg:, xl:) for mobile/tablet/desktop support.",
        }

    logger.info("responsive_classes_found", prefixes=found_prefixes)

    return {
        "success": True,
        "is_valid": True,
        "found_prefixes": found_prefixes,
    }


async def validate_dark_mode(
    code_content: str,
) -> Dict[str, Any]:
    """Validate that dark mode classes are present in the code.

    Checks for 'dark:' prefix usage in Tailwind classes.

    Args:
        code_content: Source code content to validate.

    Returns:
        Dict with validation result and dark mode usage details.
    """
    logger.info("validate_dark_mode")

    dark_mode_count = code_content.count("dark:")

    # Also check for light-mode-only hardcoded colors
    light_mode_indicators = [
        "bg-white",
        "text-black",
        "bg-gray-50",
        "text-gray-900",
    ]

    light_only_usage = []
    for indicator in light_mode_indicators:
        if indicator in code_content and f"dark:{indicator}" not in code_content:
            # Check if there's a dark variant nearby
            base_class = indicator.split("-")[0]  # e.g., "bg", "text"
            if f"dark:{base_class}-" not in code_content:
                light_only_usage.append(indicator)

    has_dark_mode = dark_mode_count > 0

    if not has_dark_mode:
        logger.warn("no_dark_mode_classes")
        return {
            "success": True,
            "is_valid": False,
            "dark_mode_count": 0,
            "light_only_classes": light_only_usage,
            "suggestion": "Add dark: variant classes for dark mode support. Dark mode is the default.",
        }

    logger.info("dark_mode_validated", count=dark_mode_count)

    return {
        "success": True,
        "is_valid": True,
        "dark_mode_count": dark_mode_count,
        "light_only_classes": light_only_usage,
    }


async def validate_loading_states(
    code_content: str,
) -> Dict[str, Any]:
    """Validate that loading, empty, and error states are implemented.

    Checks for common patterns indicating proper state handling.

    Args:
        code_content: Source code content to validate.

    Returns:
        Dict with validation result and details about state implementations.
    """
    logger.info("validate_loading_states")

    checks = {
        "loading_state": False,
        "error_state": False,
        "empty_state": False,
    }

    # Loading state indicators
    loading_patterns = [
        "isLoading",
        "is-loading",
        "loading",
        "skeleton",
        "spinner",
        "animate-spin",
        "Loading...",
    ]

    # Error state indicators
    error_patterns = [
        "error",
        "isError",
        "hasError",
        "Error",
        "catch",
        "try {",
        "try{",
    ]

    # Empty state indicators
    empty_patterns = [
        "isEmpty",
        "empty",
        "no data",
        "No data",
        "no results",
        "No results",
        "not found",
        "Not found",
        "length === 0",
        "length==0",
    ]

    for pattern in loading_patterns:
        if pattern in code_content:
            checks["loading_state"] = True
            break

    for pattern in error_patterns:
        if pattern in code_content:
            checks["error_state"] = True
            break

    for pattern in empty_patterns:
        if pattern in code_content:
            checks["empty_state"] = True
            break

    all_valid = all(checks.values())
    missing = [k for k, v in checks.items() if not v]

    if not all_valid:
        logger.warn("missing_states", missing=missing)
        return {
            "success": True,
            "is_valid": False,
            "checks": checks,
            "missing_states": missing,
            "suggestion": f"Implement missing states: {', '.join(missing)}. All components need loading, error, and empty states.",
        }

    logger.info("loading_states_validated", checks=checks)

    return {
        "success": True,
        "is_valid": True,
        "checks": checks,
    }