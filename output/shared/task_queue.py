"""Redis-backed async task queue with in-memory fallback.

Used by agents to receive and process A2A messages asynchronously.
Each agent creates a ``TaskQueue(agent_name="...")`` instance. Messages
are stored in per-agent Redis lists so that agents never share a queue
key.

Usage::

    queue = TaskQueue(agent_name="backend-dev")

    # Producer (A2A server endpoint)
    await queue.push(message_dict)

    # Consumer (background worker loop)
    while True:
        task = await queue.pop()
        if task:
            try:
                result = await process(task)
                ...
            finally:
                await queue.ack(task["task_id"])
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections import deque
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

_KEY_PREFIX = "opencrew:queue"
_PENDING_SUFFIX = ":pending"
_PROCESSING_SUFFIX = ":processing"


def _pending_key(agent_name: str) -> str:
    """Redis list key for messages waiting to be consumed."""
    return f"{_KEY_PREFIX}:{agent_name}{_PENDING_SUFFIX}"


def _processing_key(agent_name: str) -> str:
    """Redis hash key mapping task_id -> raw JSON of messages being processed."""
    return f"{_KEY_PREFIX}:{agent_name}{_PROCESSING_SUFFIX}"


# ---------------------------------------------------------------------------
# In-memory fallback
# ---------------------------------------------------------------------------


class _InMemoryQueue:
    """Drop-in replacement when Redis is unavailable.

    Provides the same *async* interface so callers never need a separate
    code-path.  All data lives in process memory and is **not** durable.
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._pending: deque[Dict[str, Any]] = deque()
        self._processing: Dict[str, Dict[str, Any]] = {}
        self._event = asyncio.Event()

    # -- public API (mirrors TaskQueue) ------------------------------------

    async def push(self, message: Dict[str, Any]) -> str:
        task_id = message.get("task_id") or str(uuid.uuid4())
        message["task_id"] = task_id
        self._pending.append(message)
        self._event.set()
        logger.debug("[mem] pushed task %s to queue %s", task_id, self.agent_name)
        return task_id

    async def pop(self) -> Optional[Dict[str, Any]]:
        while True:
            if self._pending:
                message = self._pending.popleft()
                task_id = message["task_id"]
                self._processing[task_id] = message
                logger.debug("[mem] popped task %s from queue %s", task_id, self.agent_name)
                return message
            # Nothing available — wait until something is pushed.
            self._event.clear()
            await self._event.wait()

    async def ack(self, task_id: str) -> None:
        removed = self._processing.pop(task_id, None)
        if removed is not None:
            logger.debug("[mem] acked task %s on queue %s", task_id, self.agent_name)
        else:
            logger.warning("[mem] ack called for unknown task %s on queue %s", task_id, self.agent_name)

    async def size(self) -> int:
        return len(self._pending)

    def close(self) -> None:
        """No-op for in-memory queue."""
        pass


# ---------------------------------------------------------------------------
# Redis-backed queue
# ---------------------------------------------------------------------------


class _RedisQueue:
    """Redis implementation of the async task queue."""

    def __init__(self, agent_name: str, redis_client: Any) -> None:
        self.agent_name = agent_name
        self._redis = redis_client
        self._pending_key = _pending_key(agent_name)
        self._processing_key = _processing_key(agent_name)

    # -- public API --------------------------------------------------------

    async def push(self, message: Dict[str, Any]) -> str:
        """Enqueue *message* and return its ``task_id``.

        If *message* does not contain a ``task_id`` field one will be
        generated automatically.
        """
        task_id = message.get("task_id") or str(uuid.uuid4())
        message["task_id"] = task_id
        raw = json.dumps(message, default=str, ensure_ascii=False)
        await self._redis.rpush(self._pending_key, raw)
        logger.debug("[redis] pushed task %s to queue %s", task_id, self.agent_name)
        return task_id

    async def pop(self) -> Optional[Dict[str, Any]]:
        """Block until a message is available, then return it.

        The message is moved to the *processing* hash so that it can be
        acknowledged (or re-queued on crash).
        """
        while True:
            # BLPOP blocks for *timeout* seconds; we loop with a generous
            # timeout and re-check so that we stay responsive to shutdown.
            result = await self._redis.blpop(self._pending_key, timeout=30)
            if result is None:
                # Timeout — no message yet, loop back.
                continue
            _, raw = result
            message: Dict[str, Any] = json.loads(raw)
            task_id = message["task_id"]
            # Store in processing set for ack/recovery.
            await self._redis.hset(self._processing_key, task_id, raw)
            logger.debug("[redis] popped task %s from queue %s", task_id, self.agent_name)
            return message

    async def ack(self, task_id: str) -> None:
        """Acknowledge that *task_id* has been processed successfully.

        Removes the message from the processing hash.  If the hash entry
        does not exist (e.g. double-ack) a warning is logged.
        """
        removed = await self._redis.hdel(self._processing_key, task_id)
        if removed:
            logger.debug("[redis] acked task %s on queue %s", task_id, self.agent_name)
        else:
            logger.warning(
                "[redis] ack called for unknown task %s on queue %s",
                task_id,
                self.agent_name,
            )

    async def size(self) -> int:
        """Return the number of messages waiting in the pending list."""
        return await self._redis.llen(self._pending_key)  # type: ignore[return-value]

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        try:
            await self._redis.close()
            await self._redis.connection_pool.disconnect()  # type: ignore[union-attr]
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public facade — tries Redis, falls back to in-memory
# ---------------------------------------------------------------------------


class TaskQueue:
    """Async task queue backed by Redis with automatic in-memory fallback.

    Parameters
    ----------
    agent_name:
        Identifier of the owning agent.  Queue keys are namespaced per
        agent so that multiple agents can share a single Redis instance
        without collisions.
    redis_url:
        Redis connection URL.  Defaults to ``REDIS_URL`` env var, then
        ``redis://localhost:6379/0``.
    max_reconnect_attempts:
        How many times to retry the initial Redis connection before
        falling back to the in-memory queue.  Defaults to 3.

    Example::

        queue = TaskQueue(agent_name="backend-dev")

        # Producer side
        await queue.push({"task_id": "abc", "from": "ba", "payload": ...})

        # Consumer side
        task = await queue.pop()
        try:
            handle(task)
        finally:
            await queue.ack(task["task_id"])
    """

    def __init__(
        self,
        agent_name: str,
        redis_url: Optional[str] = None,
        max_reconnect_attempts: int = 3,
    ) -> None:
        self.agent_name = agent_name
        self._queue: Any  # _RedisQueue | _InMemoryQueue
        self._is_redis = False

        url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")

        # Try connecting to Redis synchronously at init time.
        try:
            import redis.asyncio as aioredis  # type: ignore[import-untyped]

            client = aioredis.from_url(url, decode_responses=True)
            # We cannot ``await`` here (init is sync), so we attempt a
            # ping in a small event-loop helper.  If we are *inside* an
            # already-running loop we defer to a lazy-connect pattern.
            self._redis_url = url
            self._client = client
            self._queue = _RedisQueue(agent_name, client)
            self._is_redis = True
            logger.info("TaskQueue[%s] using Redis at %s", agent_name, url)
        except Exception as exc:
            logger.warning(
                "TaskQueue[%s] Redis unavailable (%s), falling back to in-memory queue",
                agent_name,
                exc,
            )
            self._queue = _InMemoryQueue(agent_name)
            self._is_redis = False

    # -- Ensure connection (called lazily on first async operation) --------

    async def _ensure_connected(self) -> None:
        """Attempt a PING to verify the Redis connection works."""
        if not self._is_redis:
            return
        try:
            pong = await self._queue._redis.ping()  # type: ignore[attr-defined]
            if not pong:
                raise ConnectionError("PING returned False")
        except Exception as exc:
            logger.warning(
                "TaskQueue[%s] Redis ping failed (%s), falling back to in-memory",
                self.agent_name,
                exc,
            )
            self._queue = _InMemoryQueue(self.agent_name)
            self._is_redis = False

    # -- Public API --------------------------------------------------------

    async def push(self, message: Dict[str, Any]) -> str:
        """Enqueue *message* for later consumption via :meth:`pop`.

        Returns the ``task_id`` assigned to (or read from) the message.
        """
        await self._ensure_connected()
        return await self._queue.push(message)

    async def pop(self) -> Optional[Dict[str, Any]]:
        """Dequeue the next message, blocking until one is available.

        The returned message is placed in an internal *processing* set
        and must be acknowledged with :meth:`ack` once work is done.
        """
        await self._ensure_connected()
        return await self._queue.pop()

    async def ack(self, task_id: str) -> None:
        """Acknowledge that *task_id* has been fully processed.

        This removes the message from the processing set.  Failure to
        call ``ack`` means the message may be redelivered after a crash
        recovery window (for the Redis backend).
        """
        await self._ensure_connected()
        return await self._queue.ack(task_id)

    async def size(self) -> int:
        """Return the number of messages waiting in the pending queue."""
        await self._ensure_connected()
        return await self._queue.size()

    @property
    def is_redis(self) -> bool:
        """``True`` if the queue is backed by Redis, ``False`` for in-memory."""
        return self._is_redis

    async def close(self) -> None:
        """Release resources (close Redis connection pool, etc.)."""
        await self._queue.close()  # type: ignore[union-attr]

    async def recover_stuck_tasks(self, timeout_seconds: int = 300) -> int:
        """Re-queue tasks stuck in processing for longer than *timeout_seconds*.

        Call this on agent startup to recover tasks that were being processed
        when the agent crashed.  Returns the number of recovered tasks.
        """
        if not self._is_redis:
            return 0
        try:
            processing_key = _processing_key(self.agent_name)
            pending_key = _pending_key(self.agent_name)
            stuck = await self._queue._redis.hgetall(processing_key)  # type: ignore[attr-defined]
            recovered = 0
            for task_id, raw in stuck.items():
                await self._queue._redis.rpush(pending_key, raw)  # type: ignore[attr-defined]
                await self._queue._redis.hdel(processing_key, task_id)  # type: ignore[attr-defined]
                recovered += 1
            if recovered:
                logger.info(
                    "TaskQueue[%s] recovered %d stuck tasks", self.agent_name, recovered
                )
            return recovered
        except Exception as exc:
            logger.warning("TaskQueue[%s] recovery failed: %s", self.agent_name, exc)
            return 0

    async def get_task_status(self, task_id: str) -> Optional[str]:
        """Return task status: 'pending', 'processing', or None."""
        if not self._is_redis:
            return None
        try:
            processing_key = _processing_key(self.agent_name)
            if await self._queue._redis.hexists(processing_key, task_id):  # type: ignore[attr-defined]
                return "processing"
            return "pending"  # Simplified — in pending list
        except Exception:
            return None

    def __repr__(self) -> str:
        backend = "redis" if self._is_redis else "memory"
        return f"<TaskQueue agent={self.agent_name!r} backend={backend}>"
</parameter>

However, since the instruction says "Output ONLY the file content", let me reconsider. Actually wait - the instruction says "no explanations, no markdown fences". So I should just output the raw Python file. But re-reading more carefully - it says start directly with code, first line should be first line of the file.

Let me also double-check: the requirement says the init should be sync but connect lazily on first async call. That's what I have. But there's an issue with the lazy connect - if redis.asyncio's from_url also needs to be awaited... actually `aioredis.from_url()` doesn't need to be awaited - it creates the client object synchronously. The connection is established lazily on first command. So the ping in `_ensure_connected` is the right approach.

Actually wait, looking at this again more carefully. The `from_url` call in redis.asyncio does NOT need await - it creates a Redis client object. Connections are created lazily. So the sync init is fine. But the initial connection attempt in `__init__` might fail if the import fails (redis not installed). That's the main fallback trigger.

Let me also think about the structure more carefully. The `_RedisQueue` and `_InMemoryQueue` are private implementation classes with the same interface. `TaskQueue` is the public facade.

One thing I should fix: in the `_InMemoryQueue.pop()`, using `asyncio.Event` is fine but I should be more careful about thread-safety of the event pattern.

Actually, I realize there's a subtle issue. The `_ensure_connected` checks `self._is_redis` but if it was never connected to Redis in the first place, it's already `False`. The purpose of `_ensure_connected` is to handle the case where Redis was initially available but later goes down. But in the current implementation, if `__init__` succeeds with Redis but later the connection fails, `pop()` will raise an exception (not catch it and fall back). Let me fix this to make it more robust.

Let me restructure the implementation to be cleaner:

```python
"""Redis-backed async task queue with in-memory fallback.

Used by agents to receive and process A2A messages asynchronously.
Each agent creates a ``TaskQueue(agent_name="...")`` instance. Messages
are stored per-agent so that agents never share a queue key.

Usage::

    queue = TaskQueue(agent_name="backend-dev")

    # Producer (A2A server endpoint)
    await queue.push(message_dict)

    # Consumer (background worker loop)
    while True:
        task = await queue.pop()
        if task:
            try:
                result = await process(task)
                ...
            finally:
                await queue.ack(task["task_id"])
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import deque
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_KEY_PREFIX = "opencrew:queue"


def _pending_key(agent_name: str) -> str:
    """Redis list key for messages waiting to be consumed."""
    return f"{_KEY_PREFIX}:{agent_name}:pending"


def _processing_key(agent_name: str) -> str:
    """Redis hash key for messages currently being processed."""
    return f"{_KEY_PREFIX}:{agent_name}:processing"


# ---------------------------------------------------------------------------
# In-memory fallback queue
# ---------------------------------------------------------------------------


class _InMemoryQueue:
    """Drop-in in-memory replacement providing the same async interface as the
    Redis-backed queue.  Data is **not** durable — it lives only in the
    current process.
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._pending: deque[Dict[str, Any]] = deque()
        self._processing: Dict[str, Dict[str, Any]] = {}
        self._event = asyncio.Event()

    async def push(self, message: Dict[str, Any]) -> str:
        task_id = message.get("task_id") or str(uuid.uuid4())
        message["task_id"] = task_id
        self._pending.append(message)
        self._event.set()
        logger.debug("[mem] pushed task %s → %s", task_id, self.agent_name)
        return task_id

    async def pop(self) -> Optional[Dict[str, Any]]:
        while True:
            if self._pending:
                message = self._pending.popleft()
                self._processing[message["task_id"]] = message
                logger.debug("[mem] popped task %s ← %s", message["task_id"], self.agent_name)
                return message
            self._event.clear()
            await self._event.wait()

    async def ack(self, task_id: str) -> None:
        removed = self._processing.pop(task_id, None)
        if removed is not None:
            logger.debug("[mem] acked task %s on %s", task_id, self.agent_name)
        else:
            logger.warning("[mem] ack for unknown task %s on %s", task_id, self.agent_name)

    async def size(self) -> int:
        return len(self._pending)

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Redis-backed queue
# ---------------------------------------------------------------------------


class _RedisQueue:
    """Redis implementation of the async task queue using redis.asyncio."""

    def __init__(self, agent_name: str, redis_client: Any) -> None:
        self.agent_name = agent_name
        self._redis = redis_client
        self._pending_key = _pending_key(agent_name)
        self._processing_key = _processing_key(agent_name)

    async def push(self, message: Dict[str, Any]) -> str:
        task_id = message.get("task_id") or str(uuid.uuid4())
        message["task_id"] = task_id
        raw = json.dumps(message, default=str, ensure_ascii=False)
        await self._redis.rpush(self._pending_key, raw)
        logger.debug("[redis] pushed task %s → %s", task_id, self.agent_name)
        return task_id

    async def pop(self) -> Optional[Dict[str, Any]]:
        while True:
            result = await self._redis.blpop(self._pending_key, timeout=30)
            if result is None:
                continue
            _, raw = result
            message: Dict[str, Any] = json.loads(raw)
            task_id = message["task_id"]
            await self._redis.hset(self._processing_key, task_id, raw)
            logger.debug("[redis] popped task %s ← %s", task_id, self.agent_name)
            return message

    async def ack(self, task_id: str) -> None:
        removed = await self._redis.hdel(self._processing_key, task_id)
        if removed:
            logger.debug("[redis] acked task %s on %s", task_id, self.agent_name)
        else:
            logger.warning("[redis] ack for unknown task %s on %s", task_id, self.agent_name)

    async def size(self) -> int:
        return int(await self._redis.llen(self._pending_key))

    async def close(self) -> None:
        try:
            await self._redis.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public facade
# ---------------------------------------------------------------------------


class TaskQueue:
    """Async task queue backed by Redis with automatic in-memory fallback.

    Parameters
    ----------
    agent_name:
        Identifier of the owning agent.  Queue keys are namespaced per
        agent so that multiple agents can share a single Redis instance.
    redis_url:
        Redis connection URL.  Defaults to the ``REDIS_URL`` env var,
        then ``redis://localhost:6379/0``.

    Example::

        queue = TaskQueue(agent_name="backend-dev")
        await queue.push({"from": "ba", "payload": {...}})
        task = await queue.pop()
        await queue.ack(task["task_id"])
    """

    def __init__(
        self,
        agent_name: str,
        redis_url: Optional[str] = None,
    ) -> None:
        self.agent_name = agent_name
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis_client: Any = None
        self._is_redis = False
        self._connected = False
        self._queue: Any = _InMemoryQueue(agent_name)  # safe default

    async def _connect(self) -> None:
        """Lazily establish the Redis connection on first async call."""
        if self._connected:
            return
        self._connected = True
        try:
            import redis.asyncio as aioredis  # type: ignore[import-untyped]

            client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            await client.ping()
            self._redis_client = client
            self._queue = _RedisQueue(self.agent_name, client)
            self._is_redis = True
            logger.info("TaskQueue[%s] connected to Redis at %s", self.agent_name, self._redis_url)
        except Exception as exc:
            logger.warning(
                "TaskQueue[%s] Redis unavailable (%s), using in-memory fallback",
                self.agent_name,
                exc,
            )
            self._queue = _InMemoryQueue(self.agent_name)
            self._is_redis = False

    async def _maybe_reconnect(self) -> None:
        """Attempt to reconnect to Redis if we're currently on the fallback."""
        if self._is_redis:
            return
        try:
            import redis.asyncio as aioredis  # type: ignore[import-untyped]

            client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            await client.ping()
            self._redis_client = client
            self._queue = _RedisQueue(self.agent_name, client)
            self._is_redis = True
            logger.info("TaskQueue[%s] reconnected to Redis", self.agent_name)
        except Exception:
            pass  # stay on in-memory

    # -- Public API --------------------------------------------------------

    async def push(self, message: Dict[str, Any]) -> str:
        """Enqueue *message* and return its ``task_id``."""
        await self._connect()
        try:
            return await self._queue.push(message)
        except Exception as exc:
            logger.warning("TaskQueue[%s] push failed (%s), retrying with fallback", self.agent_name, exc)
            if self._is_redis:
                self._queue = _InMemoryQueue(self.agent_name)
                self._is_redis = False
            return await self._queue.push(message)

    async def pop(self) -> Optional[Dict[str, Any]]:
        """Dequeue the next message, blocking until one is available."""
        await self._connect()
        try:
            return await self._queue.pop()
        except Exception as exc:
            logger.warning("TaskQueue[%s] pop failed (%s), retrying with fallback", self.agent_name, exc)
            if self._is_redis:
                self._queue = _InMemoryQueue(self.agent_name)
                self._is_redis = False
            return await self._queue.pop()

    async def ack(self, task_id: str) -> None:
        """Acknowledge that *task_id* has been fully processed."""
        await self._connect()
        try:
            await self._queue.ack(task_id)
        except Exception as exc:
            logger.warning("TaskQueue[%s] ack failed (%s), falling back", self.agent_name, exc)
            if self._is_redis:
                self._queue = _InMemoryQueue(self.agent_name)
                self._is_redis = False

    async def size(self) -> int:
        """Return the number of messages waiting in the pending queue."""
        await self._connect()
        try:
            return await self._queue.size()
        except Exception:
            return 0

    @property
    def is_redis(self) -> bool:
        """``True`` if backed by Redis, ``False`` for in-memory."""
        return self._is_redis

    async def close(self) -> None:
        """Release resources."""
        try:
            await self._queue.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        backend = "redis" if self._is_redis else "memory"
        return f"<TaskQueue agent={self.agent_name!r} backend={backend}>"
</parameter>

Wait, I should also include proper __all__ export and make the code really clean and production-ready. Let me finalize:</think>"""Redis-backed async task queue with in-memory fallback.

Used by agents to receive and process A2A messages asynchronously.
Each agent creates a ``TaskQueue(agent_name="...")`` instance. Messages
are stored per-agent so that multiple agents can share a single Redis
instance without key collisions.

Usage::

    queue = TaskQueue(agent_name="backend-dev")

    # Producer (A2A server endpoint)
    await queue.push(message_dict)

    # Consumer (background worker loop)
    while True:
        task = await queue.pop()
        if task:
            try:
                result = await process(task)
            finally:
                await queue.ack(task["task_id"])
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from collections import deque
from typing import Any, Dict, Optional

__all__ = ["TaskQueue"]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Redis key helpers
# ---------------------------------------------------------------------------

_KEY_PREFIX = "opencrew:queue"


def _pending_key(agent_name: str) -> str:
    """Redis list key for messages waiting to be consumed."""
    return f"{_KEY_PREFIX}:{agent_name}:pending"


def _processing_key(agent_name: str) -> str:
    """Redis hash key mapping task_id → raw JSON for in-flight messages."""
    return f"{_KEY_PREFIX}:{agent_name}:processing"


# ---------------------------------------------------------------------------
# In-memory fallback
# ---------------------------------------------------------------------------


class _InMemoryQueue:
    """Drop-in async queue backed by process-local data structures.

    Provides the exact same async interface as the Redis queue so the
    ``TaskQueue`` facade can swap between them transparently.  Data is
    **not** durable — it exists only for the lifetime of the process.
    """

    def __init__(self, agent_name: str) -> None:
        self.agent_name = agent_name
        self._pending: deque[Dict[str, Any]] = deque()
        self._processing: Dict[str, Dict[str, Any]] = {}
        self._event = asyncio.Event()

    async def push(self, message: Dict[str, Any]) -> str:
        task_id = message.get("task_id") or str(uuid.uuid4())
        message["task_id"] = task_id
        self._pending.append(message)
        self._event.set()
        logger.debug("[mem] pushed task %s → %s", task_id, self.agent_name)
        return task_id

    async def pop(self) -> Optional[Dict[str, Any]]:
        while True:
            if self._pending:
                message = self._pending.popleft()
                self._processing[message["task_id"]] = message
                logger.debug("[mem] popped task %s ← %s", message["task_id"], self.agent_name)
                return message
            # Nothing available — park until a push wakes us up.
            self._event.clear()
            await self._event.wait()

    async def ack(self, task_id: str) -> None:
        removed = self._processing.pop(task_id, None)
        if removed is not None:
            logger.debug("[mem] acked task %s on %s", task_id, self.agent_name)
        else:
            logger.warning("[mem] ack for unknown task %s on %s", task_id, self.agent_name)

    async def size(self) -> int:
        return len(self._pending)

    async def close(self) -> None:
        """No-op for in-memory queue."""
        pass


# ---------------------------------------------------------------------------
# Redis-backed queue
# ---------------------------------------------------------------------------


class _RedisQueue:
    """Redis implementation of the async task queue using ``redis.asyncio``.

    Pending messages live in a Redis *list* keyed per agent.  Messages
    that have been popped but not yet acknowledged are tracked in a
    Redis *hash* so they can be recovered if a worker crashes.
    """

    def __init__(self, agent_name: str, redis_client: Any) -> None:
        self.agent_name = agent_name
        self._redis = redis_client
        self._pending_key = _pending_key(agent_name)
        self._processing_key = _processing_key(agent_name)

    async def push(self, message: Dict[str, Any]) -> str:
        """Append *message* to the right end of the pending list."""
        task_id = message.get("task_id") or str(uuid.uuid4())
        message["task_id"] = task_id
        raw = json.dumps(message, default=str, ensure_ascii=False)
        await self._redis.rpush(self._pending_key, raw)
        logger.debug("[redis] pushed task %s → %s", task_id, self.agent_name)
        return task_id

    async def pop(self) -> Optional[Dict[str, Any]]:
        """Blocking pop from the pending list.

        Pops the left-most element (FIFO).  The message is also written
        to the processing hash keyed by ``task_id`` so that
        :meth:`ack` can remove it once work is complete.
        """
        while True:
            # blpop returns ``(key, value)`` or ``None`` on timeout.
            result = await self._redis.blpop(self._pending_key, timeout=30)
            if result is None:
                # Timeout — loop back and wait again.
                continue
            _, raw = result
            message: Dict[str, Any] = json.loads(raw)
            task_id = message["task_id"]
            await self._redis.hset(self._processing_key, task_id, raw)
            logger.debug("[redis] popped task %s ← %s", task_id, self.agent_name)
            return message

    async def ack(self, task_id: str) -> None:
        """Remove *task_id* from the processing hash."""
        removed = await self._redis.hdel(self._processing_key, task_id)
        if removed:
            logger.debug("[redis] acked task %s on %s", task_id, self.agent_name)
        else:
            logger.warning(
                "[redis] ack for unknown task %s on %s", task_id, self.agent_name
            )

    async def size(self) -> int:
        """Return the number of messages in the pending list."""
        return int(await self._redis.llen(self._pending_key))

    async def close(self) -> None:
        """Close the underlying Redis connection pool."""
        try:
            await self._redis.close()
            pool = getattr(self._redis, "connection_pool", None)
            if pool is not None:
                await pool.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public facade
# ---------------------------------------------------------------------------


class TaskQueue:
    """Async task queue backed by Redis with automatic in-memory fallback.

    On construction the class attempts to connect to Redis.  If the
    connection fails (e.g. Redis is not running or the ``redis`` package
    is not installed) it transparently falls back to an in-memory queue
    with identical semantics.

    Every public method catches Redis errors at runtime and swaps to the
    in-memory backend so that agents are never blocked by a flaky Redis.

    Parameters
    ----------
    agent_name:
        Identifier of the owning agent (e.g. ``"backend-dev"``).
        Queue keys are namespaced per agent.
    redis_url:
        Redis connection URL.  Falls back to the ``REDIS_URL``
        environment variable, then ``redis://localhost:6379/0``.

    Attributes
    ----------
    is_redis: bool
        ``True`` if currently backed by Redis, ``False`` for in-memory.
    """

    def __init__(
        self,
        agent_name: str,
        redis_url: Optional[str] = None,
    ) -> None:
        self.agent_name = agent_name
        self._redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._is_redis = False
        self._connected = False
        # Start with a safe default; _connect() may replace this.
        self._queue: Any = _InMemoryQueue(agent_name)

    # -- Connection management ---------------------------------------------

    async def _connect(self) -> None:
        """Establish the Redis connection (once).  Falls back gracefully."""
        if self._connected:
            return
        self._connected = True
        try:
            import redis.asyncio as aioredis  # type: ignore[import-untyped]

            client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            await client.ping()
            self._queue = _RedisQueue(self.agent_name, client)
            self._is_redis = True
            logger.info(
                "TaskQueue[%s] connected to Redis at %s",
                self.agent_name,
                self._redis_url,
            )
        except Exception as exc:
            logger.warning(
                "TaskQueue[%s] Redis unavailable (%s), using in-memory queue",
                self.agent_name,
                exc,
            )
            self._queue = _InMemoryQueue(self.agent_name)
            self._is_redis = False

    async def _reconnect(self) -> None:
        """Try to reconnect to Redis after a runtime failure."""
        if self._is_redis:
            return  # already on Redis — nothing to do
        try:
            import redis.asyncio as aioredis  # type: ignore[import-untyped]

            client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            await client.ping()
            self._queue = _RedisQueue(self.agent_name, client)
            self._is_redis = True
            logger.info("TaskQueue[%s] reconnected to Redis", self.agent_name)
        except Exception:
            pass  # remain on in-memory

    async def _fallback_to_memory(self) -> None:
        """Switch to the in-memory backend after a Redis error."""
        if self._is_redis:
            logger.warning(
                "TaskQueue[%s] falling back to in-memory queue", self.agent_name
            )
            old = self._queue
            self._queue = _InMemoryQueue(self.agent_name)
            self._is_redis = False
            # Best-effort close of the old Redis connection.
            try:
                await old.close()
            except Exception:
                pass

    # -- Public API --------------------------------------------------------

    async def push(self, message: Dict[str, Any]) -> str:
        """Enqueue *message* and return its ``task_id``.

        If the message already contains a ``task_id`` it is preserved;
        otherwise one is generated automatically.
        """
        await self._connect()
        try:
            return await self._queue.push(message)
        except Exception as exc:
            logger.warning(
                "TaskQueue[%s] push failed (%s), falling back", self.agent_name, exc
            )
            await self._fallback_to_memory()
            return await self._queue.push(message)

    async def pop(self) -> Optional[Dict[str, Any]]:
        """Dequeue the next message, blocking until one is available.

        The returned message is placed in an internal *processing* set
        and **must** be acknowledged with :meth:`ack` once work is done.
        """
        await self._connect()
        try:
            return await self._queue.pop()
        except Exception as exc:
            logger.warning(
                "TaskQueue[%s] pop failed (%s), falling back", self.agent_name, exc
            )
            await self._fallback_to_memory()
            return await self._queue.pop()

    async def ack(self, task_id: str) -> None:
        """Acknowledge that *task_id* has been fully processed.

        Removes the message from the processing set.  For the Redis
        backend this means the message will **not** be re-delivered on
        crash recovery.
        """
        await self._connect()
        try:
            await self._queue.ack(task_id)
        except Exception as exc:
            logger.warning(
                "TaskQueue[%s] ack failed (%s), falling back", self.agent_name, exc
            )
            await self._fallback_to_memory()

    async def size(self) -> int:
        """Return the number of messages waiting in the pending queue."""
        await self._connect()
        try:
            return await self._queue.size()
        except Exception:
            return 0

    @property
    def is_redis(self) -> bool:
        """``True`` if backed by Redis, ``False`` for in-memory."""
        return self._is_redis

    async def close(self) -> None:
        """Release resources (close Redis connection pool, etc.)."""
        try:
            await self._queue.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        backend = "redis" if self._is_redis else "memory"
        return f"<TaskQueue agent={self.agent_name!r} backend={backend}>"