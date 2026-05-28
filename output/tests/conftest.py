"""
Pytest configuration and shared fixtures for the OpenCrew test suite.

Provides:
- httpx.AsyncClient for testing agent HTTP endpoints
- Agent URL configuration from environment variables
- Test Redis connection for task queue testing
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Generator
from typing import Any

import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default ports for each agent (matching the project spec)
AGENT_DEFAULT_PORTS: dict[str, int] = {
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

#: Default base host
DEFAULT_HOST = "http://localhost"

#: Default Redis URL
DEFAULT_REDIS_URL = "redis://localhost:6379/15"  # Use DB 15 for tests


# ---------------------------------------------------------------------------
# Event loop fixture (scoped to session for performance)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create a session-scoped event loop for async tests.

    This ensures all async fixtures and tests share the same event loop
    within a test session, avoiding overhead of loop creation per test.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Agent URL fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def base_host() -> str:
    """Return the base host for agent connections.

    Reads from ``OPENCREW_BASE_HOST`` env var, defaults to ``http://localhost``.
    """
    return os.getenv("OPENCREW_BASE_HOST", DEFAULT_HOST)


@pytest.fixture(scope="session")
def agent_urls(base_host: str) -> dict[str, str]:
    """Return a mapping of agent name to full URL.

    Each URL can be overridden individually via environment variable
    ``OPENCREW_AGENT_<NAME>_URL`` (e.g., ``OPENCREW_AGENT_PO_URL``).

    Otherwise, constructs URL as ``{base_host}:{port}`` using the default
    port mapping from the project spec.
    """
    urls: dict[str, str] = {}
    for agent_name, default_port in AGENT_DEFAULT_PORTS.items():
        env_key = f"OPENCREW_AGENT_{agent_name.upper()}_URL"
        env_val = os.getenv(env_key)
        if env_val:
            urls[agent_name] = env_val.rstrip("/")
        else:
            port = int(os.getenv(f"OPENCREW_AGENT_{agent_name.upper()}_PORT", default_port))
            urls[agent_name] = f"{base_host}:{port}"
    return urls


@pytest.fixture(scope="session")
def po_url(agent_urls: dict[str, str]) -> str:
    """Product Owner agent URL."""
    return agent_urls["po"]


@pytest.fixture(scope="session")
def pm_url(agent_urls: dict[str, str]) -> str:
    """Project Manager agent URL."""
    return agent_urls["pm"]


@pytest.fixture(scope="session")
def ba_url(agent_urls: dict[str, str]) -> str:
    """Business Analyst agent URL."""
    return agent_urls["ba"]


@pytest.fixture(scope="session")
def solution_architect_url(agent_urls: dict[str, str]) -> str:
    """Solution Architect agent URL."""
    return agent_urls["solution_architect"]


@pytest.fixture(scope="session")
def frontend_dev_url(agent_urls: dict[str, str]) -> str:
    """Frontend Developer agent URL."""
    return agent_urls["frontend_dev"]


@pytest.fixture(scope="session")
def backend_dev_url(agent_urls: dict[str, str]) -> str:
    """Backend Developer agent URL."""
    return agent_urls["backend_dev"]


@pytest.fixture(scope="session")
def uiux_reviewer_url(agent_urls: dict[str, str]) -> str:
    """UIUX Reviewer agent URL."""
    return agent_urls["uiux_reviewer"]


@pytest.fixture(scope="session")
def security_reviewer_url(agent_urls: dict[str, str]) -> str:
    """Security Reviewer agent URL."""
    return agent_urls["security_reviewer"]


@pytest.fixture(scope="session")
def qa_url(agent_urls: dict[str, str]) -> str:
    """QA / Tester agent URL."""
    return agent_urls["qa"]


@pytest.fixture(scope="session")
def devops_url(agent_urls: dict[str, str]) -> str:
    """DevOps / SRE agent URL."""
    return agent_urls["devops"]


@pytest.fixture(scope="session")
def techlead_url(agent_urls: dict[str, str]) -> str:
    """TechLead agent URL."""
    return agent_urls["techlead"]


# ---------------------------------------------------------------------------
# HTTP client fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Session-scoped async HTTP client for general API testing.

    Uses a longer timeout (30s) to accommodate agent processing time.
    Does not follow redirects by default so tests can inspect redirect
    responses explicitly.
    """
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers={"Content-Type": "application/json"},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def agent_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Per-test async HTTP client with shorter timeout for unit tests.

    Use this for tests that should complete quickly without waiting
    for full agent processing.
    """
    timeout = httpx.Timeout(10.0, connect=5.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers={"Content-Type": "application/json"},
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def a2a_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Session-scoped async HTTP client configured for A2A protocol calls.

    Pre-configured with the A2A protocol headers and a generous timeout
    for inter-agent communication tests.
    """
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        headers={
            "Content-Type": "application/json",
            "X-Protocol": "a2a/1.0",
        },
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Redis fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def redis_url() -> str:
    """Return the Redis URL for testing.

    Reads from ``REDIS_URL`` env var, defaults to ``redis://localhost:6379/15``
    (DB 15 to avoid colliding with production data).
    """
    return os.getenv("TEST_REDIS_URL", DEFAULT_REDIS_URL)


@pytest_asyncio.fixture(scope="session")
async def redis_client(redis_url: str) -> AsyncGenerator[aioredis.Redis, None]:
    """Session-scoped async Redis client for task queue testing.

    Connects to the test Redis instance and flushes DB 15 on setup
    to ensure a clean state.  Disconnects cleanly on teardown.
    """
    client = aioredis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    try:
        # Verify connection is alive
        await client.ping()
        # Flush test DB to start clean
        await client.flushdb()
        yield client
    except aioredis.ConnectionError:
        pytest.skip("Redis is not available — skipping Redis-dependent tests")
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def clean_redis(redis_client: aioredis.Redis) -> AsyncGenerator[aioredis.Redis, None]:
    """Per-test Redis client that flushes the DB before each test.

    Use this when tests need a guaranteed clean Redis state.
    """
    await redis_client.flushdb()
    yield redis_client


# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def sample_a2a_message() -> dict[str, Any]:
    """Return a valid A2A protocol message for testing.

    Conforms to the ``a2a/1.0`` message schema defined in the project spec.
    """
    return {
        "protocol": "a2a/1.0",
        "type": "task",
        "from": "test-sender",
        "to": "test-receiver",
        "task_id": "00000000-0000-0000-0000-000000000001",
        "round": 1,
        "payload": {
            "claim": "Test task for integration testing",
            "evidence": "test/conftest.py:sample_a2a_message",
            "suggestion": "Process this test task",
            "artifacts": [],
        },
        "timestamp": "2026-01-01T00:00:00Z",
    }


@pytest.fixture(scope="session")
def sample_agent_card() -> dict[str, Any]:
    """Return a valid agent card payload for testing.

    Conforms to the ``/.well-known/agent.json`` schema.
    """
    return {
        "name": "test-agent",
        "display_name": "Test Agent",
        "url": "http://localhost:9999",
        "version": "1.0.0",
        "capabilities": ["test_capability"],
        "input_types": ["task"],
        "output_types": ["result"],
        "protocol": "a2a/1.0",
    }


@pytest_asyncio.fixture
async def wait_for_agent(async_client: httpx.AsyncClient, agent_urls: dict[str, str]):
    """Return an async helper that waits for an agent to become healthy.

    Usage::

        async def test_something(wait_for_agent):
            await wait_for_agent("backend_dev")
            # Agent is now healthy — proceed with test
    """

    async def _wait(
        agent_name: str,
        max_retries: int = 10,
        delay: float = 1.0,
    ) -> bool:
        """Poll ``/health`` endpoint until the agent responds 200.

        Args:
            agent_name: Key in ``agent_urls`` (e.g. ``"backend_dev"``).
            max_retries: Maximum number of health check attempts.
            delay: Seconds to wait between retries.

        Returns:
            ``True`` if agent became healthy, ``False`` if retries exhausted.
        """
        url = agent_urls.get(agent_name)
        if url is None:
            raise ValueError(f"Unknown agent name: {agent_name}")

        for attempt in range(max_retries):
            try:
                resp = await async_client.get(f"{url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "ok":
                        return True
            except (httpx.ConnectError, httpx.ReadTimeout):
                pass

            if attempt < max_retries - 1:
                await asyncio.sleep(delay)

        return False

    return _wait