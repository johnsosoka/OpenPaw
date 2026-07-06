"""Discord channel adapter using discord.py."""

import asyncio
import logging
import os
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import aiohttp
import discord
from discord import app_commands

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.discord.attachments import DiscordAttachmentDownloader
from openpaw.channels.discord.commands import DiscordCommandRegistrar
from openpaw.channels.discord.constants import MAX_FILE_SIZE, MAX_MESSAGE_LENGTH
from openpaw.channels.discord.history import DiscordHistoryFetcher
from openpaw.channels.discord.outbound import DiscordOutboundSender
from openpaw.channels.helpers import SecurityMixin, format_unauthorized_response
from openpaw.model.channel import ChannelEvent, ChannelHistoryEntry
from openpaw.model.message import Message, MessageDirection

logger = logging.getLogger(__name__)


class DiscordChannel(ChannelAdapter, SecurityMixin):
    """Discord channel adapter.

    Handles:
    - Bot initialization and lifecycle via discord.py Client
    - Message format conversion (discord.Message -> OpenPaw Message)
    - User / guild allowlisting
    - Slash command registration via CommandTree
    - File and approval-gate message delivery
    """

    name = "discord"

    MAX_MESSAGE_LENGTH = MAX_MESSAGE_LENGTH
    MAX_FILE_SIZE = MAX_FILE_SIZE

    # Transient Discord transport failures worth retrying (channel retry
    # interface). DiscordServerError = 5xx; ClientConnectionError = dropped
    # connection. HTTPException (4xx base) and Forbidden/NotFound stay off —
    # they are permanent. DiscordServerError subclasses HTTPException, so it
    # is listed explicitly rather than via the base.
    #
    # Resolved via getattr: under pytest's prepend-import mode the test dir
    # `tests/channels/discord/` shadows the installed `discord` package as a
    # namespace, so top-level attributes aren't materialized at collection
    # time. Dropping a missing type (never crashing import) keeps behavior
    # correct in production while tolerating that test-env artifact.
    RETRYABLE_SEND_ERRORS = tuple(
        e
        for e in (getattr(discord, "DiscordServerError", None), aiohttp.ClientConnectionError)
        if e is not None
    )

    def __init__(
        self,
        token: str | None = None,
        allowed_users: list[int] | None = None,
        allowed_groups: list[int] | None = None,
        allow_all: bool = False,
        mention_required: bool = False,
        triggers: list[str] | None = None,
        workspace_name: str = "unknown",
    ) -> None:
        """Initialize the Discord channel."""
        resolved_token = token or os.environ.get("DISCORD_BOT_TOKEN")
        if not resolved_token:
            raise ValueError(
                "Discord bot token required (pass token or set DISCORD_BOT_TOKEN)"
            )
        self._token: str = resolved_token

        self.allowed_users: set[int] = set(allowed_users or [])
        self.allowed_groups: set[int] = set(allowed_groups or [])
        self.allow_all = allow_all
        self.mention_required = mention_required
        self.triggers: list[str] = triggers or []
        self.workspace_name = workspace_name

        self._client: discord.Client | None = None
        self._tree: app_commands.CommandTree | None = None
        self._ready_event: asyncio.Event = asyncio.Event()
        self._client_task: asyncio.Task[None] | None = None

        self._message_callback: Callable[[Message], Coroutine[Any, Any, None]] | None = None
        self._approval_callback: Callable[[str, bool], Coroutine[Any, Any, None]] | None = None
        self._channel_event_callback: Callable[[ChannelEvent], Coroutine[Any, Any, None]] | None = None

        self._attachment_downloader = DiscordAttachmentDownloader()
        self._history_fetcher: DiscordHistoryFetcher | None = None
        self._command_registrar: DiscordCommandRegistrar | None = None
        self._outbound_sender: DiscordOutboundSender | None = None

    @property
    def supports_history_browsing(self) -> bool:
        """Discord supports full channel history via the channel.history() API."""
        return True

    async def start(self) -> None:
        """Start the Discord bot and wait until it is ready."""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True

        self._client = discord.Client(intents=intents)
        self._tree = app_commands.CommandTree(self._client)
        self._ready_event.clear()

        @self._client.event
        async def on_ready() -> None:
            await self._on_ready()

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            await self._on_message(message)

        self._client_task = asyncio.create_task(
            self._client.start(self._token),
            name=f"discord-client-{self.workspace_name}",
        )

        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=30.0)
        except TimeoutError as exc:
            logger.error("Discord bot did not become ready within 30 seconds")
            raise RuntimeError("Discord bot failed to connect in time") from exc

        self._outbound_sender = self._build_outbound_sender()
        self._history_fetcher = DiscordHistoryFetcher(
            client=self._client,
            resolve_channel=self._resolve_channel,
        )
        self._command_registrar = DiscordCommandRegistrar(
            client=self._client,
            tree=self._tree,
            channel_name=self.name,
            workspace_name=self.workspace_name,
            message_callback=self._message_callback,
            build_session_key=self.build_session_key,
        )

        logger.info("Discord channel started (workspace: %s)", self.workspace_name)

    def _build_outbound_sender(self) -> DiscordOutboundSender:
        """Construct the outbound sender wired to this channel's retry runner.

        Single construction point (the sender is rebuilt lazily in several
        outbound methods); injecting ``send_with_retry`` here gives every
        content-bearing call transient-failure backoff without per-call
        plumbing.
        """
        return DiscordOutboundSender(
            client=self._client,
            channel_name=self.name,
            bot_id=self._client.user.id,  # type: ignore[union-attr]
            retry=self.send_with_retry,
        )

    async def stop(self) -> None:
        """Stop the Discord bot gracefully."""
        if self._client:
            await self._client.close()
            logger.info("Discord channel stopped (workspace: %s)", self.workspace_name)

        if self._client_task and not self._client_task.done():
            try:
                await asyncio.wait_for(self._client_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._client_task.cancel()

    async def _on_ready(self) -> None:
        """Called by discord.py once the client is connected and ready."""
        logger.info(
            "Discord bot ready: %s (ID: %s)",
            self._client.user,  # type: ignore[union-attr]
            self._client.user.id,  # type: ignore[union-attr]
        )
        self._ready_event.set()

    async def _on_message(self, discord_message: discord.Message) -> None:
        """Called by discord.py for every message the bot can see."""
        if self._client and discord_message.author == self._client.user:
            return

        if self._channel_event_callback and discord_message.guild:
            try:
                event = self._build_channel_event(discord_message)
                await self._channel_event_callback(event)
            except Exception:
                logger.debug("Channel event callback failed", exc_info=True)

        if not self._is_allowed(discord_message):
            await self._send_unauthorized_response(discord_message)
            return

        if not self._passes_activation_filter(discord_message):
            return

        message = await self._to_message(discord_message)
        if message and self._message_callback:
            await self._message_callback(message)

    def _build_channel_event(self, discord_message: discord.Message) -> ChannelEvent:
        """Build a ChannelEvent from a discord.Message for persistent logging."""
        attachment_names = [
            a.filename for a in discord_message.attachments if a.filename
        ]
        return ChannelEvent(
            timestamp=discord_message.created_at or datetime.now(UTC),
            channel_name=self.name,
            channel_id=str(discord_message.channel.id),
            channel_label=getattr(discord_message.channel, "name", "unknown"),
            server_name=discord_message.guild.name if discord_message.guild else None,
            server_id=str(discord_message.guild.id) if discord_message.guild else None,
            user_id=str(discord_message.author.id),
            display_name=discord_message.author.display_name,
            content=discord_message.content or "",
            attachment_names=attachment_names,
            message_id=str(discord_message.id),
        )

    def on_message(self, callback: Callable[[Message], Coroutine[Any, Any, None]]) -> None:
        """Register callback for incoming messages."""
        self._message_callback = callback

    def on_approval(
        self, callback: Callable[[str, bool], Coroutine[Any, Any, None]]
    ) -> None:
        """Register callback for approval resolutions."""
        self._approval_callback = callback

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        """Send a message to a Discord channel."""
        if not self._outbound_sender:
            raise RuntimeError("Discord channel not started")
        return await self._outbound_sender.send_message(session_key, content, **kwargs)

    async def send_file(
        self,
        session_key: str,
        file_data: bytes,
        filename: str,
        mime_type: str | None = None,
        caption: str | None = None,
    ) -> None:
        """Send a file to a Discord channel."""
        if not self._outbound_sender:
            if not self._client:
                raise RuntimeError("Discord channel not started")
            self._outbound_sender = self._build_outbound_sender()
        await self._outbound_sender.send_file(session_key, file_data, filename, mime_type, caption)

    async def send_approval_request(
        self,
        session_key: str,
        approval_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        show_args: bool = True,
    ) -> None:
        """Send an approval request with Approve / Deny buttons."""
        if not self._outbound_sender:
            raise RuntimeError("Discord channel not started")
        if not self._approval_callback:
            logger.warning("send_approval_request called but no approval callback registered")
            return
        await self._outbound_sender.send_approval_request(
            session_key=session_key,
            approval_id=approval_id,
            tool_name=tool_name,
            tool_args=tool_args,
            show_args=show_args,
            approval_callback=self._approval_callback,
        )

    async def edit_message(
        self,
        session_key: str,
        message_id: str,
        content: str,
    ) -> bool:
        """Edit an existing Discord message."""
        if not self._outbound_sender:
            if not self._client:
                raise RuntimeError("Discord channel not started")
            self._outbound_sender = self._build_outbound_sender()
        return await self._outbound_sender.edit_message(session_key, message_id, content)

    async def delete_message(
        self,
        session_key: str,
        message_id: str,
    ) -> bool:
        """Delete an existing Discord message."""
        if not self._outbound_sender:
            if not self._client:
                raise RuntimeError("Discord channel not started")
            self._outbound_sender = self._build_outbound_sender()
        return await self._outbound_sender.delete_message(session_key, message_id)

    async def send_typing(self, session_key: str) -> None:
        """Trigger Discord typing indicator."""
        if not self._outbound_sender:
            if not self._client:
                raise RuntimeError("Discord channel not started")
            self._outbound_sender = self._build_outbound_sender()
        await self._outbound_sender.send_typing(session_key)

    async def add_reaction(self, session_key: str, message_id: str, emoji: str) -> bool:
        """Add an emoji reaction to a Discord message."""
        if not self._outbound_sender:
            if not self._client:
                raise RuntimeError("Discord channel not started")
            self._outbound_sender = self._build_outbound_sender()
        return await self._outbound_sender.add_reaction(session_key, message_id, emoji)

    async def remove_reaction(self, session_key: str, message_id: str, emoji: str) -> bool:
        """Remove a bot reaction from a Discord message."""
        if not self._outbound_sender:
            if not self._client:
                raise RuntimeError("Discord channel not started")
            self._outbound_sender = self._build_outbound_sender()
        return await self._outbound_sender.remove_reaction(session_key, message_id, emoji)

    async def register_commands(self, commands: list[Any]) -> None:
        """Register OpenPaw commands as Discord slash commands."""
        if self._command_registrar is None:
            logger.warning("register_commands called before Discord client was started")
            return
        await self._command_registrar.register(commands)

    async def _to_message(self, discord_message: discord.Message) -> Message | None:
        """Convert a discord.Message to the unified OpenPaw Message format."""
        session_key = self.build_session_key(discord_message.channel.id)

        attachments = await self._attachment_downloader.download_all(discord_message)

        return Message(
            id=str(discord_message.id),
            channel=self.name,
            session_key=session_key,
            user_id=str(discord_message.author.id),
            content=discord_message.content or "",
            direction=MessageDirection.INBOUND,
            timestamp=discord_message.created_at or datetime.now(UTC),
            metadata={
                "guild_id": discord_message.guild.id if discord_message.guild else None,
                "username": discord_message.author.name,
                "display_name": discord_message.author.display_name,
                "channel_label": getattr(discord_message.channel, "name", None),
            },
            attachments=attachments,
        )

    def _is_allowed(self, message: discord.Message) -> bool:
        """Check whether the message sender is permitted to use this workspace."""
        user_id = message.author.id
        guild_id = message.guild.id if message.guild else None
        return self._check_user_allowed(user_id, guild_id)

    def _passes_activation_filter(self, message: discord.Message) -> bool:
        """Check whether the message passes activation filters (mention OR trigger)."""
        is_dm = message.guild is None
        is_command = False
        content = message.content or ""
        is_mentioned = (
            self._client is not None
            and self._client.user in message.mentions
        )
        return self._check_activation(
            content, is_dm, is_command, is_mentioned
        )

    async def _send_unauthorized_response(self, message: discord.Message) -> None:
        """Reply to an unauthorized user with their IDs and config instructions."""
        user_id = message.author.id
        guild_id = message.guild.id if message.guild else None

        text = format_unauthorized_response(user_id, self.workspace_name, guild_id)

        try:
            await message.reply(text)
        except discord.HTTPException:
            logger.debug("Failed to send unauthorized response", exc_info=True)

        logger.warning(
            "Blocked Discord user %d from workspace '%s'", user_id, self.workspace_name
        )

    async def fetch_channel_history(
        self,
        channel_id: str,
        limit: int = 25,
        before_message_id: str | None = None,
    ) -> list[ChannelHistoryEntry]:
        """Fetch recent messages from a Discord channel."""
        if self._history_fetcher is None:
            if self._client is None:
                logger.warning("fetch_channel_history called before Discord client was started")
                return []
            self._history_fetcher = DiscordHistoryFetcher(
                client=self._client,
                resolve_channel=self._resolve_channel,
            )
        return await self._history_fetcher.fetch_history(channel_id, limit, before_message_id)

    async def _download_attachments(
        self, discord_message: Any
    ) -> list[Any]:
        """Download all attachments from a discord.Message.

        Backward-compatible wrapper for DiscordAttachmentDownloader.
        """
        return await self._attachment_downloader.download_all(discord_message)

    def _split_message(self, text: str) -> list[str]:
        """Split text into chunks that fit Discord's 2000-char message limit.

        Backward-compatible wrapper.
        """
        from openpaw.channels.helpers import split_message
        return split_message(text, self.MAX_MESSAGE_LENGTH)

    async def _resolve_channel(self, channel_id: int) -> Any:
        """Backward-compatible wrapper for DiscordOutboundSender._resolve_channel."""
        if self._outbound_sender is None:
            if self._client is None:
                raise RuntimeError("Discord channel not started")
            # Fallback for tests that set _client but not _outbound_sender
            self._outbound_sender = self._build_outbound_sender()
        return await self._outbound_sender._resolve_channel(channel_id)

    @staticmethod
    def _channel_id_from_session_key(session_key: str) -> int:
        """Extract the Discord channel ID from a session key."""
        parts = session_key.split(":")
        return int(parts[1])
