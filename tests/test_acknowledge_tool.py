"""Tests for the acknowledge_event builtin tool and message_processor integration.

Covers:
- AcknowledgeTool unit behaviour (contextvar flag lifecycle)
- MessageProcessor._is_system_event_batch() helper
- MessageProcessor integration: acknowledgment suppresses channel delivery
  for system events but not for user messages
"""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.builtins.tools.acknowledge import AcknowledgeTool
from openpaw.model.message import Message
from openpaw.workspace.message_processor import MessageProcessor
from openpaw.workspace.processors.response_handler import ResponseHandler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(user_id: str, content: str = "hello") -> Message:
    """Build a minimal Message with the given user_id."""
    return Message(
        id="1",
        channel="telegram",
        session_key=f"telegram:{user_id}",
        user_id=user_id,
        content=content,
    )


def _system_message(content: str = "[SYSTEM] cron result") -> Message:
    """Build a system-injected message."""
    return _make_message(user_id="system", content=content)


def _user_message(content: str = "hello") -> Message:
    """Build a regular user message."""
    return _make_message(user_id="42", content=content)


def _make_processor(
    builtin_loader: MagicMock | None = None,
    session_manager: MagicMock | None = None,
) -> MessageProcessor:
    """Construct a MessageProcessor with enough mocks to exercise delivery logic."""
    if builtin_loader is None:
        builtin_loader = MagicMock()
        builtin_loader.get_tool_instance.return_value = None

    if session_manager is None:
        session_manager = MagicMock()
        session_manager.get_thread_id.return_value = "telegram:42:conv_1"
        session_manager.is_session_expired.return_value = False

    agent_runner = AsyncMock()
    agent_runner.run = AsyncMock(return_value="agent response text")
    agent_runner.last_metrics = None
    agent_runner.last_tools_used = []
    agent_runner.checkpointer = None

    queue_manager = MagicMock()
    queue_manager.get_session_mode = AsyncMock(return_value=MagicMock(value="collect"))
    queue_manager.peek_pending = AsyncMock(return_value=False)

    queue_middleware = MagicMock()
    queue_middleware.was_steered = False
    queue_middleware.pending_steer_message = None
    queue_middleware.reset = MagicMock()

    approval_middleware = MagicMock()
    approval_middleware.reset = MagicMock()

    return MessageProcessor(
        agent_runner=agent_runner,
        session_manager=session_manager,
        queue_manager=queue_manager,
        builtin_loader=builtin_loader,
        queue_middleware=queue_middleware,
        approval_middleware=approval_middleware,
        approval_manager=None,
        workspace_name="test-workspace",
        token_logger=MagicMock(),
        logger=logging.getLogger("test"),
    )


# ---------------------------------------------------------------------------
# 1. AcknowledgeTool unit tests
# ---------------------------------------------------------------------------


@pytest.fixture
def ack_tool() -> AcknowledgeTool:
    tool = AcknowledgeTool(config={})
    tool.reset()
    return tool


@pytest.fixture
def ack_fn(ack_tool: AcknowledgeTool):
    """Return the raw acknowledge_event callable from the LangChain tool."""
    tool = ack_tool.get_langchain_tool()
    return tool.func


class TestAcknowledgeToolMetadata:
    def test_name(self, ack_tool: AcknowledgeTool) -> None:
        assert ack_tool.metadata.name == "acknowledge"

    def test_group(self, ack_tool: AcknowledgeTool) -> None:
        assert ack_tool.metadata.group == "automation"

    def test_prerequisites_satisfied(self, ack_tool: AcknowledgeTool) -> None:
        assert ack_tool.metadata.prerequisites.is_satisfied()

    def test_langchain_tool_name(self, ack_tool: AcknowledgeTool) -> None:
        lc_tool = ack_tool.get_langchain_tool()
        assert lc_tool.name == "acknowledge_event"


class TestAcknowledgeToolFlag:
    def test_sets_flag(self, ack_fn, ack_tool: AcknowledgeTool) -> None:
        """Calling the tool sets the contextvar and get_pending_ack returns it."""
        result = ack_fn(reason="routine check, nothing to report")

        assert "acknowledged" in result.lower() or "Event acknowledged" in result
        ack = ack_tool.get_pending_ack()
        assert ack is not None
        assert ack.reason == "routine check, nothing to report"

    def test_clears_on_get(self, ack_fn, ack_tool: AcknowledgeTool) -> None:
        """get_pending_ack() returns None on the second call (get-and-clear)."""
        ack_fn(reason="all quiet")
        ack_tool.get_pending_ack()  # consume
        assert ack_tool.get_pending_ack() is None

    def test_single_per_invocation(self, ack_fn, ack_tool: AcknowledgeTool) -> None:
        """A second call to acknowledge_event returns an error message."""
        ack_fn(reason="first")
        second_result = ack_fn(reason="second")
        assert "already pending" in second_result.lower()

        # The first acknowledgment is still intact
        ack = ack_tool.get_pending_ack()
        assert ack is not None
        assert ack.reason == "first"

    def test_reset_clears_pending(self, ack_fn, ack_tool: AcknowledgeTool) -> None:
        """reset() discards any pending acknowledgment."""
        ack_fn(reason="something")
        ack_tool.reset()
        assert ack_tool.get_pending_ack() is None

    def test_reason_preserved_in_request(self, ack_fn, ack_tool: AcknowledgeTool) -> None:
        """The reason string is faithfully stored in AcknowledgeRequest."""
        reason = "daily health check passed, no anomalies found"
        ack_fn(reason=reason)
        ack = ack_tool.get_pending_ack()
        assert ack is not None
        assert ack.reason == reason

    def test_get_pending_ack_returns_none_when_not_set(self, ack_tool: AcknowledgeTool) -> None:
        """Returns None when no acknowledgment has been made."""
        assert ack_tool.get_pending_ack() is None


# ---------------------------------------------------------------------------
# 2. MessageProcessor._is_system_event_batch() unit tests
# ---------------------------------------------------------------------------


class TestIsSystemEventBatch:
    def test_empty_list_returns_false(self) -> None:
        assert ResponseHandler.is_system_event_batch([]) is False

    def test_all_system_returns_true(self) -> None:
        messages = [_system_message(), _system_message("another [SYSTEM] event")]
        assert ResponseHandler.is_system_event_batch(messages) is True

    def test_all_user_returns_false(self) -> None:
        messages = [_user_message(), _user_message("second")]
        assert ResponseHandler.is_system_event_batch(messages) is False

    def test_mixed_returns_false(self) -> None:
        messages = [_system_message(), _user_message()]
        assert ResponseHandler.is_system_event_batch(messages) is False

    def test_single_system_returns_true(self) -> None:
        assert ResponseHandler.is_system_event_batch([_system_message()]) is True

    def test_single_user_returns_false(self) -> None:
        assert ResponseHandler.is_system_event_batch([_user_message()]) is False


# ---------------------------------------------------------------------------
# 3. MessageProcessor integration tests
# ---------------------------------------------------------------------------


class TestAcknowledgeIntegration:
    """Integration tests for the acknowledge flag in process_messages()."""

    def _make_ack_tool_mock(self, pending_ack=None) -> MagicMock:
        """Create a mock AcknowledgeTool that returns a specific pending ack."""
        from openpaw.builtins.tools.acknowledge import AcknowledgeRequest

        mock_tool = MagicMock(spec=AcknowledgeTool)
        mock_tool.get_pending_ack.return_value = (
            AcknowledgeRequest(reason="routine, nothing to report")
            if pending_ack
            else None
        )
        mock_tool.reset = MagicMock()
        return mock_tool

    def _make_loader_with_ack(self, ack_pending: bool) -> MagicMock:
        """Build a BuiltinLoader mock where 'acknowledge' returns a configured tool."""
        ack_tool_mock = self._make_ack_tool_mock(pending_ack=ack_pending)

        loader = MagicMock()

        def get_tool_instance(name: str):
            if name == "acknowledge":
                return ack_tool_mock
            return None

        loader.get_tool_instance.side_effect = get_tool_instance
        return loader

    @pytest.mark.asyncio
    async def test_system_batch_suppresses_terminal_by_default(self) -> None:
        """System batch is always suppressed — no ack call needed."""
        loader = self._make_loader_with_ack(ack_pending=False)  # no ack
        processor = _make_processor(builtin_loader=loader)
        channel = AsyncMock()

        await processor.process_messages(
            session_key="telegram:system",
            messages=[_system_message()],
            channel=channel,
        )

        channel.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_ack_increments_message_count(self) -> None:
        """Message count is still incremented even when delivery is suppressed."""
        loader = self._make_loader_with_ack(ack_pending=False)  # no ack needed
        session_manager = MagicMock()
        session_manager.get_thread_id.return_value = "telegram:sys:conv_1"
        session_manager.is_session_expired.return_value = False

        processor = _make_processor(
            builtin_loader=loader,
            session_manager=session_manager,
        )

        await processor.process_messages(
            session_key="telegram:sys",
            messages=[_system_message()],
            channel=AsyncMock(),
        )

        session_manager.increment_message_count.assert_called_once_with("telegram:sys")

    @pytest.mark.asyncio
    async def test_acknowledge_ignored_for_user_messages(self) -> None:
        """User batch + acknowledge_event called → response still sent to channel."""
        loader = self._make_loader_with_ack(ack_pending=True)
        processor = _make_processor(builtin_loader=loader)
        channel = AsyncMock()

        await processor.process_messages(
            session_key="telegram:42",
            messages=[_user_message()],
            channel=channel,
        )

        # The ack flag is set but the batch is NOT a system batch, so delivery proceeds
        channel.send_message.assert_called_once()
        call_args = channel.send_message.call_args
        assert call_args.args[0] == "telegram:42"
        assert "agent response text" in call_args.args[1]

    @pytest.mark.asyncio
    async def test_mixed_batch_still_delivered(self) -> None:
        """Mixed batch (user + system) + ack → response still sent (not suppressed)."""
        loader = self._make_loader_with_ack(ack_pending=True)
        processor = _make_processor(builtin_loader=loader)
        channel = AsyncMock()

        await processor.process_messages(
            session_key="telegram:42",
            messages=[_system_message(), _user_message()],
            channel=channel,
        )

        channel.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_system_batch_no_ack_still_suppressed(self) -> None:
        """System batch with NO acknowledge call → terminal still suppressed (core bombardment fix)."""
        loader = self._make_loader_with_ack(ack_pending=False)
        processor = _make_processor(builtin_loader=loader)
        channel = AsyncMock()

        await processor.process_messages(
            session_key="telegram:sys",
            messages=[_system_message()],
            channel=channel,
        )

        channel.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_batch_no_ack_tool_still_suppressed(self) -> None:
        """System batch with no ack tool loaded → still suppressed (suppression is unconditional)."""
        loader = MagicMock()
        loader.get_tool_instance.return_value = None  # tool not loaded

        processor = _make_processor(builtin_loader=loader)
        channel = AsyncMock()

        await processor.process_messages(
            session_key="telegram:sys",
            messages=[_system_message()],
            channel=channel,
        )

        channel.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_batch_empty_response_no_fallback(self) -> None:
        """System batch + empty response → no fallback noise sent to channel."""
        loader = self._make_loader_with_ack(ack_pending=False)
        processor = _make_processor(builtin_loader=loader)
        # Override agent runner to return empty response
        processor._agent_runner.run = AsyncMock(return_value="")
        channel = AsyncMock()

        await processor.process_messages(
            session_key="telegram:sys",
            messages=[_system_message()],
            channel=channel,
        )

        channel.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_system_batch_with_ack_logs_audit_note(self) -> None:
        """System batch + acknowledge_event called → ack reason appears as audit note in log."""
        loader = self._make_loader_with_ack(ack_pending=True)
        processor = _make_processor(builtin_loader=loader)
        channel = AsyncMock()

        with patch.object(processor._logger, "info") as mock_log:
            await processor.process_messages(
                session_key="telegram:sys",
                messages=[_system_message()],
                channel=channel,
            )

        info_calls = [str(c) for c in mock_log.call_args_list]
        assert any("agent note:" in c for c in info_calls)
        channel.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_ack_reset_called_after_loop(self) -> None:
        """AcknowledgeTool.reset() is called after process_messages exits."""
        ack_tool_mock = MagicMock(spec=AcknowledgeTool)
        ack_tool_mock.get_pending_ack.return_value = None
        ack_tool_mock.reset = MagicMock()

        loader = MagicMock()

        def get_tool_instance(name: str):
            if name == "acknowledge":
                return ack_tool_mock
            return None

        loader.get_tool_instance.side_effect = get_tool_instance
        processor = _make_processor(builtin_loader=loader)

        await processor.process_messages(
            session_key="telegram:42",
            messages=[_user_message()],
            channel=AsyncMock(),
        )

        ack_tool_mock.reset.assert_called_once()
