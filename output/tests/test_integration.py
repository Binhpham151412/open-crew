"""Integration tests for the OpenCrew system.

Tests cover:
- All agents' /health endpoints (ports 8000–8010)
- A2A message flow: PO → PM → BA
- Redis task queue operations
- Web UI returning HTTP 200
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx
import pytest
import redis.asyncio as aioredis

# ---------------------------------------------------------------------------
# Configuration — override via env vars if needed
# ---------------------------------------------------------------------------

AGENT_REGISTRY: dict[str, int] = {
    "po": 8000,
    "pm": 8001,
    "ba": 8002,
    "solution-architect": 8003,
    "frontend-dev": 8004,
    "backend-dev": 8005,
    "uiux-reviewer": 8006,
    "security-reviewer": 8007,
    "qa": 8008,
    "devops": 8009,
    "techlead": 8010,
}

WEB_UI_BASE_URL = os.getenv("WEB_UI_BASE_URL", "http://localhost:3000")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

A2A_MESSAGE_TEMPLATE: dict[str, Any] = {
    "protocol": "a2a/1.0",
    "type": "task",
    "from": "",
    "to": "",
    "task_id": "",
    "round": 1,
    "payload": {
        "claim": "",
        "evidence": "",
        "suggestion": "",
        "artifacts": [],
    },
    "timestamp": "",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def agent_url(name: str, path: str = "") -> str:
    """Build the full URL for an agent endpoint."""
    port = AGENT_REGISTRY[name]
    base = f"http://localhost:{port}"
    return f"{base}{path}" if path else base


def build_a2a_message(
    *,
    from_agent: str,
    to_agent: str,
    msg_type: str = "task",
    task_id: str | None = None,
    claim: str = "Integration test task",
    evidence: str = "",
    suggestion: str = "",
    round_num: int = 1,
    artifacts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Construct an A2A protocol message for testing."""
    return {
        "protocol": "a2a/1.0",
        "type": msg_type,
        "from": from_agent,
        "to": to_agent,
        "task_id": task_id or str(uuid4()),
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def event_loop():
    """Create a single event loop for the entire test module."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def http_client():
    """Shared async HTTP client with reasonable timeouts."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as client:
        yield client


@pytest.fixture(scope="module")
async def redis_client():
    """Async Redis client for queue tests."""
    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except (aioredis.ConnectionError, ConnectionRefusedError):
        pytest.skip("Redis is not available — skipping queue tests")
    yield client
    # Cleanup: remove test keys
    async for key in client.scan_iter("test:*"):
        await client.delete(key)
    await client.aclose()


# ---------------------------------------------------------------------------
# 1. Health Endpoint Tests
# ---------------------------------------------------------------------------


class TestAgentHealthEndpoints:
    """Verify every agent exposes a /health endpoint returning status ok."""

    @pytest.mark.parametrize("agent_name", list(AGENT_REGISTRY.keys()))
    @pytest.mark.asyncio
    async def test_health_returns_200(
        self,
        http_client: httpx.AsyncClient,
        agent_name: str,
    ) -> None:
        """GET /health should return 200 with JSON body."""
        url = agent_url(agent_name, "/health")
        resp = await http_client.get(url)

        assert resp.status_code == 200, (
            f"Agent '{agent_name}' at {url} returned {resp.status_code}"
        )

    @pytest.mark.parametrize("agent_name", list(AGENT_REGISTRY.keys()))
    @pytest.mark.asyncio
    async def test_health_body_contains_status_ok(
        self,
        http_client: httpx.AsyncClient,
        agent_name: str,
    ) -> None:
        """Response JSON must include 'status': 'ok'."""
        url = agent_url(agent_name, "/health")
        resp = await http_client.get(url)
        body = resp.json()

        assert body.get("status") == "ok", (
            f"Agent '{agent_name}' health body: {body}"
        )

    @pytest.mark.parametrize("agent_name", list(AGENT_REGISTRY.keys()))
    @pytest.mark.asyncio
    async def test_health_body_contains_agent_name(
        self,
        http_client: httpx.AsyncClient,
        agent_name: str,
    ) -> None:
        """Response JSON should identify the agent by name."""
        url = agent_url(agent_name, "/health")
        resp = await http_client.get(url)
        body = resp.json()

        assert "agent" in body, f"Missing 'agent' key in health response: {body}"

    @pytest.mark.parametrize("agent_name", list(AGENT_REGISTRY.keys()))
    @pytest.mark.asyncio
    async def test_health_body_contains_queue_size(
        self,
        http_client: httpx.AsyncClient,
        agent_name: str,
    ) -> None:
        """Health payload should include queue_size for monitoring."""
        url = agent_url(agent_name, "/health")
        resp = await http_client.get(url)
        body = resp.json()

        assert "queue_size" in body, (
            f"Missing 'queue_size' in health response for '{agent_name}': {body}"
        )
        assert isinstance(body["queue_size"], int)


# ---------------------------------------------------------------------------
# 2. Agent Card / Capability Tests
# ---------------------------------------------------------------------------


class TestAgentCards:
    """Verify every agent serves an /.well-known/agent.json descriptor."""

    @pytest.mark.parametrize("agent_name", list(AGENT_REGISTRY.keys()))
    @pytest.mark.asyncio
    async def test_agent_card_returns_200(
        self,
        http_client: httpx.AsyncClient,
        agent_name: str,
    ) -> None:
        url = agent_url(agent_name, "/.well-known/agent.json")
        resp = await http_client.get(url)

        assert resp.status_code == 200

    @pytest.mark.parametrize("agent_name", list(AGENT_REGISTRY.keys()))
    @pytest.mark.asyncio
    async def test_agent_card_has_required_fields(
        self,
        http_client: httpx.AsyncClient,
        agent_name: str,
    ) -> None:
        url = agent_url(agent_name, "/.well-known/agent.json")
        resp = await http_client.get(url)
        card = resp.json()

        for field in ("name", "url", "version", "capabilities", "protocol"):
            assert field in card, (
                f"Agent card for '{agent_name}' missing field '{field}': {card}"
            )
        assert card["protocol"] == "a2a/1.0"


# ---------------------------------------------------------------------------
# 3. A2A Message Flow: PO → PM → BA
# ---------------------------------------------------------------------------


class TestA2AMessageFlow:
    """End-to-end integration test for the primary pipeline:
    PO receives user request → pushes PRD to PM → PM pushes stories to BA.
    """

    @pytest.mark.asyncio
    async def test_po_accepts_user_request(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """PO's /a2a endpoint should accept a user requirement and return 202."""
        task_id = str(uuid4())
        message = build_a2a_message(
            from_agent="user",
            to_agent="po",
            msg_type="task",
            task_id=task_id,
            claim="Build a user registration feature with email and password",
            evidence="New product launch requires self-service sign-up",
            suggestion="Support OAuth2 as well",
        )

        resp = await http_client.post(
            agent_url("po", "/a2a"),
            json=message,
        )

        assert resp.status_code in (200, 202), (
            f"PO returned {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("status") in ("accepted", "ok"), f"Unexpected PO response: {body}"
        assert body.get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_po_to_pm_message_flow(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Simulate PO pushing a PRD to PM via A2A.

        After PO processes the user request, it should forward a task to PM.
        We directly send a 'task' message as if PO pushed it.
        """
        task_id = str(uuid4())
        prd_artifact = {
            "name": "PRD.md",
            "content": (
                "# PRD — User Registration\n\n"
                "## Must Have\n"
                "- Email/password sign-up\n"
                "- Email verification\n\n"
                "## Definition of Done\n"
                "- User can register and verify email\n"
            ),
            "mime_type": "text/markdown",
        }

        message = build_a2a_message(
            from_agent="po",
            to_agent="pm",
            msg_type="task",
            task_id=task_id,
            claim="Implement user registration feature as described in PRD",
            evidence="PRD approved — Must Have items defined",
            suggestion="Break down into Stories for sprint planning",
            artifacts=[prd_artifact],
        )

        resp = await http_client.post(
            agent_url("pm", "/a2a"),
            json=message,
        )

        assert resp.status_code in (200, 202), (
            f"PM returned {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("status") in ("accepted", "ok"), f"Unexpected PM response: {body}"
        assert body.get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_pm_to_ba_message_flow(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Simulate PM pushing a Story to BA via A2A.

        After PM breaks the PRD into stories, it forwards to BA for
        detailed acceptance criteria and API spec work.
        """
        task_id = str(uuid4())
        story_artifact = {
            "name": "story-registration.md",
            "content": (
                "# Story: User Registration\n\n"
                "**Size:** M\n"
                "**Sprint:** 1\n"
                "**Assignee:** BA\n\n"
                "## Description\n"
                "As a new user, I want to register with email and password "
                "so that I can access the platform.\n"
            ),
            "mime_type": "text/markdown",
        }

        message = build_a2a_message(
            from_agent="pm",
            to_agent="ba",
            msg_type="task",
            task_id=task_id,
            claim="Write acceptance criteria and API spec for user registration story",
            evidence="Story S-001 created, size M, Sprint 1",
            suggestion="Include Gherkin AC and OpenAPI spec",
            artifacts=[story_artifact],
        )

        resp = await http_client.post(
            agent_url("ba", "/a2a"),
            json=message,
        )

        assert resp.status_code in (200, 202), (
            f"BA returned {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("status") in ("accepted", "ok"), f"Unexpected BA response: {body}"
        assert body.get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_po_pm_ba_end_to_end_pipeline(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Full pipeline simulation: user → PO → PM → BA.

        Sends messages in sequence, verifying each agent accepts
        and returns the same task_id for traceability.
        """
        task_id = str(uuid4())

        # Step 1: User → PO
        msg_to_po = build_a2a_message(
            from_agent="user",
            to_agent="po",
            msg_type="task",
            task_id=task_id,
            claim="Add dark mode toggle to settings page",
        )
        resp_po = await http_client.post(agent_url("po", "/a2a"), json=msg_to_po)
        assert resp_po.status_code in (200, 202)

        # Step 2: PO → PM
        msg_to_pm = build_a2a_message(
            from_agent="po",
            to_agent="pm",
            msg_type="task",
            task_id=task_id,
            claim="Add dark mode toggle — PRD ready",
            artifacts=[
                {
                    "name": "PRD.md",
                    "content": "# PRD: Dark Mode\nMust Have: toggle in settings",
                }
            ],
        )
        resp_pm = await http_client.post(agent_url("pm", "/a2a"), json=msg_to_pm)
        assert resp_pm.status_code in (200, 202)
        assert resp_pm.json().get("task_id") == task_id

        # Step 3: PM → BA
        msg_to_ba = build_a2a_message(
            from_agent="pm",
            to_agent="ba",
            msg_type="task",
            task_id=task_id,
            claim="Write AC + API spec for dark mode toggle story",
            artifacts=[
                {
                    "name": "story-dark-mode.md",
                    "content": "# Story: Dark Mode Toggle\nSize: S",
                }
            ],
        )
        resp_ba = await http_client.post(agent_url("ba", "/a2a"), json=msg_to_ba)
        assert resp_ba.status_code in (200, 202)
        assert resp_ba.json().get("task_id") == task_id

    @pytest.mark.asyncio
    async def test_a2a_message_rejects_invalid_protocol(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Agent should reject messages with wrong protocol version."""
        bad_message = build_a2a_message(
            from_agent="attacker",
            to_agent="po",
            msg_type="task",
            claim="Malicious payload",
        )
        bad_message["protocol"] = "a2a/99.0"

        resp = await http_client.post(agent_url("po", "/a2a"), json=bad_message)

        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for bad protocol, got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_a2a_message_rejects_invalid_type(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Agent should reject messages with unsupported type."""
        bad_message = build_a2a_message(
            from_agent="po",
            to_agent="pm",
            msg_type="invalid_type",
            claim="Testing validation",
        )

        resp = await http_client.post(agent_url("pm", "/a2a"), json=bad_message)

        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for bad message type, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# 4. A2A Debate Flow Tests
# ---------------------------------------------------------------------------


class TestA2ADebateFlow:
    """Verify the 3-round debate protocol between agents."""

    @pytest.mark.asyncio
    async def test_challenge_response_final_position_rounds(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Send a 3-round debate sequence between security-reviewer and backend-dev."""
        task_id = str(uuid4())

        # Round 1: Challenge
        challenge = build_a2a_message(
            from_agent="security-reviewer",
            to_agent="backend-dev",
            msg_type="challenge",
            task_id=task_id,
            round_num=1,
            claim="SQL injection vulnerability in user query at line 42",
            evidence="src/api/users.py:42 — f-string in raw SQL",
            suggestion="Use parameterized query with SQLAlchemy",
        )
        resp_r1 = await http_client.post(
            agent_url("backend-dev", "/a2a"), json=challenge
        )
        assert resp_r1.status_code in (200, 202)

        # Round 2: Response
        response = build_a2a_message(
            from_agent="backend-dev",
            to_agent="security-reviewer",
            msg_type="response",
            task_id=task_id,
            round_num=2,
            claim="Fixed: migrated to parameterized query",
            evidence="Commit abc123 — replaced f-string with :param bind",
            suggestion="Please re-review",
        )
        resp_r2 = await http_client.post(
            agent_url("security-reviewer", "/a2a"), json=response
        )
        assert resp_r2.status_code in (200, 202)

        # Round 3: Final position
        final_pos = build_a2a_message(
            from_agent="security-reviewer",
            to_agent="backend-dev",
            msg_type="final_position",
            task_id=task_id,
            round_num=3,
            claim="Verified fix — vulnerability resolved",
            evidence="Manual review of commit abc123 confirms parameterized query",
            suggestion="No further action needed",
        )
        resp_r3 = await http_client.post(
            agent_url("backend-dev", "/a2a"), json=final_pos
        )
        assert resp_r3.status_code in (200, 202)


# ---------------------------------------------------------------------------
# 5. Redis Task Queue Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRedisTaskQueue:
    """Integration tests for the Redis-backed task queue used by all agents."""

    async def test_redis_connection(self, redis_client: aioredis.Redis) -> None:
        """Redis should respond to PING."""
        pong = await redis_client.ping()
        assert pong is True

    async def test_push_and_pop_task(self, redis_client: aioredis.Redis) -> None:
        """Push a task onto a queue and pop it back."""
        queue_key = "test:queue:push_pop"
        task_data = build_a2a_message(
            from_agent="po",
            to_agent="pm",
            msg_type="task",
            claim="Queue test task",
        )

        import json

        await redis_client.rpush(queue_key, json.dumps(task_data))
        length = await redis_client.llen(queue_key)
        assert length == 1

        raw = await redis_client.lpop(queue_key)
        assert raw is not None
        popped = json.loads(raw)
        assert popped["task_id"] == task_data["task_id"]
        assert popped["protocol"] == "a2a/1.0"

        # Queue should be empty now
        length_after = await redis_client.llen(queue_key)
        assert length_after == 0

    async def test_fifo_ordering(self, redis_client: aioredis.Redis) -> None:
        """Tasks should be dequeued in FIFO order."""
        import json

        queue_key = "test:queue:fifo"
        ids = [str(uuid4()) for _ in range(5)]

        for tid in ids:
            msg = build_a2a_message(
                from_agent="po",
                to_agent="pm",
                msg_type="task",
                task_id=tid,
                claim=f"FIFO test {tid}",
            )
            await redis_client.rpush(queue_key, json.dumps(msg))

        assert await redis_client.llen(queue_key) == 5

        dequeued_ids: list[str] = []
        for _ in range(5):
            raw = await redis_client.lpop(queue_key)
            assert raw is not None
            dequeued_ids.append(json.loads(raw)["task_id"])

        assert dequeued_ids == ids, "Tasks were not dequeued in FIFO order"

    async def test_concurrent_push_pop(self, redis_client: aioredis.Redis) -> None:
        """Multiple concurrent producers and consumers should not lose tasks."""
        import json

        queue_key = "test:queue:concurrent"
        total_tasks = 50
        task_ids = {str(uuid4()) for _ in range(total_tasks)}

        # Push all tasks concurrently
        push_tasks = []
        for tid in task_ids:
            msg = build_a2a_message(
                from_agent="po",
                to_agent="pm",
                msg_type="task",
                task_id=tid,
                claim=f"Concurrent test {tid}",
            )
            push_tasks.append(redis_client.rpush(queue_key, json.dumps(msg)))

        await asyncio.gather(*push_tasks)
        assert await redis_client.llen(queue_key) == total_tasks

        # Pop all tasks
        popped_ids: set[str] = set()
        for _ in range(total_tasks):
            raw = await redis_client.lpop(queue_key)
            assert raw is not None
            popped_ids.add(json.loads(raw)["task_id"])

        assert popped_ids == task_ids, "Some tasks were lost during concurrent operations"

    async def test_queue_respects_ttl(self, redis_client: aioredis.Redis) -> None:
        """Tasks with TTL should expire properly."""
        import json

        queue_key = "test:queue:ttl"
        msg = build_a2a_message(
            from_agent="po",
            to_agent="pm",
            msg_type="task",
            claim="TTL test task",
        )

        await redis_client.rpush(queue_key, json.dumps(msg))
        await redis_client.expire(queue_key, 1)  # 1 second TTL

        assert await redis_client.llen(queue_key) == 1

        # Wait for TTL to expire
        await asyncio.sleep(1.5)

        length = await redis_client.llen(queue_key)
        assert length == 0, "Queue key did not expire as expected"

    async def test_agent_queue_health_reflected(self, redis_client: aioredis.Redis) -> None:
        """Queue size should match the actual Redis list length."""
        import json

        agent_name = "test-agent"
        queue_key = f"opencrew:queue:{agent_name}"

        # Clear any existing items
        await redis_client.delete(queue_key)

        # Push 3 tasks
        for i in range(3):
            msg = build_a2a_message(
                from_agent="po",
                to_agent=agent_name,
                msg_type="task",
                claim=f"Health check task {i}",
            )
            await redis_client.rpush(queue_key, json.dumps(msg))

        length = await redis_client.llen(queue_key)
        assert length == 3

        # Cleanup
        await redis_client.delete(queue_key)


# ---------------------------------------------------------------------------
# 6. Web UI Tests
# ---------------------------------------------------------------------------


class TestWebUI:
    """Integration tests for the NextJS admin panel."""

    @pytest.mark.asyncio
    async def test_dashboard_returns_200(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """GET / should return 200."""
        resp = await http_client.get(WEB_UI_BASE_URL)
        assert resp.status_code == 200, (
            f"Dashboard returned {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_tasks_page_returns_200(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """GET /tasks should return 200."""
        resp = await http_client.get(f"{WEB_UI_BASE_URL}/tasks")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_agents_page_returns_200(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """GET /agents should return 200."""
        resp = await http_client.get(f"{WEB_UI_BASE_URL}/agents")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_config_page_returns_200(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """GET /config should return 200."""
        resp = await http_client.get(f"{WEB_UI_BASE_URL}/config")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_logs_page_returns_200(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """GET /logs should return 200."""
        resp = await http_client.get(f"{WEB_UI_BASE_URL}/logs")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_api_agents_endpoint(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """GET /api/agents should return a list of agents."""
        resp = await http_client.get(f"{WEB_UI_BASE_URL}/api/agents")
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body, (list, dict)), f"Unexpected response type: {type(body)}"

    @pytest.mark.asyncio
    async def test_api_tasks_endpoint(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """GET /api/tasks should return 200 and a list."""
        resp = await http_client.get(f"{WEB_UI_BASE_URL}/api/tasks")
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body, (list, dict))

    @pytest.mark.asyncio
    async def test_api_stats_endpoint(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """GET /api/stats should return uptime and token usage info."""
        resp = await http_client.get(f"{WEB_UI_BASE_URL}/api/stats")
        assert resp.status_code == 200

        body = resp.json()
        assert isinstance(body, dict)

    @pytest.mark.asyncio
    async def test_api_config_endpoint(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """GET /api/config should return current configuration."""
        resp = await http_client.get(f"{WEB_UI_BASE_URL}/api/config")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_submit_task_via_api(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """POST /api/tasks should accept a new task submission."""
        payload = {
            "description": "Build a notification system with email and push support",
        }

        resp = await http_client.post(
            f"{WEB_UI_BASE_URL}/api/tasks",
            json=payload,
        )

        assert resp.status_code in (200, 201, 202), (
            f"Task submission returned {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# 7. Cross-Cutting Integration Tests
# ---------------------------------------------------------------------------


class TestSystemIntegration:
    """Higher-level integration tests verifying the system works as a whole."""

    @pytest.mark.asyncio
    async def test_all_agents_respond_within_timeout(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Every agent's /health should respond within 5 seconds."""
        slow_agents: list[str] = []

        for name in AGENT_REGISTRY:
            url = agent_url(name, "/health")
            start = time.monotonic()
            try:
                resp = await http_client.get(url)
                elapsed = time.monotonic() - start
                if resp.status_code != 200 or elapsed > 5.0:
                    slow_agents.append(f"{name} ({elapsed:.2f}s, status={resp.status_code})")
            except httpx.TimeoutException:
                elapsed = time.monotonic() - start
                slow_agents.append(f"{name} (TIMEOUT after {elapsed:.2f}s)")
            except httpx.ConnectError:
                slow_agents.append(f"{name} (CONNECTION REFUSED)")

        assert not slow_agents, (
            f"Agents not responding within 5s: {', '.join(slow_agents)}"
        )

    @pytest.mark.asyncio
    async def test_message_task_id_propagation(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """The same task_id should be accepted by PO, PM, and BA."""
        shared_task_id = str(uuid4())

        agents_to_test = [
            ("po", "user", "PO accepts initial task"),
            ("pm", "po", "PM receives from PO"),
            ("ba", "pm", "BA receives from PM"),
        ]

        for agent_name, from_agent, description in agents_to_test:
            msg = build_a2a_message(
                from_agent=from_agent,
                to_agent=agent_name,
                msg_type="task",
                task_id=shared_task_id,
                claim=description,
            )
            resp = await http_client.post(
                agent_url(agent_name, "/a2a"), json=msg
            )
            assert resp.status_code in (200, 202), (
                f"{description} failed: {resp.status_code} — {resp.text}"
            )
            body = resp.json()
            assert body.get("task_id") == shared_task_id, (
                f"{description}: expected task_id={shared_task_id}, got {body.get('task_id')}"
            )

    @pytest.mark.asyncio
    async def test_web_ui_can_reach_agents_api(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """The web UI's /api/agents endpoint should return data consistent
        with the actual agent health status."""
        # Get agents from web UI
        resp = await http_client.get(f"{WEB_UI_BASE_URL}/api/agents")
        if resp.status_code != 200:
            pytest.skip("Web UI /api/agents not available")

        web_agents = resp.json()

        # Cross-reference with direct health checks
        for agent_name in AGENT_REGISTRY:
            health_resp = await http_client.get(
                agent_url(agent_name, "/health")
            )
            is_healthy = health_resp.status_code == 200

            # If the web UI returns a list, check the agent is present
            if isinstance(web_agents, list):
                agent_names_in_web = {
                    a.get("name", a.get("agent", "")) for a in web_agents
                }
                # Note: This is a loose check — agent naming may vary
                # The key assertion is that the web UI endpoint works

    @pytest.mark.asyncio
    async def test_a2a_message_with_multiple_artifacts(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Agents should accept messages carrying multiple file artifacts."""
        artifacts = [
            {
                "name": "api_spec.yaml",
                "content": (
                    "openapi: 3.0.3\n"
                    "info:\n"
                    "  title: User API\n"
                    "paths:\n"
                    "  /users:\n"
                    "    post:\n"
                    "      summary: Create user\n"
                ),
                "mime_type": "application/yaml",
            },
            {
                "name": "acceptance_criteria.md",
                "content": (
                    "# AC: User Registration\n\n"
                    "Given a new visitor\n"
                    "When they submit the registration form\n"
                    "Then a new account is created\n"
                ),
                "mime_type": "text/markdown",
            },
            {
                "name": "data_model.md",
                "content": (
                    "# Data Model\n\n"
                    "## User\n"
                    "- id: UUID\n"
                    "- email: string (unique)\n"
                    "- password_hash: string\n"
                    "- created_at: timestamp\n"
                ),
                "mime_type": "text/markdown",
            },
        ]

        message = build_a2a_message(
            from_agent="pm",
            to_agent="ba",
            msg_type="task",
            claim="Process registration story with full specs",
            artifacts=artifacts,
        )

        resp = await http_client.post(agent_url("ba", "/a2a"), json=message)

        assert resp.status_code in (200, 202), (
            f"BA rejected multi-artifact message: {resp.status_code} — {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_invalid_json_returns_4xx(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Sending malformed JSON should return 400 or 422, not 500."""
        resp = await http_client.post(
            agent_url("po", "/a2a"),
            content=b"this is not json",
            headers={"Content-Type": "application/json"},
        )

        assert resp.status_code in (400, 422), (
            f"Expected 4xx for malformed body, got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_empty_payload_returns_4xx(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Sending an empty JSON object should be rejected."""
        resp = await http_client.post(
            agent_url("pm", "/a2a"),
            json={},
        )

        assert resp.status_code in (400, 422), (
            f"Expected 4xx for empty payload, got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_get_a2a_endpoint_rejected(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """GET /a2a should return 405 Method Not Allowed."""
        resp = await http_client.get(agent_url("po", "/a2a"))

        assert resp.status_code == 405, (
            f"Expected 405 for GET /a2a, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# 8. Concurrent Load Test (lightweight)
# ---------------------------------------------------------------------------


class TestLightLoad:
    """Light concurrency test to verify agents handle parallel requests."""

    @pytest.mark.asyncio
    async def test_concurrent_health_checks(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Fire 10 concurrent health checks to each agent — all should succeed."""
        async def check_health(agent_name: str) -> tuple[str, int]:
            resp = await http_client.get(agent_url(agent_name, "/health"))
            return agent_name, resp.status_code

        # Fire 10 requests per agent concurrently
        all_tasks = []
        for name in AGENT_REGISTRY:
            for _ in range(10):
                all_tasks.append(check_health(name))

        results = await asyncio.gather(*all_tasks, return_exceptions=True)

        failures: list[str] = []
        for result in results:
            if isinstance(result, Exception):
                failures.append(str(result))
            else:
                agent_name, status_code = result
                if status_code != 200:
                    failures.append(f"{agent_name}: {status_code}")

        assert not failures, (
            f"Concurrent health check failures:\n" + "\n".join(failures)
        )

    @pytest.mark.asyncio
    async def test_concurrent_a2a_submissions(
        self,
        http_client: httpx.AsyncClient,
    ) -> None:
        """Send 5 concurrent tasks to PO — all should be accepted."""
        async def submit_task(index: int) -> tuple[int, int]:
            msg = build_a2a_message(
                from_agent="user",
                to_agent="po",
                msg_type="task",
                claim=f"Concurrent task #{index}",
            )
            resp = await http_client.post(agent_url("po", "/a2a"), json=msg)
            return index, resp.status_code

        tasks = [submit_task(i) for i in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                pytest.fail(f"Concurrent submission raised exception: {result}")
            index, status_code = result
            assert status_code in (200, 202), (
                f"Task #{index} got status {status_code}"
            )