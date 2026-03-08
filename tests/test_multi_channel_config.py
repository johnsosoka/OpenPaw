"""Tests for multi-channel configuration."""

import pytest

from openpaw.channels.factory import create_channel
from openpaw.core.config.models import (
    CronOutputConfig,
    HeartbeatConfig,
    WorkspaceChannelConfig,
    WorkspaceConfig,
)

# ---------------------------------------------------------------------------
# Config normalization: channel → channels
# ---------------------------------------------------------------------------


def test_single_channel_backward_compat() -> None:
    """Singular 'channel:' block is normalized into a one-element 'channels' list."""
    data = {"channel": {"type": "telegram", "token": "test-token"}}

    cfg = WorkspaceConfig.model_validate(data)

    assert len(cfg.channels) == 1
    assert cfg.channels[0].type == "telegram"
    assert cfg.channels[0].token == "test-token"


def test_channels_list_parses() -> None:
    """A 'channels:' list with multiple entries loads correctly."""
    data = {
        "channels": [
            {"type": "telegram", "token": "tg-token"},
            {"type": "discord", "token": "dc-token"},
        ]
    }

    cfg = WorkspaceConfig.model_validate(data)

    assert len(cfg.channels) == 2
    types = {ch.type for ch in cfg.channels}
    assert types == {"telegram", "discord"}


def test_both_channel_and_channels_raises() -> None:
    """Providing both 'channel' and 'channels' raises a validation error."""
    data = {
        "channel": {"type": "telegram", "token": "tg-token"},
        "channels": [{"type": "discord", "token": "dc-token"}],
    }

    with pytest.raises(Exception):
        WorkspaceConfig.model_validate(data)


def test_neither_channel_nor_channels_gives_empty_list() -> None:
    """Omitting both 'channel' and 'channels' results in an empty channels list."""
    cfg = WorkspaceConfig.model_validate({})

    assert cfg.channels == []


def test_channel_name_field() -> None:
    """A channel entry with an explicit 'name' preserves that name."""
    data = {
        "channels": [
            {"name": "my-tg", "type": "telegram", "token": "tg-token"},
        ]
    }

    cfg = WorkspaceConfig.model_validate(data)

    assert cfg.channels[0].name == "my-tg"


def test_channel_name_defaults_none() -> None:
    """A channel entry without an explicit 'name' has name=None."""
    data = {"channels": [{"type": "telegram", "token": "tg-token"}]}

    cfg = WorkspaceConfig.model_validate(data)

    assert cfg.channels[0].name is None


def test_triggers_field_default_empty() -> None:
    """A channel entry without 'triggers' has an empty triggers list."""
    data = {"channels": [{"type": "telegram", "token": "tg-token"}]}

    cfg = WorkspaceConfig.model_validate(data)

    assert cfg.channels[0].triggers == []


def test_triggers_field_populated() -> None:
    """'triggers' list parses correctly when provided."""
    data = {
        "channels": [
            {
                "type": "telegram",
                "token": "tg-token",
                "triggers": ["!ask", "hey bot"],
            }
        ]
    }

    cfg = WorkspaceConfig.model_validate(data)

    assert cfg.channels[0].triggers == ["!ask", "hey bot"]


def test_model_shorthand_still_works_with_channels() -> None:
    """'model: provider:model_id' shorthand coercion works alongside channels normalization."""
    data = {
        "model": "anthropic:claude-sonnet-4-20250514",
        "channels": [{"type": "telegram", "token": "tg-token"}],
    }

    cfg = WorkspaceConfig.model_validate(data)

    assert cfg.model.provider == "anthropic"
    assert cfg.model.model == "claude-sonnet-4-20250514"
    assert len(cfg.channels) == 1


def test_channels_with_same_type_different_names() -> None:
    """Two channels sharing the same type but with different names parse without error."""
    data = {
        "channels": [
            {"name": "tg-primary", "type": "telegram", "token": "token-a"},
            {"name": "tg-secondary", "type": "telegram", "token": "token-b"},
        ]
    }

    cfg = WorkspaceConfig.model_validate(data)

    assert len(cfg.channels) == 2
    names = {ch.name for ch in cfg.channels}
    assert names == {"tg-primary", "tg-secondary"}


# ---------------------------------------------------------------------------
# Factory channel name tests
# ---------------------------------------------------------------------------


def test_factory_sets_channel_name() -> None:
    """Passing channel_name to create_channel sets adapter.name accordingly."""
    config = {"token": "tg-token", "allowed_users": [111]}

    adapter = create_channel("telegram", config, "my-workspace", channel_name="my-tg")

    assert adapter.name == "my-tg"


def test_factory_default_name_unchanged() -> None:
    """Omitting channel_name leaves the adapter's default name in place."""
    config = {"token": "tg-token"}

    adapter = create_channel("telegram", config, "my-workspace")

    # TelegramChannel sets name = "telegram" by default
    assert adapter.name == "telegram"


def test_factory_discord_channel_name() -> None:
    """channel_name parameter is applied correctly for Discord adapters too."""
    from openpaw.channels.discord import DiscordChannel

    config = {"token": "dc-token"}

    adapter = create_channel("discord", config, "my-workspace", channel_name="dc-alerts")

    assert isinstance(adapter, DiscordChannel)
    assert adapter.name == "dc-alerts"


# ---------------------------------------------------------------------------
# CronOutputConfig target_id tests
# ---------------------------------------------------------------------------


def test_cron_output_target_id() -> None:
    """CronOutputConfig accepts target_id as the preferred routing field."""
    cfg = CronOutputConfig(channel="telegram", target_id=99999)

    assert cfg.target_id == 99999


def test_cron_output_legacy_chat_id_still_works() -> None:
    """Legacy 'chat_id' field still parses without error."""
    cfg = CronOutputConfig(channel="telegram", chat_id=12345)

    assert cfg.chat_id == 12345


def test_cron_output_target_id_preferred() -> None:
    """When both target_id and chat_id are present, target_id is non-None (caller decides precedence)."""
    cfg = CronOutputConfig(channel="telegram", target_id=99999, chat_id=12345)

    # Both fields are stored; usage site should prefer target_id
    assert cfg.target_id == 99999
    assert cfg.chat_id == 12345


# ---------------------------------------------------------------------------
# HeartbeatConfig target_id tests
# ---------------------------------------------------------------------------


def test_heartbeat_target_id() -> None:
    """HeartbeatConfig accepts target_id as the preferred routing field."""
    cfg = HeartbeatConfig(enabled=True, target_id=77777)

    assert cfg.target_id == 77777


def test_heartbeat_legacy_target_chat_id_still_works() -> None:
    """Legacy 'target_chat_id' field still parses without error."""
    cfg = HeartbeatConfig(enabled=True, target_chat_id=55555)

    assert cfg.target_chat_id == 55555


# ---------------------------------------------------------------------------
# User aliases merge test
# ---------------------------------------------------------------------------


def test_user_aliases_from_multiple_channels() -> None:
    """Aliases from multiple WorkspaceChannelConfig instances can be merged with first-wins."""
    channel_a = WorkspaceChannelConfig(
        type="telegram",
        token="token-a",
        user_aliases={111: "Alice", 222: "Bob"},
    )
    channel_b = WorkspaceChannelConfig(
        type="discord",
        token="token-b",
        # 222 is intentionally duplicated to test first-wins merge
        user_aliases={222: "Robert", 333: "Carol"},
    )

    # Merge: channel_a aliases take precedence over channel_b on conflict
    merged: dict[int, str] = {}
    for channel in [channel_a, channel_b]:
        for uid, display_name in channel.user_aliases.items():
            merged.setdefault(uid, display_name)

    assert merged[111] == "Alice"
    assert merged[222] == "Bob"   # channel_a wins on conflict
    assert merged[333] == "Carol"
