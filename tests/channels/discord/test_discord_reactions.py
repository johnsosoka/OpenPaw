"""Tests for Discord reactions."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.discord.outbound import DiscordOutboundSender


class TestAddReaction:
    """Test DiscordOutboundSender.add_reaction."""

    @pytest.mark.asyncio
    async def test_add_reaction_calls_add_reaction_on_fetched_message(self):
        """add_reaction calls add_reaction on the fetched message."""
        client = MagicMock()
        message = MagicMock()
        message.add_reaction = AsyncMock()
        channel = MagicMock()
        channel.fetch_message = AsyncMock(return_value=message)
        client.get_channel = MagicMock(return_value=channel)
        sender = DiscordOutboundSender(client=client, channel_name="discord", bot_id=1)

        result = await sender.add_reaction("discord:123456", "789", "👀")

        assert result is True
        channel.fetch_message.assert_awaited_once_with(789)
        message.add_reaction.assert_awaited_once_with("👀")

    @pytest.mark.asyncio
    async def test_remove_reaction_calls_remove_reaction_with_bot_user(self):
        """remove_reaction calls remove_reaction on the fetched message with the bot user."""
        client = MagicMock()
        bot_user = MagicMock()
        client.user = bot_user
        message = MagicMock()
        message.remove_reaction = AsyncMock()
        channel = MagicMock()
        channel.fetch_message = AsyncMock(return_value=message)
        client.get_channel = MagicMock(return_value=channel)
        sender = DiscordOutboundSender(client=client, channel_name="discord", bot_id=1)

        result = await sender.remove_reaction("discord:123456", "789", "👀")

        assert result is True
        channel.fetch_message.assert_awaited_once_with(789)
        message.remove_reaction.assert_awaited_once_with("👀", bot_user)

    @pytest.mark.asyncio
    async def test_reaction_methods_handle_errors_gracefully(self):
        """Reaction methods return False on exceptions."""
        client = MagicMock()
        client.get_channel = MagicMock(side_effect=Exception("api error"))
        sender = DiscordOutboundSender(client=client, channel_name="discord", bot_id=1)

        add_result = await sender.add_reaction("discord:123456", "789", "👀")
        remove_result = await sender.remove_reaction("discord:123456", "789", "👀")

        assert add_result is False
        assert remove_result is False

    @pytest.mark.asyncio
    async def test_reaction_methods_return_false_when_client_not_started(self):
        """Reaction methods return False when client is None."""
        sender = DiscordOutboundSender(client=None, channel_name="discord", bot_id=1)

        add_result = await sender.add_reaction("discord:123456", "789", "👀")
        remove_result = await sender.remove_reaction("discord:123456", "789", "👀")

        assert add_result is False
        assert remove_result is False
