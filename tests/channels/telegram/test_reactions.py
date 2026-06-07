"""Tests for Telegram reactions."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.telegram.outbound import TelegramOutboundSender


class TestAddReaction:
    """Test TelegramOutboundSender.add_reaction."""

    @pytest.mark.asyncio
    async def test_add_reaction_calls_set_message_reaction(self):
        """add_reaction calls set_message_reaction with the correct payload."""
        app = MagicMock()
        app.bot.set_message_reaction = AsyncMock()
        sender = TelegramOutboundSender(app=app, channel_name="telegram", bot_id=1)

        result = await sender.add_reaction("telegram:123456", "42", "👀")

        assert result is True
        app.bot.set_message_reaction.assert_awaited_once_with(
            chat_id=123456,
            message_id=42,
            reaction=[{"type": "emoji", "emoji": "👀"}],
        )

    @pytest.mark.asyncio
    async def test_remove_reaction_calls_set_message_reaction_with_empty_list(self):
        """remove_reaction calls set_message_reaction with an empty reaction list."""
        app = MagicMock()
        app.bot.set_message_reaction = AsyncMock()
        sender = TelegramOutboundSender(app=app, channel_name="telegram", bot_id=1)

        result = await sender.remove_reaction("telegram:123456", "42", "👀")

        assert result is True
        app.bot.set_message_reaction.assert_awaited_once_with(
            chat_id=123456,
            message_id=42,
            reaction=[],
        )

    @pytest.mark.asyncio
    async def test_reaction_methods_handle_errors_gracefully(self):
        """Reaction methods return False on exceptions."""
        app = MagicMock()
        app.bot.set_message_reaction = AsyncMock(side_effect=Exception("api error"))
        sender = TelegramOutboundSender(app=app, channel_name="telegram", bot_id=1)

        add_result = await sender.add_reaction("telegram:123456", "42", "👀")
        remove_result = await sender.remove_reaction("telegram:123456", "42", "👀")

        assert add_result is False
        assert remove_result is False

    @pytest.mark.asyncio
    async def test_reaction_methods_return_false_when_app_not_started(self):
        """Reaction methods return False when app is None."""
        sender = TelegramOutboundSender(app=None, channel_name="telegram", bot_id=1)

        add_result = await sender.add_reaction("telegram:123456", "42", "👀")
        remove_result = await sender.remove_reaction("telegram:123456", "42", "👀")

        assert add_result is False
        assert remove_result is False
