"""Tests for Discord typing indicator."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.discord.outbound import DiscordOutboundSender


class TestSendTyping:
    """Test DiscordOutboundSender.send_typing."""

    @pytest.mark.asyncio
    async def test_send_typing_calls_trigger_typing(self):
        """send_typing calls trigger_typing on the resolved channel."""
        client = MagicMock()
        channel = MagicMock()
        channel.trigger_typing = AsyncMock()
        client.get_channel = MagicMock(return_value=channel)
        sender = DiscordOutboundSender(client=client, channel_name="discord", bot_id=1)

        await sender.send_typing("discord:123456")

        channel.trigger_typing.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_typing_handles_errors_gracefully(self):
        """send_typing silently catches exceptions."""
        client = MagicMock()
        client.get_channel = MagicMock(side_effect=Exception("network error"))
        sender = DiscordOutboundSender(client=client, channel_name="discord", bot_id=1)

        # Should not raise
        await sender.send_typing("discord:123456")

    @pytest.mark.asyncio
    async def test_send_typing_is_noop_when_client_not_started(self):
        """send_typing is a no-op when client is None."""
        sender = DiscordOutboundSender(client=None, channel_name="discord", bot_id=1)

        # Should not raise
        await sender.send_typing("discord:123456")
