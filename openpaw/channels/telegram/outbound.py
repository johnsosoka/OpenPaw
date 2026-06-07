"""Telegram outbound message and file delivery."""

import logging
from datetime import UTC, datetime
from typing import Any

from openpaw.channels.helpers import check_file_size, split_message
from openpaw.channels.telegram.constants import MAX_FILE_SIZE, MAX_MESSAGE_LENGTH
from openpaw.model.message import Message, MessageDirection

logger = logging.getLogger(__name__)


class TelegramOutboundSender:
    """Send messages, audio, and files to Telegram chats."""

    def __init__(self, app: Any, channel_name: str, bot_id: int) -> None:
        self._app = app
        self._channel_name = channel_name
        self._bot_id = bot_id

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        """Send a message to a Telegram chat.

        Automatically splits messages that exceed Telegram's 4096-char limit,
        breaking at paragraph boundaries when possible. Converts markdown to
        Telegram HTML unless parse_mode is explicitly provided.
        """
        parts = session_key.split(":")
        chat_id = int(parts[1])

        # Convert markdown to HTML unless caller specifies parse_mode
        if "parse_mode" not in kwargs:
            from openpaw.channels.formatting import markdown_to_telegram_html
            html_content = markdown_to_telegram_html(content)
            sent = await self._send_with_html_fallback(chat_id, content, html_content, **kwargs)
        else:
            chunks = self._split_message(content)
            sent = None
            for chunk in chunks:
                sent = await self._app.bot.send_message(chat_id=chat_id, text=chunk, **kwargs)

        if not sent:
            raise RuntimeError("Failed to send message: no chunks were sent")

        return Message(
            id=str(sent.message_id),
            channel=self._channel_name,
            session_key=session_key,
            user_id=str(self._bot_id),
            content=content,
            direction=MessageDirection.OUTBOUND,
            timestamp=datetime.now(UTC),
        )

    async def _send_with_html_fallback(
        self,
        chat_id: int,
        original: str,
        html_content: str,
        **kwargs: Any
    ) -> Any:
        """Send HTML-formatted message with per-chunk plain text fallback."""
        from telegram.error import BadRequest

        html_chunks = self._split_message(html_content)
        plain_chunks = self._split_message(original)

        # If chunk counts differ (HTML tags changed split boundaries),
        # send all as plain text to avoid positional mismatch
        if len(html_chunks) != len(plain_chunks):
            logger.debug("HTML/plain chunk count mismatch, sending all as plain text")
            sent = None
            for chunk in plain_chunks:
                sent = await self._app.bot.send_message(
                    chat_id=chat_id, text=chunk, **kwargs
                )
            return sent

        # Try HTML for each chunk, fall back to plain on parse error
        sent = None
        for html_chunk, plain_chunk in zip(html_chunks, plain_chunks):
            try:
                sent = await self._app.bot.send_message(
                    chat_id=chat_id, text=html_chunk, parse_mode="HTML", **kwargs
                )
            except BadRequest as e:
                if "can't parse" in str(e).lower():
                    logger.warning("HTML parse failed for chunk, using plain text: %s", e)
                    sent = await self._app.bot.send_message(
                        chat_id=chat_id, text=plain_chunk, **kwargs
                    )
                else:
                    raise
        return sent

    def _split_message(self, text: str) -> list[str]:
        """Split text into chunks that fit Telegram's message limit."""
        return split_message(text, MAX_MESSAGE_LENGTH)

    async def send_audio(
        self,
        session_key: str,
        audio_data: bytes,
        filename: str = "audio.mp3",
        **kwargs: Any,
    ) -> Message:
        """Send an audio file to a Telegram chat."""
        from io import BytesIO

        parts = session_key.split(":")
        chat_id = int(parts[1])

        audio_file = BytesIO(audio_data)
        audio_file.name = filename

        sent = await self._app.bot.send_audio(chat_id=chat_id, audio=audio_file, **kwargs)

        return Message(
            id=str(sent.message_id),
            channel=self._channel_name,
            session_key=session_key,
            user_id=str(self._bot_id),
            content=f"[Audio: {filename}]",
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
        """Send a file via Telegram's sendDocument API."""
        check_file_size(file_data, MAX_FILE_SIZE, "Telegram")
        file_size = len(file_data)

        from io import BytesIO

        # Parse session key to extract chat_id
        parts = session_key.split(":")
        chat_id = int(parts[1])

        # Wrap bytes in BytesIO for Telegram API
        file_obj = BytesIO(file_data)
        file_obj.name = filename

        try:
            await self._app.bot.send_document(
                chat_id=chat_id,
                document=file_obj,
                caption=caption,
                filename=filename,
            )
            logger.info("Sent file '%s' (%s bytes) to chat %s", filename, file_size, chat_id)
        except Exception as e:
            logger.error("Failed to send file '%s' to chat %s: %s", filename, chat_id, e)
            raise RuntimeError(f"Failed to send file: {e}") from e

    async def edit_message(
        self,
        session_key: str,
        message_id: str,
        content: str,
    ) -> bool:
        """Edit an existing Telegram message.

        Args:
            session_key: Target session identifier.
            message_id: Telegram message ID to edit.
            content: New message content.

        Returns:
            True if the edit was successful.
        """
        parts = session_key.split(":")
        chat_id = int(parts[1])

        try:
            from telegram.error import BadRequest

            from openpaw.channels.formatting import markdown_to_telegram_html

            html_content = markdown_to_telegram_html(content)
            try:
                await self._app.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=int(message_id),
                    text=html_content,
                    parse_mode="HTML",
                )
            except BadRequest as e:
                if "can't parse" in str(e).lower():
                    logger.warning("HTML parse failed on edit, using plain text: %s", e)
                    await self._app.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=int(message_id),
                        text=content,
                    )
                else:
                    raise
            logger.debug("Edited Telegram message %s in chat %s", message_id, chat_id)
            return True
        except Exception as e:
            logger.debug("Failed to edit Telegram message %s: %s", message_id, e)
            return False

    async def delete_message(
        self,
        session_key: str,
        message_id: str,
    ) -> bool:
        """Delete an existing Telegram message.

        Args:
            session_key: Target session identifier.
            message_id: Telegram message ID to delete.

        Returns:
            True if the deletion was successful.
        """
        parts = session_key.split(":")
        chat_id = int(parts[1])

        try:
            await self._app.bot.delete_message(
                chat_id=chat_id,
                message_id=int(message_id),
            )
            logger.debug("Deleted Telegram message %s in chat %s", message_id, chat_id)
            return True
        except Exception as e:
            logger.debug("Failed to delete Telegram message %s: %s", message_id, e)
            return False

    async def send_typing(self, session_key: str) -> None:
        """Trigger Telegram typing indicator."""
        if not self._app:
            return
        try:
            chat_id = int(session_key.split(":")[1])
            await self._app.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            logger.debug("Failed to send typing action", exc_info=True)

    async def add_reaction(self, session_key: str, message_id: str, emoji: str) -> bool:
        """Add an emoji reaction to a Telegram message."""
        if not self._app:
            return False
        try:
            chat_id = int(session_key.split(":")[1])
            await self._app.bot.set_message_reaction(
                chat_id=chat_id,
                message_id=int(message_id),
                reaction=[{"type": "emoji", "emoji": emoji}],
            )
            return True
        except Exception:
            logger.debug("Failed to add reaction", exc_info=True)
            return False

    async def remove_reaction(self, session_key: str, message_id: str, emoji: str) -> bool:
        """Remove the bot's reactions from a Telegram message.

        Note: Telegram's set_message_reaction with an empty reaction list
        clears all reactions set by the bot. The emoji parameter is accepted
        for API compatibility but not used.
        """
        if not self._app:
            return False
        try:
            chat_id = int(session_key.split(":")[1])
            await self._app.bot.set_message_reaction(
                chat_id=chat_id,
                message_id=int(message_id),
                reaction=[],  # Empty clears all
            )
            return True
        except Exception:
            logger.debug("Failed to remove reaction", exc_info=True)
            return False
