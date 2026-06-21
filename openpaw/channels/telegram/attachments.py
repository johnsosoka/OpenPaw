"""Telegram attachment conversion utilities."""

import logging
from datetime import UTC, datetime
from typing import Any

from telegram import Update

from openpaw.model.message import Attachment, Message, MessageDirection

logger = logging.getLogger(__name__)


class TelegramAttachmentConverter:
    """Convert Telegram document/photo/voice uploads to OpenPaw Message."""

    def __init__(self, channel_name: str, build_session_key: Any) -> None:
        self._channel_name = channel_name
        self._build_session_key = build_session_key

    async def document_to_message(self, update: Update) -> Message | None:
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
        session_key = self._build_session_key(chat_id)

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
                "Downloaded document: %s "
                "(%s bytes, %s)",
                document.file_name,
                document.file_size,
                document.mime_type,
            )

        except Exception as e:
            logger.error("Failed to download document: %s", e)
            return None

        return Message(
            id=str(update.message.message_id),
            channel=self._channel_name,
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

    async def photo_to_message(self, update: Update) -> Message | None:
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
        session_key = self._build_session_key(chat_id)

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
                "Downloaded photo: %sx%s "
                "(%s bytes)",
                photo.width,
                photo.height,
                photo.file_size,
            )

        except Exception as e:
            logger.error("Failed to download photo: %s", e)
            return None

        return Message(
            id=str(update.message.message_id),
            channel=self._channel_name,
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

    async def voice_to_message(self, update: Update) -> Message | None:
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
        session_key = self._build_session_key(chat_id)

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

            logger.info("Downloaded voice message: %s bytes, %ss", len(file_bytes), duration)

        except Exception as e:
            logger.error("Failed to download voice message: %s", e)
            return None

        # Create message with audio attachment
        return Message(
            id=str(update.message.message_id),
            channel=self._channel_name,
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
