"""Tests for Telegram typing indicator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.telegram.outbound import TelegramOutboundSender


class TestSendTyping:
    """Test TelegramOutboundSender.send_typing."""

    @pytest.mark.asyncio
    async def test_send_typing_sends_chat_action(self):
        """send_typing sends send_chat_action with action='typing'."""
        app = MagicMock()
        app.bot.send_chat_action = AsyncMock()
        sender = TelegramOutboundSender(app=app, channel_name="telegram", bot_id=1)

        await sender.send_typing("telegram:123456")

        app.bot.send_chat_action.assert_awaited_once_with(chat_id=123456, action="typing")

    @pytest.mark.asyncio
    async def test_send_typing_handles_errors_gracefully(self):
        """send_typing silently catches exceptions."""
        app = MagicMock()
        app.bot.send_chat_action = AsyncMock(side_effect=Exception("network error"))
        sender = TelegramOutboundSender(app=app, channel_name="telegram", bot_id=1)

        # Should not raise
        await sender.send_typing("telegram:123456")

    @pytest.mark.asyncio
    async def test_send_typing_is_noop_when_app_not_started(self):
        """send_typing is a no-op when app is None."""
        sender = TelegramOutboundSender(app=None, channel_name="telegram", bot_id=1)

        # Should not raise
        await sender.send_typing("telegram:123456")
