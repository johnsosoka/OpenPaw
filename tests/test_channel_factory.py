"""Tests for channel factory."""

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


def test_create_channel_unsupported_type() -> None:
    """Test that unsupported channel types raise ValueError."""
    config = {"token": "test_token"}

    with pytest.raises(ValueError, match="Unsupported channel type: discord"):
        create_channel("discord", config, "test_workspace")

    with pytest.raises(ValueError, match="Unsupported channel type: slack"):
        create_channel("slack", config, "test_workspace")


def test_create_channel_passes_workspace_name() -> None:
    """Test that workspace name is correctly passed to channel."""
    config = {"token": "test_token"}

    channel = create_channel("telegram", config, "my_custom_workspace")

    assert isinstance(channel, TelegramChannel)
    assert channel.workspace_name == "my_custom_workspace"
