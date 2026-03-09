"""Tests for ChannelEvent emission in DiscordChannel and ChannelLogger lifecycle wiring.

Covers:
- Discord adapter emits ChannelEvent for guild messages
- Discord adapter does NOT emit ChannelEvent for DMs (no guild)
- Discord adapter does NOT emit ChannelEvent for self-messages
- ChannelEvent has correct fields populated from discord.Message
- Event callback failures do not crash the adapter
- Lifecycle wires ChannelLogger when channel_log.enabled=true
- Lifecycle does NOT wire ChannelLogger when channel_log.enabled=false (default)
- Lifecycle runs archive_old_logs() on startup when logging is enabled
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.discord import DiscordChannel
from openpaw.model.channel import ChannelEvent
from openpaw.workspace.lifecycle import LifecycleManager

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_discord_channel(**kwargs) -> DiscordChannel:
    """Return a DiscordChannel with sensible test defaults."""
    defaults = {
        "token": "test-bot-token",
        "workspace_name": "test_ws",
        "allowed_users": [100],
    }
    defaults.update(kwargs)
    return DiscordChannel(**defaults)


def _make_mock_guild(guild_id: int = 777, guild_name: str = "Test Server") -> MagicMock:
    guild = MagicMock()
    guild.id = guild_id
    guild.name = guild_name
    return guild


def _make_mock_discord_channel(channel_id: int = 555, channel_name: str = "general") -> MagicMock:
    ch = MagicMock()
    ch.id = channel_id
    ch.name = channel_name
    return ch


def _make_mock_author(
    user_id: int = 100,
    display_name: str = "Alice",
    is_self: bool = False,
    bot_user: MagicMock | None = None,
) -> MagicMock:
    author = bot_user if is_self and bot_user else MagicMock()
    if not (is_self and bot_user):
        author.id = user_id
        author.display_name = display_name
    return author


_SENTINEL = object()  # sentinel to distinguish "not passed" from None


def _make_mock_message(
    msg_id: int = 1,
    user_id: int = 100,
    display_name: str = "Alice",
    content: str = "Hello there",
    guild: MagicMock | None = _SENTINEL,  # type: ignore[assignment]
    channel: MagicMock | None = None,
    attachments: list | None = None,
    created_at: datetime | None = None,
    author: MagicMock | None = None,
) -> MagicMock:
    """Build a minimal mock of a discord.Message.

    Pass ``guild=None`` explicitly to simulate a DM (no guild).
    Omit ``guild`` to get a default mock guild.
    """
    msg = MagicMock()
    msg.id = msg_id
    msg.content = content
    msg.guild = _make_mock_guild() if guild is _SENTINEL else guild
    msg.channel = channel if channel is not None else _make_mock_discord_channel()
    msg.attachments = attachments or []
    msg.created_at = created_at or datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC)
    msg.reply = AsyncMock()

    if author is not None:
        msg.author = author
    else:
        msg.author = MagicMock()
        msg.author.id = user_id
        msg.author.display_name = display_name

    return msg


def _make_lifecycle(merged_config: dict, workspace_path: Path | None = None) -> LifecycleManager:
    """Build a LifecycleManager with mocked dependencies."""
    return LifecycleManager(
        workspace_name="test_ws",
        workspace_path=workspace_path or Path("/tmp/test_ws"),
        workspace_config=None,
        merged_config=merged_config,
        config=MagicMock(),
        queue_manager=AsyncMock(),
        message_handler=AsyncMock(),
        queue_handler=AsyncMock(),
        builtin_loader=MagicMock(),
        workspace_timezone="UTC",
        session_manager=MagicMock(),
        approval_handler=AsyncMock(),
        logger=logging.getLogger("test"),
    )


def _make_mock_adapter(name: str) -> MagicMock:
    adapter = MagicMock(spec=ChannelAdapter)
    adapter.name = name
    return adapter


# ---------------------------------------------------------------------------
# 1. ChannelEvent emission — guild messages
# ---------------------------------------------------------------------------


class TestChannelEventEmissionGuildMessages:
    """Discord adapter emits ChannelEvent for messages received in guild channels."""

    @pytest.mark.asyncio
    async def test_emits_channel_event_for_guild_message(self) -> None:
        """on_channel_event callback is invoked for a normal guild message."""
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        # Patch _is_allowed and _to_message so _on_message can complete
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild(guild_id=777, guild_name="Test Server")
        msg = _make_mock_message(guild=guild)

        await adapter._on_message(msg)

        assert len(received) == 1
        assert isinstance(received[0], ChannelEvent)

    @pytest.mark.asyncio
    async def test_channel_event_contains_correct_user_id(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild()
        msg = _make_mock_message(user_id=42, guild=guild)

        await adapter._on_message(msg)

        assert received[0].user_id == "42"

    @pytest.mark.asyncio
    async def test_channel_event_contains_correct_display_name(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild()
        msg = _make_mock_message(display_name="Bob", guild=guild)

        await adapter._on_message(msg)

        assert received[0].display_name == "Bob"

    @pytest.mark.asyncio
    async def test_channel_event_contains_message_content(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild()
        msg = _make_mock_message(content="deploy status?", guild=guild)

        await adapter._on_message(msg)

        assert received[0].content == "deploy status?"

    @pytest.mark.asyncio
    async def test_channel_event_contains_server_name(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild(guild_id=888, guild_name="Engineering HQ")
        msg = _make_mock_message(guild=guild)

        await adapter._on_message(msg)

        assert received[0].server_name == "Engineering HQ"
        assert received[0].server_id == "888"

    @pytest.mark.asyncio
    async def test_channel_event_contains_channel_label(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild()
        channel = _make_mock_discord_channel(channel_id=555, channel_name="ops-alerts")
        msg = _make_mock_message(guild=guild, channel=channel)

        await adapter._on_message(msg)

        assert received[0].channel_label == "ops-alerts"
        assert received[0].channel_id == "555"

    @pytest.mark.asyncio
    async def test_channel_event_contains_message_id(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild()
        msg = _make_mock_message(msg_id=98765, guild=guild)

        await adapter._on_message(msg)

        assert received[0].message_id == "98765"

    @pytest.mark.asyncio
    async def test_channel_event_contains_timestamp(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        ts = datetime(2026, 3, 7, 15, 30, 0, tzinfo=UTC)
        guild = _make_mock_guild()
        msg = _make_mock_message(created_at=ts, guild=guild)

        await adapter._on_message(msg)

        assert received[0].timestamp == ts

    @pytest.mark.asyncio
    async def test_channel_event_channel_name_is_adapter_name(self) -> None:
        """ChannelEvent.channel_name matches the adapter's .name attribute."""
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild)

        await adapter._on_message(msg)

        assert received[0].channel_name == adapter.name


# ---------------------------------------------------------------------------
# 2. ChannelEvent NOT emitted for DMs
# ---------------------------------------------------------------------------


class TestChannelEventNotEmittedForDMs:
    """DM messages (guild=None) must not trigger the channel event callback."""

    @pytest.mark.asyncio
    async def test_dm_message_does_not_emit_channel_event(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        # guild=None simulates a DM
        msg = _make_mock_message(guild=None)

        await adapter._on_message(msg)

        assert received == []

    @pytest.mark.asyncio
    async def test_dm_callback_not_called_even_when_registered(self) -> None:
        """Callback is registered but still not called for DMs."""
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        callback = AsyncMock()
        adapter.on_channel_event(callback)
        adapter._is_allowed = MagicMock(return_value=True)
        adapter._passes_activation_filter = MagicMock(return_value=False)

        msg = _make_mock_message(guild=None)

        await adapter._on_message(msg)

        callback.assert_not_awaited()


# ---------------------------------------------------------------------------
# 3. ChannelEvent NOT emitted for self-messages
# ---------------------------------------------------------------------------


class TestChannelEventNotEmittedForSelfMessages:
    """Bot's own messages are ignored before the callback is invoked."""

    @pytest.mark.asyncio
    async def test_self_message_does_not_emit_channel_event(self) -> None:
        adapter = _make_discord_channel()

        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        callback = AsyncMock()
        adapter.on_channel_event(callback)

        # Bot sends a message with the bot's own author object
        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild)
        msg.author = bot_user  # same object as _client.user

        await adapter._on_message(msg)

        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_self_message_returns_early_without_processing(self) -> None:
        """Self-message returns immediately — _is_allowed is never reached."""
        adapter = _make_discord_channel()

        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        adapter._is_allowed = MagicMock(return_value=True)

        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild)
        msg.author = bot_user

        await adapter._on_message(msg)

        adapter._is_allowed.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Callback failure resilience
# ---------------------------------------------------------------------------


class TestCallbackFailureResilience:
    """Channel event callback failures must not interrupt _on_message processing."""

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash_on_message(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        async def _failing_callback(event: ChannelEvent) -> None:
            raise RuntimeError("simulated logging failure")

        adapter.on_channel_event(_failing_callback)
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild)

        # Must not raise
        await adapter._on_message(msg)

    @pytest.mark.asyncio
    async def test_on_message_continues_after_callback_failure(self) -> None:
        """After a callback failure, the normal allowlist check still runs."""
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        async def _failing_callback(event: ChannelEvent) -> None:
            raise ValueError("boom")

        adapter.on_channel_event(_failing_callback)
        is_allowed_mock = MagicMock(return_value=False)
        adapter._is_allowed = is_allowed_mock

        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild)

        await adapter._on_message(msg)

        # _is_allowed should still have been called despite the callback failure
        is_allowed_mock.assert_called_once_with(msg)

    @pytest.mark.asyncio
    async def test_no_callback_registered_does_not_raise(self) -> None:
        """If no callback is registered, _on_message runs normally."""
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild)

        # No on_channel_event registered — must not raise
        await adapter._on_message(msg)


# ---------------------------------------------------------------------------
# 5. Attachment names in ChannelEvent
# ---------------------------------------------------------------------------


class TestChannelEventAttachmentNames:
    """ChannelEvent.attachment_names is populated from discord.Message attachments."""

    @pytest.mark.asyncio
    async def test_attachment_names_are_collected(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        att1 = MagicMock()
        att1.filename = "report.pdf"
        att2 = MagicMock()
        att2.filename = "screenshot.png"

        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild, attachments=[att1, att2])

        await adapter._on_message(msg)

        assert received[0].attachment_names == ["report.pdf", "screenshot.png"]

    @pytest.mark.asyncio
    async def test_no_attachments_gives_empty_list(self) -> None:
        adapter = _make_discord_channel()
        bot_user = MagicMock()
        bot_user.id = 999
        adapter._client = MagicMock()
        adapter._client.user = bot_user

        received: list[ChannelEvent] = []

        async def _capture(event: ChannelEvent) -> None:
            received.append(event)

        adapter.on_channel_event(_capture)
        adapter._is_allowed = MagicMock(return_value=False)

        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild, attachments=[])

        await adapter._on_message(msg)

        assert received[0].attachment_names == []


# ---------------------------------------------------------------------------
# 6. Lifecycle wires ChannelLogger when channel_log.enabled=true
# ---------------------------------------------------------------------------


class TestLifecycleChannelLoggerWiring:
    """LifecycleManager.setup_channels() wires ChannelLogger for enabled channels.

    ChannelLogger is imported lazily inside _setup_channel_logger(), so we patch
    it at its definition location: openpaw.runtime.channel_logger.ChannelLogger.
    """

    @pytest.mark.asyncio
    @patch("openpaw.workspace.lifecycle.create_channel")
    async def test_channel_logger_wired_when_enabled(
        self, mock_create_channel, tmp_path: Path
    ) -> None:
        """ChannelLogger.log_event is registered as on_channel_event callback."""
        adapter = _make_mock_adapter("discord")
        mock_create_channel.return_value = adapter

        lm = _make_lifecycle(
            {
                "channels": [
                    {
                        "type": "discord",
                        "token": "dc-tok",
                        "channel_log": {"enabled": True, "retention_days": 30},
                    }
                ]
            },
            workspace_path=tmp_path / "workspace",
        )

        mock_channel_logger = MagicMock()
        mock_channel_logger.log_event = AsyncMock()
        mock_channel_logger.archive_old_logs = MagicMock(return_value=0)

        with patch(
            "openpaw.runtime.channel_logger.ChannelLogger",
            return_value=mock_channel_logger,
        ) as mock_channel_logger_cls:
            await lm.setup_channels()

        # ChannelLogger was created
        mock_channel_logger_cls.assert_called_once()

        # on_channel_event was registered with log_event
        adapter.on_channel_event.assert_called_once_with(mock_channel_logger.log_event)

    @pytest.mark.asyncio
    @patch("openpaw.workspace.lifecycle.create_channel")
    async def test_archive_old_logs_called_on_startup(
        self, mock_create_channel, tmp_path: Path
    ) -> None:
        """archive_old_logs() is invoked during setup_channels()."""
        adapter = _make_mock_adapter("discord")
        mock_create_channel.return_value = adapter

        lm = _make_lifecycle(
            {
                "channels": [
                    {
                        "type": "discord",
                        "token": "dc-tok",
                        "channel_log": {"enabled": True},
                    }
                ]
            },
            workspace_path=tmp_path / "workspace",
        )

        mock_channel_logger = MagicMock()
        mock_channel_logger.log_event = AsyncMock()
        mock_channel_logger.archive_old_logs = MagicMock(return_value=0)

        with patch(
            "openpaw.runtime.channel_logger.ChannelLogger",
            return_value=mock_channel_logger,
        ):
            await lm.setup_channels()

        mock_channel_logger.archive_old_logs.assert_called_once()

    @pytest.mark.asyncio
    @patch("openpaw.workspace.lifecycle.create_channel")
    async def test_channel_logger_uses_max_retention_days(
        self, mock_create_channel, tmp_path: Path
    ) -> None:
        """When multiple channels have logging enabled, the max retention_days is used."""
        adapter1 = _make_mock_adapter("discord")
        adapter2 = _make_mock_adapter("telegram")
        mock_create_channel.side_effect = [adapter1, adapter2]

        lm = _make_lifecycle(
            {
                "channels": [
                    {
                        "type": "discord",
                        "token": "dc-tok",
                        "channel_log": {"enabled": True, "retention_days": 14},
                    },
                    {
                        "type": "telegram",
                        "token": "tg-tok",
                        "channel_log": {"enabled": True, "retention_days": 60},
                    },
                ]
            },
            workspace_path=tmp_path / "workspace",
        )

        mock_channel_logger = MagicMock()
        mock_channel_logger.log_event = AsyncMock()
        mock_channel_logger.archive_old_logs = MagicMock(return_value=0)

        with patch(
            "openpaw.runtime.channel_logger.ChannelLogger",
            return_value=mock_channel_logger,
        ) as mock_channel_logger_cls:
            await lm.setup_channels()

        # retention_days should be 60 (the maximum)
        call_kwargs = mock_channel_logger_cls.call_args.kwargs
        assert call_kwargs["retention_days"] == 60

    @pytest.mark.asyncio
    @patch("openpaw.workspace.lifecycle.create_channel")
    async def test_channel_logger_workspace_path_passed(
        self, mock_create_channel, tmp_path: Path
    ) -> None:
        """ChannelLogger receives the correct workspace_path."""
        adapter = _make_mock_adapter("discord")
        mock_create_channel.return_value = adapter

        workspace_path = tmp_path / "my_workspace"
        lm = _make_lifecycle(
            {
                "channels": [
                    {
                        "type": "discord",
                        "token": "dc-tok",
                        "channel_log": {"enabled": True},
                    }
                ]
            },
            workspace_path=workspace_path,
        )

        mock_channel_logger = MagicMock()
        mock_channel_logger.log_event = AsyncMock()
        mock_channel_logger.archive_old_logs = MagicMock(return_value=0)

        with patch(
            "openpaw.runtime.channel_logger.ChannelLogger",
            return_value=mock_channel_logger,
        ) as mock_channel_logger_cls:
            await lm.setup_channels()

        call_kwargs = mock_channel_logger_cls.call_args.kwargs
        assert call_kwargs["workspace_path"] == workspace_path


# ---------------------------------------------------------------------------
# 7. Lifecycle does NOT wire ChannelLogger when disabled (default)
# ---------------------------------------------------------------------------


class TestLifecycleChannelLoggerNotWired:
    """ChannelLogger is not created when channel_log.enabled=false (default).

    Because ChannelLogger is imported lazily inside _setup_channel_logger(),
    we verify the absence of wiring via the _channel_logger attribute and by
    patching at the source module to confirm the constructor is never called.
    """

    @pytest.mark.asyncio
    @patch("openpaw.workspace.lifecycle.create_channel")
    async def test_no_channel_logger_when_disabled(self, mock_create_channel) -> None:
        """Explicit channel_log.enabled=false does not create a ChannelLogger."""
        adapter = _make_mock_adapter("telegram")
        mock_create_channel.return_value = adapter

        lm = _make_lifecycle(
            {
                "channels": [
                    {
                        "type": "telegram",
                        "token": "tok",
                        "channel_log": {"enabled": False},
                    }
                ]
            }
        )

        with patch(
            "openpaw.runtime.channel_logger.ChannelLogger"
        ) as mock_channel_logger_cls:
            await lm.setup_channels()

        mock_channel_logger_cls.assert_not_called()

    @pytest.mark.asyncio
    @patch("openpaw.workspace.lifecycle.create_channel")
    async def test_no_channel_logger_when_explicitly_disabled(
        self, mock_create_channel
    ) -> None:
        """Explicit channel_log.enabled=false does not create a ChannelLogger."""
        adapter = _make_mock_adapter("discord")
        mock_create_channel.return_value = adapter

        lm = _make_lifecycle(
            {
                "channels": [
                    {
                        "type": "discord",
                        "token": "dc-tok",
                        "channel_log": {"enabled": False},
                    }
                ]
            }
        )

        with patch(
            "openpaw.runtime.channel_logger.ChannelLogger"
        ) as mock_channel_logger_cls:
            await lm.setup_channels()

        mock_channel_logger_cls.assert_not_called()

    @pytest.mark.asyncio
    @patch("openpaw.workspace.lifecycle.create_channel")
    async def test_on_channel_event_not_called_when_logging_disabled(
        self, mock_create_channel
    ) -> None:
        """on_channel_event is not registered when channel logging is explicitly disabled."""
        adapter = _make_mock_adapter("discord")
        mock_create_channel.return_value = adapter

        lm = _make_lifecycle(
            {
                "channels": [
                    {
                        "type": "discord",
                        "token": "dc-tok",
                        "channel_log": {"enabled": False},
                    }
                ]
            }
        )

        await lm.setup_channels()

        adapter.on_channel_event.assert_not_called()

    @pytest.mark.asyncio
    @patch("openpaw.workspace.lifecycle.create_channel")
    async def test_channel_logger_attribute_is_none_when_disabled(
        self, mock_create_channel
    ) -> None:
        """_channel_logger attribute remains None when logging is explicitly disabled."""
        adapter = _make_mock_adapter("telegram")
        mock_create_channel.return_value = adapter

        lm = _make_lifecycle(
            {
                "channels": [
                    {
                        "type": "telegram",
                        "token": "tok",
                        "channel_log": {"enabled": False},
                    }
                ]
            }
        )

        await lm.setup_channels()

        assert lm._channel_logger is None


# ---------------------------------------------------------------------------
# 8. _build_channel_event helper
# ---------------------------------------------------------------------------


class TestBuildChannelEvent:
    """Unit tests for DiscordChannel._build_channel_event()."""

    def test_build_channel_event_returns_channel_event_instance(self) -> None:
        adapter = _make_discord_channel()
        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild)

        event = adapter._build_channel_event(msg)

        assert isinstance(event, ChannelEvent)

    def test_build_channel_event_maps_guild_name(self) -> None:
        adapter = _make_discord_channel()
        guild = _make_mock_guild(guild_name="Devs United")
        msg = _make_mock_message(guild=guild)

        event = adapter._build_channel_event(msg)

        assert event.server_name == "Devs United"

    def test_build_channel_event_maps_guild_id(self) -> None:
        adapter = _make_discord_channel()
        guild = _make_mock_guild(guild_id=12345)
        msg = _make_mock_message(guild=guild)

        event = adapter._build_channel_event(msg)

        assert event.server_id == "12345"

    def test_build_channel_event_none_content_becomes_empty_string(self) -> None:
        adapter = _make_discord_channel()
        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild, content="")
        msg.content = None

        event = adapter._build_channel_event(msg)

        assert event.content == ""

    def test_build_channel_event_null_created_at_falls_back_to_now(self) -> None:
        adapter = _make_discord_channel()
        guild = _make_mock_guild()
        msg = _make_mock_message(guild=guild)
        msg.created_at = None

        before = datetime.now(UTC)
        event = adapter._build_channel_event(msg)
        after = datetime.now(UTC)

        assert before <= event.timestamp <= after
