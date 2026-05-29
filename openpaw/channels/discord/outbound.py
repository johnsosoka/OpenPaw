"""Discord outbound message and file delivery."""

import logging
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import discord

from openpaw.channels.discord.approval_view import DiscordApprovalView
from openpaw.channels.helpers import check_file_size, format_approval_message, split_message
from openpaw.model.message import Message, MessageDirection

logger = logging.getLogger(__name__)

# Discord free-tier message length limit
MAX_MESSAGE_LENGTH = 2000

# Discord free-tier file size limit (25 MB)
MAX_FILE_SIZE = 25 * 1024 * 1024


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
            except discord.NotFound:
                raise RuntimeError(f"Discord channel {channel_id} not found")
            except discord.Forbidden:
                raise RuntimeError(
                    f"Bot lacks permission to access Discord channel {channel_id}"
                )

        return channel  # type: ignore[no-any-return]
