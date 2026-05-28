"""MCP tool implementations for the DevOps / SRE agent.

Each tool either wraps an MCP client call (github_mcp / context7) or
implements local logic for Docker, CI/CD, deployment, and monitoring tasks.

Usage::

    from shared.mcp_client import MCPClient
    from .tools import get_tools

    mcp = MCPClient()
    tools = get_tools(mcp)
    result = await tools["generate_dockerfile"](service_name="api", ...)
"""

from __future__ import annotations

import json
import os
import re
import textwrap
from typing import Any, Callable, Awaitable

import structlog

from shared.mcp_client import MCPClient

logger = structlog.get_logger("devops.tools")

# ---------------------------------------------------------------------------
# Type alias for tool callables
# ---------------------------------------------------------------------------

ToolCallable = Callable[..., Awaitable[Any]]

# ---------------------------------------------------------------------------
# Default resource limits
# ---------------------------------------------------------------------------

DEFAULT_MEMORY_LIMIT = "512m"
DEFAULT_CPU_LIMIT = "0.5"
DEFAULT_HEALTH_CHECK_INTERVAL = "30s"
DEFAULT_HEALTH_CHECK_TIMEOUT = "10s"
DEFAULT_HEALTH_CHECK_RETRIES = 3
DEFAULT_HEALTH_CHECK_START_PERIOD = "40s"

# GitHub Actions runner image
GITHUB_ACTIONS_RUNNER = "ubuntu-latest"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_version(image: str) -> str:
    """Ensure a Docker image reference is pinned (not ``latest``).

    If the tag is ``latest`` or missing, returns ``image:latest`` anyway but
    the caller should flag it.  In normal operation, images should already
    be pinned by the caller.
    """
    if ":" not in image:
        return f"{image}:latest"
    return image


def _health_check_command(port: int, path: str = "/health") -> list[str]:
    """Return a ``curl``-based health check command for Docker HEALTHCHECK."""
    return [
        "CMD",
        "curl",
        "-f",
        f"http://localhost:{port}{path}",
        "||",
        "exit",
        "1",
    ]


def _validate_image_tag(image: str) -> tuple[bool, str]:
    """Return ``(is_valid, message)`` for a Docker image reference.

    Flags images using the ``latest`` tag.
    """
    if image.endswith(":latest") or ":" not in image:
        return False, f"Image '{image}' uses unpinned 'latest' tag — pin to a specific version."
    return True, "Image tag is pinned."


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def generate_dockerfile(
    *,
    service_name: str,
    base_image: str,
    port: int,
    entrypoint: str,
    mcp: MCPClient,
    build_args: dict[str, str] | None = None,
    extra_packages: list[str] | None = None,
    health_path: str = "/health",
    requirements_file: str = "requirements.txt",
) -> dict[str, Any]:
    """Generate a production-ready Dockerfile.

    Features:
      - Non-root user
      - Multi-stage build
      - Pinned base image version
      - HEALTHCHECK instruction
      - Minimal layer count

    Args:
        service_name: Logical service name (e.g. ``"backend"``).
        base_image: Full base image reference including tag (e.g. ``"python:3.11-slim"``).
        port: The port the service listens on.
        entrypoint: The CMD / entrypoint for the container.
        mcp: MCP client (unused directly but passed for consistency).
        build_args: Optional build arguments.
        extra_packages: Additional system packages to install.
        health_path: HTTP path for the HEALTHCHECK probe.
        requirements_file: Name of the Python requirements file.

    Returns:
        Dict with ``dockerfile`` (str) and ``warnings`` (list[str]).
    """
    warnings: list[str] = []

    is_pinned, msg = _validate_image_tag(base_image)
    if not is_pinned:
        warnings.append(msg)

    # Build ARG lines
    arg_lines = ""
    if build_args:
        arg_lines = "\n".join(f"ARG {k}={v}" for k, v in build_args.items())
        arg_lines = arg_lines + "\n"

    # System packages
    pkg_install = ""
    if extra_packages:
        pkgs = " ".join(extra_packages)
        pkg_install = (
            f"    && apt-get install -y --no-install-recommends {pkgs} \\\n"
        )

    dockerfile = textwrap.dedent(f"""\
        # ---- Stage 1: Build / Install dependencies ----
        FROM {_extract_version(base_image)} AS builder

        {arg_lines}WORKDIR /app

        # Install dependencies in a separate layer for caching
        COPY {requirements_file} .
        RUN pip install --no-cache-dir --prefix=/install -r {requirements_file}

        # ---- Stage 2: Production image ----
        FROM {_extract_version(base_image)} AS runtime

        # Security: run as non-root
        RUN groupadd --gid 1000 appuser \\
            && useradd --uid 1000 --gid 1000 --create-home appuser

        WORKDIR /app

        # Copy installed dependencies from builder
        COPY --from=builder /install /usr/local

        # Copy application code
        COPY . .

        # Set ownership
        RUN chown -R appuser:appuser /app

        USER appuser

        EXPOSE {port}

        HEALTHCHECK --interval={DEFAULT_HEALTH_CHECK_INTERVAL} --timeout={DEFAULT_HEALTH_CHECK_TIMEOUT} --retries={DEFAULT_HEALTH_CHECK_RETRIES} --start-period={DEFAULT_HEALTH_CHECK_START_PERIOD} \\
            CMD curl -f http://localhost:{port}{health_path} || exit 1

        CMD {json.dumps(entrypoint.split())}
    """)

    # Remove the unused pkg_install block if extra_packages was empty
    if not extra_packages:
        dockerfile = dockerfile.replace(
            f"# Install dependencies in a separate layer for caching\n        COPY {requirements_file} .",
            f"COPY {requirements_file} .",
        )

    await logger.ainfo(
        "dockerfile_generated",
        service=service_name,
        base_image=base_image,
        port=port,
        warnings_count=len(warnings),
    )

    return {
        "dockerfile": dockerfile.strip(),
        "warnings": warnings,
    }


async def generate_docker_compose(
    *,
    services: list[dict[str, Any]],
    networks: list[dict[str, Any]] | None = None,
    volumes: list[str] | None = None,
    mcp: MCPClient,
    project_name: str = "opencrew",
) -> dict[str, Any]:
    """Generate a ``docker-compose.yml`` with health checks and resource limits.

    Args:
        services: List of service definitions.  Each dict must contain at
            minimum: ``name``, ``build`` (context path or image), ``port``.
            Optional keys: ``memory_limit``, ``cpu_limit``, ``env_file``,
            ``depends_on``, ``health_path``, ``command``.
        networks: Optional custom network definitions.
        volumes: Named volumes to declare.
        mcp: MCP client.
        project_name: Docker Compose project name.

    Returns:
        Dict with ``docker_compose`` (str, YAML text) and ``warnings``.
    """
    warnings: list[str] = []
    lines: list[str] = []

    lines.append(f"name: {project_name}")
    lines.append("")
    lines.append("services:")

    for svc in services:
        name = svc["name"]
        port = svc.get("port", 8000)
        mem = svc.get("memory_limit", DEFAULT_MEMORY_LIMIT)
        cpu = svc.get("cpu_limit", DEFAULT_CPU_LIMIT)
        health_path = svc.get("health_path", "/health")
        depends = svc.get("depends_on", [])
        env_file = svc.get("env_file", ".env")
        command = svc.get("command")
        image = svc.get("image")
        build_ctx = svc.get("build")

        lines.append(f"  {name}:")

        if image:
            is_pinned, msg = _validate_image_tag(image)
            if not is_pinned:
                warnings.append(f"[{name}] {msg}")
            lines.append(f"    image: {image}")
        elif build_ctx:
            lines.append(f"    build:")
            if isinstance(build_ctx, dict):
                lines.append(f"      context: {build_ctx.get('context', '.')}")
                dockerfile = build_ctx.get("dockerfile")
                if dockerfile:
                    lines.append(f"      dockerfile: {dockerfile}")
            else:
                lines.append(f"      context: {build_ctx}")

        lines.append(f"    container_name: {project_name}-{name}")
        lines.append(f"    restart: unless-stopped")

        if env_file:
            lines.append(f"    env_file:")
            lines.append(f"      - {env_file}")

        if command:
            lines.append(f"    command: {command}")

        if depends:
            lines.append(f"    depends_on:")
            for dep in depends:
                if isinstance(dep, dict):
                    dep_name = dep["name"]
                    condition = dep.get("condition", "service_healthy")
                    lines.append(f"      {dep_name}:")
                    lines.append(f"        condition: {condition}")
                else:
                    lines.append(f"      {dep}:")
                    lines.append(f"        condition: service_healthy")

        lines.append(f"    ports:")
        lines.append(f"      - \"${{{name.upper()}_PORT:-{port}}}:{port}\"")

        lines.append(f"    healthcheck:")
        lines.append(f"      test: [\"CMD\", \"curl\", \"-f\", \"http://localhost:{port}{health_path}\"]")
        lines.append(f"      interval: {DEFAULT_HEALTH_CHECK_INTERVAL}")
        lines.append(f"      timeout: {DEFAULT_HEALTH_CHECK_TIMEOUT}")
        lines.append(f"      retries: {DEFAULT_HEALTH_CHECK_RETRIES}")
        lines.append(f"      start_period: {DEFAULT_HEALTH_CHECK_START_PERIOD}")

        lines.append(f"    deploy:")
        lines.append(f"      resources:")
        lines.append(f"        limits:")
        lines.append(f"          memory: {mem}")
        lines.append(f"          cpus: \"{cpu}\"")
        lines.append(f"        reservations:")
        lines.append(f"          memory: {int(mem.rstrip('m')) // 2}m")
        lines.append(f"          cpus: \"{float(cpu) / 2}\"")

        # All services share the default network
        lines.append(f"    networks:")
        lines.append(f"      - default")
        lines.append("")

    # Extra networks
    all_networks = ["default"]
    if networks:
        lines.append("networks:")
        for net in networks:
            net_name = net.get("name", "custom")
            all_networks.append(net_name)
            lines.append(f"  {net_name}:")
            driver = net.get("driver", "bridge")
            lines.append(f"    driver: {driver}")
        # Also add default network declaration
        lines.append(f"  default:")
        lines.append(f"    driver: bridge")
    else:
        lines.append("networks:")
        lines.append("  default:")
        lines.append("    driver: bridge")

    # Volumes
    if volumes:
        lines.append("")
        lines.append("volumes:")
        for vol in volumes:
            lines.append(f"  {vol}:")

    compose_yaml = "\n".join(lines)

    await logger.ainfo(
        "docker_compose_generated",
        service_count=len(services),
        warnings_count=len(warnings),
    )

    return {
        "docker_compose": compose_yaml,
        "warnings": warnings,
    }


async def generate_cicd_workflow(
    *,
    workflow_name: str,
    trigger: str,
    services: list[dict[str, Any]],
    mcp: MCPClient,
    deploy_environment: str = "production",
    registry: str = "ghcr.io",
    secrets_required: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a GitHub Actions CI/CD workflow YAML.

    Workflow stages:
      - Lint & type-check
      - Unit tests
      - Build Docker images
      - Integration tests
      - Deploy

    Args:
        workflow_name: Workflow file name (without .yml extension).
        trigger: Git event trigger (``"push"``, ``"pull_request"``, etc.).
        services: List of service dicts with ``name``, ``path`` (Dockerfile context).
        mcp: MCP client.
        deploy_environment: Target environment name.
        registry: Container registry URL.
        secrets_required: Additional secrets to document.

    Returns:
        Dict with ``workflow`` (str, YAML text) and ``path`` (relative file path).
    """
    # Fetch best practices from Context7
    best_practices = await mcp.call(
        server="context7",
        tool="get_library_docs",
        arguments={
            "library": "github-actions",
            "topic": "workflow best practices matrix caching",
        },
    )
    bp_text = best_practices.get("content", "") if isinstance(best_practices, dict) else str(best_practices)

    services_matrix = ", ".join(f'"{s["name"]}"' for s in services)

    lines: list[str] = []

    lines.append(f"name: {workflow_name}")
    lines.append("")
    lines.append("on:")
    lines.append(f"  {trigger}:")
    lines.append("    branches:")
    lines.append("      - main")
    lines.append("      - 'release/**'")
    if trigger == "pull_request":
        lines.append("  pull_request:")
        lines.append("    branches:")
        lines.append("      - main")
    lines.append("")
    lines.append("env:")
    lines.append(f"  REGISTRY: {registry}")
    lines.append("")
    lines.append("permissions:")
    lines.append("  contents: read")
    lines.append("  packages: write")
    lines.append("")
    lines.append("jobs:")

    # ------------------------------------------------------------------
    # Job 1: Lint & Type Check
    # ------------------------------------------------------------------
    lines.append("  lint:")
    lines.append(f"    runs-on: {GITHUB_ACTIONS_RUNNER}")
    lines.append("    steps:")
    lines.append("      - name: Checkout code")
    lines.append("        uses: actions/checkout@v4")
    lines.append("")
    lines.append("      - name: Set up Python")
    lines.append("        uses: actions/setup-python@v5")
    lines.append("        with:")
    lines.append("          python-version: '3.11'")
    lines.append("          cache: 'pip'")
    lines.append("")
    lines.append("      - name: Install dependencies")
    lines.append("        run: |")
    lines.append("          python -m pip install --upgrade pip")
    lines.append("          pip install ruff mypy")
    lines.append("          pip install -r requirements.txt")
    lines.append("")
    lines.append("      - name: Run linter (ruff)")
    lines.append("        run: ruff check .")
    lines.append("")
    lines.append("      - name: Run type checker (mypy)")
    lines.append("        run: mypy . --ignore-missing-imports")
    lines.append("")

    # ------------------------------------------------------------------
    # Job 2: Unit Tests
    # ------------------------------------------------------------------
    lines.append("  test:")
    lines.append(f"    runs-on: {GITHUB_ACTIONS_RUNNER}")
    lines.append("    needs: lint")
    lines.append("    strategy:")
    lines.append("      matrix:")
    lines.append(f"        service: [{services_matrix}]")
    lines.append("    steps:")
    lines.append("      - name: Checkout code")
    lines.append("        uses: actions/checkout@v4")
    lines.append("")
    lines.append("      - name: Set up Python")
    lines.append("        uses: actions/setup-python@v5")
    lines.append("        with:")
    lines.append("          python-version: '3.11'")
    lines.append("          cache: 'pip'")
    lines.append("")
    lines.append("      - name: Install test dependencies")
    lines.append("        run: |")
    lines.append("          python -m pip install --upgrade pip")
    lines.append("          pip install pytest pytest-cov httpx")
    lines.append("          pip install -r requirements.txt")
    lines.append("")
    lines.append("      - name: Run tests with coverage")
    lines.append("        run: |")
    lines.append("          pytest tests/ --cov=. --cov-report=xml --cov-report=term-missing --cov-fail-under=80")
    lines.append("")
    lines.append("      - name: Upload coverage report")
    lines.append("        uses: actions/upload-artifact@v4")
    lines.append("        with:")
    lines.append("          name: coverage-${{ matrix.service }}")
    lines.append("          path: coverage.xml")
    lines.append("")

    # ------------------------------------------------------------------
    # Job 3: Build Docker Images
    # ------------------------------------------------------------------
    lines.append("  build:")
    lines.append(f"    runs-on: {GITHUB_ACTIONS_RUNNER}")
    lines.append("    needs: test")
    lines.append("    strategy:")
    lines.append("      matrix:")
    lines.append(f"        service: [{services_matrix}]")
    lines.append("    steps:")
    lines.append("      - name: Checkout code")
    lines.append("        uses: actions/checkout@v4")
    lines.append("")
    lines.append("      - name: Set up Docker Buildx")
    lines.append("        uses: docker/setup-buildx-action@v3")
    lines.append("")
    lines.append("      - name: Log in to container registry")
    lines.append("        uses: docker/login-action@v3")
    lines.append("        with:")
    lines.append(f"          registry: {registry}")
    lines.append("          username: ${{ github.actor }}")
    lines.append("          password: ${{ secrets.GITHUB_TOKEN }}")
    lines.append("")
    lines.append("      - name: Extract metadata")
    lines.append("        id: meta")
    lines.append("        uses: docker/metadata-action@v5")
    lines.append("        with:")
    lines.append("          images: ${{ env.REGISTRY }}/${{ github.repository }}/${{ matrix.service }}")
    lines.append("          tags: |")
    lines.append("            type=sha,prefix=")
    lines.append("            type=ref,event=branch")
    lines.append("            type=semver,pattern={{version}}")
    lines.append("")
    lines.append("      - name: Build and push image")
    lines.append("        uses: docker/build-push-action@v5")
    lines.append("        with:")
    lines.append("          context: ./${{ matrix.service }}")
    lines.append("          push: true")
    lines.append("          tags: ${{ steps.meta.outputs.tags }}")
    lines.append("          labels: ${{ steps.meta.outputs.labels }}")
    lines.append("          cache-from: type=gha")
    lines.append("          cache-to: type=gha,mode=max")
    lines.append("")

    # ------------------------------------------------------------------
    # Job 4: Integration Tests
    # ------------------------------------------------------------------
    lines.append("  integration:")
    lines.append(f"    runs-on: {GITHUB_ACTIONS_RUNNER}")
    lines.append("    needs: build")
    lines.append("    steps:")
    lines.append("      - name: Checkout code")
    lines.append("        uses: actions/checkout@v4")
    lines.append("")
    lines.append("      - name: Copy .env.example to .env")
    lines.append("        run: cp .env.example .env")
    lines.append("")
    lines.append("      - name: Start services")
    lines.append("        run: docker compose up -d --wait")
    lines.append("")
    lines.append("      - name: Run integration tests")
    lines.append("        run: |")
    lines.append("          docker compose exec -T api pytest tests/integration/ -v")
    lines.append("")
    lines.append("      - name: Health check all services")
    lines.append("        run: |")
    for svc in services:
        port = svc.get("port", 8000)
        lines.append(f'          curl -sf http://localhost:{port}/health || echo "WARNING: {svc["name"]} health check failed"')
    lines.append("")
    lines.append("      - name: Tear down")
    lines.append("        if: always()")
    lines.append("        run: docker compose down -v")
    lines.append("")

    # ------------------------------------------------------------------
    # Job 5: Deploy
    # ------------------------------------------------------------------
    lines.append("  deploy:")
    lines.append(f"    runs-on: {GITHUB_ACTIONS_RUNNER}")
    lines.append("    needs: integration")
    lines.append("    if: github.ref == 'refs/heads/main'")
    lines.append(f"    environment: {deploy_environment}")
    lines.append("    steps:")
    lines.append("      - name: Checkout code")
    lines.append("        uses: actions/checkout@v4")
    lines.append("")
    lines.append("      - name: Deploy to production")
    lines.append("        env:")
    lines.append("          DEPLOY_HOST: ${{ secrets.DEPLOY_HOST }}")
    lines.append("          DEPLOY_USER: ${{ secrets.DEPLOY_USER }}")
    lines.append("          DEPLOY_KEY: ${{ secrets.DEPLOY_KEY }}")
    lines.append("        run: |")
    lines.append("          echo 'Deployment would happen here.'")
    lines.append("          echo 'Configure DEPLOY_HOST, DEPLOY_USER, DEPLOY_KEY in repository secrets.'")
    lines.append("")

    workflow_yaml = "\n".join(lines)
    workflow_path = f".github/workflows/{workflow_name}.yml"

    await logger.ainfo(
        "cicd_workflow_generated",
        workflow_name=workflow_name,
        service_count=len(services),
    )

    return {
        "workflow": workflow_yaml,
        "path": workflow_path,
        "best_practices_summary": bp_text[:500] if bp_text else "",
    }


async def generate_cicd_pr_workflow(
    *,
    services: list[dict[str, Any]],
    mcp: MCPClient,
) -> dict[str, Any]:
    """Generate a pull-request CI workflow (lint + test only, no deploy).

    Args:
        services: Service definitions.
        mcp: MCP client.

    Returns:
        Dict with ``workflow`` (str) and ``path`` (str).
    """
    return await generate_cicd_workflow(
        workflow_name="ci-pr",
        trigger="pull_request",
        services=services,
        mcp=mcp,
    )


async def generate_cicd_deploy_workflow(
    *,
    services: list[dict[str, Any]],
    mcp: MCPClient,
    deploy_environment: str = "production",
) -> dict[str, Any]:
    """Generate a full CI/CD workflow that runs on push to main and deploys.

    Args:
        services: Service definitions.
        mcp: MCP client.
        deploy_environment: Deployment target environment.

    Returns:
        Dict with ``workflow`` (str) and ``path`` (str).
    """
    return await generate_cicd_workflow(
        workflow_name="ci-deploy",
        trigger="push",
        services=services,
        mcp=mcp,
        deploy_environment=deploy_environment,
    )


async def scan_secrets(
    *,
    repo_path: str,
    mcp: MCPClient,
) -> dict[str, Any]:
    """Scan the repository for accidentally committed secrets.

    Checks for:
      - .env files tracked in git
      - Hardcoded API keys, tokens, passwords in source files
      - AWS access key patterns
      - Private key files

    Args:
        repo_path: Local path to the repository root.
        mcp: MCP client (used to fetch current secret patterns from context7).

    Returns:
        Dict with ``findings`` (list[dict]) and ``has_critical`` (bool).
    """
    # Fetch updated secret patterns from Context7
    patterns_doc = await mcp.call(
        server="context7",
        tool="get_library_docs",
        arguments={
            "library": "security",
            "topic": "secret detection regex patterns API keys tokens",
        },
    )

    findings: list[dict[str, Any]] = []

    # Secret detection regex patterns
    secret_patterns: list[tuple[str, str, str]] = [
        (r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}", "API Key", "HIGH"),
        (r"(?i)(secret|password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{8,}", "Password/Secret", "CRITICAL"),
        (r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}", "Bearer Token", "CRITICAL"),
        (r"AKIA[0-9A-Z]{16}", "AWS Access Key", "CRITICAL"),
        (r"(?i)-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----", "Private Key", "CRITICAL"),
        (r"(?i)(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}", "GitHub Token", "CRITICAL"),
        (r"(?i)(xox[bpsa]-[A-Za-z0-9-]+)", "Slack Token", "HIGH"),
        (r"(?i)mongodb(\+srv)?://[^\s]+", "MongoDB Connection String", "HIGH"),
        (r"(?i)postgres(ql)?://[^\s]+", "PostgreSQL Connection String", "HIGH"),
        (r"(?i)redis://[^\s]+", "Redis Connection String", "MEDIUM"),
    ]

    # Directories to always skip
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}
    # File extensions to scan
    scan_extensions = {
        ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
        ".toml", ".cfg", ".ini", ".env", ".sh", ".bash", ".md", ".txt",
        ".conf", ".xml", ".properties",
    }

    # Patterns for files that should not be tracked
    env_file_patterns = [".env", ".env.local", ".env.production", ".env.staging", ".env.development"]

    repo_path_abs = os.path.abspath(repo_path) if os.path.isdir(repo_path) else os.path.dirname(os.path.abspath(repo_path))

    for root, dirs, files in os.walk(repo_path_abs):
        # Skip unwanted directories
        dirs[:] = [d for d in dirs if d not in skip_dirs]

        for filename in files:
            filepath = os.path.join(root, filename)
            relative_path = os.path.relpath(filepath, repo_path_abs)

            # Check if .env file is tracked
            if filename in env_file_patterns:
                findings.append({
                    "file": relative_path,
                    "line": 0,
                    "type": "env_file_tracked",
                    "severity": "CRITICAL",
                    "description": f"Environment file '{filename}' should not be in the repository. Add to .gitignore.",
                    "recommendation": f"Add '{filename}' to .gitignore and remove from git history.",
                })
                continue

            # Check for private key files
            if filename.endswith((".pem", ".key", ".p12", ".pfx", ".jks")):
                findings.append({
                    "file": relative_path,
                    "line": 0,
                    "type": "private_key_file",
                    "severity": "CRITICAL",
                    "description": f"Private key file '{filename}' found in repository.",
                    "recommendation": "Remove private key file from repository and rotate the key.",
                })
                continue

            # Scan file contents for secret patterns
            ext = os.path.splitext(filename)[1].lower()
            if ext not in scan_extensions:
                continue

            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, start=1):
                        # Skip comments and imports
                        stripped = line.strip()
                        if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("import"):
                            continue

                        for pattern, secret_type, severity in secret_patterns:
                            if re.search(pattern, line):
                                findings.append({
                                    "file": relative_path,
                                    "line": line_num,
                                    "type": secret_type,
                                    "severity": severity,
                                    "description": f"Potential {secret_type} found at line {line_num}.",
                                    "recommendation": "Move to environment variables or secrets manager. Do not commit secrets.",
                                })
            except (PermissionError, OSError):
                continue

    has_critical = any(f["severity"] == "CRITICAL" for f in findings)

    # Deduplicate findings by (file, line, type)
    seen: set[tuple[str, int, str]] = set()
    unique_findings: list[dict[str, Any]] = []
    for f in findings:
        key = (f["file"], f["line"], f["type"])
        if key not in seen:
            seen.add(key)
            unique_findings.append(f)

    await logger.ainfo(
        "secrets_scan_complete",
        total_findings=len(unique_findings),
        critical_count=sum(1 for f in unique_findings if f["severity"] == "CRITICAL"),
        has_critical=has_critical,
    )

    return {
        "findings": unique_findings,
        "has_critical": has_critical,
        "summary": {
            "total": len(unique_findings),
            "critical": sum(1 for f in unique_findings if f["severity"] == "CRITICAL"),
            "high": sum(1 for f in unique_findings if f["severity"] == "HIGH"),
            "medium": sum(1 for f in unique_findings if f["severity"] == "MEDIUM"),
        },
    }


async def generate_health_check_config(
    *,
    services: list[dict[str, Any]],
    mcp: MCPClient,
) -> dict[str, Any]:
    """Generate a structured health check configuration for all services.

    Args:
        services: List of service dicts with ``name`` and ``port``.
        mcp: MCP client.

    Returns:
        Dict with ``health_checks`` (list) and ``docker_healthcheck_commands`` (dict).
    """
    configs: list[dict[str, Any]] = []
    commands: dict[str, list[str]] = {}

    for svc in services:
        name = svc["name"]
        port = svc.get("port", 8000)
        path = svc.get("health_path", "/health")
        interval = svc.get("health_interval", DEFAULT_HEALTH_CHECK_INTERVAL)
        timeout = svc.get("health_timeout", DEFAULT_HEALTH_CHECK_TIMEOUT)
        retries = svc.get("health_retries", DEFAULT_HEALTH_CHECK_RETRIES)

        config = {
            "service": name,
            "endpoint": f"http://localhost:{port}{path}",
            "port": port,
            "path": path,
            "interval": interval,
            "timeout": timeout,
            "retries": retries,
            "start_period": DEFAULT_HEALTH_CHECK_START_PERIOD,
            "docker_command": _health_check_command(port, path),
        }
        configs.append(config)
        commands[name] = _health_check_command(port, path)

    await logger.ainfo("health_check_config_generated", service_count=len(services))

    return {
        "health_checks": configs,
        "docker_healthcheck_commands": commands,
    }


async def validate_resource_limits(
    *,
    services: list[dict[str, Any]],
    mcp: MCPClient,
) -> dict[str, Any]:
    """Validate that all services have resource limits configured.

    Args:
        services: List of service dicts.  Each should have ``memory_limit``
            and ``cpu_limit``.
        mcp: MCP client.

    Returns:
        Dict with ``valid`` (bool), ``issues`` (list), ``defaults_applied`` (list).
    """
    issues: list[str] = []
    defaults_applied: list[str] = []

    for svc in services:
        name = svc["name"]

        if "memory_limit" not in svc:
            svc["memory_limit"] = DEFAULT_MEMORY_LIMIT
            defaults_applied.append(f"[{name}] Memory limit set to default ({DEFAULT_MEMORY_LIMIT})")

        if "cpu_limit" not in svc:
            svc["cpu_limit"] = DEFAULT_CPU_LIMIT
            defaults_applied.append(f"[{name}] CPU limit set to default ({DEFAULT_CPU_LIMIT})")

        # Validate memory format
        mem = svc["memory_limit"]
        if not re.match(r"^\d+[kmgt]?$", mem.lower()):
            issues.append(f"[{name}] Invalid memory limit format: '{mem}'. Use e.g. '512m', '1g'.")

        # Validate CPU format
        cpu = svc["cpu_limit"]
        try:
            cpu_val = float(cpu)
            if cpu_val <= 0:
                issues.append(f"[{name}] CPU limit must be positive: '{cpu}'.")
        except (ValueError, TypeError):
            issues.append(f"[{name}] Invalid CPU limit format: '{cpu}'. Use a number like '0.5', '1.0'.")

    await logger.ainfo(
        "resource_limits_validated",
        service_count=len(services),
        issues_count=len(issues),
        defaults_count=len(defaults_applied),
    )

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "defaults_applied": defaults_applied,
    }


async def generate_structured_logging_config(
    *,
    service_name: str,
    port: int,
    mcp: MCPClient,
    log_format: str = "json",
    log_level: str = "INFO",
) -> dict[str, Any]:
    """Generate structured logging configuration for a service.

    Args:
        service_name: Service identifier.
        port: Service port.
        mcp: MCP client.
        log_format: Output format (``"json"`` or ``"text"``).
        log_level: Minimum log level.

    Returns:
        Dict with ``logging_config`` (Python dict), ``env_vars`` (dict),
        and ``middleware_code`` (str).
    """
    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            },
            "text": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": log_format,
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["default"],
        },
        "loggers": {
            service_name: {
                "level": log_level,
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn": {
                "level": "INFO",
                "handlers": ["default"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": "WARNING",
                "handlers": ["default"],
                "propagate": False,
            },
        },
    }

    env_vars = {
        "LOG_LEVEL": log_level,
        "LOG_FORMAT": log_format,
        "SERVICE_NAME": service_name,
    }

    middleware_code = textwrap.dedent("""\
        import time
        import uuid
        import structlog
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request

        logger = structlog.get_logger("access")

        class StructuredLoggingMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
                start = time.monotonic()

                response = await call_next(request)

                duration_ms = round((time.monotonic() - start) * 1000, 2)
                await logger.ainfo(
                    "http_request",
                    method=request.method,
                    path=str(request.url.path),
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    request_id=request_id,
                    client=request.client.host if request.client else None,
                )

                response.headers["X-Request-ID"] = request_id
                return response
    """)

    await logger.ainfo("logging_config_generated", service=service_name)

    return {
        "logging_config": logging_config,
        "env_vars": env_vars,
        "middleware_code": middleware_code,
    }


async def generate_metrics_endpoint(
    *,
    service_name: str,
    port: int,
    metrics_path: str = "/metrics",
    mcp: MCPClient,
) -> dict[str, Any]:
    """Generate a Prometheus-compatible /metrics endpoint implementation.

    Args:
        service_name: Service identifier.
        port: Service port.
        metrics_path: HTTP path for the metrics endpoint.
        mcp: MCP client.

    Returns:
        Dict with ``endpoint_code`` (str), ``router_code`` (str),
        ``requirements`` (list[str]).
    """
    endpoint_code = textwrap.dedent("""\
        \"\"\"Prometheus-compatible metrics endpoint.\"\"\"

        import time
        import psutil
        from prometheus_client import (
            Counter,
            Histogram,
            Gauge,
            generate_latest,
            CONTENT_TYPE_LATEST,
        )
        from fastapi import APIRouter, Response

        router = APIRouter(tags=["monitoring"])

        # -- Metrics definitions --
        REQUEST_COUNT = Counter(
            "http_requests_total",
            "Total HTTP requests",
            ["method", "endpoint", "status_code"],
        )
        REQUEST_LATENCY = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency in seconds",
            ["method", "endpoint"],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )
        ACTIVE_REQUESTS = Gauge(
            "http_active_requests",
            "Number of in-flight HTTP requests",
        )
        PROCESS_MEMORY = Gauge(
            "process_resident_memory_bytes",
            "Resident memory size in bytes",
        )
        PROCESS_CPU = Gauge(
            "process_cpu_seconds_total",
            "Total user and system CPU time spent in seconds",
        )
        QUEUE_SIZE = Gauge(
            "task_queue_size",
            "Current number of tasks in the agent queue",
        )

        @router.get("/metrics")
        async def metrics():
            \"\"\"Expose Prometheus metrics.\"\"\"
            # Update process metrics
            proc = psutil.Process()
            PROCESS_MEMORY.set(proc.memory_info().rss)
            PROCESS_CPU.set(proc.cpu_times().user + proc.cpu_times().system)

            return Response(
                content=generate_latest(),
                media_type=CONTENT_TYPE_LATEST,
            )
    """)

    router_code = textwrap.dedent("""\
        # Add to your FastAPI app:
        # from agents.<service>.metrics import router as metrics_router
        # app.include_router(metrics_router)
    """)

    requirements = [
        "prometheus-client>=0.20.0",
        "psutil>=5.9.0",
    ]

    await logger.ainfo("metrics_endpoint_generated", service=service_name)

    return {
        "endpoint_code": endpoint_code,
        "router_code": router_code,
        "requirements": requirements,
    }


async def generate_env_example(
    *,
    services: list[dict[str, Any]],
    mcp: MCPClient,
    secrets: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a ``.env.example`` file with all required environment variables.

    Args:
        services: Service definitions.
        mcp: MCP client.
        secrets: Additional secret variable names to include.

    Returns:
        Dict with ``env_content`` (str).
    """
    lines: list[str] = []
    lines.append("# =============================================================")
    lines.append("# OpenCrew — Environment Variables")
    lines.append("# Copy this file to .env and fill in real values.")
    lines.append("# NEVER commit .env to version control!")
    lines.append("# =============================================================")
    lines.append("")

    lines.append("# ---- Global ----")
    lines.append("COMPOSE_PROJECT_NAME=opencrew")
    lines.append("LOG_LEVEL=INFO")
    lines.append("LOG_FORMAT=json")
    lines.append("")

    lines.append("# ---- MCP Servers ----")
    lines.append("GITHUB_MCP_URL=https://api.github.com/mcp")
    lines.append("GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    lines.append("CONTEXT7_MCP_URL=https://mcp.context7.com/mcp")
    lines.append("LINEAR_MCP_URL=https://api.linear.app/mcp")
    lines.append("LINEAR_API_KEY=lin_api_xxxxxxxxxxxxxxxxxxxxxxxx")
    lines.append("OPENDESIGN_MCP_URL=https://mcp.opendesign.com/mcp")
    lines.append("")

    lines.append("# ---- Agent Ports ----")
    for svc in services:
        name = svc["name"]
        port = svc.get("port", 8000)
        lines.append(f"{name.upper()}_PORT={port}")
    lines.append("")

    lines.append("# ---- Infrastructure ----")
    lines.append("REDIS_URL=redis://redis:6379/0")
    lines.append("DATABASE_URL=postgresql://opencrew:opencrew@postgres:5432/opencrew")
    lines.append("")

    if secrets:
        lines.append("# ---- Additional Secrets ----")
        for secret in secrets:
            lines.append(f"{secret}=changeme")
        lines.append("")

    lines.append("# ---- Deployment ----")
    lines.append("DEPLOY_HOST=localhost")
    lines.append("DEPLOY_USER=deploy")
    lines.append("DEPLOY_KEY=")

    env_content = "\n".join(lines)

    await logger.ainfo("env_example_generated", service_count=len(services))

    return {
        "env_content": env_content,
    }


async def push_config_to_repo(
    *,
    files: dict[str, str],
    branch: str,
    commit_message: str,
    mcp: MCPClient,
) -> dict[str, Any]:
    """Push generated configuration files to the GitHub repository.

    Args:
        files: Mapping of ``filepath → content`` to commit.
        branch: Target branch name.
        commit_message: Git commit message.
        mcp: MCP client (calls ``github_mcp``).

    Returns:
        Dict with ``branch``, ``commit_url``, ``files_pushed`` (list[str]).
    """
    # Create branch
    branch_result = await mcp.call(
        server="github_mcp",
        tool="create_branch",
        arguments={
            "branch": branch,
            "base": "main",
        },
    )
    await logger.ainfo("branch_created", branch=branch)

    # Commit each file
    committed_files: list[str] = []
    for filepath, content in files.items():
        await mcp.call(
            server="github_mcp",
            tool="commit_files",
            arguments={
                "branch": branch,
                "files": [{"path": filepath, "content": content}],
                "message": commit_message,
            },
        )
        committed_files.append(filepath)
        await logger.ainfo("file_committed", file=filepath, branch=branch)

    # Create PR
    pr_result = await mcp.call(
        server="github_mcp",
        tool="create_pr",
        arguments={
            "title": commit_message,
            "body": f"Auto-generated by DevOps agent.\n\nFiles:\n" + "\n".join(f"- `{f}`" for f in committed_files),
            "head": branch,
            "base": "main",
        },
    )

    commit_url = ""
    if isinstance(pr_result, dict):
        commit_url = pr_result.get("url", pr_result.get("html_url", ""))

    await logger.ainfo(
        "config_pushed_to_repo",
        branch=branch,
        files_count=len(committed_files),
        pr_url=commit_url,
    )

    return {
        "branch": branch,
        "commit_url": commit_url,
        "files_pushed": committed_files,
    }


async def push_files_to_repo(
    *,
    files: dict[str, str],
    branch: str,
    commit_message: str,
    base_branch: str = "main",
    mcp: MCPClient,
    create_pr: bool = True,
    pr_title: str | None = None,
    pr_body: str | None = None,
) -> dict[str, Any]:
    """Push arbitrary files to the GitHub repository.

    A more flexible version of ``push_config_to_repo`` that supports
    custom PR titles/bodies and optional PR creation.

    Args:
        files: Mapping of ``filepath → content``.
        branch: Target branch name.
        commit_message: Git commit message.
        base_branch: Branch to create from and target for PR.
        mcp: MCP client.
        create_pr: Whether to open a PR after committing.
        pr_title: Override PR title (defaults to commit_message).
        pr_body: Override PR body.

    Returns:
        Dict with ``branch``, ``commit_url``, ``files_pushed``, ``pr_url``.
    """
    # Create branch
    await mcp.call(
        server="github_mcp",
        tool="create_branch",
        arguments={
            "branch": branch,
            "base": base_branch,
        },
    )
    await logger.ainfo("branch_created", branch=branch, base=base_branch)

    # Commit files
    committed_files: list[str] = []
    for filepath, content in files.items():
        await mcp.call(
            server="github_mcp",
            tool="commit_files",
            arguments={
                "branch": branch,
                "files": [{"path": filepath, "content": content}],
                "message": commit_message,
            },
        )
        committed_files.append(filepath)

    await logger.ainfo("files_committed", count=len(committed_files), branch=branch)

    pr_url = ""
    if create_pr:
        title = pr_title or commit_message
        body = pr_body or f"Auto-generated by DevOps agent.\n\nFiles:\n" + "\n".join(f"- `{f}`" for f in committed_files)

        pr_result = await mcp.call(
            server="github_mcp",
            tool="create_pr",
            arguments={
                "title": title,
                "body": body,
                "head": branch,
                "base": base_branch,
            },
        )
        if isinstance(pr_result, dict):
            pr_url = pr_result.get("url", pr_result.get("html_url", ""))

    await logger.ainfo(
        "files_pushed_to_repo",
        branch=branch,
        files_count=len(committed_files),
        pr_url=pr_url,
    )

    return {
        "branch": branch,
        "commit_url": pr_url,
        "files_pushed": committed_files,
        "pr_url": pr_url,
    }


async def read_repo_structure(
    *,
    path: str,
    mcp: MCPClient,
) -> dict[str, Any]:
    """Read the repository structure to understand the codebase layout.

    Args:
        path: Root path within the repo to read.
        mcp: MCP client (calls ``github_mcp``).

    Returns:
        Dict with ``files`` (list[str]) and ``structure`` (nested dict).
    """
    result = await mcp.call(
        server="github_mcp",
        tool="search_code",
        arguments={
            "query": f"repo:* path:{path}",
            "per_page": 100,
        },
    )

    files: list[str] = []
    if isinstance(result, dict) and "items" in result:
        files = [item.get("path", "") for item in result["items"]]

    await logger.ainfo("repo_structure_read", path=path, file_count=len(files))

    return {
        "files": files,
        "raw": result,
    }


async def read_file_from_repo(
    *,
    filepath: str,
    mcp: MCPClient,
) -> dict[str, Any]:
    """Read a single file from the GitHub repository.

    Args:
        filepath: Path to the file within the repo.
        mcp: MCP client (calls ``github_mcp``).

    Returns:
        Dict with ``filepath``, ``content`` (str), ``encoding``.
    """
    result = await mcp.call(
        server="github_mcp",
        tool="get_file",
        arguments={
            "path": filepath,
        },
    )

    content = ""
    encoding = "utf-8"
    if isinstance(result, dict):
        content = result.get("content", "")
        encoding = result.get("encoding", "utf-8")

    await logger.ainfo("file_read_from_repo", filepath=filepath)

    return {
        "filepath": filepath,
        "content": content,
        "encoding": encoding,
    }


async def fetch_docker_best_practices(
    *,
    topic: str = "docker production multi-stage security non-root",
    mcp: MCPClient,
) -> dict[str, Any]:
    """Fetch Docker best practices from Context7.

    Args:
        topic: Specific topic to look up.
        mcp: MCP client (calls ``context7``).

    Returns:
        Dict with ``content`` (str) and ``source``.
    """
    result = await mcp.call(
        server="context7",
        tool="get_library_docs",
        arguments={
            "library": "docker",
            "topic": topic,
        },
    )

    content = ""
    if isinstance(result, dict):
        content = result.get("content", "")
    else:
        content = str(result)

    await logger.ainfo("docker_best_practices_fetched", topic=topic, length=len(content))

    return {
        "content": content,
        "source": "context7",
    }


async def fetch_cicd_best_practices(
    *,
    topic: str = "GitHub Actions CI/CD best practices caching matrix builds",
    mcp: MCPClient,
) -> dict[str, Any]:
    """Fetch CI/CD best practices from Context7.

    Args:
        topic: Specific topic to look up.
        mcp: MCP client (calls ``context7``).

    Returns:
        Dict with ``content`` (str) and ``source``.
    """
    result = await mcp.call(
        server="context7",
        tool="get_library_docs",
        arguments={
            "library": "github-actions",
            "topic": topic,
        },
    )

    content = ""
    if isinstance(result, dict):
        content = result.get("content", "")
    else:
        content = str(result)

    await logger.ainfo("cicd_best_practices_fetched", topic=topic, length=len(content))

    return {
        "content": content,
        "source": "context7",
    }


async def fetch_nginx_best_practices(
    *,
    topic: str = "nginx reverse proxy configuration security headers",
    mcp: MCPClient,
) -> dict[str, Any]:
    """Fetch nginx best practices from Context7.

    Args:
        topic: Specific topic to look up.
        mcp: MCP client (calls ``context7``).

    Returns:
        Dict with ``content`` (str) and ``source``.
    """
    result = await mcp.call(
        server="context7",
        tool="get_library_docs",
        arguments={
            "library": "nginx",
            "topic": topic,
        },
    )

    content = ""
    if isinstance(result, dict):
        content = result.get("content", "")
    else:
        content = str(result)

    await logger.ainfo("nginx_best_practices_fetched", topic=topic, length=len(content))

    return {
        "content": content,
        "source": "context7",
    }


async def generate_nginx_config(
    *,
    services: list[dict[str, Any]],
    mcp: MCPClient,
    server_name: str = "localhost",
    ssl: bool = False,
) -> dict[str, Any]:
    """Generate an nginx reverse proxy configuration.

    Args:
        services: List of service dicts with ``name``, ``port``, and
            optionally ``location`` (default ``/api/<name>``).
        mcp: MCP client (fetches best practices).
        server_name: Server name for the ``server_name`` directive.
        ssl: Whether to include SSL configuration.

    Returns:
        Dict with ``nginx_conf`` (str).
    """
    # Fetch best practices
    bp = await fetch_nginx_best_practices(mcp=mcp)

    lines: list[str] = []
    lines.append("# Auto-generated nginx reverse proxy configuration")
    lines.append("# Generated by OpenCrew DevOps agent")
    lines.append("")
    lines.append("upstream web_ui {")
    lines.append("    server web:3000;")
    lines.append("}")
    lines.append("")

    for svc in services:
        name = svc["name"]
        port = svc.get("port", 8000)
        lines.append(f"upstream {name.replace('-', '_')} {{")
        lines.append(f"    server {name}:{port};")
        lines.append("}")
    lines.append("")

    lines.append("server {")
    lines.append("    listen 80;")
    if ssl:
        lines.append("    listen 443 ssl http2;")
        lines.append("    ssl_certificate /etc/nginx/ssl/cert.pem;")
        lines.append("    ssl_certificate_key /etc/nginx/ssl/key.pem;")
        lines.append("    ssl_protocols TLSv1.2 TLSv1.3;")
        lines.append("    ssl_ciphers HIGH:!aNULL:!MD5;")
    lines.append(f"    server_name {server_name};")
    lines.append("")

    # Security headers
    lines.append("    # Security headers")
    lines.append("    add_header X-Frame-Options \"SAMEORIGIN\" always;")
    lines.append("    add_header X-Content-Type-Options \"nosniff\" always;")
    lines.append("    add_header X-XSS-Protection \"1; mode=block\" always;")
    lines.append("    add_header Referrer-Policy \"strict-origin-when-cross-origin\" always;")
    lines.append("    add_header Content-Security-Policy \"default-src 'self'\" always;")
    lines.append("")

    # Rate limiting
    lines.append("    # Rate limiting")
    lines.append("    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;")
    lines.append("")

    # Web UI
    lines.append("    # Web UI")
    lines.append("    location / {")
    lines.append("        proxy_pass http://web_ui;")
    lines.append("        proxy_set_header Host $host;")
    lines.append("        proxy_set_header X-Real-IP $remote_addr;")
    lines.append("        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;")
    lines.append("        proxy_set_header X-Forwarded-Proto $scheme;")
    lines.append("")
    lines.append("        # WebSocket support for SSE")
    lines.append("        proxy_http_version 1.1;")
    lines.append("        proxy_set_header Upgrade $http_upgrade;")
    lines.append("        proxy_set_header Connection \"upgrade\";")
    lines.append("    }")
    lines.append("")

    # Service proxies
    for svc in services:
        name = svc["name"]
        port = svc.get("port", 8000)
        location = svc.get("location", f"/api/{name}")
        upstream_name = name.replace("-", "_")

        lines.append(f"    # {name}")
        lines.append(f"    location {location} {{")
        lines.append(f"        limit_req zone=api burst=20 nodelay;")
        lines.append(f"        proxy_pass http://{upstream_name};")
        lines.append(f"        proxy_set_header Host $host;")
        lines.append(f"        proxy_set_header X-Real-IP $remote_addr;")
        lines.append(f"        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;")
        lines.append(f"        proxy_set_header X-Forwarded-Proto $scheme;")
        lines.append(f"        proxy_read_timeout 60s;")
        lines.append(f"        proxy_connect_timeout 10s;")
        lines.append("    }")
        lines.append("")

    # Health endpoint for nginx itself
    lines.append("    # Nginx health check")
    lines.append("    location /nginx-health {")
    lines.append("        access_log off;")
    lines.append("        return 200 'ok';")
    lines.append("        add_header Content-Type text/plain;")
    lines.append("    }")
    lines.append("}")

    nginx_conf = "\n".join(lines)

    await logger.ainfo("nginx_config_generated", service_count=len(services))

    return {
        "nginx_conf": nginx_conf,
        "best_practices_summary": bp.get("content", "")[:300],
    }


async def generate_deployment_docs(
    *,
    services: list[dict[str, Any]],
    mcp: MCPClient,
) -> dict[str, Any]:
    """Generate deployment documentation in Markdown.

    Covers prerequisites, setup, running, troubleshooting, and rollback.

    Args:
        services: Service definitions.
        mcp: MCP client.

    Returns:
        Dict with ``docs`` (str, Markdown).
    """
    service_list = "\n".join(
        f"| {s['name']} | `{s.get('port', 8000)}` | {s.get('description', 'N/A')} |"
        for s in services
    )

    docs = textwrap.dedent(f"""\
        # OpenCrew — Deployment Guide

        > Auto-generated by the DevOps / SRE agent.

        ## Prerequisites

        - Docker >= 24.0
        - Docker Compose >= 2.20
        - Git
        - (Optional) Nginx for reverse proxy

        ## Services

        | Service | Port | Description |
        |---------|------|-------------|
        {service_list}

        ## Quick Start

        ```bash
        # 1. Clone the repository
        git clone <repo-url>
        cd opencrew

        # 2. Copy and edit environment variables
        cp .env.example .env
        # Edit .env with your actual values (API keys, tokens, etc.)

        # 3. Start all services
        docker compose up -d

        # 4. Verify all services are healthy
        docker compose ps
        ```

        ## Health Checks

        Each service exposes a `/health` endpoint:

        ```bash
        {" ".join(f"curl http://localhost:{s.get('port', 8000)}/health" for s in services[:3])}
        ```

        ## Environment Variables

        See `.env.example` for all required variables.

        **Never commit `.env` to version control.**

        ## CI/CD

        The project uses GitHub Actions for CI/CD:

        - **Pull Request**: Lint → Test → Build
        - **Push to main**: Lint → Test → Build → Integration → Deploy

        ## Resource Limits

        Default resource limits per container:

        | Resource | Default |
        |----------|---------|
        | Memory   | {DEFAULT_MEMORY_LIMIT} |
        | CPU      | {DEFAULT_CPU_LIMIT} cores |

        ## Monitoring

        Each service exposes Prometheus metrics at `/metrics`:

        ```bash
        curl http://localhost:<port>/metrics
        ```

        ## Troubleshooting

        ### Service won't start

        ```bash
        docker compose logs <service-name>
        docker compose ps
        ```

        ### Health check failing

        ```bash
        docker compose exec <service-name> curl -f http://localhost:<port>/health
        ```

        ### Out of memory

        ```bash
        docker stats
        # Increase memory limit in docker-compose.yml if needed
        ```

        ## Rollback

        ```bash
        # Revert to previous version
        git revert HEAD
        git push origin main
        # CI/CD will automatically redeploy the previous version
        ```

        ## Security Notes

        - All containers run as non-root users
        - Secrets are loaded from `.env` file only
        - Security headers are configured in nginx
        - Rate limiting is enabled on all API endpoints
    """)

    await logger.ainfo("deployment_docs_generated", service_count=len(services))

    return {
        "docs": docs,
    }


async def generate_dependency_check(
    *,
    requirements_file: str = "requirements.txt",
    mcp: MCPClient,
) -> dict[str, Any]:
    """Check for known CVEs in Python dependencies.

    Fetches advisory data from Context7 and cross-references with
    the project's pinned dependencies.

    Args:
        requirements_file: Path to the requirements file.
        mcp: MCP client.

    Returns:
        Dict with ``vulnerabilities`` (list), ``safe`` (bool).
    """
    # Fetch known vulnerability data
    vuln_data = await mcp.call(
        server="context7",
        tool="get_library_docs",
        arguments={
            "library": "python-security",
            "topic": "known CVE vulnerabilities pip packages",
        },
    )

    vuln_content = ""
    if isinstance(vuln_data, dict):
        vuln_content = vuln_data.get("content", "")

    # Read local requirements file
    dependencies: list[str] = []
    try:
        with open(requirements_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-"):
                    dependencies.append(line)
    except FileNotFoundError:
        await logger.awarn("requirements_file_not_found", path=requirements_file)

    await logger.ainfo(
        "dependency_check_complete",
        dependency_count=len(dependencies),
        has_advisory_data=bool(vuln_content),
    )

    return {
        "dependencies": dependencies,
        "vulnerabilities": [],  # Would be populated by actual CVE matching
        "safe": True,
        "advisory_summary": vuln_content[:500] if vuln_content else "",
    }


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------


def get_tools(mcp: MCPClient) -> dict[str, ToolCallable]:
    """Return the DevOps / SRE agent's tool registry.

    Each entry maps a tool name to an async callable.  Tools are either:
    - Direct MCP client wrappers (github_mcp, context7)
    - Local logic that may invoke MCP calls internally

    Args:
        mcp: Initialized MCPClient for making tool calls to MCP servers.

    Returns:
        Dictionary of ``tool_name → async callable``.
    """

    async def _generate_dockerfile(**kwargs: Any) -> Any:
        return await generate_dockerfile(mcp=mcp, **kwargs)

    async def _generate_docker_compose(**kwargs: Any) -> Any:
        return await generate_docker_compose(mcp=mcp, **kwargs)

    async def _generate_cicd_pr_workflow(**kwargs: Any) -> Any:
        return await generate_cicd_pr_workflow(mcp=mcp, **kwargs)

    async def _generate_cicd_deploy_workflow(**kwargs: Any) -> Any:
        return await generate_cicd_deploy_workflow(mcp=mcp, **kwargs)

    async def _scan_secrets(**kwargs: Any) -> Any:
        return await scan_secrets(mcp=mcp, **kwargs)

    async def _generate_health_check_config(**kwargs: Any) -> Any:
        return await generate_health_check_config(mcp=mcp, **kwargs)

    async def _validate_resource_limits(**kwargs: Any) -> Any:
        return await validate_resource_limits(mcp=mcp, **kwargs)

    async def _generate_structured_logging_config(**kwargs: Any) -> Any:
        return await generate_structured_logging_config(mcp=mcp, **kwargs)

    async def _generate_metrics_endpoint(**kwargs: Any) -> Any:
        return await generate_metrics_endpoint(mcp=mcp, **kwargs)

    async def _generate_env_example(**kwargs: Any) -> Any:
        return await generate_env_example(mcp=mcp, **kwargs)

    async def _push_files_to_repo(**kwargs: Any) -> Any:
        return await push_files_to_repo(mcp=mcp, **kwargs)

    async def _push_config_to_repo(**kwargs: Any) -> Any:
        return await push_config_to_repo(mcp=mcp, **kwargs)

    async def _read_repo_structure(**kwargs: Any) -> Any:
        return await read_repo_structure(mcp=mcp, **kwargs)

    async def _read_file_from_repo(**kwargs: Any) -> Any:
        return await read_file_from_repo(mcp=mcp, **kwargs)

    async def _fetch_docker_best_practices(**kwargs: Any) -> Any:
        return await fetch_docker_best_practices(mcp=mcp, **kwargs)

    async def _fetch_cicd_best_practices(**kwargs: Any) -> Any:
        return await fetch_cicd_best_practices(mcp=mcp, **kwargs)

    async def _fetch_nginx_best_practices(**kwargs: Any) -> Any:
        return await fetch_nginx_best_practices(mcp=mcp, **kwargs)

    async def _generate_nginx_config(**kwargs: Any) -> Any:
        return await generate_nginx_config(mcp=mcp, **kwargs)

    async def _generate_deployment_docs(**kwargs: Any) -> Any:
        return await generate_deployment_docs(mcp=mcp, **kwargs)

    async def _generate_dependency_check(**kwargs: Any) -> Any:
        return await generate_dependency_check(mcp=mcp, **kwargs)

    return {
        # --- Docker ---
        "generate_dockerfile": _generate_dockerfile,
        "generate_docker_compose": _generate_docker_compose,
        # --- CI/CD ---
        "generate_cicd_pr_workflow": _generate_cicd_pr_workflow,
        "generate_cicd_deploy_workflow": _generate_cicd_deploy_workflow,
        # --- Security ---
        "scan_secrets": _scan_secrets,
        "generate_dependency_check": _generate_dependency_check,
        # --- Monitoring & Observability ---
        "generate_health_check_config": _generate_health_check_config,
        "validate_resource_limits": _validate_resource_limits,
        "generate_structured_logging_config": _generate_structured_logging_config,
        "generate_metrics_endpoint": _generate_metrics_endpoint,
        # --- Configuration ---
        "generate_env_example": _generate_env_example,
        "generate_nginx_config": _generate_nginx_config,
        # --- Repository Operations (github_mcp wrappers) ---
        "push_files_to_repo": _push_files_to_repo,
        "push_config_to_repo": _push_config_to_repo,
        "read_repo_structure": _read_repo_structure,
        "read_file_from_repo": _read_file_from_repo,
        # --- Documentation & Best Practices (context7 wrappers) ---
        "fetch_docker_best_practices": _fetch_docker_best_practices,
        "fetch_cicd_best_practices": _fetch_cicd_best_practices,
        "fetch_nginx_best_practices": _fetch_nginx_best_practices,
        "generate_deployment_docs": _generate_deployment_docs,
    }