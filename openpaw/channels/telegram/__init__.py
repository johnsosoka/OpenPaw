"""Telegram channel adapter using python-telegram-bot."""

import logging
import os
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.helpers import SecurityMixin, format_unauthorized_response
from openpaw.channels.telegram.approval import TelegramApprovalSender
from openpaw.channels.telegram.attachments import TelegramAttachmentConverter
from openpaw.channels.telegram.constants import MAX_FILE_SIZE, MAX_MESSAGE_LENGTH
from openpaw.channels.telegram.handlers import TelegramInboundHandler
from openpaw.channels.telegram.outbound import TelegramOutboundSender
from openpaw.model.channel import ChannelEvent
from openpaw.model.message import Message, MessageDirection

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

    MAX_MESSAGE_LENGTH = MAX_MESSAGE_LENGTH
    MAX_FILE_SIZE = MAX_FILE_SIZE

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
        """Initialize the Telegram channel."""
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
        self._channel_event_callback: Callable[[ChannelEvent], Coroutine[Any, Any, None]] | None = None

        self._attachment_converter = TelegramAttachmentConverter(
            channel_name=self.name,
            build_session_key=self.build_session_key,
        )
        self._inbound_handler = TelegramInboundHandler(
            channel=self,
            attachment_converter=self._attachment_converter,
        )
        self._approval_sender: TelegramApprovalSender | None = None
        self._outbound_sender: TelegramOutboundSender | None = None

    async def start(self) -> None:
        """Start the Telegram bot."""
        self._app = Application.builder().token(self.token).build()

        # Add callback query handler for approval buttons (BEFORE message handlers)
        self._app.add_handler(CallbackQueryHandler(self._inbound_handler.handle_approval_callback))

        # Route all messages through the unified callback
        self._app.add_handler(MessageHandler(filters.COMMAND, self._inbound_handler.handle_command))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._inbound_handler.handle_message))
        self._app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._inbound_handler.handle_voice_message))
        self._app.add_handler(MessageHandler(filters.Document.ALL, self._inbound_handler.handle_document))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._inbound_handler.handle_photo))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()  # type: ignore[union-attr]

        # Capture bot username for mention detection in group chats
        if self._app.bot:
            bot_info = await self._app.bot.get_me()
            self._bot_username = bot_info.username
            logger.debug("Bot username: @%s", self._bot_username)

        self._approval_sender = TelegramApprovalSender(self._app)
        self._outbound_sender = TelegramOutboundSender(
            app=self._app,
            channel_name=self.name,
            bot_id=self._app.bot.id,
        )

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

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Any:
        """Send a message to a Telegram chat."""
        if not self._outbound_sender:
            if not self._app:
                raise RuntimeError("Telegram channel not started")
            self._outbound_sender = TelegramOutboundSender(
                app=self._app,
                channel_name=self.name,
                bot_id=self._app.bot.id,
            )
        return await self._outbound_sender.send_message(session_key, content, **kwargs)

    async def send_audio(self, session_key: str, audio_data: bytes, filename: str = "audio.mp3", **kwargs: Any) -> Any:
        """Send an audio file to a Telegram chat."""
        if not self._outbound_sender:
            if not self._app:
                raise RuntimeError("Telegram channel not started")
            self._outbound_sender = TelegramOutboundSender(
                app=self._app,
                channel_name=self.name,
                bot_id=self._app.bot.id,
            )
        return await self._outbound_sender.send_audio(session_key, audio_data, filename, **kwargs)

    async def send_file(
        self,
        session_key: str,
        file_data: bytes,
        filename: str,
        mime_type: str | None = None,
        caption: str | None = None,
    ) -> None:
        """Send a file via Telegram's sendDocument API."""
        if not self._outbound_sender:
            if not self._app:
                raise RuntimeError("Telegram channel not started")
            self._outbound_sender = TelegramOutboundSender(
                app=self._app,
                channel_name=self.name,
                bot_id=self._app.bot.id,
            )
        await self._outbound_sender.send_file(session_key, file_data, filename, mime_type, caption)

    def _is_allowed(self, update: Update) -> bool:
        """Check if the message sender is allowed."""
        if not update.effective_user:
            return False

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id if update.effective_chat else None
        group_id = chat_id if chat_id is not None and chat_id < 0 else None
        return self._check_user_allowed(user_id, group_id)

    def _passes_activation_filter(self, update: Update) -> bool:
        """Check whether the message passes activation filters."""
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

    def _to_message(self, update: Update) -> Any:
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
        logger.warning("Blocked user %s from workspace '%s'", user_id, self.workspace_name)

    def on_approval(self, callback: Callable[[str, bool], Coroutine[Any, Any, None]]) -> None:
        """Register a callback for approval resolutions."""
        self._approval_callback = callback

    async def _document_to_message(self, update: Any) -> Any:
        """Backward-compatible wrapper for TelegramAttachmentConverter."""
        return await self._attachment_converter.document_to_message(update)

    async def _photo_to_message(self, update: Any) -> Any:
        """Backward-compatible wrapper for TelegramAttachmentConverter."""
        return await self._attachment_converter.photo_to_message(update)

    async def _voice_to_message(self, update: Any) -> Any:
        """Backward-compatible wrapper for TelegramAttachmentConverter."""
        return await self._attachment_converter.voice_to_message(update)

    async def _handle_message(self, update: Any, context: Any) -> None:
        """Backward-compatible wrapper for TelegramInboundHandler."""
        await self._inbound_handler.handle_message(update, context)

    async def _handle_command(self, update: Any, context: Any) -> None:
        """Backward-compatible wrapper for TelegramInboundHandler."""
        await self._inbound_handler.handle_command(update, context)

    async def _handle_voice_message(self, update: Any, context: Any) -> None:
        """Backward-compatible wrapper for TelegramInboundHandler."""
        await self._inbound_handler.handle_voice_message(update, context)

    async def _handle_document(self, update: Any, context: Any) -> None:
        """Backward-compatible wrapper for TelegramInboundHandler."""
        await self._inbound_handler.handle_document(update, context)

    async def _handle_photo(self, update: Any, context: Any) -> None:
        """Backward-compatible wrapper for TelegramInboundHandler."""
        await self._inbound_handler.handle_photo(update, context)

    async def _handle_approval_callback(self, update: Any, context: Any) -> None:
        """Backward-compatible wrapper for TelegramInboundHandler."""
        await self._inbound_handler.handle_approval_callback(update, context)

    async def send_approval_request(
        self,
        session_key: str,
        approval_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        show_args: bool = True,
    ) -> None:
        """Send approval request with Telegram inline keyboard."""
        if self._approval_sender is None:
            if not self._app:
                raise RuntimeError("Telegram channel not started")
            self._approval_sender = TelegramApprovalSender(self._app)
        await self._approval_sender.send_request(
            session_key=session_key,
            approval_id=approval_id,
            tool_name=tool_name,
            tool_args=tool_args,
            show_args=show_args,
        )
