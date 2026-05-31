"""Tests for InterruptHandler."""

import logging
from unittest.mock import AsyncMock

import pytest

from openpaw.agent.middleware import InterruptSignalError
from openpaw.workspace.processors.combiner import ContentCombiner
from openpaw.workspace.processors.interrupt_handler import InterruptHandler


@pytest.fixture
def handler():
    return InterruptHandler(
        logger=logging.getLogger("test"),
        combiner=ContentCombiner(),
    )


class TestHandle:
    @pytest.mark.asyncio
    async def test_with_channel_sends_notification(self, handler):
        channel = AsyncMock()
        result = await handler.handle(
            error=InterruptSignalError([("ch1", "msg1")]),
            channel=channel,
            session_key="s1",
        )
        channel.send_message.assert_called_once_with("s1", "[Run interrupted — processing new message]")
        assert result == "msg1"

    @pytest.mark.asyncio
    async def test_no_channel_skips_notification(self, handler):
        result = await handler.handle(
            error=InterruptSignalError([("ch1", "msg1")]),
            channel=None,
            session_key="s1",
        )
        assert result == "msg1"

    @pytest.mark.asyncio
    async def test_builds_combined_content(self, handler):
        from openpaw.model.message import Message
        msg = Message(id="1", channel="tg", session_key="s1", user_id="123", content="hello")
        result = await handler.handle(
            error=InterruptSignalError([("ch1", msg)]),
            channel=None,
            session_key="s1",
        )
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_empty_pending_returns_empty(self, handler):
        result = await handler.handle(
            error=InterruptSignalError([]),
            channel=None,
            session_key="s1",
        )
        assert result == ""
