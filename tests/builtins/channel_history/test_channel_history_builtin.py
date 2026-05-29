"""Tests for ChannelHistoryToolBuiltin metadata, init, and set_channels."""

from unittest.mock import MagicMock

from openpaw.builtins.tools.channel_history import ChannelHistoryToolBuiltin
from openpaw.channels.discord import DiscordChannel


def _make_mock_discord_channel(
    name: str = "discord",
    entries: list | None = None,
) -> MagicMock:
    """Build a MagicMock ChannelAdapter that supports history browsing."""
    channel = MagicMock(spec=DiscordChannel)
    channel.name = name
    channel.supports_history_browsing = True
    from unittest.mock import AsyncMock
    channel.fetch_channel_history = AsyncMock(return_value=entries or [])
    return channel


def test_metadata() -> None:
    """Metadata fields are correctly defined."""
    meta = ChannelHistoryToolBuiltin.metadata
    assert meta.name == "channel_history"
    assert meta.display_name == "Channel History Browser"
    assert meta.group == "communication"
    assert meta.builtin_type.value == "tool"
    assert len(meta.prerequisites.env_vars) == 0  # Runtime gating, no env vars


def test_initialization_defaults() -> None:
    """Default config values are applied correctly."""
    t = ChannelHistoryToolBuiltin()
    assert t.max_messages_per_request == 100
    assert t.content_truncation == 500
    assert t._channels is None


def test_initialization_with_config() -> None:
    """Custom config values override defaults."""
    t = ChannelHistoryToolBuiltin(config={"max_messages_per_request": 50, "content_truncation": 200})
    assert t.max_messages_per_request == 50
    assert t.content_truncation == 200


def test_get_langchain_tool_returns_list() -> None:
    """get_langchain_tool returns a one-element list."""
    t = ChannelHistoryToolBuiltin()
    tools = t.get_langchain_tool()
    assert isinstance(tools, list)
    assert len(tools) == 1
    assert tools[0].name == "browse_channel_history"


def test_set_channels_stores_reference() -> None:
    """set_channels stores the channels dict on the instance."""
    t = ChannelHistoryToolBuiltin()
    channels = {"discord": _make_mock_discord_channel()}
    t.set_channels(channels)
    assert t._channels is channels


def test_set_channels_overrides_previous() -> None:
    """Calling set_channels twice replaces the previous reference."""
    t = ChannelHistoryToolBuiltin()
    ch1 = {"discord": _make_mock_discord_channel()}
    ch2 = {"discord-work": _make_mock_discord_channel(name="discord-work")}
    t.set_channels(ch1)
    t.set_channels(ch2)
    assert t._channels is ch2


def test_base_adapter_does_not_support_history() -> None:
    """ChannelAdapter base property returns False by default."""
    from openpaw.channels.base import ChannelAdapter
    channel = MagicMock(spec=ChannelAdapter)
    channel.supports_history_browsing = False
    assert channel.supports_history_browsing is False


def test_discord_supports_history() -> None:
    """DiscordChannel.supports_history_browsing returns True."""
    channel = _make_mock_discord_channel()
    assert channel.supports_history_browsing is True
