"""Tests for MessageProcessor reaction and typing lifecycle."""

import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.agent.middleware.queue_aware import InterruptSignalError
from openpaw.model.message import Message, MessageDirection
from openpaw.workspace.message_processor import MessageProcessor


def _make_message_processor(
    agent_runner: MagicMock | None = None,
    status_update_middleware: MagicMock | None = None,
    queue_middleware: MagicMock | None = None,
    approval_middleware: MagicMock | None = None,
    approval_manager: MagicMock | None = None,
    queue_manager: MagicMock | None = None,
    session_manager: MagicMock | None = None,
    builtin_loader: MagicMock | None = None,
    token_logger: MagicMock | None = None,
    conversation_archiver: MagicMock | None = None,
    auto_compact_config: MagicMock | None = None,
    lifecycle_config: MagicMock | None = None,
    status_reminder_middleware: MagicMock | None = None,
) -> MessageProcessor:
    """Create a MessageProcessor with sensible test defaults."""
    qm = queue_manager or MagicMock()
    qm.get_session_mode = AsyncMock(return_value=None)
    qm.peek_pending = AsyncMock(return_value=False)
    qm.consume_pending = AsyncMock(return_value=None)

    sm = session_manager or MagicMock()
    sm.get_thread_id = MagicMock(return_value="telegram:123:conv1")
    sm.increment_message_count = MagicMock()
    sm.is_session_expired = MagicMock(return_value=False)

    bl = builtin_loader or MagicMock()
    bl.get_tool_instance = MagicMock(return_value=None)

    qmw = queue_middleware or MagicMock()
    qmw.was_steered = False
    qmw.pending_steer_message = None

    sumw = status_update_middleware
    if sumw is not None:
        sumw.set_context = MagicMock()
        sumw.delete_status = AsyncMock()
        sumw.reset = MagicMock()

    srmw = status_reminder_middleware
    if srmw is not None:
        srmw.reset = MagicMock()

    return MessageProcessor(
        agent_runner=agent_runner or MagicMock(),
        session_manager=sm,
        queue_manager=qm,
        builtin_loader=bl,
        queue_middleware=qmw,
        approval_middleware=approval_middleware or MagicMock(),
        approval_manager=approval_manager,
        workspace_name="test_workspace",
        token_logger=token_logger or MagicMock(),
        logger=logging.getLogger("test"),
        conversation_archiver=conversation_archiver,
        auto_compact_config=auto_compact_config,
        lifecycle_config=lifecycle_config,
        status_reminder_middleware=srmw,
        status_update_middleware=sumw,
    )


def _make_inbound_message(
    content: str = "hello",
    user_id: str = "123",
    message_id: str = "1",
    metadata: dict | None = None,
) -> Message:
    """Create an inbound message for testing."""
    return Message(
        id=message_id,
        channel="telegram",
        session_key="telegram:123",
        user_id=user_id,
        content=content,
        direction=MessageDirection.INBOUND,
        timestamp=datetime.now(UTC),
        metadata=metadata or {},
    )


def _make_system_message(
    content: str = "cron result",
    message_id: str = "2",
) -> Message:
    """Create a system message for testing."""
    return Message(
        id=message_id,
        channel="telegram",
        session_key="telegram:123",
        user_id="system",
        content=content,
        direction=MessageDirection.INBOUND,
        timestamp=datetime.now(UTC),
    )


def _make_status_update_middleware(
    typing_indicator: bool = True,
    reactions: bool = True,
    enabled: bool = True,
) -> MagicMock:
    """Create a mock status update middleware with config."""
    config = MagicMock()
    config.typing_indicator = typing_indicator
    config.reactions = reactions
    config.enabled = enabled
    config.use_emojis = False
    config.agent_start = True
    config.tool_calls_detected = True
    config.subagent_spawned = True
    config.min_interval_seconds = 0
    config.max_updates_per_run = 10
    config.hermes_mode = True
    middleware = MagicMock()
    middleware._config = config
    return middleware


class MockChannel:
    """Minimal mock channel for reaction/typing tests."""

    def __init__(self):
        self.sent_messages: list[tuple[str, str]] = []
        self.typing_calls: list[str] = []
        self.reactions: list[tuple[str, str, str]] = []
        self.removed_reactions: list[tuple[str, str, str]] = []

    async def send_message(self, session_key: str, content: str) -> None:
        self.sent_messages.append((session_key, content))

    async def send_typing(self, session_key: str) -> None:
        self.typing_calls.append(session_key)

    async def add_reaction(self, session_key: str, message_id: str, emoji: str) -> bool:
        self.reactions.append((session_key, message_id, emoji))
        return True

    async def remove_reaction(self, session_key: str, message_id: str, emoji: str) -> bool:
        self.removed_reactions.append((session_key, message_id, emoji))
        return True


# ---------------------------------------------------------------------------
# Typing indicator
# ---------------------------------------------------------------------------


class TestTypingIndicator:
    """Test typing indicator lifecycle in process_messages."""

    @pytest.mark.asyncio
    async def test_sends_typing_when_enabled(self):
        """process_messages sends typing indicator when typing_indicator is enabled."""
        channel = MockChannel()
        agent_runner = MagicMock()
        agent_runner.run = AsyncMock(return_value="Hello")
        agent_runner.last_metrics = None
        middleware = _make_status_update_middleware(typing_indicator=True)
        processor = _make_message_processor(
            agent_runner=agent_runner,
            status_update_middleware=middleware,
        )

        messages = [_make_inbound_message()]
        await processor.process_messages("telegram:123", messages, channel)

        assert len(channel.typing_calls) == 1
        assert channel.typing_calls[0] == "telegram:123"

    @pytest.mark.asyncio
    async def test_skips_typing_when_disabled(self):
        """process_messages does not send typing when typing_indicator is disabled."""
        channel = MockChannel()
        agent_runner = MagicMock()
        agent_runner.run = AsyncMock(return_value="Hello")
        agent_runner.last_metrics = None
        middleware = _make_status_update_middleware(typing_indicator=False)
        processor = _make_message_processor(
            agent_runner=agent_runner,
            status_update_middleware=middleware,
        )

        messages = [_make_inbound_message()]
        await processor.process_messages("telegram:123", messages, channel)

        assert len(channel.typing_calls) == 0


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------


class TestReactions:
    """Test reaction lifecycle in process_messages."""

    @pytest.mark.asyncio
    async def test_adds_eyes_on_start_and_check_on_success(self):
        """👀 is added on start, then removed and ✅ added on success."""
        channel = MockChannel()
        agent_runner = MagicMock()
        agent_runner.run = AsyncMock(return_value="Hello")
        agent_runner.last_metrics = None
        middleware = _make_status_update_middleware(reactions=True)
        processor = _make_message_processor(
            agent_runner=agent_runner,
            status_update_middleware=middleware,
        )

        messages = [_make_inbound_message(message_id="42")]
        await processor.process_messages("telegram:123", messages, channel)

        assert ("telegram:123", "42", "👀") in channel.reactions
        assert ("telegram:123", "42", "👀") in channel.removed_reactions
        assert ("telegram:123", "42", "✅") in channel.reactions
        assert ("telegram:123", "42", "❌") not in channel.reactions

    @pytest.mark.asyncio
    async def test_adds_cross_on_failure(self):
        """❌ is added and 👀 removed when the agent run fails."""
        channel = MockChannel()
        agent_runner = MagicMock()
        agent_runner.run = AsyncMock(side_effect=RuntimeError("boom"))
        agent_runner.last_metrics = None
        middleware = _make_status_update_middleware(reactions=True)
        processor = _make_message_processor(
            agent_runner=agent_runner,
            status_update_middleware=middleware,
        )

        messages = [_make_inbound_message(message_id="42")]
        await processor.process_messages("telegram:123", messages, channel)

        assert ("telegram:123", "42", "👀") in channel.reactions
        assert ("telegram:123", "42", "👀") in channel.removed_reactions
        assert ("telegram:123", "42", "❌") in channel.reactions
        assert ("telegram:123", "42", "✅") not in channel.reactions

    @pytest.mark.asyncio
    async def test_interrupt_followed_by_success(self):
        """👀 stays through interrupt and is replaced by ✅ after re-run succeeds."""
        channel = MockChannel()
        agent_runner = MagicMock()
        agent_runner.run = AsyncMock(
            side_effect=[
                InterruptSignalError(
                    pending_messages=[("telegram", _make_inbound_message(content="new"))]
                ),
                "Hello",
            ]
        )
        agent_runner.last_metrics = None
        queue_manager = MagicMock()
        queue_manager.get_session_mode = AsyncMock(return_value=None)
        queue_manager.peek_pending = AsyncMock(return_value=False)
        middleware = _make_status_update_middleware(reactions=True)
        processor = _make_message_processor(
            agent_runner=agent_runner,
            status_update_middleware=middleware,
            queue_manager=queue_manager,
        )

        messages = [_make_inbound_message(message_id="42")]
        await processor.process_messages("telegram:123", messages, channel)

        # After interrupt, the loop re-runs and succeeds, so final reaction is success
        assert ("telegram:123", "42", "👀") in channel.reactions
        assert ("telegram:123", "42", "👀") in channel.removed_reactions
        assert ("telegram:123", "42", "✅") in channel.reactions

    @pytest.mark.asyncio
    async def test_skipped_when_disabled(self):
        """Reactions are skipped when reactions config is False."""
        channel = MockChannel()
        agent_runner = MagicMock()
        agent_runner.run = AsyncMock(return_value="Hello")
        agent_runner.last_metrics = None
        middleware = _make_status_update_middleware(reactions=False)
        processor = _make_message_processor(
            agent_runner=agent_runner,
            status_update_middleware=middleware,
        )

        messages = [_make_inbound_message(message_id="42")]
        await processor.process_messages("telegram:123", messages, channel)

        assert len(channel.reactions) == 0
        assert len(channel.removed_reactions) == 0

    @pytest.mark.asyncio
    async def test_skipped_for_system_only_batches(self):
        """Reactions are skipped when there is no user message to react to."""
        channel = MockChannel()
        agent_runner = MagicMock()
        agent_runner.run = AsyncMock(return_value="Hello")
        agent_runner.last_metrics = None
        middleware = _make_status_update_middleware(reactions=True)
        processor = _make_message_processor(
            agent_runner=agent_runner,
            status_update_middleware=middleware,
        )

        messages = [_make_system_message()]
        await processor.process_messages("telegram:123", messages, channel)

        assert len(channel.reactions) == 0
        assert len(channel.removed_reactions) == 0
