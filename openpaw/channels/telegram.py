"""Telegram channel adapter using python-telegram-bot."""

import logging
import os
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.helpers import (
    SecurityMixin,
    check_file_size,
    format_approval_message,
    format_unauthorized_response,
    split_message,
)
from openpaw.model.message import Attachment, Message, MessageDirection

logger = logging.getLogger(__name__)


class TelegramChannel(ChannelAdapter, SecurityMixin):
    """Telegram channel adapter.

    Handles:
    - Bot initialization and lifecycle
    - Message format conversion
    - User/group allowlisting
    - Command parsing
    """

    name = "telegram"

    def __init__(
        self,
        token: str | None = None,
        allowed_users: list[int] | None = None,
        allowed_groups: list[int] | None = None,
        allow_all: bool = False,
        mention_required: bool = False,
        triggers: list[str] | None = None,
        workspace_name: str = "unknown",
    ):
        """Initialize the Telegram channel.

        Args:
            token: Bot token (falls back to TELEGRAM_BOT_TOKEN env var).
            allowed_users: List of allowed user IDs.
            allowed_groups: List of allowed group IDs.
            allow_all: If True, allow all users (insecure). If False, requires allowlists.
            mention_required: If True, only respond in group chats when @mentioned.
            triggers: Keyword triggers for group chat activation (OR with mention).
            workspace_name: Name of the workspace (for error messages).
        """
        resolved_token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not resolved_token:
            raise ValueError("Telegram bot token required (pass token or set TELEGRAM_BOT_TOKEN)")
        self.token: str = resolved_token

        self.allowed_users = set(allowed_users or [])
        self.allowed_groups = set(allowed_groups or [])
        self.allow_all = allow_all
        self.mention_required = mention_required
        self.triggers: list[str] = triggers or []
        self.workspace_name = workspace_name
        self._bot_username: str | None = None
        self._app: Application | None = None  # type: ignore[type-arg]
        self._message_callback: Callable[[Message], Coroutine[Any, Any, None]] | None = None
        self._approval_callback: Callable[[str, bool], Coroutine[Any, Any, None]] | None = None
        self._channel_event_callback: Callable[..., Any] | None = None

    async def start(self) -> None:
        """Start the Telegram bot."""
        self._app = Application.builder().token(self.token).build()

        # Add callback query handler for approval buttons (BEFORE message handlers)
        self._app.add_handler(CallbackQueryHandler(self._handle_approval_callback))

        # Route all messages through the unified callback
        self._app.add_handler(MessageHandler(filters.COMMAND, self._handle_command))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self._app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._handle_voice_message))
        self._app.add_handler(MessageHandler(filters.Document.ALL, self._handle_document))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()  # type: ignore[union-attr]

        # Capture bot username for mention detection in group chats
        if self._app.bot:
            bot_info = await self._app.bot.get_me()
            self._bot_username = bot_info.username
            logger.debug("Bot username: @%s", self._bot_username)

        logger.info("Telegram channel started")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            await self._app.updater.stop()  # type: ignore[union-attr]
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram channel stopped")

    def on_message(self, callback: Callable[[Message], Coroutine[Any, Any, None]]) -> None:
        """Register callback for incoming messages."""
        self._message_callback = callback

    # Telegram maximum message length
    MAX_MESSAGE_LENGTH = 4096

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        """Send a message to a Telegram chat.

        Automatically splits messages that exceed Telegram's 4096-char limit,
        breaking at paragraph boundaries when possible. Converts markdown to
        Telegram HTML unless parse_mode is explicitly provided.

        Args:
            session_key: Session key in format 'telegram:chat_id'.
            content: Message text (supports markdown formatting).
            **kwargs: Additional telegram.Bot.send_message kwargs.

        Returns:
            The sent Message object (last chunk if split).
        """
        if not self._app:
            raise RuntimeError("Telegram channel not started")

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
            channel=self.name,
            session_key=session_key,
            user_id=str(self._app.bot.id),
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
        """Send HTML-formatted message with per-chunk plain text fallback.

        Attempts to send HTML-formatted content. If Telegram rejects the HTML
        for a specific chunk (e.g., unclosed tags from message splitting),
        falls back to sending the plain text version of that chunk.

        When chunk counts between HTML and plain versions differ (due to HTML
        tags changing text length), falls back to all-plain-text as a safety valve.

        Args:
            chat_id: Telegram chat ID.
            original: Original markdown content.
            html_content: HTML-converted content.
            **kwargs: Additional telegram.Bot.send_message kwargs.

        Returns:
            The last sent telegram.Message object.
        """
        from telegram.error import BadRequest

        html_chunks = self._split_message(html_content)
        plain_chunks = self._split_message(original)

        # If chunk counts differ (HTML tags changed split boundaries),
        # send all as plain text to avoid positional mismatch
        if len(html_chunks) != len(plain_chunks):
            logger.debug("HTML/plain chunk count mismatch, sending all as plain text")
            sent = None
            for chunk in plain_chunks:
                sent = await self._app.bot.send_message(  # type: ignore[union-attr]
                    chat_id=chat_id, text=chunk, **kwargs
                )
            return sent

        # Try HTML for each chunk, fall back to plain on parse error
        sent = None
        for html_chunk, plain_chunk in zip(html_chunks, plain_chunks):
            try:
                sent = await self._app.bot.send_message(  # type: ignore[union-attr]
                    chat_id=chat_id, text=html_chunk, parse_mode="HTML", **kwargs
                )
            except BadRequest as e:
                if "can't parse" in str(e).lower():
                    logger.warning(f"HTML parse failed for chunk, using plain text: {e}")
                    sent = await self._app.bot.send_message(  # type: ignore[union-attr]
                        chat_id=chat_id, text=plain_chunk, **kwargs
                    )
                else:
                    raise
        return sent

    def _split_message(self, text: str) -> list[str]:
        """Split text into chunks that fit Telegram's message limit.

        Delegates to the shared split_message helper.

        Args:
            text: The full message text.

        Returns:
            List of message chunks, each within MAX_MESSAGE_LENGTH.
        """
        return split_message(text, self.MAX_MESSAGE_LENGTH)

    async def send_audio(
        self,
        session_key: str,
        audio_data: bytes,
        filename: str = "audio.mp3",
        **kwargs: Any,
    ) -> Message:
        """Send an audio file to a Telegram chat.

        Args:
            session_key: Session key in format 'telegram:chat_id'.
            audio_data: Raw audio bytes.
            filename: Filename for the audio file.
            **kwargs: Additional telegram.Bot.send_audio kwargs.

        Returns:
            The sent Message object.
        """
        if not self._app:
            raise RuntimeError("Telegram channel not started")

        from io import BytesIO

        parts = session_key.split(":")
        chat_id = int(parts[1])

        audio_file = BytesIO(audio_data)
        audio_file.name = filename

        sent = await self._app.bot.send_audio(chat_id=chat_id, audio=audio_file, **kwargs)

        return Message(
            id=str(sent.message_id),
            channel=self.name,
            session_key=session_key,
            user_id=str(self._app.bot.id),
            content=f"[Audio: {filename}]",
            direction=MessageDirection.OUTBOUND,
            timestamp=datetime.now(UTC),
        )

    # Telegram file size limit
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

    async def send_file(
        self,
        session_key: str,
        file_data: bytes,
        filename: str,
        mime_type: str | None = None,
        caption: str | None = None,
    ) -> None:
        """Send a file via Telegram's sendDocument API.

        Args:
            session_key: Session key in format 'telegram:chat_id'.
            file_data: Raw file bytes.
            filename: Display filename for the file.
            mime_type: Optional MIME type hint (currently unused by Telegram API).
            caption: Optional caption/message to accompany the file.

        Raises:
            RuntimeError: If the channel is not started.
            ValueError: If file size exceeds Telegram's 50MB limit.
        """
        if not self._app:
            raise RuntimeError("Telegram channel not started")

        check_file_size(file_data, self.MAX_FILE_SIZE, "Telegram")
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
            logger.info(f"Sent file '{filename}' ({file_size} bytes) to chat {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send file '{filename}' to chat {chat_id}: {e}")
            raise RuntimeError(f"Failed to send file: {e}") from e

    def _is_allowed(self, update: Update) -> bool:
        """Check if the message sender is allowed.

        Extracts primitive IDs and delegates to SecurityMixin.

        Args:
            update: The Telegram Update object.

        Returns:
            True if the sender is allowed, False otherwise.
        """
        if not update.effective_user:
            return False

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id if update.effective_chat else None
        # In Telegram, negative chat IDs are group chats
        group_id = chat_id if chat_id is not None and chat_id < 0 else None
        return self._check_user_allowed(user_id, group_id)

    def _passes_activation_filter(self, update: Update) -> bool:
        """Check whether the message passes activation filters (mention OR trigger).

        Extracts primitive flags and delegates to SecurityMixin.

        Args:
            update: The Telegram Update object.

        Returns:
            True if the message should be processed.
        """
        is_dm = (
            update.effective_chat is not None
            and update.effective_chat.id > 0
        )
        is_command = bool(
            update.message
            and update.message.text
            and update.message.text.startswith("/")
        )
        content = (
            (update.message.text or update.message.caption or "")
            if update.message
            else ""
        )
        is_mentioned = self._has_bot_mention(update)
        return self._check_activation(
            content, is_dm, is_command, is_mentioned
        )

    def _has_bot_mention(self, update: Update) -> bool:
        """Check if the message contains an @mention of this bot."""
        if not update.message or not update.message.entities or not self._bot_username:
            return False

        text = update.message.text or ""
        for entity in update.message.entities:
            if entity.type == "mention":
                mention_text = text[entity.offset:entity.offset + entity.length]
                if mention_text.lower() == f"@{self._bot_username.lower()}":
                    return True
        return False

    def _to_message(self, update: Update) -> Message | None:
        """Convert Telegram update to unified Message format."""
        if not update.message or not update.effective_user or not update.effective_chat:
            return None

        chat_id = update.effective_chat.id
        session_key = self.build_session_key(chat_id)

        return Message(
            id=str(update.message.message_id),
            channel=self.name,
            session_key=session_key,
            user_id=str(update.effective_user.id),
            content=update.message.text or "",
            direction=MessageDirection.INBOUND,
            timestamp=update.message.date or datetime.now(UTC),
            reply_to_id=str(update.message.reply_to_message.message_id) if update.message.reply_to_message else None,
            metadata={
                "chat_type": update.effective_chat.type,
                "username": update.effective_user.username,
                "first_name": update.effective_user.first_name,
            },
        )

    async def _send_unauthorized_response(self, update: Update) -> None:
        """Send a helpful response to unauthorized users with their ID."""
        if not update.message or not update.effective_user:
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id if update.effective_chat else None
        group_id = chat_id if chat_id is not None and chat_id < 0 else None

        text = format_unauthorized_response(user_id, self.workspace_name, group_id)

        await update.message.reply_text(text, parse_mode="Markdown")
        logger.warning(f"Blocked user {user_id} from workspace '{self.workspace_name}'")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages."""
        if not self._is_allowed(update):
            await self._send_unauthorized_response(update)
            return
        if not self._passes_activation_filter(update):
            return

        message = self._to_message(update)
        if message and self._message_callback:
            await self._message_callback(message)

    async def _handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming commands."""
        if not self._is_allowed(update):
            await self._send_unauthorized_response(update)
            return

        message = self._to_message(update)
        if message and self._message_callback:
            await self._message_callback(message)

    async def _handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming voice and audio messages."""
        if not self._is_allowed(update):
            await self._send_unauthorized_response(update)
            return
        if not self._passes_activation_filter(update):
            return

        message = await self._voice_to_message(update)
        if message and self._message_callback:
            await self._message_callback(message)

    async def _handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming document uploads (PDF, DOCX, images, etc.)."""
        if not self._is_allowed(update):
            await self._send_unauthorized_response(update)
            return
        if not self._passes_activation_filter(update):
            return

        message = await self._document_to_message(update)
        if message and self._message_callback:
            await self._message_callback(message)

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming photo messages."""
        if not self._is_allowed(update):
            await self._send_unauthorized_response(update)
            return
        if not self._passes_activation_filter(update):
            return

        message = await self._photo_to_message(update)
        if message and self._message_callback:
            await self._message_callback(message)

    async def _document_to_message(self, update: Update) -> Message | None:
        """Convert document upload to unified Message format with attachment.

        Downloads the file and creates a document Attachment for processing
        by inbound processors (e.g., DoclingProcessor).
        """
        if not update.message or not update.effective_user or not update.effective_chat:
            return None

        document = update.message.document
        if not document:
            return None

        chat_id = update.effective_chat.id
        session_key = self.build_session_key(chat_id)

        try:
            file = await document.get_file()
            file_bytes = await file.download_as_bytearray()

            attachment = Attachment(
                type="document",
                data=bytes(file_bytes),
                filename=document.file_name,
                mime_type=document.mime_type or "application/octet-stream",
                metadata={"file_size": document.file_size},
            )

            logger.info(
                f"Downloaded document: {document.file_name} "
                f"({document.file_size} bytes, {document.mime_type})"
            )

        except Exception as e:
            logger.error(f"Failed to download document: {e}")
            return None

        return Message(
            id=str(update.message.message_id),
            channel=self.name,
            session_key=session_key,
            user_id=str(update.effective_user.id),
            content=update.message.caption or "",
            direction=MessageDirection.INBOUND,
            timestamp=update.message.date or datetime.now(UTC),
            reply_to_id=str(update.message.reply_to_message.message_id) if update.message.reply_to_message else None,
            metadata={
                "chat_type": update.effective_chat.type,
                "username": update.effective_user.username,
                "first_name": update.effective_user.first_name,
                "has_document": True,
            },
            attachments=[attachment],
        )

    async def _photo_to_message(self, update: Update) -> Message | None:
        """Convert photo message to unified Message format with attachment.

        Downloads the highest resolution photo and creates an Attachment for processing
        by inbound processors (e.g., vision models).

        Telegram sends photos as an array of PhotoSize objects with different resolutions.
        We select the last element which has the highest resolution.
        """
        if not update.message or not update.effective_user or not update.effective_chat:
            return None

        if not update.message.photo:
            return None

        chat_id = update.effective_chat.id
        session_key = self.build_session_key(chat_id)

        # Get highest resolution photo (last element in array)
        photo = update.message.photo[-1]

        try:
            file = await photo.get_file()
            file_bytes = await file.download_as_bytearray()

            attachment = Attachment(
                type="image",
                data=bytes(file_bytes),
                filename=None,  # Telegram photos don't have filenames
                mime_type="image/jpeg",  # Telegram compresses to JPEG
                metadata={
                    "width": photo.width,
                    "height": photo.height,
                    "file_size": photo.file_size,
                },
            )

            logger.info(
                f"Downloaded photo: {photo.width}x{photo.height} "
                f"({photo.file_size} bytes)"
            )

        except Exception as e:
            logger.error(f"Failed to download photo: {e}")
            return None

        return Message(
            id=str(update.message.message_id),
            channel=self.name,
            session_key=session_key,
            user_id=str(update.effective_user.id),
            content=update.message.caption or "",
            direction=MessageDirection.INBOUND,
            timestamp=update.message.date or datetime.now(UTC),
            reply_to_id=str(update.message.reply_to_message.message_id) if update.message.reply_to_message else None,
            metadata={
                "chat_type": update.effective_chat.type,
                "username": update.effective_user.username,
                "first_name": update.effective_user.first_name,
                "has_photo": True,
            },
            attachments=[attachment],
        )

    async def _voice_to_message(self, update: Update) -> Message | None:
        """Convert voice/audio message to unified Message format with attachment.

        Downloads the audio file and creates an Attachment for processing
        by the Whisper transcription processor.
        """
        if not update.message or not update.effective_user or not update.effective_chat:
            return None

        # Get voice or audio file
        voice = update.message.voice
        audio = update.message.audio

        if not voice and not audio:
            return None

        chat_id = update.effective_chat.id
        session_key = self.build_session_key(chat_id)

        # Download the audio file
        try:
            if voice:
                file = await voice.get_file()
                mime_type = voice.mime_type or "audio/ogg"
                duration = voice.duration
            else:
                file = await audio.get_file()  # type: ignore[union-attr]
                mime_type = audio.mime_type or "audio/mpeg"  # type: ignore[union-attr]
                duration = audio.duration  # type: ignore[union-attr]

            file_bytes = await file.download_as_bytearray()

            attachment = Attachment(
                type="audio",
                data=bytes(file_bytes),
                mime_type=mime_type,
                metadata={"duration": duration},
            )

            logger.info(f"Downloaded voice message: {len(file_bytes)} bytes, {duration}s")

        except Exception as e:
            logger.error(f"Failed to download voice message: {e}")
            return None

        # Create message with audio attachment
        return Message(
            id=str(update.message.message_id),
            channel=self.name,
            session_key=session_key,
            user_id=str(update.effective_user.id),
            content="",  # Will be filled by Whisper processor
            direction=MessageDirection.INBOUND,
            timestamp=update.message.date or datetime.now(UTC),
            reply_to_id=str(update.message.reply_to_message.message_id) if update.message.reply_to_message else None,
            metadata={
                "chat_type": update.effective_chat.type,
                "username": update.effective_user.username,
                "first_name": update.effective_user.first_name,
                "has_voice": True,
            },
            attachments=[attachment],
        )

    def on_approval(
        self, callback: Callable[[str, bool], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback for approval resolutions."""
        self._approval_callback = callback

    async def send_approval_request(
        self,
        session_key: str,
        approval_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        show_args: bool = True,
    ) -> None:
        """Send approval request with Telegram inline keyboard."""
        chat_id = int(session_key.split(":")[1])

        text = format_approval_message(tool_name, tool_args, show_args)

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Approve", callback_data=f"approve:{approval_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ Deny", callback_data=f"deny:{approval_id}"
                    ),
                ]
            ]
        )

        await self._app.bot.send_message(  # type: ignore[union-attr]
            chat_id=chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    async def _handle_approval_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle inline keyboard button presses for approval gates."""
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()  # Acknowledge the button press

        parts = query.data.split(":", 1)
        if len(parts) != 2:
            return

        action, approval_id = parts
        approved = action == "approve"

        # Update the button message to show result
        result_text = "Approved" if approved else "Denied"
        if query.message and query.message.text:
            try:
                await query.edit_message_text(
                    text=f"{query.message.text}\n\nResult: {result_text}",
                )
            except Exception:
                logger.debug("Failed to update approval message", exc_info=True)

        # Invoke the callback
        if self._approval_callback:
            await self._approval_callback(approval_id, approved)
