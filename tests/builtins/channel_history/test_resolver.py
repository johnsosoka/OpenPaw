"""Tests for channel history resolver functions."""

from unittest.mock import MagicMock, patch

from openpaw.builtins.tools.channel_history.resolver import (
    _resolve_adapter,
    _resolve_channel_id,
)
from openpaw.channels.base import ChannelAdapter


def _make_mock_discord_channel(name: str = "discord") -> MagicMock:
    """Build a MagicMock ChannelAdapter that supports history browsing."""
    from openpaw.channels.discord import DiscordChannel
    channel = MagicMock(spec=DiscordChannel)
    channel.name = name
    channel.supports_history_browsing = True
    return channel


def test_resolve_adapter_single_auto_select() -> None:
    """Single history-capable channel is auto-selected when channel=None."""
    ch = _make_mock_discord_channel()
    channels = {"discord": ch}
    adapter, error = _resolve_adapter(channels, channel_name=None)
    assert adapter is ch
    assert error is None


def test_resolve_adapter_multi_requires_explicit() -> None:
    """Multiple channels require explicit channel= parameter."""
    channels = {
        "discord": _make_mock_discord_channel(),
        "discord-work": _make_mock_discord_channel(name="discord-work"),
    }
    adapter, error = _resolve_adapter(channels, channel_name=None)
    assert adapter is None
    assert "Multiple history-capable channels" in error
    assert "discord" in error
    assert "discord-work" in error


def test_resolve_adapter_explicit_found() -> None:
    """Explicit channel= that exists is returned."""
    ch = _make_mock_discord_channel()
    channels = {"discord": ch, "discord-work": _make_mock_discord_channel(name="discord-work")}
    adapter, error = _resolve_adapter(channels, channel_name="discord")
    assert adapter is ch
    assert error is None


def test_resolve_adapter_explicit_not_found() -> None:
    """Explicit channel= that does not exist returns a descriptive error."""
    channels = {"discord": _make_mock_discord_channel()}
    adapter, error = _resolve_adapter(channels, channel_name="slack")
    assert adapter is None
    assert "slack" in error
    assert "discord" in error


def test_resolve_channel_id_malformed_session_key() -> None:
    """_resolve_channel_id handles session keys without a colon gracefully."""
    mock_adapter = MagicMock(spec=ChannelAdapter)

    with patch(
        "openpaw.builtins.tools.channel_history.resolver.get_current_session_key",
        return_value="nocolonhere",
    ):
        channel_id, error = _resolve_channel_id(mock_adapter)

    assert error is not None
    assert "Error" in error
    assert channel_id == ""
