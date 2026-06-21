"""Tests for trigger-based activation filtering in channel adapters.

Covers:
- ChannelAdapter._passes_trigger_filter (base class static method)
- DiscordChannel._passes_activation_filter (mention OR trigger OR logic)
- TelegramChannel._passes_activation_filter (mention OR trigger OR logic)
"""

from unittest.mock import MagicMock

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.discord import DiscordChannel
from openpaw.channels.telegram import TelegramChannel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_discord_channel(**kwargs) -> DiscordChannel:
    """Return a DiscordChannel with sensible test defaults."""
    defaults = {"token": "test-bot-token", "allowed_users": [123]}
    defaults.update(kwargs)
    return DiscordChannel(**defaults)


def _make_discord_message(
    content: str = "hello",
    guild_id: int | None = 100,
    mentions: list | None = None,
) -> MagicMock:
    """Return a minimal mock discord.Message.

    guild_id=None simulates a DM; any integer simulates a guild (server) message.
    """
    msg = MagicMock()
    msg.content = content
    msg.mentions = mentions if mentions is not None else []

    if guild_id is not None:
        msg.guild = MagicMock()
        msg.guild.id = guild_id
    else:
        msg.guild = None

    return msg


def _make_tg_channel(**kwargs) -> TelegramChannel:
    """Return a TelegramChannel with sensible test defaults."""
    defaults = {"token": "test-bot-token", "allowed_users": [123]}
    defaults.update(kwargs)
    return TelegramChannel(**defaults)


def _make_tg_update(
    chat_id: int = -100,
    text: str = "hello",
    entities: list | None = None,
) -> MagicMock:
    """Return a minimal mock Telegram Update.

    chat_id < 0 simulates a group chat; chat_id > 0 simulates a DM.
    """
    update = MagicMock()
    update.effective_chat = MagicMock()
    update.effective_chat.id = chat_id
    update.message = MagicMock()
    update.message.text = text
    update.message.caption = None
    update.message.entities = entities or []
    return update


# ---------------------------------------------------------------------------
# Base class: _passes_trigger_filter
# ---------------------------------------------------------------------------


def test_trigger_filter_empty_triggers_returns_false() -> None:
    """Empty trigger list never matches — trigger filter is opt-in."""
    assert ChannelAdapter._passes_trigger_filter("!ask me anything", []) is False


def test_trigger_filter_match_case_insensitive() -> None:
    """Trigger matching is case-insensitive; '!Ask' matches trigger '!ask'."""
    assert ChannelAdapter._passes_trigger_filter("!Ask me something", ["!ask"]) is True


def test_trigger_filter_no_match() -> None:
    """Content not containing any trigger keyword returns False."""
    assert ChannelAdapter._passes_trigger_filter("hello world", ["!ask"]) is False


def test_trigger_filter_multiple_any_match() -> None:
    """A single matching trigger in the list is sufficient to return True."""
    triggers = ["!ask", "hey bot"]
    # Only "hey bot" is present; "!ask" is not — still True
    assert ChannelAdapter._passes_trigger_filter("hey bot, help me out", triggers) is True


def test_trigger_filter_substring_match() -> None:
    """Trigger match is a substring check, not a word-boundary check."""
    assert ChannelAdapter._passes_trigger_filter("hey bot, help me", ["hey bot"]) is True


def test_trigger_filter_empty_content() -> None:
    """Empty message content never matches any trigger."""
    assert ChannelAdapter._passes_trigger_filter("", ["!ask", "hey bot"]) is False


# ---------------------------------------------------------------------------
# Discord: _passes_activation_filter
# ---------------------------------------------------------------------------


def test_discord_no_filters_passes_all() -> None:
    """No mention_required and no triggers — all guild messages pass through."""
    channel = _make_discord_channel(mention_required=False, triggers=[])
    msg = _make_discord_message(content="just chatting", guild_id=100)
    assert channel._passes_activation_filter(msg) is True


def test_discord_triggers_only_match() -> None:
    """Trigger keyword present in message → passes, even without a mention."""
    channel = _make_discord_channel(triggers=["!ask"])
    msg = _make_discord_message(content="!ask for help", guild_id=100)
    assert channel._passes_activation_filter(msg) is True


def test_discord_triggers_only_no_match() -> None:
    """Trigger keyword absent from message → blocked (mention_required not set)."""
    channel = _make_discord_channel(triggers=["!ask"])
    msg = _make_discord_message(content="hello there", guild_id=100)
    assert channel._passes_activation_filter(msg) is False


def test_discord_triggers_dm_always_passes() -> None:
    """DMs (guild=None) pass through regardless of trigger configuration."""
    channel = _make_discord_channel(triggers=["!ask"])
    msg = _make_discord_message(content="hello there", guild_id=None)
    assert channel._passes_activation_filter(msg) is True


def test_discord_mention_or_trigger_mention_wins() -> None:
    """mention_required=True + triggers set: bot mention alone satisfies the filter."""
    channel = _make_discord_channel(mention_required=True, triggers=["!ask"])
    channel._client = MagicMock()
    bot_user = MagicMock()
    channel._client.user = bot_user

    # Has bot mention, but no trigger keyword
    msg = _make_discord_message(content="hey can you help?", guild_id=100, mentions=[bot_user])
    assert channel._passes_activation_filter(msg) is True


def test_discord_mention_or_trigger_trigger_wins() -> None:
    """mention_required=True + triggers set: trigger keyword alone satisfies the filter."""
    channel = _make_discord_channel(mention_required=True, triggers=["!ask"])
    channel._client = MagicMock()
    channel._client.user = MagicMock()

    # Has trigger keyword, but no bot mention
    msg = _make_discord_message(content="!ask something", guild_id=100, mentions=[])
    assert channel._passes_activation_filter(msg) is True


def test_discord_mention_or_trigger_neither() -> None:
    """mention_required=True + triggers set: neither mention nor trigger → blocked."""
    channel = _make_discord_channel(mention_required=True, triggers=["!ask"])
    channel._client = MagicMock()
    channel._client.user = MagicMock()

    msg = _make_discord_message(content="just a regular message", guild_id=100, mentions=[])
    assert channel._passes_activation_filter(msg) is False


# ---------------------------------------------------------------------------
# Telegram: _passes_activation_filter
# ---------------------------------------------------------------------------


def test_telegram_no_filters_passes_all() -> None:
    """No mention_required and no triggers — all group messages pass through."""
    channel = _make_tg_channel(mention_required=False, triggers=[])
    update = _make_tg_update(chat_id=-100, text="just chatting")
    assert channel._passes_activation_filter(update) is True


def test_telegram_triggers_only_match() -> None:
    """Trigger keyword present in message → passes, even without a mention."""
    channel = _make_tg_channel(triggers=["!ask"])
    update = _make_tg_update(chat_id=-100, text="!ask for help")
    assert channel._passes_activation_filter(update) is True


def test_telegram_triggers_only_no_match() -> None:
    """Trigger keyword absent from message → blocked (mention_required not set)."""
    channel = _make_tg_channel(triggers=["!ask"])
    update = _make_tg_update(chat_id=-100, text="hello there")
    assert channel._passes_activation_filter(update) is False


def test_telegram_triggers_dm_always_passes() -> None:
    """Private chats (positive chat_id) pass through regardless of trigger configuration."""
    channel = _make_tg_channel(triggers=["!ask"])
    # Positive chat_id = private/DM chat in Telegram
    update = _make_tg_update(chat_id=99999, text="hello there")
    assert channel._passes_activation_filter(update) is True


def test_telegram_command_always_passes() -> None:
    """Messages starting with '/' are commands and always pass through."""
    channel = _make_tg_channel(triggers=["!ask"])
    update = _make_tg_update(chat_id=-100, text="/status")
    assert channel._passes_activation_filter(update) is True


def test_telegram_mention_or_trigger_trigger_wins() -> None:
    """mention_required=True + triggers set: trigger keyword alone satisfies the filter."""
    channel = _make_tg_channel(mention_required=True, triggers=["!ask"])
    # No entities (no @mention), but has trigger keyword
    update = _make_tg_update(chat_id=-100, text="!ask something please")
    assert channel._passes_activation_filter(update) is True


def test_telegram_mention_or_trigger_neither() -> None:
    """mention_required=True + triggers set: neither mention nor trigger → blocked."""
    channel = _make_tg_channel(mention_required=True, triggers=["!ask"])
    # No @mention entities and no trigger keyword
    update = _make_tg_update(chat_id=-100, text="just a regular message")
    assert channel._passes_activation_filter(update) is False
