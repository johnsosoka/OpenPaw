"""Telegram inbound message handlers."""

import logging
from typing import Any

from telegram import Update
from telegram.ext import ContextTypes

from openpaw.channels.telegram.attachments import TelegramAttachmentConverter

logger = logging.getLogger(__name__)


class TelegramInboundHandler:
    """Handle incoming Telegram messages and route them to the callback."""

    def __init__(
        self,
        channel: Any,
        attachment_converter: TelegramAttachmentConverter,
    ) -> None:
        self._channel = channel
        self._attachment_converter = attachment_converter

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages."""
        if not self._channel._is_allowed(update):
            await self._channel._send_unauthorized_response(update)
            return
        if not self._channel._passes_activation_filter(update):
            return

        message = self._channel._to_message(update)
        if message and self._channel._message_callback:
            await self._channel._message_callback(message)

    async def handle_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming commands."""
        if not self._channel._is_allowed(update):
            await self._channel._send_unauthorized_response(update)
            return

        message = self._channel._to_message(update)
        if message and self._channel._message_callback:
            await self._channel._message_callback(message)

    async def handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming voice and audio messages."""
        if not self._channel._is_allowed(update):
            await self._channel._send_unauthorized_response(update)
            return
        if not self._channel._passes_activation_filter(update):
            return

        message = await self._attachment_converter.voice_to_message(update)
        if message and self._channel._message_callback:
            await self._channel._message_callback(message)

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming document uploads (PDF, DOCX, images, etc.)."""
        if not self._channel._is_allowed(update):
            await self._channel._send_unauthorized_response(update)
            return
        if not self._channel._passes_activation_filter(update):
            return

        message = await self._attachment_converter.document_to_message(update)
        if message and self._channel._message_callback:
            await self._channel._message_callback(message)

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming photo messages."""
        if not self._channel._is_allowed(update):
            await self._channel._send_unauthorized_response(update)
            return
        if not self._channel._passes_activation_filter(update):
            return

        message = await self._attachment_converter.photo_to_message(update)
        if message and self._channel._message_callback:
            await self._channel._message_callback(message)

    async def handle_approval_callback(
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
        if query.message and hasattr(query.message, "text") and query.message.text:
            try:
                await query.edit_message_text(
                    text=f"{query.message.text}\n\nResult: {result_text}",
                )
            except Exception:
                logger.debug("Failed to update approval message", exc_info=True)

        # Invoke the callback
        if self._channel._approval_callback:
            await self._channel._approval_callback(approval_id, approved)
