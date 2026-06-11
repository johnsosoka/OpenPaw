"""Discord outbound message and file delivery."""

import logging
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import discord

from openpaw.channels.discord.approval_view import DiscordApprovalView
from openpaw.channels.discord.constants import MAX_FILE_SIZE, MAX_MESSAGE_LENGTH
from openpaw.channels.helpers import check_file_size, format_approval_message, split_message
from openpaw.model.message import Message, MessageDirection

logger = logging.getLogger(__name__)


class DiscordOutboundSender:
    """Send messages, files, and approval requests to Discord channels."""

    def __init__(self, client: Any, channel_name: str, bot_id: int) -> None:
        self._client = client
        self._channel_name = channel_name
        self._bot_id = bot_id

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        """Send a message to a Discord channel.

        Automatically splits messages that exceed Discord's 2000-char limit.
        """
        channel_id = self._channel_id_from_session_key(session_key)
        channel = await self._resolve_channel(channel_id)

        chunks = self._split_message(content)
        sent: discord.Message | None = None
        for chunk in chunks:
            sent = await channel.send(chunk, **kwargs)

        if sent is None:
            raise RuntimeError("Failed to send message: no chunks were sent")

        return Message(
            id=str(sent.id),
            channel=self._channel_name,
            session_key=session_key,
            user_id=str(self._bot_id),
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
        """Send a file to a Discord channel."""
        check_file_size(file_data, MAX_FILE_SIZE, "Discord")
        file_size = len(file_data)

        channel_id = self._channel_id_from_session_key(session_key)
        channel = await self._resolve_channel(channel_id)

        discord_file = discord.File(fp=BytesIO(file_data), filename=filename)

        try:
            await channel.send(content=caption, file=discord_file)
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
        approval_callback: Any = None,
    ) -> None:
        """Send an approval request with Approve / Deny buttons."""
        text = format_approval_message(tool_name, tool_args, show_args)

        channel_id = self._channel_id_from_session_key(session_key)
        channel = await self._resolve_channel(channel_id)

        view = DiscordApprovalView(
            approval_id=approval_id,
            callback=approval_callback,
        )

        await channel.send(content=text, view=view)

    async def edit_message(
        self,
        session_key: str,
        message_id: str,
        content: str,
    ) -> bool:
        """Edit an existing Discord message.

        Args:
            session_key: Target session identifier.
            message_id: Discord message ID (snowflake) to edit.
            content: New message content.

        Returns:
            True if the edit was successful.
        """
        channel_id = self._channel_id_from_session_key(session_key)
        try:
            channel = await self._resolve_channel(channel_id)
            message = await channel.fetch_message(int(message_id))
            await message.edit(content=content)
            logger.debug("Edited Discord message %s in channel %s", message_id, channel_id)
            return True
        except Exception as e:
            logger.debug("Failed to edit Discord message %s: %s", message_id, e)
            return False

    async def delete_message(
        self,
        session_key: str,
        message_id: str,
    ) -> bool:
        """Delete an existing Discord message.

        Args:
            session_key: Target session identifier.
            message_id: Discord message ID (snowflake) to delete.

        Returns:
            True if the deletion was successful.
        """
        channel_id = self._channel_id_from_session_key(session_key)
        try:
            channel = await self._resolve_channel(channel_id)
            message = await channel.fetch_message(int(message_id))
            await message.delete()
            logger.debug("Deleted Discord message %s in channel %s", message_id, channel_id)
            return True
        except Exception as e:
            logger.debug("Failed to delete Discord message %s: %s", message_id, e)
            return False

    async def send_typing(self, session_key: str) -> None:
        """Trigger Discord typing indicator."""
        if not self._client:
            return
        try:
            channel_id = self._channel_id_from_session_key(session_key)
            channel = await self._resolve_channel(channel_id)
            await channel.trigger_typing()  # type: ignore[union-attr]
        except Exception:
            logger.debug("Failed to trigger typing", exc_info=True)

    async def add_reaction(self, session_key: str, message_id: str, emoji: str) -> bool:
        """Add an emoji reaction to a Discord message."""
        if not self._client:
            return False
        try:
            channel_id = self._channel_id_from_session_key(session_key)
            channel = await self._resolve_channel(channel_id)
            message = await channel.fetch_message(int(message_id))
            await message.add_reaction(emoji)
            return True
        except Exception:
            logger.debug("Failed to add reaction", exc_info=True)
            return False

    async def remove_reaction(self, session_key: str, message_id: str, emoji: str) -> bool:
        """Remove a bot reaction from a Discord message."""
        if not self._client:
            return False
        try:
            channel_id = self._channel_id_from_session_key(session_key)
            channel = await self._resolve_channel(channel_id)
            message = await channel.fetch_message(int(message_id))
            await message.remove_reaction(emoji, self._client.user)
            return True
        except Exception:
            logger.debug("Failed to remove reaction", exc_info=True)
            return False

    def _split_message(self, text: str) -> list[str]:
        """Split text into chunks that fit Discord's 2000-char message limit."""
        return split_message(text, MAX_MESSAGE_LENGTH)

    @staticmethod
    def _channel_id_from_session_key(session_key: str) -> int:
        """Extract the Discord channel ID from a session key."""
        parts = session_key.split(":")
        return int(parts[1])

    async def _resolve_channel(
        self, channel_id: int
    ) -> discord.TextChannel | discord.DMChannel | discord.Thread:
        """Return a sendable Discord channel object for the given ID."""
        channel = self._client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self._client.fetch_channel(channel_id)
            except discord.NotFound as exc:
                raise RuntimeError(f"Discord channel {channel_id} not found") from exc
            except discord.Forbidden as exc:
                raise RuntimeError(
                    f"Bot lacks permission to access Discord channel {channel_id}"
                ) from exc
            except discord.HTTPException as e:
                raise RuntimeError(f"Discord API error fetching channel {channel_id}: {e}") from e

        return channel  # type: ignore[no-any-return]
