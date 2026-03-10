"""Discord channel adapter using discord.py."""

import asyncio
import logging
import os
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import discord
from discord import app_commands

from openpaw.channels.base import ChannelAdapter
from openpaw.model.channel import ChannelEvent, ChannelHistoryEntry
from openpaw.model.message import Attachment, Message, MessageDirection

logger = logging.getLogger(__name__)


class _ApprovalView(discord.ui.View):
    """Discord UI view for approval gate requests.

    Renders Approve / Deny buttons. On interaction the stored callback is
    invoked and the view is disabled so buttons cannot be pressed twice.
    """

    def __init__(
        self,
        approval_id: str,
        callback: Callable[[str, bool], Coroutine[Any, Any, None]],
        timeout: float = 120.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._approval_id = approval_id
        self._callback = callback

    async def _resolve(self, interaction: discord.Interaction, approved: bool) -> None:
        """Disable buttons and invoke the approval callback."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        result_label = "Approved" if approved else "Denied"
        try:
            await interaction.response.edit_message(
                content=f"{interaction.message.content}\n\nResult: {result_label}",
                view=self,
            )
        except Exception:
            logger.debug("Failed to update approval message after resolution", exc_info=True)

        await self._callback(self._approval_id, approved)
        self.stop()

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Handle approve button press."""
        await self._resolve(interaction, approved=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="❌")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """Handle deny button press."""
        await self._resolve(interaction, approved=False)

    async def on_timeout(self) -> None:
        """Disable buttons when the view times out."""
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        self.stop()


class DiscordChannel(ChannelAdapter):
    """Discord channel adapter.

    Handles:
    - Bot initialization and lifecycle via discord.py Client
    - Message format conversion (discord.Message -> OpenPaw Message)
    - User / guild allowlisting
    - Slash command registration via CommandTree
    - File and approval-gate message delivery
    """

    name = "discord"

    # Discord free-tier message length limit
    MAX_MESSAGE_LENGTH = 2000

    # Discord free-tier file size limit (25 MB)
    MAX_FILE_SIZE = 25 * 1024 * 1024

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
        """Initialize the Discord channel.

        Args:
            token: Bot token (falls back to DISCORD_BOT_TOKEN env var).
            allowed_users: List of allowed Discord user IDs (snowflakes).
            allowed_groups: List of allowed guild IDs.
            allow_all: If True, allow all users (insecure).
            mention_required: If True, only respond in guild channels when @mentioned.
            triggers: Keyword triggers for group chat activation (OR with mention).
            workspace_name: Workspace name used in error/access-denied messages.
        """
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
        self._channel_event_callback: Callable[..., Any] | None = None

    @property
    def supports_history_browsing(self) -> bool:
        """Discord supports full channel history via the channel.history() API."""
        return True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the Discord bot and wait until it is ready."""
        intents = discord.Intents.default()
        intents.message_content = True   # privileged — enable in Developer Portal
        intents.guilds = True
        intents.guild_messages = True
        intents.dm_messages = True

        self._client = discord.Client(intents=intents)
        self._tree = app_commands.CommandTree(self._client)
        self._ready_event.clear()

        # Register event handlers — discord.py dispatches by function name,
        # so we alias our methods to the expected names.
        @self._client.event
        async def on_ready() -> None:
            await self._on_ready()

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            await self._on_message(message)

        # Start the client in a background task — client.start() blocks until logout
        self._client_task = asyncio.create_task(
            self._client.start(self._token),
            name=f"discord-client-{self.workspace_name}",
        )

        # Wait until the bot has connected and is ready to use
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=30.0)
        except TimeoutError:
            logger.error("Discord bot did not become ready within 30 seconds")
            raise RuntimeError("Discord bot failed to connect in time")

        logger.info("Discord channel started (workspace: %s)", self.workspace_name)

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

    # ------------------------------------------------------------------
    # discord.py event handlers
    # ------------------------------------------------------------------

    async def _on_ready(self) -> None:
        """Called by discord.py once the client is connected and ready."""
        logger.info(
            "Discord bot ready: %s (ID: %s)",
            self._client.user,  # type: ignore[union-attr]
            self._client.user.id,  # type: ignore[union-attr]
        )
        self._ready_event.set()

    async def _on_message(self, discord_message: discord.Message) -> None:
        """Called by discord.py for every message the bot can see.

        Ignores the bot's own messages, enforces the allowlist, converts the
        message to the unified OpenPaw format, and invokes the registered
        callback.
        """
        # Ignore messages sent by the bot itself
        if self._client and discord_message.author == self._client.user:
            return

        # Emit channel event for persistent logging (before any filters).
        # Only emit for guild messages — DMs are excluded for privacy.
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
        """Build a ChannelEvent from a discord.Message for persistent logging.

        Args:
            discord_message: The incoming discord.Message to convert.

        Returns:
            A ChannelEvent populated with message metadata.
        """
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

    # ------------------------------------------------------------------
    # ChannelAdapter interface
    # ------------------------------------------------------------------

    def on_message(self, callback: Callable[[Message], Coroutine[Any, Any, None]]) -> None:
        """Register a callback for incoming messages."""
        self._message_callback = callback

    def on_approval(
        self, callback: Callable[[str, bool], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback for approval resolutions."""
        self._approval_callback = callback

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        """Send a message to a Discord channel.

        Automatically splits messages that exceed Discord's 2000-char limit,
        breaking at paragraph boundaries when possible. Discord renders markdown
        natively so no conversion is applied.

        Args:
            session_key: Session key in format 'discord:channel_id'.
            content: Message text (Discord markdown supported natively).
            **kwargs: Additional kwargs passed to channel.send().

        Returns:
            The sent Message object (last chunk if split).
        """
        if not self._client:
            raise RuntimeError("Discord channel not started")

        channel_id = self._channel_id_from_session_key(session_key)
        channel = await self._resolve_channel(channel_id)

        chunks = self._split_message(content)
        sent: discord.Message | None = None
        for chunk in chunks:
            sent = await channel.send(chunk, **kwargs)  # type: ignore[union-attr]

        if sent is None:
            raise RuntimeError("Failed to send message: no chunks were sent")

        return Message(
            id=str(sent.id),
            channel=self.name,
            session_key=session_key,
            user_id=str(self._client.user.id),  # type: ignore[union-attr]
            content=content,
            direction=MessageDirection.OUTBOUND,
            timestamp=datetime.now(UTC),
        )

    async def send_file(
        self,
        session_key: str,
        file_data: bytes,
        filename: str,
        mime_type: str | None = None,
        caption: str | None = None,
    ) -> None:
        """Send a file to a Discord channel.

        Args:
            session_key: Session key in format 'discord:channel_id'.
            file_data: Raw file bytes.
            filename: Display filename for the file.
            mime_type: Optional MIME type hint (informational, not sent to Discord).
            caption: Optional caption/message to accompany the file.

        Raises:
            RuntimeError: If the channel is not started.
            ValueError: If file size exceeds the 25 MB limit.
        """
        if not self._client:
            raise RuntimeError("Discord channel not started")

        file_size = len(file_data)
        if file_size > self.MAX_FILE_SIZE:
            size_mb = file_size / (1024 * 1024)
            raise ValueError(
                f"File size ({size_mb:.1f} MB) exceeds Discord's 25 MB limit"
            )

        channel_id = self._channel_id_from_session_key(session_key)
        channel = await self._resolve_channel(channel_id)

        discord_file = discord.File(fp=BytesIO(file_data), filename=filename)

        try:
            await channel.send(content=caption, file=discord_file)  # type: ignore[union-attr]
            logger.info("Sent file '%s' (%d bytes) to channel %d", filename, file_size, channel_id)
        except Exception as e:
            logger.error("Failed to send file '%s' to channel %d: %s", filename, channel_id, e)
            raise RuntimeError(f"Failed to send file: {e}") from e

    async def send_approval_request(
        self,
        session_key: str,
        approval_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        show_args: bool = True,
    ) -> None:
        """Send an approval request with Approve / Deny buttons.

        Args:
            session_key: Session key in format 'discord:channel_id'.
            approval_id: Unique ID for this approval request.
            tool_name: Name of the tool requiring approval.
            tool_args: Arguments passed to the tool.
            show_args: Whether to display tool arguments to the user.
        """
        if not self._client:
            raise RuntimeError("Discord channel not started")

        if not self._approval_callback:
            logger.warning("send_approval_request called but no approval callback registered")
            return

        # Build the request message text
        safe_tool_name = tool_name.replace("`", "'")
        text = f"**Approval Required**\nTool: `{safe_tool_name}`\n"
        if show_args and tool_args:
            args_str = str(tool_args)
            if len(args_str) > 500:
                args_str = args_str[:500] + "..."
            args_str = args_str.replace("`", "'")
            text += f"Args: `{args_str}`\n"

        channel_id = self._channel_id_from_session_key(session_key)
        channel = await self._resolve_channel(channel_id)

        view = _ApprovalView(
            approval_id=approval_id,
            callback=self._approval_callback,
        )

        await channel.send(content=text, view=view)  # type: ignore[union-attr]

    async def register_commands(self, commands: list[Any]) -> None:
        """Register OpenPaw commands as Discord slash commands.

        Each CommandDefinition from the framework command system becomes a
        Discord slash command. When invoked, the interaction is deferred
        immediately (agents may take time to respond) and the handler creates
        a synthetic Message routed through the message callback — exactly as
        if the user had typed the command in chat.

        Args:
            commands: List of CommandDefinition objects from CommandRouter.
        """
        if not self._client or not self._tree:
            logger.warning("register_commands called before Discord client was started")
            return

        for command_def in commands:
            # Skip commands that are hidden or internal-only
            if getattr(command_def, "hidden", False):
                continue

            # Capture in closure for the async handler below
            cmd_name: str = command_def.name
            cmd_description: str = getattr(command_def, "description", f"/{cmd_name}")

            # discord.py slash commands require a description <= 100 chars
            if len(cmd_description) > 100:
                cmd_description = cmd_description[:97] + "..."

            async def _slash_handler(
                interaction: discord.Interaction,
                args: str = "",
                *,
                _cmd_name: str = cmd_name,
            ) -> None:
                await interaction.response.defer()

                content = f"/{_cmd_name}"
                if args:
                    content = f"{content} {args}"

                message = Message(
                    id=str(interaction.id),
                    channel=self.name,
                    session_key=self.build_session_key(interaction.channel_id),
                    user_id=str(interaction.user.id),
                    content=content,
                    direction=MessageDirection.INBOUND,
                    timestamp=datetime.now(UTC),
                    metadata={
                        "guild_id": interaction.guild_id,
                        "username": interaction.user.name,
                        "display_name": interaction.user.display_name,
                    },
                )

                if self._message_callback:
                    await self._message_callback(message)

                # Delete the deferred "thinking..." message — the actual
                # response is sent via channel.send() through the normal path.
                try:
                    await interaction.delete_original_response()
                except discord.HTTPException:
                    logger.debug("Failed to delete deferred interaction response", exc_info=True)

            slash_cmd = app_commands.Command(
                name=cmd_name,
                description=cmd_description,
                callback=_slash_handler,
            )
            self._tree.add_command(slash_cmd)

        try:
            await self._tree.sync()
            logger.info(
                "Synced %d Discord slash commands for workspace '%s'",
                len(commands),
                self.workspace_name,
            )
        except discord.HTTPException as e:
            logger.error("Failed to sync Discord slash commands: %s", e)

    # ------------------------------------------------------------------
    # Allowlist / security
    # ------------------------------------------------------------------

    def _is_allowed(self, message: discord.Message) -> bool:
        """Check whether the message sender is permitted to use this workspace.

        Security model (mirrors TelegramChannel):
        - allow_all=True  → everyone is allowed (insecure, use with caution)
        - allowed_users non-empty → user.id must be in the set
        - No allowed_users → deny all (secure default)
        - In a guild + allowed_groups non-empty → guild.id must be in the set

        Args:
            message: The incoming discord.Message.

        Returns:
            True if the sender is allowed, False otherwise.
        """
        if self.allow_all:
            return True

        user_id = message.author.id

        # User allowlist check
        if self.allowed_users:
            if user_id not in self.allowed_users:
                return False
        else:
            # No user allowlist configured and allow_all is False — deny
            return False

        # Guild allowlist check for server messages
        if message.guild and self.allowed_groups:
            if message.guild.id not in self.allowed_groups:
                return False

        return True

    def _passes_activation_filter(self, message: discord.Message) -> bool:
        """Check whether the message passes activation filters (mention OR trigger).

        In guild channels, messages must pass at least one activation condition:
        - Bot is @mentioned (when mention_required is True)
        - Message contains a trigger keyword (when triggers are configured)

        If neither mention_required nor triggers are configured, all messages pass.
        DMs always pass through regardless.

        Args:
            message: The incoming discord.Message.

        Returns:
            True if the message should be processed.
        """
        # No activation filters configured — pass everything
        if not self.mention_required and not self.triggers:
            return True

        # DMs always pass through
        if message.guild is None:
            return True

        # OR logic: either mention or trigger is sufficient
        if self.mention_required and self._client and self._client.user in message.mentions:
            return True

        content = message.content or ""
        if self._passes_trigger_filter(content, self.triggers):
            return True

        return False

    async def _send_unauthorized_response(self, message: discord.Message) -> None:
        """Reply to an unauthorized user with their IDs and config instructions.

        Args:
            message: The discord.Message from the unauthorized user.
        """
        user_id = message.author.id
        guild_id = message.guild.id if message.guild else None

        text = (
            f"Access denied.\n\n"
            f"Your user ID: `{user_id}`\n"
        )
        if guild_id:
            text += f"Guild (server) ID: `{guild_id}`\n"

        text += (
            f"\nTo gain access, add your ID to the allowlist:\n"
            f"`agent_workspaces/{self.workspace_name}/agent.yaml`\n\n"
            f"```yaml\n"
            f"channel:\n"
            f"  allowed_users:\n"
            f"    - {user_id}\n"
            f"```"
        )

        try:
            await message.reply(text)
        except discord.HTTPException:
            logger.debug("Failed to send unauthorized response", exc_info=True)

        logger.warning(
            "Blocked Discord user %d from workspace '%s'", user_id, self.workspace_name
        )

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    async def _to_message(self, discord_message: discord.Message) -> Message | None:
        """Convert a discord.Message to the unified OpenPaw Message format.

        Downloads any attachments so downstream inbound processors (e.g.,
        WhisperProcessor, DoclingProcessor) receive raw bytes.

        Args:
            discord_message: The incoming discord.Message object.

        Returns:
            An OpenPaw Message, or None if conversion is not possible.
        """
        session_key = self.build_session_key(discord_message.channel.id)

        attachments = await self._download_attachments(discord_message)

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

    async def _download_attachments(
        self, discord_message: discord.Message
    ) -> list[Attachment]:
        """Download all attachments from a discord.Message.

        Determines the OpenPaw attachment type from the Discord MIME type:
        - audio/* → "audio"
        - image/* → "image"
        - anything else → "document"

        Args:
            discord_message: The discord.Message whose attachments to download.

        Returns:
            List of Attachment objects with raw bytes populated.
        """
        result: list[Attachment] = []

        for discord_attachment in discord_message.attachments:
            try:
                data = await discord_attachment.read()
            except Exception as e:
                logger.error(
                    "Failed to download attachment '%s': %s",
                    discord_attachment.filename,
                    e,
                )
                continue

            content_type = discord_attachment.content_type or "application/octet-stream"

            if content_type.startswith("audio/"):
                attachment_type = "audio"
            elif content_type.startswith("image/"):
                attachment_type = "image"
            else:
                attachment_type = "document"

            result.append(
                Attachment(
                    type=attachment_type,
                    data=data,
                    filename=discord_attachment.filename,
                    mime_type=content_type,
                    metadata={"file_size": discord_attachment.size},
                )
            )

            logger.info(
                "Downloaded attachment: %s (%d bytes, %s)",
                discord_attachment.filename,
                discord_attachment.size,
                content_type,
            )

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _split_message(self, text: str) -> list[str]:
        """Split text into chunks that fit Discord's 2000-char message limit.

        Tries to break at paragraph boundaries (double newline), falls back
        to single newlines, then hard-splits as a last resort.

        Args:
            text: The full message text.

        Returns:
            List of message chunks, each within MAX_MESSAGE_LENGTH.
        """
        if len(text) <= self.MAX_MESSAGE_LENGTH:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= self.MAX_MESSAGE_LENGTH:
                chunks.append(remaining)
                break

            # Prefer paragraph boundary
            split_at = remaining.rfind("\n\n", 0, self.MAX_MESSAGE_LENGTH)

            # Fall back to single newline
            if split_at == -1:
                split_at = remaining.rfind("\n", 0, self.MAX_MESSAGE_LENGTH)

            # Hard split as last resort
            if split_at == -1:
                split_at = self.MAX_MESSAGE_LENGTH

            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

        return chunks

    @staticmethod
    def _channel_id_from_session_key(session_key: str) -> int:
        """Extract the Discord channel ID from a session key.

        Args:
            session_key: Session key in format 'discord:channel_id'.

        Returns:
            Integer channel ID.
        """
        parts = session_key.split(":")
        return int(parts[1])

    async def _resolve_channel(
        self, channel_id: int
    ) -> discord.TextChannel | discord.DMChannel | discord.Thread:
        """Return a sendable Discord channel object for the given ID.

        Attempts the local cache first; falls back to an API fetch if the
        channel is not cached.

        Args:
            channel_id: Discord snowflake channel ID.

        Returns:
            A channel object that supports .send().

        Raises:
            RuntimeError: If the channel cannot be found or fetched.
        """
        if not self._client:
            raise RuntimeError("Discord channel not started")

        channel = self._client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(channel_id)
            except discord.NotFound:
                raise RuntimeError(f"Discord channel {channel_id} not found")
            except discord.Forbidden:
                raise RuntimeError(
                    f"Bot lacks permission to access Discord channel {channel_id}"
                )

        return channel  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Channel history (context fetch for group messages)
    # ------------------------------------------------------------------

    async def fetch_channel_history(
        self,
        channel_id: str,
        limit: int = 25,
        before_message_id: str | None = None,
    ) -> list[ChannelHistoryEntry]:
        """Fetch recent messages from a Discord channel.

        Retrieves up to `limit` messages in reverse-chronological order
        from Discord's API, then returns them in chronological order (oldest
        first) after filtering out the bot's own messages.

        Args:
            channel_id: Discord snowflake channel ID as a string.
            limit: Maximum number of messages to fetch (before self-filtering).
            before_message_id: When provided, fetch only messages sent before
                this message ID (for pagination). Optional.

        Returns:
            List of ChannelHistoryEntry in chronological order (oldest first).
            Returns an empty list on any error.
        """
        try:
            channel = await self._resolve_channel(int(channel_id))

            before_obj: discord.Object | None = None
            if before_message_id is not None:
                before_obj = discord.Object(id=int(before_message_id))

            entries: list[ChannelHistoryEntry] = []
            async for msg in channel.history(limit=limit, before=before_obj):  # type: ignore[union-attr]
                # Skip the bot's own messages — they are not useful context
                if self._client and msg.author == self._client.user:
                    continue

                attachments_summary: str | None = None
                if msg.attachments:
                    names = [a.filename for a in msg.attachments]
                    count = len(names)
                    label = "file" if count == 1 else "files"
                    attachments_summary = f"[{count} {label}: {', '.join(names)}]"

                entries.append(
                    ChannelHistoryEntry(
                        timestamp=msg.created_at,
                        user_id=str(msg.author.id),
                        display_name=msg.author.display_name,
                        content=msg.content or "",
                        is_bot=msg.author.bot,
                        attachments_summary=attachments_summary,
                        message_id=str(msg.id),
                    )
                )

            # Discord returns newest-first; reverse to chronological order
            entries.reverse()
            return entries

        except Exception:
            logger.warning(
                "Failed to fetch channel history for channel %s", channel_id, exc_info=True
            )
            return []
