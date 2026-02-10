"""Tests for multi-channel support in WorkspaceRunner."""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.core.queue.manager import QueueManager
from openpaw.workspace.lifecycle import LifecycleManager


@pytest.fixture
def mock_channel():
    """Create a mock channel adapter."""
    channel = MagicMock(spec=ChannelAdapter)
    channel.on_message = MagicMock()
    channel.start = AsyncMock()
    channel.stop = AsyncMock()
    return channel


@pytest.fixture
def base_lifecycle_params():
    """Base parameters for LifecycleManager initialization."""
    return {
        "workspace_name": "test_workspace",
        "workspace_path": Path("/tmp/test_workspace"),
        "workspace_config": None,
        "config": MagicMock(),
        "queue_manager": MagicMock(spec=QueueManager),
        "message_handler": MagicMock(),
        "queue_handler": MagicMock(),
        "builtin_loader": MagicMock(),
        "workspace_timezone": "UTC",
        "session_manager": MagicMock(),
        "approval_handler": MagicMock(),
        "logger": logging.getLogger("test"),
    }


@pytest.fixture
def lifecycle_manager(base_lifecycle_params):
    """Create a LifecycleManager instance with base params."""
    return LifecycleManager(
        merged_config={},
        **base_lifecycle_params
    )


@pytest.mark.asyncio
class TestSingleChannelBackwardCompat:
    """Test backward compatibility with singular 'channel' config."""

    async def test_single_channel_telegram_works(
        self, lifecycle_manager, mock_channel, base_lifecycle_params
    ):
        """Single 'channel:' config with telegram still works."""
        lifecycle_manager._merged_config = {
            "channel": {
                "type": "telegram",
                "token": "test-token",
                "allowed_users": [123],
            }
        }
        lifecycle_manager._queue_manager.register_handler = AsyncMock()

        with patch("openpaw.workspace.lifecycle.create_channel", return_value=mock_channel):
            channels = await lifecycle_manager.setup_channels()

        assert len(channels) == 1
        assert "telegram" in channels
        assert channels["telegram"] == mock_channel
        mock_channel.on_message.assert_called_once()
        lifecycle_manager._queue_manager.register_handler.assert_called_once_with(
            "telegram", lifecycle_manager._queue_handler
        )

    async def test_single_channel_slack_works(
        self, lifecycle_manager, mock_channel
    ):
        """Single 'channel:' config with slack still works."""
        lifecycle_manager._merged_config = {
            "channel": {
                "type": "slack",
                "token": "xoxb-test",
                "app_token": "xapp-test",
                "allowed_users": ["U123"],
            }
        }
        lifecycle_manager._queue_manager.register_handler = AsyncMock()

        with patch("openpaw.workspace.lifecycle.create_channel", return_value=mock_channel):
            channels = await lifecycle_manager.setup_channels()

        assert len(channels) == 1
        assert "slack" in channels

    async def test_missing_token_raises_error(self, lifecycle_manager):
        """Missing token in single channel raises ValueError."""
        lifecycle_manager._merged_config = {
            "channel": {
                "type": "telegram",
                # Missing token
                "allowed_users": [123],
            }
        }

        with pytest.raises(ValueError, match="telegram channel requires a token"):
            await lifecycle_manager.setup_channels()

    async def test_slack_missing_app_token_raises_error(self, lifecycle_manager):
        """Slack channel without app_token raises ValueError."""
        lifecycle_manager._merged_config = {
            "channel": {
                "type": "slack",
                "token": "xoxb-test",
                # Missing app_token
            }
        }

        with pytest.raises(ValueError, match="Slack channel requires app_token"):
            await lifecycle_manager.setup_channels()


@pytest.mark.asyncio
class TestMultiChannelSupport:
    """Test new 'channels' (plural) list support."""

    async def test_channels_list_with_one_entry(
        self, lifecycle_manager, mock_channel
    ):
        """'channels:' list with one entry works."""
        lifecycle_manager._merged_config = {
            "channels": [
                {
                    "type": "telegram",
                    "token": "test-token",
                    "allowed_users": [123],
                }
            ]
        }
        lifecycle_manager._queue_manager.register_handler = AsyncMock()

        with patch("openpaw.workspace.lifecycle.create_channel", return_value=mock_channel):
            channels = await lifecycle_manager.setup_channels()

        assert len(channels) == 1
        assert "telegram" in channels

    async def test_channels_list_with_two_entries(self, lifecycle_manager):
        """'channels:' list with two entries creates both channels."""
        lifecycle_manager._merged_config = {
            "channels": [
                {
                    "type": "telegram",
                    "token": "telegram-token",
                    "allowed_users": [123],
                },
                {
                    "type": "slack",
                    "token": "xoxb-slack-token",
                    "app_token": "xapp-slack-token",
                    "allowed_users": ["U123"],
                },
            ]
        }
        lifecycle_manager._queue_manager.register_handler = AsyncMock()

        telegram_channel = MagicMock(spec=ChannelAdapter)
        telegram_channel.on_message = MagicMock()
        slack_channel = MagicMock(spec=ChannelAdapter)
        slack_channel.on_message = MagicMock()

        def channel_factory(channel_type: str, config: dict, workspace: str):
            if channel_type == "telegram":
                return telegram_channel
            elif channel_type == "slack":
                return slack_channel
            raise ValueError(f"Unknown channel type: {channel_type}")

        with patch("openpaw.workspace.lifecycle.create_channel", side_effect=channel_factory):
            channels = await lifecycle_manager.setup_channels()

        assert len(channels) == 2
        assert "telegram" in channels
        assert "slack" in channels
        assert channels["telegram"] == telegram_channel
        assert channels["slack"] == slack_channel
        telegram_channel.on_message.assert_called_once()
        slack_channel.on_message.assert_called_once()
        assert lifecycle_manager._queue_manager.register_handler.call_count == 2

    async def test_missing_token_in_multi_channel_raises_error(self, lifecycle_manager):
        """Missing token in any channel of the list raises ValueError."""
        lifecycle_manager._merged_config = {
            "channels": [
                {
                    "type": "telegram",
                    "token": "telegram-token",
                },
                {
                    "type": "slack",
                    # Missing token
                    "app_token": "xapp-test",
                },
            ]
        }

        with pytest.raises(ValueError, match="slack channel requires a token"):
            await lifecycle_manager.setup_channels()

    async def test_slack_missing_app_token_in_multi_channel(self, lifecycle_manager):
        """Slack channel without app_token in multi-channel raises ValueError."""
        lifecycle_manager._merged_config = {
            "channels": [
                {
                    "type": "telegram",
                    "token": "telegram-token",
                },
                {
                    "type": "slack",
                    "token": "xoxb-test",
                    # Missing app_token
                },
            ]
        }

        with pytest.raises(ValueError, match="Slack channel requires app_token"):
            await lifecycle_manager.setup_channels()


@pytest.mark.asyncio
class TestEmptyChannelConfig:
    """Test error handling for empty channel configuration."""

    async def test_empty_config_raises_error(self, lifecycle_manager):
        """Missing both 'channel' and 'channels' raises ValueError."""
        lifecycle_manager._merged_config = {}

        with pytest.raises(ValueError, match="must define channel or channels"):
            await lifecycle_manager.setup_channels()

    async def test_none_config_raises_error(self, lifecycle_manager):
        """Config with channel: null raises ValueError."""
        lifecycle_manager._merged_config = {"channel": None}

        with pytest.raises(ValueError, match="must define channel or channels"):
            await lifecycle_manager.setup_channels()


@pytest.mark.asyncio
class TestSecurityLogging:
    """Test security-related logging for each channel."""

    async def test_allow_all_logs_warning(
        self, lifecycle_manager, mock_channel, caplog
    ):
        """allow_all=true logs security warning."""
        lifecycle_manager._merged_config = {
            "channel": {
                "type": "telegram",
                "token": "test-token",
                "allow_all": True,
            }
        }
        lifecycle_manager._queue_manager.register_handler = AsyncMock()

        with caplog.at_level(logging.WARNING):
            with patch("openpaw.workspace.lifecycle.create_channel", return_value=mock_channel):
                await lifecycle_manager.setup_channels()

        assert "allow_all=true (insecure mode)" in caplog.text

    async def test_allowlist_logs_info(
        self, lifecycle_manager, mock_channel, caplog
    ):
        """Allowlist with users/groups logs info."""
        lifecycle_manager._merged_config = {
            "channel": {
                "type": "telegram",
                "token": "test-token",
                "allowed_users": [123, 456],
                "allowed_groups": [-789],
            }
        }
        lifecycle_manager._queue_manager.register_handler = AsyncMock()

        with caplog.at_level(logging.INFO):
            with patch("openpaw.workspace.lifecycle.create_channel", return_value=mock_channel):
                await lifecycle_manager.setup_channels()

        assert "2 users, 1 groups" in caplog.text

    async def test_empty_allowlist_logs_warning(
        self, lifecycle_manager, mock_channel, caplog
    ):
        """Empty allowlist logs warning."""
        lifecycle_manager._merged_config = {
            "channel": {
                "type": "telegram",
                "token": "test-token",
                "allowed_users": [],
                "allowed_groups": [],
            }
        }
        lifecycle_manager._queue_manager.register_handler = AsyncMock()

        with caplog.at_level(logging.WARNING):
            with patch("openpaw.workspace.lifecycle.create_channel", return_value=mock_channel):
                await lifecycle_manager.setup_channels()

        assert "empty allowlist - all requests denied" in caplog.text


class TestHasGroupSessionsDetection:
    """Test has_group_sessions detection across multiple channels."""

    def test_single_channel_with_groups(self):
        """Single channel with allowed_groups sets has_group_sessions=True."""
        merged_config = {
            "channel": {
                "type": "telegram",
                "allowed_groups": [-123],
            }
        }

        # Replicate the detection logic from runner.py
        channel_configs = merged_config.get("channels")
        if not channel_configs:
            single = merged_config.get("channel", {})
            channel_configs = [single] if single else []

        has_group_sessions = any(
            cc.get("allowed_groups") or cc.get("allowed_channels")
            for cc in channel_configs
        )

        assert has_group_sessions is True

    def test_single_channel_with_channels(self):
        """Single channel with allowed_channels sets has_group_sessions=True."""
        merged_config = {
            "channel": {
                "type": "slack",
                "allowed_channels": ["C123"],
            }
        }

        channel_configs = merged_config.get("channels")
        if not channel_configs:
            single = merged_config.get("channel", {})
            channel_configs = [single] if single else []

        has_group_sessions = any(
            cc.get("allowed_groups") or cc.get("allowed_channels")
            for cc in channel_configs
        )

        assert has_group_sessions is True

    def test_single_channel_without_groups(self):
        """Single channel without groups/channels sets has_group_sessions=False."""
        merged_config = {
            "channel": {
                "type": "telegram",
                "allowed_users": [123],
            }
        }

        channel_configs = merged_config.get("channels")
        if not channel_configs:
            single = merged_config.get("channel", {})
            channel_configs = [single] if single else []

        has_group_sessions = any(
            cc.get("allowed_groups") or cc.get("allowed_channels")
            for cc in channel_configs
        )

        assert has_group_sessions is False

    def test_multi_channel_one_has_groups(self):
        """Multi-channel with one having groups sets has_group_sessions=True."""
        merged_config = {
            "channels": [
                {
                    "type": "telegram",
                    "allowed_users": [123],
                },
                {
                    "type": "slack",
                    "allowed_channels": ["C123"],  # This one has groups
                },
            ]
        }

        channel_configs = merged_config.get("channels")
        if not channel_configs:
            single = merged_config.get("channel", {})
            channel_configs = [single] if single else []

        has_group_sessions = any(
            cc.get("allowed_groups") or cc.get("allowed_channels")
            for cc in channel_configs
        )

        assert has_group_sessions is True

    def test_multi_channel_none_have_groups(self):
        """Multi-channel with none having groups sets has_group_sessions=False."""
        merged_config = {
            "channels": [
                {
                    "type": "telegram",
                    "allowed_users": [123],
                },
                {
                    "type": "slack",
                    "allowed_users": ["U123"],
                },
            ]
        }

        channel_configs = merged_config.get("channels")
        if not channel_configs:
            single = merged_config.get("channel", {})
            channel_configs = [single] if single else []

        has_group_sessions = any(
            cc.get("allowed_groups") or cc.get("allowed_channels")
            for cc in channel_configs
        )

        assert has_group_sessions is False

    def test_empty_config(self):
        """Empty config sets has_group_sessions=False."""
        merged_config = {}

        channel_configs = merged_config.get("channels")
        if not channel_configs:
            single = merged_config.get("channel", {})
            channel_configs = [single] if single else []

        has_group_sessions = any(
            cc.get("allowed_groups") or cc.get("allowed_channels")
            for cc in channel_configs
        )

        assert has_group_sessions is False
