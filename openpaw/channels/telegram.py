"""Telegram channel adapter using python-telegram-bot."""

import logging
import os
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from openpaw.channels.base import ChannelAdapter, Message, MessageDirection

logger = logging.getLogger(__name__)


class TelegramChannel(ChannelAdapter):
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
    ):
        """Initialize the Telegram channel.

        Args:
            token: Bot token (falls back to TELEGRAM_BOT_TOKEN env var).
            allowed_users: List of allowed user IDs (empty = allow all).
            allowed_groups: List of allowed group IDs (empty = allow all).
        """
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("Telegram bot token required (pass token or set TELEGRAM_BOT_TOKEN)")

        self.allowed_users = set(allowed_users or [])
        self.allowed_groups = set(allowed_groups or [])
        self._app: Application | None = None  # type: ignore[type-arg]
        self._message_callback: Callable[[Message], Coroutine[Any, Any, None]] | None = None

    async def start(self) -> None:
        """Start the Telegram bot."""
        self._app = Application.builder().token(self.token).build()

        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("help", self._handle_help))
        self._app.add_handler(CommandHandler("queue", self._handle_queue_command))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))
        self._app.add_handler(MessageHandler(filters.COMMAND, self._handle_command))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()  # type: ignore[union-attr]

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

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        """Send a message to a Telegram chat.

        Args:
            session_key: Session key in format 'telegram:chat_id'.
            content: Message text.
            **kwargs: Additional telegram.Bot.send_message kwargs.

        Returns:
            The sent Message object.
        """
        if not self._app:
            raise RuntimeError("Telegram channel not started")

        parts = session_key.split(":")
        chat_id = int(parts[1])

        sent = await self._app.bot.send_message(chat_id=chat_id, text=content, **kwargs)

        return Message(
            id=str(sent.message_id),
            channel=self.name,
            session_key=session_key,
            user_id=str(self._app.bot.id),
            content=content,
            direction=MessageDirection.OUTBOUND,
            timestamp=datetime.now(),
        )

    def _is_allowed(self, update: Update) -> bool:
        """Check if the message sender is allowed."""
        if not update.effective_user:
            return False

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id if update.effective_chat else None

        if self.allowed_users and user_id not in self.allowed_users:
            return False

        if chat_id and chat_id < 0:
            if self.allowed_groups and chat_id not in self.allowed_groups:
                return False

        return True

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
            timestamp=update.message.date or datetime.now(),
            reply_to_id=str(update.message.reply_to_message.message_id) if update.message.reply_to_message else None,
            metadata={
                "chat_type": update.effective_chat.type,
                "username": update.effective_user.username,
                "first_name": update.effective_user.first_name,
            },
        )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages."""
        if not self._is_allowed(update):
            logger.warning(f"Blocked message from unauthorized user: {update.effective_user}")
            return

        message = self._to_message(update)
        if message and self._message_callback:
            await self._message_callback(message)

    async def _handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming commands."""
        if not self._is_allowed(update):
            return

        message = self._to_message(update)
        if message and self._message_callback:
            await self._message_callback(message)

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not self._is_allowed(update):
            return

        if update.message:
            await update.message.reply_text(
                "OpenPaw agent ready. Send me a message to begin.\n\n"
                "Commands:\n"
                "/help - Show this help\n"
                "/queue <mode> - Set queue mode (collect, steer, followup)"
            )

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not self._is_allowed(update):
            return

        if update.message:
            await update.message.reply_text(
                "OpenPaw Commands:\n\n"
                "/start - Initialize the bot\n"
                "/help - Show this help\n"
                "/queue <mode> - Set queue mode\n"
                "  - collect: Coalesce messages (default)\n"
                "  - steer: Inject immediately\n"
                "  - followup: Queue for next turn\n"
                "\nJust send a message to chat with the agent."
            )

    async def _handle_queue_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /queue command for setting queue mode."""
        if not self._is_allowed(update):
            return

        message = self._to_message(update)
        if message and self._message_callback:
            await self._message_callback(message)
