"""Tests for ChannelAdapter base defaults."""

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.model.message import Message


class _MinimalChannel(ChannelAdapter):
    """Minimal concrete implementation for testing base defaults."""

    name = "minimal"

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(self, session_key: str, content: str, **kwargs) -> Message:
        raise NotImplementedError

    def on_message(self, callback) -> None:
        pass


class TestBaseDefaults:
    """Test default implementations in ChannelAdapter."""

    @pytest.mark.asyncio
    async def test_send_typing_is_noop(self):
        """send_typing default is a no-op."""
        channel = _MinimalChannel()
        # Should not raise
        await channel.send_typing("minimal:123")

    @pytest.mark.asyncio
    async def test_add_reaction_returns_false(self):
        """add_reaction default returns False."""
        channel = _MinimalChannel()
        result = await channel.add_reaction("minimal:123", "1", "👀")
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_reaction_returns_false(self):
        """remove_reaction default returns False."""
        channel = _MinimalChannel()
        result = await channel.remove_reaction("minimal:123", "1", "👀")
        assert result is False
