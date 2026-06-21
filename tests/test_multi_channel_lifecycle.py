"""Tests for multi-channel lifecycle management (LifecycleManager.setup_channels)."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.workspace.lifecycle import LifecycleManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lifecycle(merged_config: dict) -> LifecycleManager:
    """Build a LifecycleManager with mocked dependencies for testing."""
    return LifecycleManager(
        workspace_name="test_ws",
        workspace_path=Path("/tmp/test_ws"),
        workspace_config=None,
        merged_config=merged_config,
        config=MagicMock(),
        queue_manager=AsyncMock(),
        message_handler=AsyncMock(),
        queue_handler=AsyncMock(),
        builtin_loader=MagicMock(),
        workspace_timezone="UTC",
        session_manager=MagicMock(),
        approval_handler=AsyncMock(),
        logger=logging.getLogger("test"),
    )


def _make_mock_adapter(name: str) -> MagicMock:
    """Return a MagicMock shaped like a ChannelAdapter with the given name."""
    adapter = MagicMock(spec=ChannelAdapter)
    adapter.name = name
    return adapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("openpaw.workspace.lifecycle.create_channel")
async def test_setup_single_channel(mock_create_channel):
    """Single channel in list is created and registered correctly."""
    adapter = _make_mock_adapter("telegram")
    mock_create_channel.return_value = adapter

    lm = _make_lifecycle({"channels": [{"type": "telegram", "token": "tok123"}]})
    channels = await lm.setup_channels()

    assert list(channels.keys()) == ["telegram"]
    assert channels["telegram"] is adapter

    mock_create_channel.assert_called_once_with(
        "telegram",
        {"type": "telegram", "token": "tok123"},
        "test_ws",
        channel_name="telegram",
    )
    adapter.on_message.assert_called_once()
    lm._queue_manager.register_handler.assert_awaited_once_with("telegram", lm._queue_handler)


@pytest.mark.asyncio
@patch("openpaw.workspace.lifecycle.create_channel")
async def test_setup_multiple_channels(mock_create_channel):
    """Two channels of different types are both created and keyed by type name."""
    tg_adapter = _make_mock_adapter("telegram")
    dc_adapter = _make_mock_adapter("discord")
    mock_create_channel.side_effect = [tg_adapter, dc_adapter]

    lm = _make_lifecycle(
        {
            "channels": [
                {"type": "telegram", "token": "tg-tok"},
                {"type": "discord", "token": "dc-tok"},
            ]
        }
    )
    channels = await lm.setup_channels()

    assert set(channels.keys()) == {"telegram", "discord"}
    assert channels["telegram"] is tg_adapter
    assert channels["discord"] is dc_adapter

    assert mock_create_channel.call_count == 2
    assert lm._queue_manager.register_handler.await_count == 2
    tg_adapter.on_message.assert_called_once()
    dc_adapter.on_message.assert_called_once()


@pytest.mark.asyncio
async def test_setup_no_channels_raises():
    """Empty channels list raises ValueError with workspace name in message."""
    lm = _make_lifecycle({"channels": []})

    with pytest.raises(ValueError, match="test_ws"):
        await lm.setup_channels()


@pytest.mark.asyncio
async def test_setup_missing_channels_key_raises():
    """Absent 'channels' key (defaults to []) raises ValueError."""
    lm = _make_lifecycle({})

    with pytest.raises(ValueError, match="test_ws"):
        await lm.setup_channels()


@pytest.mark.asyncio
async def test_setup_missing_token_raises():
    """Channel config without a token raises ValueError before calling factory."""
    lm = _make_lifecycle({"channels": [{"type": "telegram"}]})

    with pytest.raises(ValueError, match="token"):
        await lm.setup_channels()


@pytest.mark.asyncio
@patch("openpaw.workspace.lifecycle.create_channel")
async def test_setup_custom_channel_name(mock_create_channel):
    """Explicit 'name' field is used as the dict key instead of the channel type."""
    adapter = _make_mock_adapter("my-tg")
    mock_create_channel.return_value = adapter

    lm = _make_lifecycle(
        {"channels": [{"type": "telegram", "token": "tok", "name": "my-tg"}]}
    )
    channels = await lm.setup_channels()

    assert "my-tg" in channels
    assert "telegram" not in channels

    mock_create_channel.assert_called_once_with(
        "telegram",
        {"type": "telegram", "token": "tok", "name": "my-tg"},
        "test_ws",
        channel_name="my-tg",
    )
    lm._queue_manager.register_handler.assert_awaited_once_with("my-tg", lm._queue_handler)


@pytest.mark.asyncio
async def test_setup_duplicate_names_raises():
    """Two channels that resolve to the same name raise ValueError."""
    lm = _make_lifecycle(
        {
            "channels": [
                {"type": "telegram", "token": "tok1", "name": "primary"},
                {"type": "discord", "token": "tok2", "name": "primary"},
            ]
        }
    )

    with pytest.raises(ValueError, match="duplicate channel name.*primary"):
        await lm.setup_channels()


@pytest.mark.asyncio
async def test_setup_duplicate_type_without_names_raises():
    """Two telegram channels without explicit names both resolve to 'telegram', raising ValueError."""
    lm = _make_lifecycle(
        {
            "channels": [
                {"type": "telegram", "token": "tok1"},
                {"type": "telegram", "token": "tok2"},
            ]
        }
    )

    with pytest.raises(ValueError, match="duplicate channel name.*telegram"):
        await lm.setup_channels()


@pytest.mark.asyncio
@patch("openpaw.workspace.lifecycle.create_channel")
async def test_setup_same_type_with_different_names(mock_create_channel):
    """Two telegram channels with distinct explicit names succeed without conflict."""
    adapter_a = _make_mock_adapter("tg-main")
    adapter_b = _make_mock_adapter("tg-alerts")
    mock_create_channel.side_effect = [adapter_a, adapter_b]

    lm = _make_lifecycle(
        {
            "channels": [
                {"type": "telegram", "token": "tok1", "name": "tg-main"},
                {"type": "telegram", "token": "tok2", "name": "tg-alerts"},
            ]
        }
    )
    channels = await lm.setup_channels()

    assert set(channels.keys()) == {"tg-main", "tg-alerts"}
    assert channels["tg-main"] is adapter_a
    assert channels["tg-alerts"] is adapter_b

    assert mock_create_channel.call_count == 2
    mock_create_channel.assert_any_call(
        "telegram",
        {"type": "telegram", "token": "tok1", "name": "tg-main"},
        "test_ws",
        channel_name="tg-main",
    )
    mock_create_channel.assert_any_call(
        "telegram",
        {"type": "telegram", "token": "tok2", "name": "tg-alerts"},
        "test_ws",
        channel_name="tg-alerts",
    )


@pytest.mark.asyncio
@patch("openpaw.workspace.lifecycle.create_channel")
async def test_setup_returns_internal_channels_dict(mock_create_channel):
    """Return value is the same object as lm.get_channels() (not a copy)."""
    adapter = _make_mock_adapter("telegram")
    mock_create_channel.return_value = adapter

    lm = _make_lifecycle({"channels": [{"type": "telegram", "token": "tok"}]})
    channels = await lm.setup_channels()

    assert channels is lm.get_channels()


@pytest.mark.asyncio
@patch("openpaw.workspace.lifecycle.create_channel")
async def test_setup_queue_handler_registered_per_channel(mock_create_channel):
    """register_handler is called once for each channel with the right lane name."""
    adapters = [_make_mock_adapter("telegram"), _make_mock_adapter("discord")]
    mock_create_channel.side_effect = adapters

    lm = _make_lifecycle(
        {
            "channels": [
                {"type": "telegram", "token": "tok1"},
                {"type": "discord", "token": "tok2"},
            ]
        }
    )
    await lm.setup_channels()

    call_args_list = lm._queue_manager.register_handler.await_args_list
    registered_names = [call.args[0] for call in call_args_list]
    assert registered_names == ["telegram", "discord"]
