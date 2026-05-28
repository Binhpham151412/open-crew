"""MCP Client — Calls MCP tools via JSON-RPC 2.0 over HTTP.

Supports multiple MCP servers configured via environment variables.
Each MCP server URL is read from environment config and tools are routed
to the appropriate server based on tool name prefix mapping.

Usage:
    client = MCPClient()
    result = await client.call("github_create_pr", {"title": "feat: add user", "head": "feature/x", "base": "main"})
"""

from __future__ import annotations

import os
import uuid
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("mcp_client")

# Default MCP server URL mappings — env var name → default URL (if any)
_MCP_SERVER_ENV_VARS: dict[str, str | None] = {
    "github": "GITHUB_MCP_URL",
    "context7": "CONTEXT7_MCP_URL",
    "linear": "LINEAR_MCP_URL",
    "opendesign": "OPENDESIGN_MCP_URL",
}

# Known tool-name prefixes → which MCP server handles them
_TOOL_PREFIX_TO_SERVER: dict[str, str] = {
    "github_": "github",
    "context7_": "context7",
    "resolve_library": "context7",
    "get_library": "context7",
    "linear_": "linear",
    "create_epic": "linear",
    "create_story": "linear",
    "update_story": "linear",
    "create_sprint": "linear",
    "assign_story": "linear",
    "opendesign_": "opendesign",
    "get_design": "opendesign",
    "export_component": "opendesign",
    "compare_design": "opendesign",
}


class MCPError(Exception):
    """Raised when an MCP JSON-RPC call returns an error or transport fails."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"MCP error {code}: {message}")


class MCPClient:
    """Async client that routes tool calls to the correct MCP server via JSON-RPC 2.0.

    Server URLs are resolved lazily from environment variables on first use.
    You can also register servers programmatically via ``register_server``.

    Args:
        timeout: Default HTTP request timeout in seconds.
        max_retries: Number of transient-failure retries (0 = no retry).
    """

    def __init__(
        self,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        # server_key → URL  (populated lazily from env or explicit registration)
        self._server_urls: dict[str, str] = {}
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the shared httpx async client, creating it on first call."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20,
                ),
            )
        return self._client

    async def close(self) -> None:
        """Gracefully close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "MCPClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Server configuration
    # ------------------------------------------------------------------

    def register_server(self, server_key: str, url: str) -> None:
        """Explicitly register an MCP server URL.

        This overrides whatever value might come from the environment.

        Args:
            server_key: Short identifier, e.g. ``"github"``, ``"context7"``.
            url: Full HTTP(S) URL of the MCP server endpoint.
        """
        self._server_urls[server_key] = url.rstrip("/")
        logger.info("Registered MCP server %s → %s", server_key, url)

    def _resolve_server_url(self, server_key: str) -> str:
        """Resolve the URL for *server_key*, checking cache then env vars.

        Raises:
            MCPError: If no URL can be found for the server key.
        """
        if server_key in self._server_urls:
            return self._server_urls[server_key]

        env_var = _MCP_SERVER_ENV_VARS.get(server_key)
        url: str | None = None

        if env_var:
            url = os.getenv(env_var)

        # Hard-coded fallback for Context7 (public endpoint)
        if url is None and server_key == "context7":
            url = "https://mcp.context7.com/mcp"

        if url is None:
            raise MCPError(
                code=-32602,
                message=(
                    f"No URL configured for MCP server '{server_key}'. "
                    f"Set env var {env_var or '(unknown)' or 'or call register_server()'}."
                ),
            )

        self._server_urls[server_key] = url.rstrip("/")
        return self._server_urls[server_key]

    def _guess_server_key(self, tool_name: str) -> str:
        """Infer which MCP server owns *tool_name* based on known prefixes.

        Falls back to ``"github"`` if no prefix matches (most common tool).
        """
        for prefix, server_key in _TOOL_PREFIX_TO_SERVER.items():
            if tool_name.startswith(prefix):
                return server_key
        # Default fallback
        return "github"

    def server_key_for_tool(self, tool_name: str, explicit: str | None = None) -> str:
        """Return the server key that should handle *tool_name*.

        Args:
            tool_name: The MCP tool name (e.g. ``"github_create_pr"``).
            explicit: Optional override — if provided, used directly.
        """
        if explicit:
            return explicit
        return self._guess_server_key(tool_name)

    # ------------------------------------------------------------------
    # Core RPC call
    # ------------------------------------------------------------------

    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        server_key: str | None = None,
        request_id: str | None = None,
    ) -> Any:
        """Call an MCP tool via JSON-RPC 2.0 ``tools/call`` method.

        Routes the request to the correct MCP server automatically unless
        *server_key* is explicitly provided.

        Args:
            tool_name: Name of the MCP tool to invoke.
            arguments: Tool-specific keyword arguments.
            server_key: Explicitly target this MCP server (skip auto-detection).
            request_id: Optional custom request ID (auto-generated UUID if omitted).

        Returns:
            The ``result`` field from the JSON-RPC response.

        Raises:
            MCPError: On transport failure, HTTP error, or JSON-RPC error response.
        """
        key = self.server_key_for_tool(tool_name, explicit=server_key)
        url = self._resolve_server_url(key)
        req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments or {},
            },
            "id": req_id,
        }

        logger.debug(
            "MCP call → %s %s | tool=%s id=%s",
            key,
            url,
            tool_name,
            req_id,
        )

        client = await self._get_client()
        last_exc: Exception | None = None

        for attempt in range(1, self._max_retries + 2):  # 1-indexed, inclusive
            try:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()

                data = response.json()
                return self._handle_response(data, tool_name, req_id)

            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "MCP timeout (attempt %d/%d) for %s: %s",
                    attempt,
                    self._max_retries + 1,
                    tool_name,
                    exc,
                )
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                logger.warning(
                    "MCP HTTP %d (attempt %d/%d) for %s: %s",
                    exc.response.status_code,
                    attempt,
                    self._max_retries + 1,
                    tool_name,
                    exc,
                )
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning(
                    "MCP transport error (attempt %d/%d) for %s: %s",
                    attempt,
                    self._max_retries + 1,
                    tool_name,
                    exc,
                )
            except MCPError:
                # JSON-RPC errors from _handle_response are not retried
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "MCP unexpected error (attempt %d/%d) for %s: %s",
                    attempt,
                    self._max_retries + 1,
                    tool_name,
                    exc,
                )

        # All retries exhausted
        raise MCPError(
            code=-32000,
            message=f"MCP call to '{tool_name}' failed after {self._max_retries + 1} attempts",
            data=str(last_exc) if last_exc else None,
        )

    @staticmethod
    def _handle_response(data: dict[str, Any], tool_name: str, req_id: str) -> Any:
        """Validate a JSON-RPC 2.0 response and return its result.

        Raises:
            MCPError: If the response contains a ``error`` field.
        """
        # Validate JSON-RPC structure
        if not isinstance(data, dict):
            raise MCPError(
                code=-32700,
                message="Invalid JSON-RPC response: not a JSON object",
            )

        if "jsonrpc" not in data:
            raise MCPError(
                code=-32700,
                message="Invalid JSON-RPC response: missing 'jsonrpc' field",
            )

        if data.get("id") != req_id:
            logger.warning(
                "MCP response ID mismatch: sent %s, got %s",
                req_id,
                data.get("id"),
            )

        # Check for error
        if "error" in data:
            err = data["error"]
            raise MCPError(
                code=err.get("code", -32000),
                message=err.get("message", "Unknown MCP error"),
                data=err.get("data"),
            )

        # Return the result
        result = data.get("result")
        logger.debug("MCP result for %s: %s", tool_name, _truncate(repr(result), 200))
        return result

    # ------------------------------------------------------------------
    # Convenience: discover available tools on a server
    # ------------------------------------------------------------------

    async def list_tools(
        self,
        server_key: str,
        *,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Call ``tools/list`` on the specified MCP server.

        Returns:
            A list of tool descriptors (each a dict with ``name``, ``description``, etc.).
        """
        url = self._resolve_server_url(server_key)
        req_id = request_id or f"req-{uuid.uuid4().hex[:12]}"

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": req_id,
        }

        client = await self._get_client()
        response = await client.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()

        data = response.json()
        result = self._handle_response(data, f"tools/list@{server_key}", req_id)

        if isinstance(result, dict) and "tools" in result:
            return result["tools"]
        if isinstance(result, list):
            return result
        return []

    # ------------------------------------------------------------------
    # Health / connectivity check
    # ------------------------------------------------------------------

    async def ping(self, server_key: str) -> bool:
        """Check whether an MCP server is reachable.

        Returns ``True`` if the server responds (even with an error payload),
        ``False`` on transport/timeout failure.
        """
        try:
            url = self._resolve_server_url(server_key)
        except MCPError:
            return False

        client = await self._get_client()
        try:
            # Try a lightweight tools/list call
            payload = {
                "jsonrpc": "2.0",
                "method": "tools/list",
                "params": {},
                "id": f"ping-{uuid.uuid4().hex[:8]}",
            }
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
            return resp.status_code < 500
        except Exception:
            return False

    async def health_check(self) -> dict[str, bool]:
        """Ping all configured / known MCP servers and return their status.

        Returns:
            Dict mapping server_key → ``True`` (reachable) / ``False``.
        """
        results: dict[str, bool] = {}
        for server_key in _MCP_SERVER_ENV_VARS:
            results[server_key] = await self.ping(server_key)
        return results

    # ------------------------------------------------------------------
    # Registered servers introspection
    # ------------------------------------------------------------------

    @property
    def registered_servers(self) -> dict[str, str]:
        """Return a snapshot of currently known server URLs (cached + env)."""
        snapshot: dict[str, str] = dict(self._server_urls)
        for key, env_var in _MCP_SERVER_ENV_VARS.items():
            if key not in snapshot:
                val = os.getenv(env_var) if env_var else None
                if key == "context7" and val is None:
                    val = "https://mcp.context7.com/mcp"
                if val:
                    snapshot[key] = val
        return snapshot


# ------------------------------------------------------------------
# Module-level convenience
# ------------------------------------------------------------------

_default_client: MCPClient | None = None


def get_mcp_client() -> MCPClient:
    """Return a module-level singleton ``MCPClient``.

    Creates one on first call; subsequent calls return the same instance.
    Useful so multiple agents can share one client without explicit wiring.
    """
    global _default_client  # noqa: PLW0603
    if _default_client is None:
        _default_client = MCPClient()
    return _default_client


def _truncate(text: str, max_len: int) -> str:
    """Truncate *text* to *max_len* characters, appending '…' if needed."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"