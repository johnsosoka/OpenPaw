"""Tests for cross-channel messaging feature.

Covers:
- WorkspaceConfig.validate_primary_channel validator
- WorkspaceChannelConfig new fields (primary, default_target_id)
- build_channels_section prompt builder
- SendMessageTool cross-channel registry wiring
- _extract_channel_name_from_context and _build_cross_channel_system_event helpers
- SendFileTool cross-channel registry wiring
"""

import pytest

from openpaw.builtins.tools.send_file import SendFileTool
from openpaw.builtins.tools.send_message import (
    SendMessageTool,
    _build_cross_channel_system_event,
    _extract_channel_name_from_context,
)
from openpaw.core.config.models import WorkspaceChannelConfig, WorkspaceConfig
from openpaw.core.prompts.framework import build_channels_section


# ---------------------------------------------------------------------------
# WorkspaceConfig.validate_primary_channel validator
# ---------------------------------------------------------------------------


def test_multi_channel_with_one_primary_passes() -> None:
    """Multi-channel config with exactly one primary channel is valid."""
    config = WorkspaceConfig.model_validate(
        {
            "channels": [
                {"name": "telegram", "type": "telegram", "primary": True},
                {"name": "discord", "type": "discord"},
            ]
        }
    )
    assert len(config.channels) == 2
    primary_channels = [ch for ch in config.channels if ch.primary]
    assert len(primary_channels) == 1
    assert primary_channels[0].name == "telegram"


def test_multi_channel_no_primary_raises() -> None:
    """Multi-channel config with no primary channel raises ValueError."""
    with pytest.raises(ValueError, match="must be marked 'primary: true'"):
        WorkspaceConfig.model_validate(
            {
                "channels": [
                    {"name": "telegram", "type": "telegram"},
                    {"name": "discord", "type": "discord"},
                ]
            }
        )


def test_multi_channel_two_primary_raises() -> None:
    """Multi-channel config with two primary channels raises ValueError."""
    with pytest.raises(ValueError, match="Only one channel"):
        WorkspaceConfig.model_validate(
            {
                "channels": [
                    {"name": "telegram", "type": "telegram", "primary": True},
                    {"name": "discord", "type": "discord", "primary": True},
                ]
            }
        )


def test_single_channel_no_primary_passes() -> None:
    """Single-channel config with no primary field does not require primary."""
    config = WorkspaceConfig.model_validate(
        {"channels": [{"name": "telegram", "type": "telegram"}]}
    )
    assert len(config.channels) == 1
    assert config.channels[0].primary is False


def test_single_channel_with_primary_passes() -> None:
    """Single-channel config with primary=True is valid (no multi-channel constraint)."""
    config = WorkspaceConfig.model_validate(
        {"channels": [{"name": "telegram", "type": "telegram", "primary": True}]}
    )
    assert len(config.channels) == 1
    assert config.channels[0].primary is True


def test_empty_channels_passes() -> None:
    """Empty channel list requires no primary (validator only fires for 2+ channels)."""
    config = WorkspaceConfig.model_validate({})
    assert config.channels == []


# ---------------------------------------------------------------------------
# WorkspaceChannelConfig new fields
# ---------------------------------------------------------------------------


def test_channel_config_default_target_id() -> None:
    """WorkspaceChannelConfig accepts and stores default_target_id."""
    ch = WorkspaceChannelConfig(type="telegram", default_target_id=123456)
    assert ch.default_target_id == 123456


def test_channel_config_default_target_id_defaults_none() -> None:
    """default_target_id defaults to None when not set."""
    ch = WorkspaceChannelConfig(type="telegram")
    assert ch.default_target_id is None


def test_channel_config_primary_default_false() -> None:
    """primary field defaults to False."""
    ch = WorkspaceChannelConfig(type="telegram")
    assert ch.primary is False


def test_channel_config_primary_set_true() -> None:
    """primary field can be set to True."""
    ch = WorkspaceChannelConfig(type="telegram", primary=True)
    assert ch.primary is True


def test_channel_config_both_new_fields() -> None:
    """Both primary and default_target_id can be set together."""
    ch = WorkspaceChannelConfig(type="discord", primary=True, default_target_id=99999)
    assert ch.primary is True
    assert ch.default_target_id == 99999


# ---------------------------------------------------------------------------
# build_channels_section
# ---------------------------------------------------------------------------


def test_build_channels_section_empty_list_returns_empty() -> None:
    """Empty channel list returns empty string."""
    assert build_channels_section([]) == ""


def test_build_channels_section_single_channel_returns_empty() -> None:
    """Single channel list returns empty string (no cross-channel needed)."""
    channels = [WorkspaceChannelConfig(type="telegram")]
    assert build_channels_section(channels) == ""


def test_build_channels_section_two_channels_returns_content() -> None:
    """Two channels produce a non-empty channels section."""
    channels = [
        WorkspaceChannelConfig(name="telegram", type="telegram", primary=True, default_target_id=123),
        WorkspaceChannelConfig(name="discord", type="discord"),
    ]
    result = build_channels_section(channels)
    assert result != ""


def test_build_channels_section_includes_channel_names() -> None:
    """Channel names appear in the generated section."""
    channels = [
        WorkspaceChannelConfig(name="telegram", type="telegram", primary=True, default_target_id=123),
        WorkspaceChannelConfig(name="discord-alerts", type="discord"),
    ]
    result = build_channels_section(channels)
    assert "telegram" in result
    assert "discord-alerts" in result


def test_build_channels_section_marks_primary_role() -> None:
    """Primary channel is labelled with '**primary**' role."""
    channels = [
        WorkspaceChannelConfig(name="telegram", type="telegram", primary=True, default_target_id=123),
        WorkspaceChannelConfig(name="discord", type="discord"),
    ]
    result = build_channels_section(channels)
    assert "**primary**" in result


def test_build_channels_section_marks_public_role() -> None:
    """Non-primary channels are labelled as 'public'."""
    channels = [
        WorkspaceChannelConfig(name="telegram", type="telegram", primary=True, default_target_id=123),
        WorkspaceChannelConfig(name="discord", type="discord"),
    ]
    result = build_channels_section(channels)
    assert "public" in result


def test_build_channels_section_includes_channel_types() -> None:
    """Channel types appear in the generated table."""
    channels = [
        WorkspaceChannelConfig(name="tg", type="telegram", primary=True, default_target_id=1),
        WorkspaceChannelConfig(name="dc", type="discord"),
    ]
    result = build_channels_section(channels)
    assert "telegram" in result
    assert "discord" in result


def test_build_channels_section_shows_default_target_id() -> None:
    """default_target_id appears in the channel table row."""
    channels = [
        WorkspaceChannelConfig(name="telegram", type="telegram", primary=True, default_target_id=987654),
        WorkspaceChannelConfig(name="discord", type="discord"),
    ]
    result = build_channels_section(channels)
    assert "987654" in result


def test_build_channels_section_falls_back_to_allowed_users() -> None:
    """Falls back to first allowed_users entry when default_target_id is not set."""
    channels = [
        WorkspaceChannelConfig(
            name="telegram",
            type="telegram",
            primary=True,
            allowed_users=[555444],
        ),
        WorkspaceChannelConfig(name="discord", type="discord"),
    ]
    result = build_channels_section(channels)
    assert "555444" in result


def test_build_channels_section_uses_type_as_name_fallback() -> None:
    """When name is None, the channel type is used as the display name."""
    channels = [
        WorkspaceChannelConfig(type="telegram", primary=True, default_target_id=1),
        WorkspaceChannelConfig(type="discord"),
    ]
    result = build_channels_section(channels)
    # type should appear as the name in the table row
    assert "telegram" in result
    assert "discord" in result


# ---------------------------------------------------------------------------
# SendMessageTool cross-channel registry
# ---------------------------------------------------------------------------


def test_send_message_tool_set_channel_registry() -> None:
    """set_channel_registry stores channels and targets on the tool instance."""
    tool = SendMessageTool()
    channels = {"telegram": object(), "discord": object()}
    targets = {"telegram": 123}

    tool.set_channel_registry(channels, targets)

    assert tool._channel_registry == channels
    assert tool._channel_targets == targets


def test_send_message_tool_registry_defaults_empty() -> None:
    """Channel registry defaults to empty dicts before wiring."""
    tool = SendMessageTool()
    assert tool._channel_registry == {}
    assert tool._channel_targets == {}


def test_send_message_tool_set_channel_registry_with_callback() -> None:
    """set_channel_registry accepts an optional system_event_callback."""
    tool = SendMessageTool()
    channels = {"telegram": object()}
    targets = {"telegram": 111}
    callback = object()

    tool.set_channel_registry(channels, targets, system_event_callback=callback)

    assert tool._channel_registry == channels
    assert tool._channel_targets == targets
    assert tool._system_event_callback is callback


def test_send_message_tool_callback_defaults_none() -> None:
    """System event callback defaults to None before wiring."""
    tool = SendMessageTool()
    assert tool._system_event_callback is None


# ---------------------------------------------------------------------------
# _extract_channel_name_from_context helper
# ---------------------------------------------------------------------------


def test_extract_channel_name_from_context_no_session_returns_unknown() -> None:
    """Returns 'unknown' when no session context is active."""
    # No context set — should safely return "unknown"
    result = _extract_channel_name_from_context()
    assert result == "unknown"


# ---------------------------------------------------------------------------
# _build_cross_channel_system_event helper
# ---------------------------------------------------------------------------


def test_build_cross_channel_system_event_contains_system_marker() -> None:
    """Result includes the [SYSTEM] marker."""
    result = _build_cross_channel_system_event("discord-alerts", "Server is down!")
    assert "[SYSTEM]" in result


def test_build_cross_channel_system_event_contains_source_channel() -> None:
    """Result includes the source channel name."""
    result = _build_cross_channel_system_event("discord-alerts", "Server is down!")
    assert "discord-alerts" in result


def test_build_cross_channel_system_event_contains_message_content() -> None:
    """Result includes the original message content."""
    result = _build_cross_channel_system_event("discord-alerts", "Server is down!")
    assert "Server is down!" in result


def test_build_cross_channel_system_event_contains_log_path_hint() -> None:
    """Result includes reference to channel logs for context recovery."""
    result = _build_cross_channel_system_event("discord-alerts", "Server is down!")
    assert "memory/logs/channel/" in result


def test_build_cross_channel_system_event_various_inputs() -> None:
    """Helper works with different channel names and message contents."""
    result = _build_cross_channel_system_event("telegram-personal", "Deploy complete.")
    assert "telegram-personal" in result
    assert "Deploy complete." in result


# ---------------------------------------------------------------------------
# SendFileTool cross-channel registry
# ---------------------------------------------------------------------------


def test_send_file_tool_set_channel_registry() -> None:
    """set_channel_registry stores channels and targets on SendFileTool."""
    tool = SendFileTool(config={"workspace_path": "/tmp"})
    channels = {"telegram": object(), "discord": object()}
    targets = {"telegram": 123}

    tool.set_channel_registry(channels, targets)

    assert tool._channel_registry == channels
    assert tool._channel_targets == targets


def test_send_file_tool_registry_defaults_empty() -> None:
    """SendFileTool channel registry defaults to empty dicts before wiring."""
    tool = SendFileTool(config={"workspace_path": "/tmp"})
    assert tool._channel_registry == {}
    assert tool._channel_targets == {}


def test_send_file_tool_registry_overwrite() -> None:
    """Calling set_channel_registry twice replaces the previous registry."""
    tool = SendFileTool(config={"workspace_path": "/tmp"})
    first_channels = {"telegram": object()}
    second_channels = {"discord": object()}

    tool.set_channel_registry(first_channels, {})
    tool.set_channel_registry(second_channels, {"discord": 999})

    assert tool._channel_registry == second_channels
    assert tool._channel_targets == {"discord": 999}
