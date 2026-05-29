"""Tests for context overflow detection and emergency recovery."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.core.config.models import AutoCompactConfig
from openpaw.core.utils import is_context_overflow_error, sanitize_error_for_user
from openpaw.workspace.processors.compactor import AutoCompactor


class TestIsContextOverflowError:
    """Test is_context_overflow_error() detection logic."""

    def test_fireworks_invalid_request_prompt_too_long(self):
        from fireworks.client.error import InvalidRequestError

        err = InvalidRequestError(
            '{"error": {"message": "The prompt is too long: 262377, model maximum context length: 262143"}}'
        )
        assert is_context_overflow_error(err) is True

    def test_fireworks_invalid_request_other_error(self):
        from fireworks.client.error import InvalidRequestError

        err = InvalidRequestError('{"error": {"message": "Invalid model name"}}')
        assert is_context_overflow_error(err) is False

    def test_generic_exception_with_context_length(self):
        class FakeError(Exception):
            pass

        err = FakeError("context_length_exceeded: too many tokens")
        assert is_context_overflow_error(err) is True

    def test_generic_exception_unrelated(self):
        err = RuntimeError("Database connection failed")
        assert is_context_overflow_error(err) is False

    def test_empty_error_message(self):
        err = RuntimeError("")
        assert is_context_overflow_error(err) is False

    def test_maximum_context_length_pattern(self):
        err = RuntimeError("maximum context length exceeded")
        assert is_context_overflow_error(err) is True


class TestSanitizeErrorForUser:
    """Test sanitize_error_for_user with context overflow."""

    def test_context_overflow_message(self):
        from fireworks.client.error import InvalidRequestError

        err = InvalidRequestError(
            '{"error": {"message": "The prompt is too long: 262377, model maximum context length: 262143"}}'
        )
        msg = sanitize_error_for_user(err)
        assert "too long" in msg.lower() or "context" in msg.lower()
        assert "fresh conversation" in msg

    def test_timeout_message_unchanged(self):
        err = TimeoutError()
        msg = sanitize_error_for_user(err)
        assert msg == "The request timed out. Please try again."

    def test_generic_error_message_unchanged(self):
        err = RuntimeError("database error")
        msg = sanitize_error_for_user(err)
        assert msg == "Something went wrong processing your message. Please try again."


@pytest.fixture
def mock_compactor():
    session_manager = MagicMock()
    archiver = AsyncMock()
    return AutoCompactor(
        session_manager=session_manager,
        conversation_archiver=archiver,
        auto_compact_config=AutoCompactConfig(enabled=True, trigger=0.8),
        lifecycle_config=None,
        logger=logging.getLogger("test"),
    )


class TestRecoverContextOverflow:
    """Test AutoCompactor.recover_overflow emergency recovery."""

    @pytest.mark.asyncio
    async def test_recovery_rotates_conversation(self, mock_compactor):
        mock_compactor._conversation_archiver.archive = AsyncMock()
        agent_runner = MagicMock()
        agent_runner.checkpointer = MagicMock()
        mock_compactor._session_manager.new_conversation = MagicMock(
            return_value="conv_recovered"
        )
        mock_compactor._session_manager.get_thread_id = MagicMock(
            return_value="telegram:123:conv_recovered"
        )
        mock_compactor._lifecycle_config = MagicMock(notify_auto_compact=False)

        result = await mock_compactor.recover_overflow(
            "telegram:123", "telegram:123:conv_old", None, agent_runner
        )

        assert result is not None
        assert "conv_recovered" in result
        mock_compactor._session_manager.new_conversation.assert_called_once_with(
            "telegram:123"
        )

    @pytest.mark.asyncio
    async def test_recovery_notifies_user(self, mock_compactor):
        mock_compactor._conversation_archiver.archive = AsyncMock()
        agent_runner = MagicMock()
        agent_runner.checkpointer = MagicMock()
        mock_compactor._session_manager.new_conversation = MagicMock(
            return_value="conv_recovered"
        )
        mock_compactor._session_manager.get_thread_id = MagicMock(
            return_value="telegram:123:conv_recovered"
        )
        mock_compactor._lifecycle_config = MagicMock(notify_auto_compact=True)

        channel = AsyncMock()
        result = await mock_compactor.recover_overflow(
            "telegram:123", "telegram:123:conv_old", channel, agent_runner
        )

        assert result is not None
        channel.send_message.assert_called_once()
        msg = channel.send_message.call_args.args[1]
        assert "archived" in msg.lower() or "fresh" in msg.lower()

    @pytest.mark.asyncio
    async def test_recovery_without_archiver(self, mock_compactor):
        mock_compactor._conversation_archiver = None
        mock_compactor._session_manager.new_conversation = MagicMock(
            return_value="conv_recovered"
        )
        mock_compactor._session_manager.get_thread_id = MagicMock(
            return_value="telegram:123:conv_recovered"
        )
        mock_compactor._lifecycle_config = MagicMock(notify_auto_compact=False)
        agent_runner = MagicMock()

        result = await mock_compactor.recover_overflow(
            "telegram:123", "telegram:123:conv_old", None, agent_runner
        )

        assert result is not None
        assert "conv_recovered" in result

    @pytest.mark.asyncio
    async def test_recovery_archive_failure_still_rotates(self, mock_compactor):
        mock_compactor._conversation_archiver.archive = AsyncMock(
            side_effect=Exception("archive failed")
        )
        agent_runner = MagicMock()
        agent_runner.checkpointer = MagicMock()
        mock_compactor._session_manager.new_conversation = MagicMock(
            return_value="conv_recovered"
        )
        mock_compactor._session_manager.get_thread_id = MagicMock(
            return_value="telegram:123:conv_recovered"
        )
        mock_compactor._lifecycle_config = MagicMock(notify_auto_compact=False)

        result = await mock_compactor.recover_overflow(
            "telegram:123", "telegram:123:conv_old", None, agent_runner
        )

        assert result is not None
        assert "conv_recovered" in result

    @pytest.mark.asyncio
    async def test_recovery_total_failure_returns_none(self, mock_compactor):
        mock_compactor._session_manager.new_conversation = MagicMock(
            side_effect=Exception("session manager broken")
        )
        mock_compactor._lifecycle_config = MagicMock(notify_auto_compact=False)
        agent_runner = MagicMock()

        result = await mock_compactor.recover_overflow(
            "telegram:123", "telegram:123:conv_old", None, agent_runner
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_recovery_tags_archive_context_overflow(self, mock_compactor):
        mock_compactor._conversation_archiver.archive = AsyncMock()
        agent_runner = MagicMock()
        agent_runner.checkpointer = MagicMock()
        mock_compactor._session_manager.new_conversation = MagicMock(
            return_value="conv_recovered"
        )
        mock_compactor._session_manager.get_thread_id = MagicMock(
            return_value="telegram:123:conv_recovered"
        )
        mock_compactor._lifecycle_config = MagicMock(notify_auto_compact=False)

        await mock_compactor.recover_overflow(
            "telegram:123", "telegram:123:conv_old", None, agent_runner
        )

        archive_call = mock_compactor._conversation_archiver.archive.call_args
        assert "context_overflow" in archive_call.kwargs["tags"]
