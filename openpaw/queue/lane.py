"""Lane-based queue system inspired by OpenClaw's architecture."""

import asyncio
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class QueueMode(Enum):
    """Queue modes for handling inbound messages.

    Based on OpenClaw's queue modes:
    - STEER: Inject immediately into current run (cancels pending tool calls)
    - FOLLOWUP: Enqueue for next agent turn after current run ends
    - COLLECT: Coalesce all queued messages into single followup turn (default)
    - STEER_BACKLOG: Steer now AND preserve for followup turn
    - INTERRUPT: Abort active run, execute newest message
    """

    STEER = "steer"
    FOLLOWUP = "followup"
    COLLECT = "collect"
    STEER_BACKLOG = "steer-backlog"
    INTERRUPT = "interrupt"


@dataclass
class QueueItem:
    """An item in the queue waiting for processing."""

    session_key: str
    payload: Any
    mode: QueueMode = QueueMode.COLLECT
    priority: int = 0


@dataclass
class Lane:
    """A processing lane with configurable concurrency.

    Each lane maintains a FIFO queue and tracks active tasks.
    """

    name: str
    max_concurrency: int = 1
    queue: deque[QueueItem] = field(default_factory=deque)
    active_count: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _item_available: asyncio.Event = field(default_factory=asyncio.Event)

    def __hash__(self) -> int:
        return hash(self.name)


class LaneQueue:
    """Lane-aware FIFO queue that drains each lane with configurable concurrency.

    Architecture based on OpenClaw:
    - Session-specific lanes (session:<key>) ensure one active run per session
    - Global lanes (main, subagent, cron) cap overall parallelism
    - Messages are first queued by session, then by global lane
    """

    def __init__(
        self,
        main_concurrency: int = 4,
        subagent_concurrency: int = 8,
        cron_concurrency: int = 2,
    ):
        """Initialize the lane queue system.

        Args:
            main_concurrency: Max concurrent tasks in main lane.
            subagent_concurrency: Max concurrent tasks in subagent lane.
            cron_concurrency: Max concurrent tasks in cron lane.
        """
        self._lanes: dict[str, Lane] = {
            "main": Lane("main", main_concurrency),
            "subagent": Lane("subagent", subagent_concurrency),
            "cron": Lane("cron", cron_concurrency),
        }
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def get_lane(self, name: str) -> Lane:
        """Get or create a lane by name."""
        if name not in self._lanes:
            self._lanes[name] = Lane(name, max_concurrency=1)
        return self._lanes[name]

    async def get_session_lock(self, session_key: str) -> asyncio.Lock:
        """Get or create a lock for a specific session."""
        async with self._global_lock:
            if session_key not in self._session_locks:
                self._session_locks[session_key] = asyncio.Lock()
            return self._session_locks[session_key]

    async def enqueue(
        self,
        item: QueueItem,
        lane_name: str = "main",
    ) -> None:
        """Add an item to a lane's queue.

        Args:
            item: The queue item to add.
            lane_name: Which lane to add to (main, subagent, cron, or custom).
        """
        lane = self.get_lane(lane_name)
        async with lane._lock:
            lane.queue.append(item)
            lane._item_available.set()  # Signal that an item is available

    async def process(
        self,
        lane_name: str,
        handler: Callable[[QueueItem], Coroutine[Any, Any, Any]],
    ) -> None:
        """Process items from a lane using the provided handler.

        Respects concurrency limits and session serialization.

        Args:
            lane_name: Which lane to process.
            handler: Async function to handle each queue item.
        """
        lane = self.get_lane(lane_name)

        while True:
            item: QueueItem | None = None

            async with lane._lock:
                if lane.queue and lane.active_count < lane.max_concurrency:
                    item = lane.queue.popleft()
                    lane.active_count += 1

                # Clear event if queue is now empty (after potentially dequeuing)
                if not lane.queue:
                    lane._item_available.clear()

            if item is None:
                # Wait for signal that an item is available instead of polling
                await lane._item_available.wait()
                continue

            session_lock = await self.get_session_lock(item.session_key)

            try:
                async with session_lock:
                    await handler(item)
            finally:
                async with lane._lock:
                    lane.active_count -= 1

    async def peek_session_pending(self, session_key: str, lane_name: str = "main") -> bool:
        """Check if a session has pending items in a lane queue.

        Non-destructive check for use by steer/interrupt middleware.

        Args:
            session_key: Session to check for.
            lane_name: Lane to check (default: main).

        Returns:
            True if there are queued items for this session.
        """
        lane = self.get_lane(lane_name)
        async with lane._lock:
            return any(item.session_key == session_key for item in lane.queue)

    async def consume_session_pending(self, session_key: str, lane_name: str = "main") -> list[QueueItem]:
        """Remove and return all pending items for a session from a lane queue.

        Destructive operation for steer/interrupt middleware.

        Args:
            session_key: Session to consume for.
            lane_name: Lane to consume from (default: main).

        Returns:
            List of QueueItems removed from the lane queue.
        """
        lane = self.get_lane(lane_name)
        async with lane._lock:
            remaining = deque()
            consumed = []
            for item in lane.queue:
                if item.session_key == session_key:
                    consumed.append(item)
                else:
                    remaining.append(item)
            lane.queue = remaining
            if not lane.queue:
                lane._item_available.clear()
            return consumed

    def get_stats(self) -> dict[str, dict[str, int]]:
        """Get current queue statistics."""
        return {
            name: {
                "queued": len(lane.queue),
                "active": lane.active_count,
                "max_concurrency": lane.max_concurrency,
            }
            for name, lane in self._lanes.items()
        }
