"""Tests for DiscordChannel.fetch_channel_history().

Covers:
- Returns ChannelHistoryEntry list from Discord messages
- Results are in chronological order (oldest first)
- Bot's own messages are filtered out
- Attachment summary is built correctly
- Error handling returns empty list
- Empty channel returns empty list
- before_message_id is passed through to channel.history()
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.discord import DiscordChannel
from openpaw.model.channel import ChannelHistoryEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_discord_channel(**kwargs) -> DiscordChannel:
    """Return a DiscordChannel with sensible test defaults."""
    defaults = {"token": "test-bot-token", "workspace_name": "test_ws"}
    defaults.update(kwargs)
    return DiscordChannel(**defaults)


def _make_mock_discord_message(
    msg_id: int = 1,
    user_id: int = 100,
    display_name: str = "Alice",
    content: str = "hello",
    created_at: datetime | None = None,
    is_bot: bool = False,
    attachments: list | None = None,
    is_self: bool = False,
) -> MagicMock:
    """Build a minimal mock of a discord.Message."""
    msg = MagicMock()
    msg.id = msg_id
    msg.content = content
    msg.author.id = user_id
    msg.author.display_name = display_name
    msg.author.bot = is_bot
    msg.created_at = created_at or datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC)
    msg.attachments = attachments or []
    # is_self flag is resolved by patching _client.user comparison in tests
    msg._is_self = is_self
    return msg


def _make_mock_attachment(filename: str = "image.png") -> MagicMock:
    att = MagicMock()
    att.filename = filename
    return att


def _build_channel_with_client(
    bot_user_id: int = 999,
    channel_messages: list | None = None,
) -> tuple[DiscordChannel, MagicMock, MagicMock]:
    """Return (adapter, mock_client, mock_discord_channel).

    Sets up the adapter's _client so bot-self-message filtering works.
    mock_discord_channel.history() is an async generator yielding channel_messages.
    """
    adapter = _make_discord_channel()

    mock_bot_user = MagicMock()
    mock_bot_user.id = bot_user_id

    mock_client = MagicMock()
    mock_client.user = mock_bot_user
    adapter._client = mock_client

    # Build the async generator for channel.history()
    messages = channel_messages or []

    async def _history_gen(**_kwargs):
        for m in messages:
            yield m

    mock_discord_channel = MagicMock()
    mock_discord_channel.history = MagicMock(side_effect=_history_gen)

    # Patch _resolve_channel to return mock_discord_channel
    adapter._resolve_channel = AsyncMock(return_value=mock_discord_channel)

    # Mark "self" messages so we can differentiate in the mock
    for m in messages:
        if getattr(m, "_is_self", False):
            m.author = mock_bot_user

    return adapter, mock_client, mock_discord_channel


# ---------------------------------------------------------------------------
# 1. Basic fetch — returns ChannelHistoryEntry list
# ---------------------------------------------------------------------------


class TestFetchChannelHistoryBasic:
    """fetch_channel_history() returns the right shape of data."""

    @pytest.mark.asyncio
    async def test_returns_channel_history_entry_instances(self) -> None:
        msg = _make_mock_discord_message(msg_id=1, user_id=10, display_name="Alice", content="hi")
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert all(isinstance(e, ChannelHistoryEntry) for e in result)

    @pytest.mark.asyncio
    async def test_maps_fields_correctly(self) -> None:
        ts = datetime(2026, 3, 7, 10, 0, 0, tzinfo=UTC)
        msg = _make_mock_discord_message(
            msg_id=42, user_id=77, display_name="Bob", content="test message", created_at=ts
        )
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert len(result) == 1
        entry = result[0]
        assert entry.user_id == "77"
        assert entry.display_name == "Bob"
        assert entry.content == "test message"
        assert entry.timestamp == ts

    @pytest.mark.asyncio
    async def test_is_bot_false_for_human_messages(self) -> None:
        msg = _make_mock_discord_message(is_bot=False)
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert result[0].is_bot is False

    @pytest.mark.asyncio
    async def test_is_bot_true_for_bot_messages(self) -> None:
        msg = _make_mock_discord_message(user_id=88, is_bot=True)
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert result[0].is_bot is True

    @pytest.mark.asyncio
    async def test_empty_content_becomes_empty_string(self) -> None:
        msg = _make_mock_discord_message(content="")
        # discord.py may return None for content on embed-only messages
        msg.content = None
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert result[0].content == ""


# ---------------------------------------------------------------------------
# 2. Chronological ordering
# ---------------------------------------------------------------------------


class TestChronologicalOrder:
    """Discord returns newest-first; fetch_channel_history() reverses to oldest-first."""

    @pytest.mark.asyncio
    async def test_single_message_is_returned(self) -> None:
        msg = _make_mock_discord_message(msg_id=1)
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_messages_are_in_chronological_order(self) -> None:
        # Discord yields newest first: msg3 → msg2 → msg1
        ts1 = datetime(2026, 3, 7, 9, 0, 0, tzinfo=UTC)
        ts2 = datetime(2026, 3, 7, 10, 0, 0, tzinfo=UTC)
        ts3 = datetime(2026, 3, 7, 11, 0, 0, tzinfo=UTC)

        msg3 = _make_mock_discord_message(msg_id=3, display_name="C", created_at=ts3)
        msg2 = _make_mock_discord_message(msg_id=2, display_name="B", created_at=ts2)
        msg1 = _make_mock_discord_message(msg_id=1, display_name="A", created_at=ts1)

        adapter, _, _ = _build_channel_with_client(channel_messages=[msg3, msg2, msg1])

        result = await adapter.fetch_channel_history("555")

        # Oldest first after reversal
        assert result[0].display_name == "A"
        assert result[1].display_name == "B"
        assert result[2].display_name == "C"

    @pytest.mark.asyncio
    async def test_timestamps_are_ascending(self) -> None:
        ts_early = datetime(2026, 3, 7, 8, 0, 0, tzinfo=UTC)
        ts_late = datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC)

        # Discord order: late first, early second
        msg_late = _make_mock_discord_message(msg_id=2, created_at=ts_late)
        msg_early = _make_mock_discord_message(msg_id=1, created_at=ts_early)

        adapter, _, _ = _build_channel_with_client(channel_messages=[msg_late, msg_early])

        result = await adapter.fetch_channel_history("555")

        assert result[0].timestamp <= result[1].timestamp


# ---------------------------------------------------------------------------
# 3. Bot self-message filtering
# ---------------------------------------------------------------------------


class TestBotSelfFiltering:
    """The bot's own messages must not appear in the returned entries."""

    @pytest.mark.asyncio
    async def test_bot_own_message_is_excluded(self) -> None:
        # bot_user_id=999; one message authored by user 100, one "by the bot"
        ts = datetime(2026, 3, 7, 10, 0, 0, tzinfo=UTC)
        human_msg = _make_mock_discord_message(user_id=100, display_name="Alice", created_at=ts)
        self_msg = _make_mock_discord_message(msg_id=2, is_self=True)

        adapter, mock_client, _ = _build_channel_with_client(
            bot_user_id=999, channel_messages=[self_msg, human_msg]
        )

        result = await adapter.fetch_channel_history("555")

        assert len(result) == 1
        assert result[0].display_name == "Alice"

    @pytest.mark.asyncio
    async def test_all_bot_own_messages_excluded(self) -> None:
        self_msg1 = _make_mock_discord_message(msg_id=1, is_self=True)
        self_msg2 = _make_mock_discord_message(msg_id=2, is_self=True)

        adapter, mock_client, _ = _build_channel_with_client(
            bot_user_id=999, channel_messages=[self_msg1, self_msg2]
        )

        result = await adapter.fetch_channel_history("555")

        assert result == []

    @pytest.mark.asyncio
    async def test_non_bot_messages_are_kept(self) -> None:
        msg = _make_mock_discord_message(user_id=50, display_name="Carol")
        adapter, _, _ = _build_channel_with_client(bot_user_id=999, channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert len(result) == 1


# ---------------------------------------------------------------------------
# 4. Attachment summary
# ---------------------------------------------------------------------------


class TestAttachmentSummary:
    """attachments_summary is built from discord.Attachment filenames."""

    @pytest.mark.asyncio
    async def test_no_attachments_gives_none(self) -> None:
        msg = _make_mock_discord_message(attachments=[])
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert result[0].attachments_summary is None

    @pytest.mark.asyncio
    async def test_single_attachment_uses_singular_label(self) -> None:
        att = _make_mock_attachment("photo.jpg")
        msg = _make_mock_discord_message(attachments=[att])
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert result[0].attachments_summary == "[1 file: photo.jpg]"

    @pytest.mark.asyncio
    async def test_multiple_attachments_use_plural_label(self) -> None:
        att1 = _make_mock_attachment("image.png")
        att2 = _make_mock_attachment("report.pdf")
        msg = _make_mock_discord_message(attachments=[att1, att2])
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert result[0].attachments_summary == "[2 files: image.png, report.pdf]"

    @pytest.mark.asyncio
    async def test_attachment_filenames_all_listed(self) -> None:
        att1 = _make_mock_attachment("a.pdf")
        att2 = _make_mock_attachment("b.docx")
        att3 = _make_mock_attachment("c.png")
        msg = _make_mock_discord_message(attachments=[att1, att2, att3])
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        summary = result[0].attachments_summary
        assert summary is not None
        assert "a.pdf" in summary
        assert "b.docx" in summary
        assert "c.png" in summary


# ---------------------------------------------------------------------------
# 5. Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Any exception during fetch must return [] without propagating."""

    @pytest.mark.asyncio
    async def test_resolve_channel_failure_returns_empty(self) -> None:
        adapter = _make_discord_channel()
        adapter._client = MagicMock()
        adapter._resolve_channel = AsyncMock(side_effect=RuntimeError("not found"))

        result = await adapter.fetch_channel_history("555")

        assert result == []

    @pytest.mark.asyncio
    async def test_discord_http_error_returns_empty(self) -> None:
        """A discord.HTTPException from _resolve_channel results in an empty list."""

        class _FakeHTTPError(Exception):
            """Stand-in for discord.HTTPException (avoids brittle constructor call)."""

        adapter = _make_discord_channel()
        adapter._client = MagicMock()
        adapter._resolve_channel = AsyncMock(side_effect=_FakeHTTPError("Rate limited"))

        result = await adapter.fetch_channel_history("555")

        assert result == []

    @pytest.mark.asyncio
    async def test_no_client_returns_empty(self) -> None:
        """fetch_channel_history returns [] when _client is not set."""
        adapter = _make_discord_channel()
        # _client defaults to None — _resolve_channel will raise RuntimeError
        # which fetch_channel_history should catch and return []
        result = await adapter.fetch_channel_history("555")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_list_type_on_success(self) -> None:
        msg = _make_mock_discord_message()
        adapter, _, _ = _build_channel_with_client(channel_messages=[msg])

        result = await adapter.fetch_channel_history("555")

        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 6. Empty channel
# ---------------------------------------------------------------------------


class TestEmptyChannel:
    """When the channel has no messages the result is an empty list."""

    @pytest.mark.asyncio
    async def test_empty_channel_returns_empty_list(self) -> None:
        adapter, _, _ = _build_channel_with_client(channel_messages=[])

        result = await adapter.fetch_channel_history("555")

        assert result == []

    @pytest.mark.asyncio
    async def test_empty_channel_result_is_a_list(self) -> None:
        adapter, _, _ = _build_channel_with_client(channel_messages=[])

        result = await adapter.fetch_channel_history("555")

        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 7. before_message_id passthrough
# ---------------------------------------------------------------------------


class TestBeforeMessageId:
    """before_message_id is passed to channel.history() as a discord.Object."""

    @pytest.mark.asyncio
    async def test_before_message_id_passed_to_history(self) -> None:
        import discord as _discord

        adapter, _, mock_discord_channel = _build_channel_with_client(channel_messages=[])

        await adapter.fetch_channel_history("555", before_message_id="12345")

        call_kwargs = mock_discord_channel.history.call_args[1]
        before_arg = call_kwargs.get("before")
        assert before_arg is not None
        assert isinstance(before_arg, _discord.Object)
        assert before_arg.id == 12345

    @pytest.mark.asyncio
    async def test_no_before_message_id_passes_none(self) -> None:
        adapter, _, mock_discord_channel = _build_channel_with_client(channel_messages=[])

        await adapter.fetch_channel_history("555")

        call_kwargs = mock_discord_channel.history.call_args[1]
        before_arg = call_kwargs.get("before")
        assert before_arg is None
