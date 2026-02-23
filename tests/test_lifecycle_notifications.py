"""Tests for lifecycle notifications."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.core.config.models import LifecycleConfig
from openpaw.workspace.runner import WorkspaceRunner


@pytest.fixture
def mock_runner():
    """Create a minimal mock WorkspaceRunner for notification tests."""
    runner = MagicMock(spec=WorkspaceRunner)
    runner.workspace_name = "test_workspace"
    runner.logger = MagicMock()

    # Create mock channel with allowed_users
    mock_channel = AsyncMock()
    mock_channel.name = "telegram"
    mock_channel._allowed_users = [12345]
    runner._channels = {"telegram": mock_channel}

    return runner


@pytest.mark.asyncio
async def test_notify_lifecycle_sends_to_channels(mock_runner):
    """Mock channels with allowed_users, verify send_message called."""
    # Call the real _notify_lifecycle method with our mock runner
    await WorkspaceRunner._notify_lifecycle(mock_runner, "Started")

    # Verify send_message was called
    mock_channel = mock_runner._channels["telegram"]
    mock_channel.send_message.assert_called_once()

    # Verify call args
    call_args = mock_channel.send_message.call_args
    session_key = call_args.args[0]
    message = call_args.args[1]

    assert session_key == "telegram:12345"
    assert "test_workspace" in message
    assert "Started" in message


@pytest.mark.asyncio
async def test_notify_lifecycle_with_detail(mock_runner):
    """Verify detail message is included in notification."""
    await WorkspaceRunner._notify_lifecycle(
        mock_runner, "Auto-compacted", "150 messages archived"
    )

    mock_channel = mock_runner._channels["telegram"]
    call_args = mock_channel.send_message.call_args
    message = call_args.args[1]

    assert "test_workspace" in message
    assert "Auto-compacted" in message
    assert "150 messages archived" in message


@pytest.mark.asyncio
async def test_notify_lifecycle_handles_no_channels(mock_runner):
    """Empty channels dict no error."""
    # Remove channels
    mock_runner._channels = {}

    # Should not raise exception
    await WorkspaceRunner._notify_lifecycle(mock_runner, "Started")

    # No error should be logged (debug only)
    mock_runner.logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_notify_lifecycle_handles_send_failure(mock_runner):
    """Channel raises exception graceful handling."""
    # Make send_message raise exception
    mock_channel = mock_runner._channels["telegram"]
    mock_channel.send_message = AsyncMock(side_effect=Exception("Network error"))

    # Should not raise exception
    await WorkspaceRunner._notify_lifecycle(mock_runner, "Started")

    # Verify debug log (not error, since this is best-effort)
    mock_runner.logger.debug.assert_called_once()
    debug_call = mock_runner.logger.debug.call_args
    assert "Failed to send lifecycle notification" in debug_call.args[0]


@pytest.mark.asyncio
async def test_notify_lifecycle_no_allowed_users(mock_runner):
    """Channel with no allowed_users does not send."""
    # Remove allowed_users
    mock_channel = mock_runner._channels["telegram"]
    mock_channel._allowed_users = []

    await WorkspaceRunner._notify_lifecycle(mock_runner, "Started")

    # send_message should not be called (no users to notify)
    mock_channel.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_notify_lifecycle_multiple_channels(mock_runner):
    """Verify notification sent to all channels."""
    # Add a second channel
    slack_channel = AsyncMock()
    slack_channel.name = "slack"
    slack_channel._allowed_users = [67890]
    mock_runner._channels["slack"] = slack_channel

    await WorkspaceRunner._notify_lifecycle(mock_runner, "Shutting down")

    # Verify both channels received notification
    telegram_channel = mock_runner._channels["telegram"]
    telegram_channel.send_message.assert_called_once()
    telegram_call = telegram_channel.send_message.call_args
    assert telegram_call.args[0] == "telegram:12345"
    assert "Shutting down" in telegram_call.args[1]

    slack_channel.send_message.assert_called_once()
    slack_call = slack_channel.send_message.call_args
    assert slack_call.args[0] == "slack:67890"
    assert "Shutting down" in slack_call.args[1]


def test_lifecycle_config_defaults():
    """LifecycleConfig() defaults: startup=False, shutdown=True, auto_compact=True."""
    config = LifecycleConfig()

    assert config.notify_startup is False
    assert config.notify_shutdown is True
    assert config.notify_auto_compact is True


def test_lifecycle_config_fields():
    """Create with custom values, verify all fields."""
    config = LifecycleConfig(
        notify_startup=True, notify_shutdown=False, notify_auto_compact=False
    )

    assert config.notify_startup is True
    assert config.notify_shutdown is False
    assert config.notify_auto_compact is False


def test_lifecycle_config_partial_override():
    """Partial override preserves defaults for unspecified fields."""
    config = LifecycleConfig(notify_startup=True)

    assert config.notify_startup is True
    # Defaults should still apply
    assert config.notify_shutdown is True
    assert config.notify_auto_compact is True
