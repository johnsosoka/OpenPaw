"""Tests for WorkspaceRunner._inject_channel_context().

Covers:
- Skips DMs (no guild_id in metadata)
- Skips when context_messages=0 for the channel
- Prepends XML context block when history is available
- Returns original message on fetch failure
- Returns original message when adapter returns empty list
- Skips when channel adapter is not found
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.model.channel import ChannelHistoryEntry
from openpaw.model.message import Message, MessageDirection
from openpaw.workspace.runner import WorkspaceRunner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_inbound_message(
    channel: str = "discord",
    session_key: str = "discord:555",
    content: str = "what is the status?",
    guild_id: int | None = 999,
    channel_label: str = "general",
) -> Message:
    """Build a minimal inbound Message."""
    metadata: dict = {}
    if guild_id is not None:
        metadata["guild_id"] = guild_id
    if channel_label:
        metadata["channel_label"] = channel_label

    return Message(
        id="msg-1",
        channel=channel,
        session_key=session_key,
        user_id="100",
        content=content,
        direction=MessageDirection.INBOUND,
        timestamp=datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC),
        metadata=metadata,
    )


def _make_history_entries(count: int = 3) -> list[ChannelHistoryEntry]:
    """Build a small list of ChannelHistoryEntry objects."""
    base = datetime(2026, 3, 7, 11, 0, 0, tzinfo=UTC)
    return [
        ChannelHistoryEntry(
            timestamp=base.replace(minute=i * 5),
            user_id=str(i),
            display_name=f"User{i}",
            content=f"message {i}",
        )
        for i in range(count)
    ]


def _make_mock_channel_adapter(
    name: str = "discord",
    history_entries: list[ChannelHistoryEntry] | None = None,
    history_side_effect: Exception | None = None,
) -> MagicMock:
    """Build a MagicMock that behaves like a ChannelAdapter.

    Configures fetch_channel_history() to return `history_entries` or raise
    `history_side_effect` when provided.
    """
    adapter = MagicMock(spec=ChannelAdapter)
    adapter.name = name

    if history_side_effect is not None:
        adapter.fetch_channel_history = AsyncMock(side_effect=history_side_effect)
    else:
        adapter.fetch_channel_history = AsyncMock(return_value=history_entries or [])

    return adapter


def _make_runner_stub(
    channel_context_limits: dict[str, int] | None = None,
    channels: dict[str, MagicMock] | None = None,
) -> MagicMock:
    """Build a MagicMock that stands in for WorkspaceRunner.

    Only patches the attributes and methods needed by _inject_channel_context.
    We call the real method via WorkspaceRunner._inject_channel_context(stub, msg).
    """
    stub = MagicMock()
    stub._channel_context_limits = channel_context_limits if channel_context_limits is not None else {"discord": 25}
    stub._channels = channels or {}
    stub._session_ttl_minutes = 0  # Disabled by default in tests
    stub._session_manager = MagicMock()
    stub.logger = MagicMock()
    return stub


# ---------------------------------------------------------------------------
# Unbound method reference for direct calls on stub runner objects
# ---------------------------------------------------------------------------

_inject = WorkspaceRunner._inject_channel_context


# ---------------------------------------------------------------------------
# 1. DM skipping (no guild_id)
# ---------------------------------------------------------------------------


class TestDMSkip:
    """_inject_channel_context is a no-op for direct messages."""

    @pytest.mark.asyncio
    async def test_dm_message_returns_unchanged(self) -> None:
        dm_message = _make_inbound_message(guild_id=None)
        adapter = _make_mock_channel_adapter(history_entries=_make_history_entries())
        runner = _make_runner_stub(channels={"discord": adapter})

        result = await _inject(runner, dm_message)

        assert result is dm_message
        adapter.fetch_channel_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_dm_message_content_not_modified(self) -> None:
        original_content = "private question"
        dm_message = _make_inbound_message(guild_id=None, content=original_content)
        runner = _make_runner_stub()

        result = await _inject(runner, dm_message)

        assert result.content == original_content

    @pytest.mark.asyncio
    async def test_guild_id_none_skips_fetch(self) -> None:
        """Explicit guild_id=None in metadata skips fetch."""
        msg = _make_inbound_message(guild_id=None)
        adapter = _make_mock_channel_adapter()
        runner = _make_runner_stub(channels={"discord": adapter})

        await _inject(runner, msg)

        adapter.fetch_channel_history.assert_not_called()


# ---------------------------------------------------------------------------
# 2. context_messages=0 skip
# ---------------------------------------------------------------------------


class TestContextMessagesZero:
    """When context_messages is 0 no fetch is performed."""

    @pytest.mark.asyncio
    async def test_zero_limit_skips_fetch(self) -> None:
        msg = _make_inbound_message()
        adapter = _make_mock_channel_adapter(history_entries=_make_history_entries())
        runner = _make_runner_stub(
            channel_context_limits={"discord": 0},
            channels={"discord": adapter},
        )

        result = await _inject(runner, msg)

        adapter.fetch_channel_history.assert_not_called()
        assert result is msg

    @pytest.mark.asyncio
    async def test_zero_limit_content_unchanged(self) -> None:
        original = "hello bot"
        msg = _make_inbound_message(content=original)
        runner = _make_runner_stub(channel_context_limits={"discord": 0})

        result = await _inject(runner, msg)

        assert result.content == original


# ---------------------------------------------------------------------------
# 3. Successful context injection
# ---------------------------------------------------------------------------


class TestContextInjection:
    """When history is available, XML context block is prepended to content."""

    @pytest.mark.asyncio
    async def test_xml_block_is_prepended(self) -> None:
        msg = _make_inbound_message(content="what is the status?")
        entries = _make_history_entries(3)
        adapter = _make_mock_channel_adapter(history_entries=entries)
        runner = _make_runner_stub(channels={"discord": adapter})

        result = await _inject(runner, msg)

        assert result.content.startswith("<channel_context")

    @pytest.mark.asyncio
    async def test_original_content_follows_context_block(self) -> None:
        original = "what is the status?"
        msg = _make_inbound_message(content=original)
        entries = _make_history_entries(2)
        adapter = _make_mock_channel_adapter(history_entries=entries)
        runner = _make_runner_stub(channels={"discord": adapter})

        result = await _inject(runner, msg)

        assert original in result.content
        assert result.content.index("<channel_context") < result.content.index(original)

    @pytest.mark.asyncio
    async def test_context_block_contains_history_messages(self) -> None:
        entries = [
            ChannelHistoryEntry(
                timestamp=datetime(2026, 3, 7, 11, 0, 0, tzinfo=UTC),
                user_id="1",
                display_name="Alice",
                content="anyone around?",
            )
        ]
        msg = _make_inbound_message()
        adapter = _make_mock_channel_adapter(history_entries=entries)
        runner = _make_runner_stub(channels={"discord": adapter})

        result = await _inject(runner, msg)

        assert "Alice" in result.content
        assert "anyone around?" in result.content

    @pytest.mark.asyncio
    async def test_fetch_called_with_correct_limit(self) -> None:
        msg = _make_inbound_message(session_key="discord:555")
        adapter = _make_mock_channel_adapter(history_entries=[])
        runner = _make_runner_stub(
            channel_context_limits={"discord": 10},
            channels={"discord": adapter},
        )

        await _inject(runner, msg)

        adapter.fetch_channel_history.assert_called_once_with("555", limit=10)

    @pytest.mark.asyncio
    async def test_channel_id_extracted_from_session_key(self) -> None:
        """Channel ID is the last colon-separated part of session_key."""
        msg = _make_inbound_message(session_key="discord:12345678")
        entries = _make_history_entries(1)
        adapter = _make_mock_channel_adapter(history_entries=entries)
        runner = _make_runner_stub(channels={"discord": adapter})

        await _inject(runner, msg)

        call_args = adapter.fetch_channel_history.call_args
        assert call_args[0][0] == "12345678"

    @pytest.mark.asyncio
    async def test_xml_closing_tag_present(self) -> None:
        msg = _make_inbound_message()
        entries = _make_history_entries(1)
        adapter = _make_mock_channel_adapter(history_entries=entries)
        runner = _make_runner_stub(channels={"discord": adapter})

        result = await _inject(runner, msg)

        assert "</channel_context>" in result.content


# ---------------------------------------------------------------------------
# 4. Fetch failure → original message returned
# ---------------------------------------------------------------------------


class TestFetchFailure:
    """Errors from fetch_channel_history must not propagate; original message is returned."""

    @pytest.mark.asyncio
    async def test_runtime_error_returns_original_message(self) -> None:
        msg = _make_inbound_message(content="original text")
        adapter = _make_mock_channel_adapter(history_side_effect=RuntimeError("boom"))
        runner = _make_runner_stub(channels={"discord": adapter})

        result = await _inject(runner, msg)

        assert result is msg
        assert result.content == "original text"

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self) -> None:
        msg = _make_inbound_message()
        adapter = _make_mock_channel_adapter(history_side_effect=Exception("network error"))
        runner = _make_runner_stub(channels={"discord": adapter})

        # Must not raise
        result = await _inject(runner, msg)

        assert isinstance(result, Message)

    @pytest.mark.asyncio
    async def test_content_unchanged_on_fetch_failure(self) -> None:
        original = "my question"
        msg = _make_inbound_message(content=original)
        adapter = _make_mock_channel_adapter(history_side_effect=ValueError("bad channel"))
        runner = _make_runner_stub(channels={"discord": adapter})

        result = await _inject(runner, msg)

        assert result.content == original


# ---------------------------------------------------------------------------
# 5. Empty history → original message returned unchanged
# ---------------------------------------------------------------------------


class TestEmptyHistory:
    """When fetch returns [], content must not be modified."""

    @pytest.mark.asyncio
    async def test_empty_history_returns_original_message(self) -> None:
        original = "original content"
        msg = _make_inbound_message(content=original)
        adapter = _make_mock_channel_adapter(history_entries=[])
        runner = _make_runner_stub(channels={"discord": adapter})

        result = await _inject(runner, msg)

        assert result is msg

    @pytest.mark.asyncio
    async def test_empty_history_content_not_modified(self) -> None:
        original = "ask something"
        msg = _make_inbound_message(content=original)
        adapter = _make_mock_channel_adapter(history_entries=[])
        runner = _make_runner_stub(channels={"discord": adapter})

        result = await _inject(runner, msg)

        assert result.content == original

    @pytest.mark.asyncio
    async def test_empty_history_no_xml_tag(self) -> None:
        msg = _make_inbound_message()
        adapter = _make_mock_channel_adapter(history_entries=[])
        runner = _make_runner_stub(channels={"discord": adapter})

        result = await _inject(runner, msg)

        assert "<channel_context" not in result.content


# ---------------------------------------------------------------------------
# 6. Channel adapter not found
# ---------------------------------------------------------------------------


class TestMissingAdapter:
    """When no adapter is registered for the channel, return original message."""

    @pytest.mark.asyncio
    async def test_missing_adapter_returns_original(self) -> None:
        msg = _make_inbound_message(channel="discord")
        # No adapter registered under "discord"
        runner = _make_runner_stub(channels={})

        result = await _inject(runner, msg)

        assert result is msg

    @pytest.mark.asyncio
    async def test_missing_adapter_content_unchanged(self) -> None:
        original = "some text"
        msg = _make_inbound_message(content=original, channel="discord")
        runner = _make_runner_stub(channels={})

        result = await _inject(runner, msg)

        assert result.content == original


# ---------------------------------------------------------------------------
# 7. TTL-expired session skips context injection
# ---------------------------------------------------------------------------


class TestTTLExpiredSkip:
    """Channel context is not injected when the session is about to be TTL-rotated."""

    @pytest.mark.asyncio
    async def test_expired_session_skips_context(self) -> None:
        """When session TTL is expired, channel context is not injected."""
        adapter = _make_mock_channel_adapter(history_entries=_make_history_entries())
        runner = _make_runner_stub(channels={"discord": adapter})
        runner._session_ttl_minutes = 60
        runner._session_manager.is_session_expired.return_value = True

        msg = _make_inbound_message()
        result = await _inject(runner, msg)

        assert "<channel_context" not in result.content
        adapter.fetch_channel_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_expired_session_gets_context(self) -> None:
        """When session TTL is configured but not expired, context is injected."""
        adapter = _make_mock_channel_adapter(history_entries=_make_history_entries())
        runner = _make_runner_stub(channels={"discord": adapter})
        runner._session_ttl_minutes = 60
        runner._session_manager.is_session_expired.return_value = False

        msg = _make_inbound_message()
        result = await _inject(runner, msg)

        assert "<channel_context" in result.content

    @pytest.mark.asyncio
    async def test_ttl_disabled_does_not_check_expiry(self) -> None:
        """When session_ttl_minutes is 0, expiry is never checked."""
        adapter = _make_mock_channel_adapter(history_entries=_make_history_entries())
        runner = _make_runner_stub(channels={"discord": adapter})
        runner._session_ttl_minutes = 0

        msg = _make_inbound_message()
        await _inject(runner, msg)

        runner._session_manager.is_session_expired.assert_not_called()
