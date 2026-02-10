"""Tests for Slack-related configuration models."""

import pytest
from pydantic import ValidationError

from openpaw.core.config.models import HeartbeatConfig, WorkspaceChannelConfig


def test_workspace_channel_config_mixed_allowed_users() -> None:
    """Test that WorkspaceChannelConfig accepts mixed int/str allowed_users."""
    config = WorkspaceChannelConfig(
        type="slack",
        token="xoxb-test-token",
        allowed_users=[123456, "U0ABC", "U1DEF", 789012],
    )

    assert config.type == "slack"
    assert config.token == "xoxb-test-token"
    assert config.allowed_users == [123456, "U0ABC", "U1DEF", 789012]


def test_workspace_channel_config_slack_fields() -> None:
    """Test that WorkspaceChannelConfig accepts Slack-specific fields."""
    config = WorkspaceChannelConfig(
        type="slack",
        token="xoxb-test-token",
        app_token="xapp-test-token",
        signing_secret="test-signing-secret",
        allowed_users=["U123", "U456"],
        allowed_channels=["C789", "CABC"],
    )

    assert config.type == "slack"
    assert config.token == "xoxb-test-token"
    assert config.app_token == "xapp-test-token"
    assert config.signing_secret == "test-signing-secret"
    assert config.allowed_users == ["U123", "U456"]
    assert config.allowed_channels == ["C789", "CABC"]


def test_workspace_channel_config_default_slack_fields() -> None:
    """Test that Slack-specific fields default to None/empty list."""
    config = WorkspaceChannelConfig(
        type="slack",
        token="xoxb-test-token",
    )

    assert config.app_token is None
    assert config.signing_secret is None
    assert config.allowed_channels == []


def test_workspace_channel_config_telegram_int_users() -> None:
    """Test that WorkspaceChannelConfig accepts int-only allowed_users for Telegram."""
    config = WorkspaceChannelConfig(
        type="telegram",
        token="test-telegram-token",
        allowed_users=[123456, 789012],
        allowed_groups=[-987654],
    )

    assert config.type == "telegram"
    assert config.token == "test-telegram-token"
    assert config.allowed_users == [123456, 789012]
    assert config.allowed_groups == [-987654]


def test_workspace_channel_config_backward_compatibility() -> None:
    """Test that existing int-only configs still work (backward compatibility)."""
    config = WorkspaceChannelConfig(
        type="telegram",
        token="test-telegram-token",
        allowed_users=[111, 222, 333],
        allowed_groups=[-444],
    )

    assert config.allowed_users == [111, 222, 333]
    assert config.allowed_groups == [-444]


def test_workspace_channel_config_allow_all() -> None:
    """Test allow_all flag works correctly."""
    config = WorkspaceChannelConfig(
        type="slack",
        token="xoxb-test-token",
        allow_all=True,
    )

    assert config.allow_all is True
    assert config.allowed_users == []
    assert config.allowed_channels == []


def test_heartbeat_config_string_target_chat_id() -> None:
    """Test that HeartbeatConfig accepts string target_chat_id for Slack."""
    config = HeartbeatConfig(
        enabled=True,
        interval_minutes=30,
        target_channel="slack",
        target_chat_id="C123456",
    )

    assert config.enabled is True
    assert config.interval_minutes == 30
    assert config.target_channel == "slack"
    assert config.target_chat_id == "C123456"


def test_heartbeat_config_int_target_chat_id() -> None:
    """Test that HeartbeatConfig accepts int target_chat_id for Telegram."""
    config = HeartbeatConfig(
        enabled=True,
        interval_minutes=30,
        target_channel="telegram",
        target_chat_id=123456789,
    )

    assert config.enabled is True
    assert config.interval_minutes == 30
    assert config.target_channel == "telegram"
    assert config.target_chat_id == 123456789


def test_heartbeat_config_none_target_chat_id() -> None:
    """Test that HeartbeatConfig accepts None for target_chat_id (default)."""
    config = HeartbeatConfig(
        enabled=True,
        interval_minutes=15,
    )

    assert config.enabled is True
    assert config.target_chat_id is None


def test_workspace_channel_config_extra_fields_allowed() -> None:
    """Test that extra fields are allowed in WorkspaceChannelConfig (for future extensibility)."""
    config = WorkspaceChannelConfig(
        type="slack",
        token="xoxb-test-token",
        app_token="xapp-test-token",
        custom_field="custom_value",  # Extra field should be allowed
    )

    assert config.type == "slack"
    assert config.token == "xoxb-test-token"
    # Extra field should be accessible via model_dump
    dumped = config.model_dump()
    assert dumped["custom_field"] == "custom_value"


def test_workspace_channel_config_empty_lists() -> None:
    """Test that empty lists work correctly for allowlists."""
    config = WorkspaceChannelConfig(
        type="slack",
        token="xoxb-test-token",
        allowed_users=[],
        allowed_channels=[],
        allowed_groups=[],
    )

    assert config.allowed_users == []
    assert config.allowed_channels == []
    assert config.allowed_groups == []


def test_workspace_channel_config_mixed_str_groups() -> None:
    """Test that allowed_groups accepts mixed int/str (for future multi-channel support)."""
    config = WorkspaceChannelConfig(
        type="slack",
        token="xoxb-test-token",
        allowed_groups=["G123", -456, "G789"],  # Slack uses string IDs, Telegram uses negative ints
    )

    assert config.allowed_groups == ["G123", -456, "G789"]
