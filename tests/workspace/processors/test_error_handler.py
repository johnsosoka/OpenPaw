"""Tests for ErrorHandler."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.core.config.models import AutoCompactConfig
from openpaw.workspace.processors.compactor import AutoCompactor
from openpaw.workspace.processors.error_handler import ErrorHandler, ErrorResult


@pytest.fixture
def handler():
    return ErrorHandler(
        logger=logging.getLogger("test"),
        compactor=AutoCompactor(
            session_manager=MagicMock(),
            conversation_archiver=AsyncMock(),
            auto_compact_config=AutoCompactConfig(enabled=True, trigger=0.8),
            lifecycle_config=None,
            logger=logging.getLogger("test"),
        ),
    )


class TestErrorResult:
    def test_continue(self):
        result = ErrorResult(action="continue", combined_content="new")
        assert result.action == "continue"
        assert result.combined_content == "new"

    def test_break(self):
        result = ErrorResult(action="break")
        assert result.action == "break"
        assert result.combined_content is None


class TestHandle:
    @pytest.mark.asyncio
    async def test_context_overflow_returns_continue(self, handler):
        from fireworks.client.error import InvalidRequestError
        err = InvalidRequestError(
            '{"error": {"message": "The prompt is too long: 262377, model maximum context length: 262143"}}'
        )
        handler._compactor._session_manager.get_thread_id = MagicMock(return_value="new_thread")
        handler._compactor._session_manager.new_conversation = MagicMock(return_value="conv_new")

        result = await handler.handle(
            error=err,
            channel=AsyncMock(),
            session_key="s1",
            thread_id="t1",
            agent_runner=MagicMock(checkpointer=MagicMock()),
        )
        assert result.action == "continue"
        assert result.combined_content is not None
        assert "archived" in result.combined_content

    @pytest.mark.asyncio
    async def test_generic_error_sends_message_and_breaks(self, handler):
        channel = AsyncMock()
        result = await handler.handle(
            error=RuntimeError("db error"),
            channel=channel,
            session_key="s1",
            thread_id="t1",
            agent_runner=MagicMock(),
        )
        assert result.action == "break"
        channel.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_generic_error_no_channel_breaks(self, handler):
        result = await handler.handle(
            error=RuntimeError("db error"),
            channel=None,
            session_key="s1",
            thread_id="t1",
            agent_runner=MagicMock(),
        )
        assert result.action == "break"
