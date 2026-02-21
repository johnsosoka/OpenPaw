"""Queue manager for coordinating message processing across channels."""

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from openpaw.runtime.queue.lane import LaneQueue, QueueItem, QueueMode

logger = logging.getLogger(__name__)


@dataclass
class SessionQueue:
    """Per-session message queue with coalescing support."""

    session_key: str
    messages: deque[Any] = field(default_factory=deque)
    mode: QueueMode = QueueMode.COLLECT
    debounce_ms: int = 1000
    cap: int = 20
    drop_policy: str = "summarize"
    _debounce_task: asyncio.Task[None] | None = None


class QueueManager:
    """High-level queue manager coordinating message flow.

    Handles:
    - Per-session message collection and coalescing
    - Debouncing for rapid message sequences
    - Overflow policies (cap exceeded)
    - Delegation to lane queue for execution
    """

    def __init__(
        self,
        lane_queue: LaneQueue,
        default_mode: QueueMode = QueueMode.COLLECT,
        default_debounce_ms: int = 1000,
        default_cap: int = 20,
        default_drop_policy: str = "summarize",
    ):
        """Initialize the queue manager.

        Args:
            lane_queue: The underlying lane queue for execution.
            default_mode: Default queue mode for new sessions.
            default_debounce_ms: Default debounce delay.
            default_cap: Default max messages per session.
            default_drop_policy: Default overflow policy.
        """
        self.lane_queue = lane_queue
        self.default_mode = default_mode
        self.default_debounce_ms = default_debounce_ms
        self.default_cap = default_cap
        self.default_drop_policy = default_drop_policy

        self._sessions: dict[str, SessionQueue] = {}
        self._handlers: dict[str, Callable[[str, list[Any]], Coroutine[Any, Any, Any]]] = {}
        self._lock = asyncio.Lock()

    async def register_handler(
        self,
        channel_name: str,
        handler: Callable[[str, list[Any]], Coroutine[Any, Any, Any]],
    ) -> None:
        """Register a handler for a channel.

        Args:
            channel_name: Channel identifier (e.g., 'telegram', 'discord').
            handler: Async function taking (session_key, messages) and processing them.
        """
        self._handlers[channel_name] = handler

    async def _get_or_create_session(self, session_key: str) -> SessionQueue:
        """Get or create a session queue."""
        async with self._lock:
            if session_key not in self._sessions:
                self._sessions[session_key] = SessionQueue(
                    session_key=session_key,
                    mode=self.default_mode,
                    debounce_ms=self.default_debounce_ms,
                    cap=self.default_cap,
                    drop_policy=self.default_drop_policy,
                )
            return self._sessions[session_key]

    async def submit(
        self,
        session_key: str,
        channel_name: str,
        message: Any,
        mode: QueueMode | None = None,
    ) -> None:
        """Submit a message for processing.

        Args:
            session_key: Unique session identifier.
            channel_name: Which channel this came from.
            message: The message payload.
            mode: Override queue mode for this message.
        """
        session = await self._get_or_create_session(session_key)
        effective_mode = mode or session.mode

        if effective_mode == QueueMode.STEER:
            await self._handle_steer(session_key, channel_name, message)
        elif effective_mode == QueueMode.INTERRUPT:
            await self._handle_interrupt(session_key, channel_name, message)
        else:
            await self._collect_message(session, channel_name, message)

    async def _handle_steer(self, session_key: str, channel_name: str, message: Any) -> None:
        """Handle steer mode - immediate injection."""
        handler = self._handlers.get(channel_name)
        if handler:
            item = QueueItem(session_key=session_key, payload=(channel_name, [message]), mode=QueueMode.STEER)
            await self.lane_queue.enqueue(item, lane_name="main")

    async def _handle_interrupt(self, session_key: str, channel_name: str, message: Any) -> None:
        """Handle interrupt mode - abort and execute newest."""
        handler = self._handlers.get(channel_name)
        if handler:
            item = QueueItem(session_key=session_key, payload=(channel_name, [message]), mode=QueueMode.INTERRUPT)
            await self.lane_queue.enqueue(item, lane_name="main")

    async def _collect_message(self, session: SessionQueue, channel_name: str, message: Any) -> None:
        """Collect message for coalescing."""
        if len(session.messages) >= session.cap:
            self._apply_drop_policy(session)

        session.messages.append((channel_name, message))

        if session._debounce_task:
            session._debounce_task.cancel()

        session._debounce_task = asyncio.create_task(self._debounce_flush(session))

    def _apply_drop_policy(self, session: SessionQueue) -> None:
        """Apply overflow policy when cap is exceeded."""
        if session.drop_policy == "old":
            session.messages.popleft()
        elif session.drop_policy == "new":
            pass
        elif session.drop_policy == "summarize":
            session.messages.popleft()

    async def _debounce_flush(self, session: SessionQueue) -> None:
        """Wait for debounce period then flush collected messages."""
        try:
            await asyncio.sleep(session.debounce_ms / 1000.0)
            await self._flush_session(session)
        except asyncio.CancelledError:
            pass

    async def _flush_session(self, session: SessionQueue) -> None:
        """Flush collected messages to the lane queue."""
        if not session.messages:
            return

        messages_by_channel: dict[str, list[Any]] = {}
        while session.messages:
            channel_name, msg = session.messages.popleft()
            if channel_name not in messages_by_channel:
                messages_by_channel[channel_name] = []
            messages_by_channel[channel_name].append(msg)

        for channel_name, msgs in messages_by_channel.items():
            item = QueueItem(
                session_key=session.session_key,
                payload=(channel_name, msgs),
                mode=session.mode,
            )
            await self.lane_queue.enqueue(item, lane_name="main")

    async def set_session_mode(self, session_key: str, mode: QueueMode) -> None:
        """Update queue mode for a session."""
        session = await self._get_or_create_session(session_key)
        session.mode = mode

    async def set_session_config(
        self,
        session_key: str,
        debounce_ms: int | None = None,
        cap: int | None = None,
        drop_policy: str | None = None,
    ) -> None:
        """Update configuration for a session."""
        session = await self._get_or_create_session(session_key)
        if debounce_ms is not None:
            session.debounce_ms = debounce_ms
        if cap is not None:
            session.cap = cap
        if drop_policy is not None:
            session.drop_policy = drop_policy

    async def peek_pending(self, session_key: str) -> bool:
        """Check if session has pending messages without removing them.

        Checks both the session's pre-debounce buffer AND the lane queue
        for messages that have already been flushed. This ensures the
        middleware detects pending messages regardless of debounce timing.

        Args:
            session_key: The session to check.

        Returns:
            True if there are pending messages anywhere in the pipeline.
        """
        # Check pre-debounce session buffer
        async with self._lock:
            if session_key in self._sessions:
                session = self._sessions[session_key]
                buf_count = len(session.messages)
                if buf_count > 0:
                    logger.debug(f"peek_pending: {buf_count} in session buffer for {session_key}")
                    return True

        # Check lane queue for already-flushed items
        lane_pending = await self.lane_queue.peek_session_pending(session_key)
        logger.debug(f"peek_pending: lane_queue has_pending={lane_pending} for {session_key}")
        return lane_pending

    async def consume_pending(self, session_key: str) -> list[Any]:
        """Remove and return all pending messages for a session.

        Drains both the session's pre-debounce buffer AND any items
        already flushed to the lane queue.

        Returns list of (channel_name, message) tuples, matching the
        format used by _collect_message() and _flush_session().

        Args:
            session_key: The session to consume from.

        Returns:
            List of (channel_name, message) tuples (may be empty).
        """
        messages: list[Any] = []

        # Drain pre-debounce session buffer — already (channel_name, msg) tuples
        async with self._lock:
            if session_key in self._sessions:
                session = self._sessions[session_key]

                # Cancel pending debounce task if any
                if session._debounce_task:
                    session._debounce_task.cancel()
                    session._debounce_task = None

                messages.extend(list(session.messages))
                session.messages.clear()

        # Drain lane queue for already-flushed items
        lane_items = await self.lane_queue.consume_session_pending(session_key)
        for item in lane_items:
            # QueueItem.payload is (channel_name, [msg1, msg2, ...]) from _flush_session
            if isinstance(item.payload, tuple) and len(item.payload) == 2:
                channel_name, msg_list = item.payload
                if isinstance(msg_list, list):
                    for msg in msg_list:
                        messages.append((channel_name, msg))
                else:
                    messages.append((channel_name, msg_list))
            else:
                messages.append(("unknown", item.payload))

        return messages
