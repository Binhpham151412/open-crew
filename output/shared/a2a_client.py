"""
A2A Client — Agent-to-Agent message pushing for OpenCrew.

Provides async HTTP POST to target agent's /a2a endpoint with retry
and exponential backoff using httpx.AsyncClient.

Usage:
    from shared.a2a_client import push

    await push(to_agent="backend-dev", message={
        "protocol": "a2a/1.0",
        "type": "task",
        "from": "ba",
        "to": "backend-dev",
        "task_id": "550e8400-e29b-41d4-a716-446655440000",
        "round": 1,
        "payload": {
            "claim": "Implement user registration endpoint",
            "evidence": "api_spec.yaml line 1-50",
            "suggestion": "Follow OpenAPI spec",
            "artifacts": []
        },
        "timestamp": "2026-05-27T10:00:00Z"
    })
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import httpx
import structlog

# ---------------------------------------------------------------------------
# Configuration (env-overridable defaults)
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = float(os.getenv("A2A_TIMEOUT", "30.0"))
DEFAULT_MAX_RETRIES = int(os.getenv("A2A_MAX_RETRIES", "3"))
DEFAULT_BASE_DELAY = float(os.getenv("A2A_BASE_DELAY", "1.0"))
DEFAULT_MAX_DELAY = float(os.getenv("A2A_MAX_DELAY", "30.0"))
DEFAULT_PROTOCOL = "a2a/1.0"

# Pre-registered agent URL mapping.  The registry (shared/registry.py) may
# update this at runtime; for bootstrap we allow env-based overrides keyed
# as A2A_URL_<AGENT_NAME>.
_AGENT_URLS: dict[str, str] = {}


def _build_default_urls() -> dict[str, str]:
    """Build default agent URL table from environment or localhost convention."""
    agents = {
        "po": 8000,
        "pm": 8001,
        "ba": 8002,
        "solution_architect": 8003,
        "frontend_dev": 8004,
        "backend_dev": 8005,
        "uiux_reviewer": 8006,
        "security_reviewer": 8007,
        "qa": 8008,
        "devops": 8009,
        "techlead": 8010,
    }
    base_host = os.getenv("A2A_HOST", "localhost")
    urls: dict[str, str] = {}
    for name, port in agents.items():
        env_key = f"A2A_URL_{name.upper()}"
        urls[name] = os.getenv(env_key, f"http://{base_host}:{port}")
    return urls


# Lazy initialisation
_URL_CACHE: dict[str, str] | None = None


def _resolve_base_url(to_agent: str) -> str:
    """Return the base URL for *to_agent*.

    Resolution order:
    1. Runtime-registered URL (_AGENT_URLS)
    2. Environment variable  A2A_URL_<AGENT_NAME>
    3. Default localhost:<port> convention
    """
    global _URL_CACHE
    if _URL_CACHE is None:
        _URL_CACHE = _build_default_urls()

    # Runtime override takes priority
    if to_agent in _AGENT_URLS:
        return _AGENT_URLS[to_agent]

    if to_agent in _URL_CACHE:
        return _URL_CACHE[to_agent]

    # Last resort: assume same host with agent name as subdomain
    raise ValueError(
        f"Unknown agent '{to_agent}'. Register it via register_agent() or "
        f"set environment variable A2A_URL_{to_agent.upper()}."
    )


def register_agent(name: str, base_url: str) -> None:
    """Register or update an agent's base URL at runtime.

    Called by the registry module after auto-discovering new agents via
    ``/.well-known/agent.json``.
    """
    _AGENT_URLS[name] = base_url.rstrip("/")


# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------

logger = structlog.get_logger("a2a_client")


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def build_message(
    *,
    msg_type: Literal[
        "task", "challenge", "response", "final_position",
        "escalate", "decision", "result",
    ],
    from_agent: str,
    to_agent: str,
    payload: dict[str, Any],
    task_id: str | None = None,
    round: int = 1,
    protocol: str = DEFAULT_PROTOCOL,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Construct a valid A2A message dict.

    This helper ensures every required field is present and properly
    formatted before a message leaves an agent.
    """
    return {
        "protocol": protocol,
        "type": msg_type,
        "from": from_agent,
        "to": to_agent,
        "task_id": task_id or str(uuid.uuid4()),
        "round": round,
        "payload": payload,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Core push function
# ---------------------------------------------------------------------------

async def push(
    to_agent: str,
    message: dict[str, Any],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    timeout: float = DEFAULT_TIMEOUT,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Send an A2A message to *to_agent*'s ``/a2a`` endpoint.

    Parameters
    ----------
    to_agent:
        Registry name of the target agent (e.g. ``"backend-dev"``).
    message:
        The A2A message payload (must conform to A2A/1.0 schema).
    max_retries:
        Maximum number of retry attempts after the initial request.
    base_delay:
        Initial backoff delay in seconds (doubled each retry).
    max_delay:
        Cap for the exponential backoff delay.
    timeout:
        Per-request timeout in seconds.
    client:
        Optional pre-existing ``httpx.AsyncClient``.  If ``None`` a new
        client is created for this call.

    Returns
    -------
    dict
        The JSON response body from the target agent.

    Raises
    ------
    httpx.HTTPStatusError
        If the target agent responds with 4xx/5xx after all retries.
    httpx.ConnectError
        If the target agent is unreachable after all retries.
    ValueError
        If *to_agent* is not registered.
    """
    base_url = _resolve_base_url(to_agent)
    url = f"{base_url}/a2a"

    task_id = message.get("task_id", "unknown")
    msg_type = message.get("type", "unknown")

    logger.info(
        "a2a_push_start",
        to=to_agent,
        url=url,
        task_id=task_id,
        msg_type=msg_type,
        round=message.get("round", 1),
    )

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    last_exc: Exception | None = None
    attempt = 0

    try:
        for attempt in range(max_retries + 1):
            t0 = time.monotonic()
            try:
                response = await client.post(
                    url,
                    json=message,
                    headers={
                        "Content-Type": "application/json",
                        "X-A2A-Protocol": DEFAULT_PROTOCOL,
                        "X-A2A-From": message.get("from", ""),
                        "X-A2A-Task-ID": task_id,
                    },
                )
                elapsed_ms = (time.monotonic() - t0) * 1000

                # Raise for 4xx / 5xx — will be caught below
                response.raise_for_status()

                result = response.json()

                logger.info(
                    "a2a_push_success",
                    to=to_agent,
                    task_id=task_id,
                    status_code=response.status_code,
                    elapsed_ms=round(elapsed_ms, 2),
                    attempt=attempt,
                )
                return result

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                elapsed_ms = (time.monotonic() - t0) * 1000
                last_exc = exc
                logger.warning(
                    "a2a_push_retry",
                    to=to_agent,
                    task_id=task_id,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(exc),
                    elapsed_ms=round(elapsed_ms, 2),
                )

            except httpx.HTTPStatusError as exc:
                elapsed_ms = (time.monotonic() - t0) * 1000
                status = exc.response.status_code

                # Retry on 5xx and 429 (rate limit); do NOT retry on other 4xx
                if status >= 500 or status == 429:
                    last_exc = exc
                    logger.warning(
                        "a2a_push_retry_status",
                        to=to_agent,
                        task_id=task_id,
                        status_code=status,
                        attempt=attempt,
                        max_retries=max_retries,
                        elapsed_ms=round(elapsed_ms, 2),
                    )
                else:
                    logger.error(
                        "a2a_push_client_error",
                        to=to_agent,
                        task_id=task_id,
                        status_code=status,
                        body=exc.response.text,
                        elapsed_ms=round(elapsed_ms, 2),
                    )
                    raise

            # Exponential backoff with jitter
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                # Add ±25% jitter to avoid thundering herd
                import random
                jitter = delay * 0.25 * (2 * random.random() - 1)
                actual_delay = max(0.0, delay + jitter)
                logger.debug(
                    "a2a_push_backoff",
                    to=to_agent,
                    task_id=task_id,
                    delay_s=round(actual_delay, 3),
                    attempt=attempt,
                )
                await asyncio.sleep(actual_delay)

        # All retries exhausted
        logger.error(
            "a2a_push_failed",
            to=to_agent,
            task_id=task_id,
            attempts=attempt + 1,
            error=str(last_exc),
        )
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(
            f"A2A push to '{to_agent}' failed after {max_retries + 1} attempts"
        )

    finally:
        if owns_client:
            await client.aclose()


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

async def push_task(
    to_agent: str,
    from_agent: str,
    payload: dict[str, Any],
    *,
    task_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Push a ``task`` type message (most common use case)."""
    message = build_message(
        msg_type="task",
        from_agent=from_agent,
        to_agent=to_agent,
        payload=payload,
        task_id=task_id,
    )
    return await push(to_agent, message, **kwargs)


async def push_challenge(
    to_agent: str,
    from_agent: str,
    payload: dict[str, Any],
    *,
    task_id: str,
    round: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """Push a ``challenge`` message (debate round 1)."""
    message = build_message(
        msg_type="challenge",
        from_agent=from_agent,
        to_agent=to_agent,
        payload=payload,
        task_id=task_id,
        round=round,
    )
    return await push(to_agent, message, **kwargs)


async def push_response(
    to_agent: str,
    from_agent: str,
    payload: dict[str, Any],
    *,
    task_id: str,
    round: int = 2,
    **kwargs: Any,
) -> dict[str, Any]:
    """Push a ``response`` message (debate round 2)."""
    message = build_message(
        msg_type="response",
        from_agent=from_agent,
        to_agent=to_agent,
        payload=payload,
        task_id=task_id,
        round=round,
    )
    return await push(to_agent, message, **kwargs)


async def push_escalate(
    to_agent: str,
    from_agent: str,
    payload: dict[str, Any],
    *,
    task_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Push an ``escalate`` message to TechLead after debate deadlock."""
    message = build_message(
        msg_type="escalate",
        from_agent=from_agent,
        to_agent=to_agent,
        payload=payload,
        task_id=task_id,
        round=3,
    )
    return await push(to_agent, message, **kwargs)


async def push_decision(
    to_agent: str,
    from_agent: str,
    payload: dict[str, Any],
    *,
    task_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Push a ``decision`` message (TechLead final arbitration)."""
    message = build_message(
        msg_type="decision",
        from_agent=from_agent,
        to_agent=to_agent,
        payload=payload,
        task_id=task_id,
    )
    return await push(to_agent, message, **kwargs)


async def push_result(
    to_agent: str,
    from_agent: str,
    payload: dict[str, Any],
    *,
    task_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Push a ``result`` message (final output delivery)."""
    message = build_message(
        msg_type="result",
        from_agent=from_agent,
        to_agent=to_agent,
        payload=payload,
        task_id=task_id,
    )
    return await push(to_agent, message, **kwargs)


# ---------------------------------------------------------------------------
# Connection pooling singleton
# ---------------------------------------------------------------------------

_global_client: httpx.AsyncClient | None = None


async def get_global_client() -> httpx.AsyncClient:
    """Return (and lazily create) a shared ``httpx.AsyncClient``.

    Agents that process many messages should use this to benefit from
    connection pooling.  Remember to call ``close_global_client()`` on
    shutdown.
    """
    global _global_client
    if _global_client is None or _global_client.is_closed:
        _global_client = httpx.AsyncClient(
            timeout=httpx.Timeout(DEFAULT_TIMEOUT),
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30,
            ),
        )
    return _global_client


async def close_global_client() -> None:
    """Gracefully close the shared HTTP client."""
    global _global_client
    if _global_client is not None and not _global_client.is_closed:
        await _global_client.aclose()
        _global_client = None


async def push_pooled(
    to_agent: str,
    message: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """Push via the shared pooled client.

    Identical to ``push()`` but uses the global connection pool instead
    of creating a one-off client.
    """
    client = await get_global_client()
    return await push(to_agent, message, client=client, **kwargs)