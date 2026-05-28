import asyncio
import json
import os
import uuid
from typing import Any, Optional

import structlog

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

logger = structlog.get_logger(__name__)


class InMemoryQueue:
    """Async in-memory queue used as fallback when Redis is unavailable."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._pending: dict[str, dict[str, Any]] = {}

    async def push(self, message: dict[str, Any]) -> str:
        task_id = message.get("task_id") or str(uuid.uuid4())
        message["task_id"] = task_id
        self._pending[task_id] = message
        await self._queue.put(message)
        return task_id

    async def pop(self) -> Optional[dict[str, Any]]:
        if self._queue.empty():
            return None
        return await self._queue.get()

    def size(self) -> int:
        return self._queue.qsize()

    def ack(self, task_id: str) -> None:
        self._pending.pop(task_id, None)


class TaskQueue:
    """Redis-backed async task queue with in-memory fallback.

    Each agent gets its own queue identified by ``agent_name``.
    Messages are stored as JSON strings in a Redis list.

    If Redis is unavailable at construction time or during an operation,
    the queue transparently falls back to an :class:`InMemoryQueue`.

    Args:
        agent_name: Identifier for the agent owning this queue.
        redis_url: Redis connection URL. Defaults to ``"redis://localhost:6379/0"``.
        namespace: Redis key namespace. Defaults to ``"opencrew:queue"``.

    Example::

        queue = TaskQueue(agent_name="backend-dev")
        await queue.push({"task_id": "abc-123", "type": "task", "payload": {...}})
        message = await queue.pop()
        await queue.ack(message["task_id"])
    """

    DEFAULT_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    NAMESPACE = "opencrew:queue"
    CONNECT_TIMEOUT = 3.0  # seconds

    def __init__(
        self,
        agent_name: str,
        redis_url: str = DEFAULT_REDIS_URL,
        namespace: str = NAMESPACE,
    ) -> None:
        self._agent_name = agent_name
        self._redis_url = redis_url
        self._namespace = namespace
        self._redis: Optional[Any] = None
        self._fallback: Optional[InMemoryQueue] = None
        self._use_fallback: bool = False

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    @property
    def _queue_key(self) -> str:
        """Redis key for the main FIFO list."""
        return f"{self._namespace}:{self._agent_name}:pending"

    @property
    def _data_key(self) -> str:
        """Redis hash key that maps task_id → full JSON payload (for ack)."""
        return f"{self._namespace}:{self._agent_name}:data"

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def _get_redis(self) -> Optional[Any]:
        """Return an active Redis connection, creating one if needed.

        Returns ``None`` and switches to fallback if connection fails.
        """
        if self._use_fallback:
            return None

        if self._redis is not None:
            return self._redis

        if aioredis is None:
            logger.warning(
                "redis.asyncio not installed; using in-memory fallback",
                agent=self._agent_name,
            )
            self._use_fallback = True
            self._fallback = InMemoryQueue()
            return None

        try:
            client = aioredis.from_url(
                self._redis_url,
                decode_responses=True,
                socket_connect_timeout=self.CONNECT_TIMEOUT,
                socket_timeout=self.CONNECT_TIMEOUT,
                retry_on_timeout=True,
            )
            # Verify the connection with a ping
            await asyncio.wait_for(
                client.ping(), timeout=self.CONNECT_TIMEOUT
            )
            self._redis = client
            logger.info(
                "Connected to Redis",
                agent=self._agent_name,
                url=self._redis_url,
            )
            return self._redis
        except Exception as exc:
            logger.warning(
                "Redis connection failed; falling back to in-memory queue",
                agent=self._agent_name,
                error=str(exc),
            )
            self._use_fallback = True
            self._fallback = InMemoryQueue()
            return None

    def _ensure_fallback(self) -> InMemoryQueue:
        """Return the fallback queue, creating it if necessary."""
        if self._fallback is None:
            self._fallback = InMemoryQueue()
        return self._fallback

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def push(self, message: dict[str, Any]) -> str:
        """Push a message onto the queue.

        If the message does not contain a ``task_id``, one is generated
        automatically.

        Args:
            message: The task payload (must be JSON-serialisable).

        Returns:
            The ``task_id`` of the enqueued message.
        """
        task_id = message.get("task_id") or str(uuid.uuid4())
        message["task_id"] = task_id

        redis = await self._get_redis()

        if redis is not None:
            try:
                payload = json.dumps(message, ensure_ascii=False)
                # Use a pipeline for atomicity
                async with redis.pipeline(transaction=True) as pipe:
                    pipe.rpush(self._queue_key, payload)
                    pipe.hset(self._data_key, task_id, payload)
                    await pipe.execute()
                logger.debug(
                    "Message pushed to Redis",
                    agent=self._agent_name,
                    task_id=task_id,
                )
                return task_id
            except Exception as exc:
                logger.warning(
                    "Redis push failed; falling back to in-memory",
                    agent=self._agent_name,
                    task_id=task_id,
                    error=str(exc),
                )
                self._use_fallback = True
                self._redis = None

        fallback = self._ensure_fallback()
        await fallback.push(message)
        logger.debug(
            "Message pushed to in-memory queue",
            agent=self._agent_name,
            task_id=task_id,
        )
        return task_id

    async def pop(self) -> Optional[dict[str, Any]]:
        """Pop the next message from the queue (non-blocking).

        Returns:
            The message dict, or ``None`` if the queue is empty.
        """
        redis = await self._get_redis()

        if redis is not None:
            try:
                # BLPOP with timeout=0 would block; we want non-blocking
                # so use LPOP instead.
                result = await redis.lpop(self._queue_key)
                if result is None:
                    return None
                message = json.loads(result)
                logger.debug(
                    "Message popped from Redis",
                    agent=self._agent_name,
                    task_id=message.get("task_id"),
                )
                return message
            except Exception as exc:
                logger.warning(
                    "Redis pop failed; falling back to in-memory",
                    agent=self._agent_name,
                    error=str(exc),
                )
                self._use_fallback = True
                self._redis = None

        fallback = self._ensure_fallback()
        return await fallback.pop()

    async def size(self) -> int:
        """Return the number of messages currently in the queue.

        Returns:
            Integer count of pending messages.
        """
        redis = await self._get_redis()

        if redis is not None:
            try:
                return await redis.llen(self._queue_key)
            except Exception as exc:
                logger.warning(
                    "Redis size check failed; falling back to in-memory",
                    agent=self._agent_name,
                    error=str(exc),
                )
                self._use_fallback = True
                self._redis = None

        fallback = self._ensure_fallback()
        return fallback.size()

    async def ack(self, task_id: str) -> None:
        """Acknowledge a task, removing it from the pending tracking store.

        This is useful for at-least-once processing: after a message is
        popped and successfully processed, call ``ack`` to remove the
        reference. If the worker crashes between ``pop`` and ``ack``,
        the message data can still be recovered from the hash.

        Args:
            task_id: The identifier of the task to acknowledge.
        """
        redis = await self._get_redis()

        if redis is not None:
            try:
                await redis.hdel(self._data_key, task_id)
                logger.debug(
                    "Task acknowledged in Redis",
                    agent=self._agent_name,
                    task_id=task_id,
                )
                return
            except Exception as exc:
                logger.warning(
                    "Redis ack failed; falling back to in-memory",
                    agent=self._agent_name,
                    task_id=task_id,
                    error=str(exc),
                )
                self._use_fallback = True
                self._redis = None

        fallback = self._ensure_fallback()
        fallback.ack(task_id)

    async def close(self) -> None:
        """Gracefully close the Redis connection.

        Safe to call multiple times.
        """
        if self._redis is not None:
            try:
                await self._redis.close()
                logger.info(
                    "Redis connection closed",
                    agent=self._agent_name,
                )
            except Exception as exc:
                logger.warning(
                    "Error closing Redis connection",
                    agent=self._agent_name,
                    error=str(exc),
                )
            finally:
                self._redis = None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def using_fallback(self) -> bool:
        """Return ``True`` if the queue is operating in in-memory mode."""
        return self._use_fallback

    @property
    def agent_name(self) -> str:
        """Return the agent name this queue belongs to."""
        return self._agent_name

    async def recover_stuck_tasks(self, timeout_seconds: int = 300) -> int:
        """Re-queue tasks stuck in processing for longer than *timeout_seconds*.

        Call this on agent startup to recover tasks that were being processed
        when the agent crashed.  Returns the number of recovered tasks.
        """
        if self._redis is None:
            return 0
        try:
            data_key = f"opencrew:queue:{self._agent_name}:data"
            stuck = await self._redis.hgetall(data_key)
            recovered = 0
            for task_id, raw in stuck.items():
                await self._redis.rpush(
                    f"opencrew:queue:{self._agent_name}:pending", raw
                )
                await self._redis.hdel(data_key, task_id)
                recovered += 1
            if recovered:
                logger.info(
                    "Recovered stuck tasks",
                    agent=self._agent_name,
                    count=recovered,
                )
            return recovered
        except Exception as exc:
            logger.warning(
                "Task recovery failed",
                agent=self._agent_name,
                error=str(exc),
            )
            return 0

    def __repr__(self) -> str:
        backend = "in-memory" if self._use_fallback else "redis"
        return (
            f"TaskQueue(agent={self._agent_name!r}, backend={backend})"
        )