"""Whisper audio transcription processor."""

import logging
import os
from io import BytesIO
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinProcessor,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
    ProcessorResult,
)
from openpaw.channels.base import Attachment, Message

logger = logging.getLogger(__name__)


class WhisperProcessor(BaseBuiltinProcessor):
    """Transcribes audio attachments in inbound messages using OpenAI Whisper.

    Processes audio attachments before the message reaches the agent,
    converting speech to text and appending it to the message content.

    Requires OPENAI_API_KEY environment variable to be set.

    Config options:
        model: Whisper model to use (default: "whisper-1")
        language: Language hint for transcription (default: auto-detect)
    """

    metadata = BuiltinMetadata(
        name="whisper",
        display_name="Whisper Audio Transcription",
        description="Transcribes voice/audio messages before sending to agent",
        builtin_type=BuiltinType.PROCESSOR,
        group="voice",
        prerequisites=BuiltinPrerequisite(env_vars=["OPENAI_API_KEY"]),
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy initialization of OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise ImportError(
                    "openai is required for Whisper transcription. "
                    "Install with: pip install openai"
                ) from e

            self._client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        return self._client

    async def process_inbound(self, message: Message) -> ProcessorResult:
        """Transcribe audio attachments and append text to message content.

        Args:
            message: The incoming message, possibly with audio attachments.

        Returns:
            ProcessorResult with transcribed text appended to content.
        """
        audio_attachments = [a for a in message.attachments if a.type == "audio"]

        if not audio_attachments:
            return ProcessorResult(message=message)

        transcriptions: list[str] = []

        for attachment in audio_attachments:
            if not attachment.data:
                logger.warning("Audio attachment has no data, skipping")
                continue

            try:
                text = await self._transcribe(attachment)
                if text:
                    transcriptions.append(text)
                    logger.info(f"Transcribed audio: {text[:50]}...")
            except Exception as e:
                logger.error(f"Failed to transcribe audio: {e}")

        if not transcriptions:
            return ProcessorResult(message=message)

        # Append transcriptions to message content
        transcribed_text = "\n".join(transcriptions)

        if message.content:
            new_content = f"{message.content}\n\n[Voice message]: {transcribed_text}"
        else:
            new_content = f"[Voice message]: {transcribed_text}"

        # Create new message with updated content
        updated_message = Message(
            id=message.id,
            channel=message.channel,
            session_key=message.session_key,
            user_id=message.user_id,
            content=new_content,
            direction=message.direction,
            timestamp=message.timestamp,
            reply_to_id=message.reply_to_id,
            metadata={**message.metadata, "transcribed": True},
            attachments=message.attachments,
        )

        return ProcessorResult(message=updated_message)

    async def _transcribe(self, attachment: Attachment) -> str:
        """Transcribe a single audio attachment.

        Args:
            attachment: Audio attachment with data.

        Returns:
            Transcribed text.
        """
        client = self._get_client()

        model = self.config.get("model", "whisper-1")
        language = self.config.get("language")

        # Determine file extension from mime type or default to ogg
        ext = "ogg"
        if attachment.mime_type:
            mime_to_ext = {
                "audio/ogg": "ogg",
                "audio/mpeg": "mp3",
                "audio/mp4": "m4a",
                "audio/wav": "wav",
                "audio/webm": "webm",
            }
            ext = mime_to_ext.get(attachment.mime_type, ext)

        # attachment.data is guaranteed non-None by caller
        assert attachment.data is not None
        audio_file = BytesIO(attachment.data)
        audio_file.name = f"audio.{ext}"

        kwargs: dict[str, Any] = {
            "model": model,
            "file": audio_file,
        }
        if language:
            kwargs["language"] = language

        result = await client.audio.transcriptions.create(**kwargs)

        return str(result.text)
