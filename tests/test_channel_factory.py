"""Tests for channel factory."""

from unittest.mock import MagicMock, patch

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.factory import create_channel
from openpaw.channels.telegram import TelegramChannel


def test_create_telegram_channel() -> None:
    """Test creating a Telegram channel via factory."""
    config = {
        "token": "test_token_123",
        "allowed_users": [123, 456],
        "allowed_groups": [-789],
        "allow_all": False,
    }

    channel = create_channel("telegram", config, "test_workspace")

    assert isinstance(channel, TelegramChannel)
    assert isinstance(channel, ChannelAdapter)
    assert channel.token == "test_token_123"
    assert channel.allowed_users == {123, 456}
    assert channel.allowed_groups == {-789}
    assert channel.allow_all is False
    assert channel.workspace_name == "test_workspace"


def test_create_telegram_channel_with_allow_all() -> None:
    """Test creating a Telegram channel with allow_all mode."""
    config = {
        "token": "test_token_456",
        "allow_all": True,
    }

    channel = create_channel("telegram", config, "public_workspace")

    assert isinstance(channel, TelegramChannel)
    assert channel.allow_all is True
    assert channel.workspace_name == "public_workspace"


def test_create_telegram_channel_empty_allowlists() -> None:
    """Test creating a Telegram channel with empty allowlists (defaults)."""
    config = {
        "token": "test_token_789",
    }

    channel = create_channel("telegram", config, "restricted_workspace")

    assert isinstance(channel, TelegramChannel)
    assert channel.allowed_users == set()
    assert channel.allowed_groups == set()
    assert channel.allow_all is False


def test_create_slack_channel() -> None:
    """Test creating a Slack channel via factory."""
    with patch("openpaw.channels.slack.SlackChannel") as mock_slack_cls:
        mock_instance = MagicMock()
        mock_slack_cls.return_value = mock_instance

        config = {
            "token": "xoxb-test-bot-token",
            "app_token": "xapp-test-app-token",
            "signing_secret": "test-signing-secret",
            "allowed_users": ["U123", "U456"],
            "allowed_channels": ["C789"],
            "allow_all": False,
        }

        channel = create_channel("slack", config, "test_workspace")

        assert channel is mock_instance
        mock_slack_cls.assert_called_once_with(
            bot_token="xoxb-test-bot-token",
            app_token="xapp-test-app-token",
            signing_secret="test-signing-secret",
            allowed_users=["U123", "U456"],
            allowed_channels=["C789"],
            allow_all=False,
            workspace_name="test_workspace",
        )


def test_create_slack_channel_minimal_config() -> None:
    """Test creating a Slack channel with minimal config (only required fields)."""
    with patch("openpaw.channels.slack.SlackChannel") as mock_slack_cls:
        mock_instance = MagicMock()
        mock_slack_cls.return_value = mock_instance

        config = {
            "token": "xoxb-test-bot-token",
            "app_token": "xapp-test-app-token",
        }

        channel = create_channel("slack", config, "minimal_workspace")

        assert channel is mock_instance
        mock_slack_cls.assert_called_once_with(
            bot_token="xoxb-test-bot-token",
            app_token="xapp-test-app-token",
            signing_secret=None,
            allowed_users=[],
            allowed_channels=[],
            allow_all=False,
            workspace_name="minimal_workspace",
        )


def test_create_channel_unsupported_type() -> None:
    """Test that unsupported channel types raise ValueError."""
    config = {"token": "test_token"}

    with pytest.raises(ValueError, match="Unsupported channel type: discord"):
        create_channel("discord", config, "test_workspace")

    with pytest.raises(ValueError, match="Unsupported channel type: matrix"):
        create_channel("matrix", config, "test_workspace")


def test_create_channel_passes_workspace_name() -> None:
    """Test that workspace name is correctly passed to channel."""
    config = {"token": "test_token"}

    channel = create_channel("telegram", config, "my_custom_workspace")

    assert isinstance(channel, TelegramChannel)
    assert channel.workspace_name == "my_custom_workspace"
