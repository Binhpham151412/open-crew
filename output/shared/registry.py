"""Agent auto-discovery registry for OpenCrew.

Discovers agents by polling their /.well-known/agent.json endpoints.
Stores agent cards in Redis (if available) or falls back to in-memory dict.
Provides register, discover, and list_all operations for the A2A protocol layer.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REGISTRY_REDIS_PREFIX = "opencrew:registry:"
POLL_INTERVAL_SECONDS = int(os.getenv("REGISTRY_POLL_INTERVAL", "30"))
POLL_TIMEOUT_SECONDS = float(os.getenv("REGISTRY_POLL_TIMEOUT", "5"))
HEARTBEAT_TTL_SECONDS = int(os.getenv("REGISTRY_HEARTBEAT_TTL", "90"))

# All known agents and their default URLs (used for initial discovery seed)
KNOWN_AGENTS: dict[str, str] = {
    "po":                "http://po:8000",
    "pm":                "http://pm:8001",
    "ba":                "http://ba:8002",
    "solution_architect": "http://solution-architect:8003",
    "frontend_dev":      "http://frontend-dev:8004",
    "backend_dev":       "http://backend-dev:8005",
    "uiux_reviewer":     "http://uiux-reviewer:8006",
    "security_reviewer": "http://security-reviewer:8007",
    "qa":                "http://qa:8008",
    "devops":            "http://devops:8009",
    "techlead":          "http://techlead:8010",
}


# ---------------------------------------------------------------------------
# Agent Card model
# ---------------------------------------------------------------------------

@dataclass
class AgentCard:
    """Represents an agent's public identity, served at /.well-known/agent.json."""

    name: str
    display_name: str
    url: str
    version: str = "1.0.0"
    capabilities: list[str] = field(default_factory=list)
    input_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    protocol: str = "a2a/1.0"
    # --- metadata managed by the registry ---
    last_seen: float = field(default_factory=time.time)
    status: str = "unknown"  # online | offline | unknown

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON encoding."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentCard:
        """Deserialize from a dict, ignoring unknown keys."""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    @classmethod
    def from_json(cls, raw: str) -> AgentCard:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(raw))

    def heartbeat(self) -> None:
        """Update last_seen to now and mark status as online."""
        self.last_seen = time.time()
        self.status = "online"

    def is_stale(self, ttl: float = HEARTBEAT_TTL_SECONDS) -> bool:
        """Return True if the agent hasn't been seen within *ttl* seconds."""
        return (time.time() - self.last_seen) > ttl


# ---------------------------------------------------------------------------
# Storage backends
# ---------------------------------------------------------------------------

class _InMemoryStore:
    """Simple dict-based store (fallback when Redis is unavailable)."""

    def __init__(self) -> None:
        self._data: dict[str, str] = {}  # agent_name -> AgentCard JSON

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def keys(self, pattern: str = "*") -> list[str]:
        prefix = pattern.rstrip("*")
        if not prefix:
            return list(self._data.keys())
        return [k for k in self._data if k.startswith(prefix)]


class _RedisStore:
    """Thin async wrapper around redis.asyncio."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._redis: Any = None

    async def _ensure(self) -> Any:
        if self._redis is None:
            import redis.asyncio as aioredis  # type: ignore[import-untyped]
            self._redis = aioredis.from_url(self._url, decode_responses=True)
        return self._redis

    async def get(self, key: str) -> str | None:
        r = await self._ensure()
        return await r.get(key)  # type: ignore[no-any-return]

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        r = await self._ensure()
        await r.set(key, value, ex=ex)

    async def delete(self, key: str) -> None:
        r = await self._ensure()
        await r.delete(key)

    async def keys(self, pattern: str = "*") -> list[str]:
        r = await self._ensure()
        return list(await r.keys(pattern))  # type: ignore[arg-type]


def _build_store() -> _RedisStore | _InMemoryStore:
    """Try Redis first; fall back to in-memory store."""
    try:
        store = _RedisStore(REDIS_URL)
        logger.info("registry_store_created", backend="redis", url=REDIS_URL)
        return store
    except Exception:
        logger.warning("registry_store_fallback", backend="in_memory", reason="redis_unavailable")
        return _InMemoryStore()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class Registry:
    """Central agent discovery registry.

    Agents self-register by calling :meth:`register` (typically triggered when
    they start up).  The registry also periodically polls every known agent's
    ``/.well-known/agent.json`` endpoint so that it can detect agents that
    start *after* the registry or recover from downtime.

    Usage::

        registry = Registry()
        await registry.start()          # begin background polling loop

        card = AgentCard(name="ba", display_name="Business Analyst",
                         url="http://ba:8002")
        await registry.register(card)

        ba_card = await registry.discover("ba")
        all_cards = await registry.list_all()

        await registry.stop()           # stop polling
    """

    def __init__(
        self,
        *,
        seed_agents: dict[str, str] | None = None,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        poll_timeout: float = POLL_TIMEOUT_SECONDS,
    ) -> None:
        self._store = _build_store()
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._seed_agents: dict[str, str] = seed_agents or dict(KNOWN_AGENTS)
        self._poll_task: asyncio.Task[None] | None = None
        self._running = False

    # ---- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop(), name="registry-poll")
        logger.info("registry_started", poll_interval=self._poll_interval)

    async def stop(self) -> None:
        """Stop the background polling loop gracefully."""
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        logger.info("registry_stopped")

    # ---- public API -------------------------------------------------------

    async def register(self, agent_card: AgentCard | dict[str, Any]) -> AgentCard:
        """Register or update an agent in the registry.

        If a plain dict is passed it will be converted to an
        :class:`AgentCard` automatically.
        """
        if isinstance(agent_card, dict):
            agent_card = AgentCard.from_dict(agent_card)

        agent_card.heartbeat()
        key = self._key(agent_card.name)
        await self._store.set(key, agent_card.to_json(), ex=HEARTBEAT_TTL_SECONDS)
        logger.info(
            "agent_registered",
            agent=agent_card.name,
            url=agent_card.url,
            status=agent_card.status,
        )
        return agent_card

    async def unregister(self, agent_name: str) -> None:
        """Remove an agent from the registry."""
        key = self._key(agent_name)
        await self._store.delete(key)
        logger.info("agent_unregistered", agent=agent_name)

    async def discover(self, agent_name: str) -> AgentCard | None:
        """Look up a single agent by name.

        Returns ``None`` if the agent is not in the registry.
        Returns the :class:`AgentCard` even if it is stale (the caller can
        check ``card.is_stale()``).
        """
        key = self._key(agent_name)
        raw = await self._store.get(key)
        if raw is None:
            return None
        card = AgentCard.from_json(raw)
        if card.is_stale():
            card.status = "offline"
        return card

    async def list_all(self) -> list[AgentCard]:
        """Return every registered agent card, sorted by name."""
        pattern = self._key("*")
        keys = await self._store.keys(pattern)
        cards: list[AgentCard] = []
        for key in keys:
            raw = await self._store.get(key)
            if raw is not None:
                card = AgentCard.from_json(raw)
                if card.is_stale():
                    card.status = "offline"
                cards.append(card)
        cards.sort(key=lambda c: c.name)
        return cards

    async def list_online(self) -> list[AgentCard]:
        """Return only agents whose last heartbeat is within the TTL window."""
        all_cards = await self.list_all()
        return [c for c in all_cards if not c.is_stale()]

    async def heartbeat(self, agent_name: str) -> bool:
        """Refresh an agent's heartbeat. Returns False if the agent is unknown."""
        card = await self.discover(agent_name)
        if card is None:
            return False
        await self.register(card)
        return True

    # ---- background polling -----------------------------------------------

    async def _poll_loop(self) -> None:
        """Continuously poll all known agent endpoints."""
        while self._running:
            try:
                await self._poll_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("registry_poll_error")
            await asyncio.sleep(self._poll_interval)

    async def _poll_all(self) -> None:
        """Fetch /.well-known/agent.json from every known agent in parallel."""
        tasks = [
            self._fetch_and_register(name, url)
            for name, url in self._seed_agents.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for name, result in zip(self._seed_agents, results):
            if isinstance(result, Exception):
                logger.debug("poll_failed", agent=name, error=str(result))

    async def _fetch_and_register(self, agent_name: str, base_url: str) -> None:
        """Fetch an agent's card from its well-known endpoint and register it."""
        url = f"{base_url.rstrip('/')}/.well-known/agent.json"
        async with httpx.AsyncClient(timeout=self._poll_timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        data = resp.json()

        # Normalise the name to our canonical form (the remote card may use
        # a different casing or hyphenated form).
        data["name"] = agent_name

        # Ensure the URL is set to the known base URL if the card doesn't
        # override it (useful when running inside Docker with different
        # hostnames).
        if "url" not in data or not data["url"]:
            data["url"] = base_url

        await self.register(data)

    # ---- helpers ----------------------------------------------------------

    @staticmethod
    def _key(agent_name: str) -> str:
        """Build the store key for an agent."""
        return f"{REGISTRY_REDIS_PREFIX}{agent_name}"

    def __repr__(self) -> str:
        backend = "redis" if isinstance(self._store, _RedisStore) else "in_memory"
        return f"<Registry backend={backend} seeds={len(self._seed_agents)}>"