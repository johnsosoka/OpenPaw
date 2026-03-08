"""Tests for the channel history foundation layer.

Covers:
- ChannelHistoryEntry and ChannelEvent dataclasses (openpaw/model/channel.py)
- ChannelLogConfig and WorkspaceChannelConfig additions (openpaw/core/config/models.py)
- CHANNEL_LOGS_DIR path constant (openpaw/core/paths.py)
- Backward compatibility of existing configs
"""

from datetime import UTC, datetime
from pathlib import PurePosixPath

import pytest

from openpaw.core.config.models import (
    ChannelLogConfig,
    WorkspaceChannelConfig,
    WorkspaceConfig,
)
from openpaw.core.paths import (
    CHANNEL_LOGS_DIR,
    MEMORY_LOGS_DIR,
    WRITE_PROTECTED_DIRS,
)
from openpaw.model.channel import ChannelEvent, ChannelHistoryEntry

# ---------------------------------------------------------------------------
# ChannelHistoryEntry
# ---------------------------------------------------------------------------


class TestChannelHistoryEntry:
    """ChannelHistoryEntry is a pure dataclass with sensible defaults."""

    def test_construction_with_required_fields(self) -> None:
        ts = datetime(2026, 3, 7, 14, 30, 0, tzinfo=UTC)
        entry = ChannelHistoryEntry(
            timestamp=ts,
            user_id="123",
            display_name="Alice",
            content="hello",
        )

        assert entry.timestamp == ts
        assert entry.user_id == "123"
        assert entry.display_name == "Alice"
        assert entry.content == "hello"

    def test_is_bot_defaults_false(self) -> None:
        entry = ChannelHistoryEntry(
            timestamp=datetime.now(UTC),
            user_id="1",
            display_name="Bob",
            content="hi",
        )

        assert entry.is_bot is False

    def test_attachments_summary_defaults_none(self) -> None:
        entry = ChannelHistoryEntry(
            timestamp=datetime.now(UTC),
            user_id="1",
            display_name="Carol",
            content="check this",
        )

        assert entry.attachments_summary is None

    def test_is_bot_can_be_set_true(self) -> None:
        entry = ChannelHistoryEntry(
            timestamp=datetime.now(UTC),
            user_id="bot-999",
            display_name="MyBot",
            content="I can help",
            is_bot=True,
        )

        assert entry.is_bot is True

    def test_attachments_summary_can_be_set(self) -> None:
        entry = ChannelHistoryEntry(
            timestamp=datetime.now(UTC),
            user_id="1",
            display_name="Dave",
            content="see attached",
            attachments_summary="[file: report.pdf]",
        )

        assert entry.attachments_summary == "[file: report.pdf]"

    def test_all_fields_stored_correctly(self) -> None:
        ts = datetime(2026, 3, 7, 9, 0, 0, tzinfo=UTC)
        entry = ChannelHistoryEntry(
            timestamp=ts,
            user_id="42",
            display_name="Eve",
            content="test message",
            is_bot=True,
            attachments_summary="[image]",
        )

        assert entry.timestamp is ts
        assert entry.user_id == "42"
        assert entry.display_name == "Eve"
        assert entry.content == "test message"
        assert entry.is_bot is True
        assert entry.attachments_summary == "[image]"


# ---------------------------------------------------------------------------
# ChannelEvent
# ---------------------------------------------------------------------------


class TestChannelEvent:
    """ChannelEvent is a pure dataclass covering raw pre-filter message data."""

    def _make_event(self, **overrides):
        defaults = dict(
            timestamp=datetime(2026, 3, 7, 14, 0, 0, tzinfo=UTC),
            channel_name="discord",
            channel_id="444555666",
            channel_label="general",
            server_name="My Server",
            server_id="111222333",
            user_id="987654321",
            display_name="Alice",
            content="Has anyone tried the new deployment?",
            attachment_names=["screenshot.png"],
            message_id="1234567890",
        )
        defaults.update(overrides)
        return ChannelEvent(**defaults)

    def test_construction_with_all_fields(self) -> None:
        event = self._make_event()

        assert event.channel_name == "discord"
        assert event.channel_id == "444555666"
        assert event.channel_label == "general"
        assert event.server_name == "My Server"
        assert event.server_id == "111222333"
        assert event.user_id == "987654321"
        assert event.display_name == "Alice"
        assert event.content == "Has anyone tried the new deployment?"
        assert event.attachment_names == ["screenshot.png"]
        assert event.message_id == "1234567890"

    def test_server_name_can_be_none_for_dms(self) -> None:
        event = self._make_event(server_name=None, server_id=None)

        assert event.server_name is None
        assert event.server_id is None

    def test_attachment_names_defaults_empty(self) -> None:
        # Construct without attachment_names
        event = ChannelEvent(
            timestamp=datetime.now(UTC),
            channel_name="discord",
            channel_id="1",
            channel_label="general",
            server_name="Test",
            server_id="99",
            user_id="1",
            display_name="Fred",
            content="no files here",
        )

        assert event.attachment_names == []

    def test_message_id_defaults_empty_string(self) -> None:
        event = ChannelEvent(
            timestamp=datetime.now(UTC),
            channel_name="discord",
            channel_id="1",
            channel_label="general",
            server_name="Test",
            server_id="99",
            user_id="1",
            display_name="Gina",
            content="hello",
        )

        assert event.message_id == ""

    def test_multiple_attachment_names(self) -> None:
        event = self._make_event(attachment_names=["a.png", "b.pdf", "c.zip"])

        assert event.attachment_names == ["a.png", "b.pdf", "c.zip"]

    def test_timestamp_stored_correctly(self) -> None:
        ts = datetime(2026, 1, 15, 8, 45, 0, tzinfo=UTC)
        event = self._make_event(timestamp=ts)

        assert event.timestamp == ts


# ---------------------------------------------------------------------------
# ChannelLogConfig
# ---------------------------------------------------------------------------


class TestChannelLogConfig:
    """ChannelLogConfig Pydantic model validation."""

    def test_defaults(self) -> None:
        cfg = ChannelLogConfig()

        assert cfg.enabled is True
        assert cfg.retention_days == 30

    def test_enabled_can_be_set_true(self) -> None:
        cfg = ChannelLogConfig(enabled=True)

        assert cfg.enabled is True

    def test_retention_days_can_be_customized(self) -> None:
        cfg = ChannelLogConfig(retention_days=7)

        assert cfg.retention_days == 7

    def test_retention_days_one_is_valid(self) -> None:
        cfg = ChannelLogConfig(retention_days=1)

        assert cfg.retention_days == 1

    def test_retention_days_zero_raises(self) -> None:
        with pytest.raises(Exception):
            ChannelLogConfig(retention_days=0)

    def test_retention_days_negative_raises(self) -> None:
        with pytest.raises(Exception):
            ChannelLogConfig(retention_days=-5)

    def test_retention_days_large_value_accepted(self) -> None:
        cfg = ChannelLogConfig(retention_days=365)

        assert cfg.retention_days == 365


# ---------------------------------------------------------------------------
# WorkspaceChannelConfig — new fields
# ---------------------------------------------------------------------------


class TestWorkspaceChannelConfigNewFields:
    """context_messages and channel_log fields on WorkspaceChannelConfig."""

    def test_context_messages_default(self) -> None:
        cfg = WorkspaceChannelConfig()

        assert cfg.context_messages == 25

    def test_context_messages_can_be_set_to_zero(self) -> None:
        cfg = WorkspaceChannelConfig(context_messages=0)

        assert cfg.context_messages == 0

    def test_context_messages_can_be_set_to_max(self) -> None:
        cfg = WorkspaceChannelConfig(context_messages=100)

        assert cfg.context_messages == 100

    def test_context_messages_negative_raises(self) -> None:
        with pytest.raises(Exception):
            WorkspaceChannelConfig(context_messages=-1)

    def test_context_messages_above_max_raises(self) -> None:
        with pytest.raises(Exception):
            WorkspaceChannelConfig(context_messages=101)

    def test_channel_log_default_is_enabled(self) -> None:
        cfg = WorkspaceChannelConfig()

        assert isinstance(cfg.channel_log, ChannelLogConfig)
        assert cfg.channel_log.enabled is True

    def test_channel_log_default_retention(self) -> None:
        cfg = WorkspaceChannelConfig()

        assert cfg.channel_log.retention_days == 30

    def test_channel_log_can_be_enabled(self) -> None:
        cfg = WorkspaceChannelConfig(channel_log={"enabled": True, "retention_days": 14})

        assert cfg.channel_log.enabled is True
        assert cfg.channel_log.retention_days == 14

    def test_channel_log_nested_validation_propagates(self) -> None:
        with pytest.raises(Exception):
            WorkspaceChannelConfig(channel_log={"enabled": True, "retention_days": 0})


# ---------------------------------------------------------------------------
# CHANNEL_LOGS_DIR path constant
# ---------------------------------------------------------------------------


class TestChannelLogsDir:
    """CHANNEL_LOGS_DIR constant correctness and write-protection."""

    def test_channel_logs_dir_is_pure_posix_path(self) -> None:
        assert isinstance(CHANNEL_LOGS_DIR, PurePosixPath)

    def test_channel_logs_dir_parent_is_memory_logs_dir(self) -> None:
        assert CHANNEL_LOGS_DIR.parent == MEMORY_LOGS_DIR

    def test_channel_logs_dir_name(self) -> None:
        assert CHANNEL_LOGS_DIR.name == "channel"

    def test_channel_logs_dir_string_value(self) -> None:
        assert str(CHANNEL_LOGS_DIR) == "memory/logs/channel"

    def test_channel_logs_dir_covered_by_write_protected_dirs(self) -> None:
        """CHANNEL_LOGS_DIR is under memory/logs which is already write-protected."""
        # The sandbox checks by parts prefix, so memory/logs covers memory/logs/channel
        assert str(MEMORY_LOGS_DIR) in WRITE_PROTECTED_DIRS


# ---------------------------------------------------------------------------
# Backward compatibility: existing configs load without changes
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Existing configs without the new fields continue to load correctly."""

    def test_workspace_config_no_channels_still_works(self) -> None:
        cfg = WorkspaceConfig.model_validate({})

        assert cfg.channels == []

    def test_workspace_channel_config_minimal_still_works(self) -> None:
        cfg = WorkspaceChannelConfig(type="telegram", token="test-token")

        assert cfg.type == "telegram"
        assert cfg.token == "test-token"
        # New fields have safe defaults
        assert cfg.context_messages == 25
        assert cfg.channel_log.enabled is True

    def test_telegram_channel_in_workspace_config_still_works(self) -> None:
        data = {"channel": {"type": "telegram", "token": "tg-token"}}

        cfg = WorkspaceConfig.model_validate(data)

        assert len(cfg.channels) == 1
        channel = cfg.channels[0]
        assert channel.type == "telegram"
        assert channel.context_messages == 25
        assert channel.channel_log.enabled is True

    def test_discord_channel_with_existing_fields_still_works(self) -> None:
        data = {
            "channels": [
                {
                    "type": "discord",
                    "token": "dc-token",
                    "allowed_groups": [111],
                    "mention_required": True,
                    "triggers": ["!ask"],
                }
            ]
        }

        cfg = WorkspaceConfig.model_validate(data)

        channel = cfg.channels[0]
        assert channel.mention_required is True
        assert channel.triggers == ["!ask"]
        # New fields still have defaults
        assert channel.context_messages == 25
        assert channel.channel_log.enabled is True

    def test_new_fields_round_trip_in_workspace_config(self) -> None:
        """New fields are preserved when explicitly set in a full WorkspaceConfig."""
        data = {
            "channels": [
                {
                    "type": "discord",
                    "token": "dc-token",
                    "context_messages": 10,
                    "channel_log": {"enabled": True, "retention_days": 7},
                }
            ]
        }

        cfg = WorkspaceConfig.model_validate(data)

        channel = cfg.channels[0]
        assert channel.context_messages == 10
        assert channel.channel_log.enabled is True
        assert channel.channel_log.retention_days == 7
