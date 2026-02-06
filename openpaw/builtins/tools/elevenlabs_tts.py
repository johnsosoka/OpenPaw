"""ElevenLabs text-to-speech tool builtin."""

import logging
import os
from typing import Any

from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)

logger = logging.getLogger(__name__)


class TTSInput(BaseModel):
    """Input schema for text-to-speech tool."""

    text: str = Field(description="The text to convert to speech")
    voice_id: str | None = Field(
        default=None,
        description="Optional voice ID override (uses default if not specified)",
    )


class ElevenLabsTTSTool(BaseBuiltinTool):
    """Text-to-speech capability via ElevenLabs API.

    Provides agents with the ability to generate audio responses.
    The generated audio is stored and can be retrieved for sending via channel.

    Requires ELEVENLABS_API_KEY environment variable to be set.

    Config options:
        voice_id: Default voice ID to use
        model_id: ElevenLabs model (default: "eleven_monolingual_v1")
        output_format: Audio format (default: "mp3_44100_128")
    """

    metadata = BuiltinMetadata(
        name="elevenlabs",
        display_name="ElevenLabs Text-to-Speech",
        description="Convert text responses to audio using ElevenLabs",
        builtin_type=BuiltinType.TOOL,
        group="voice",
        prerequisites=BuiltinPrerequisite(env_vars=["ELEVENLABS_API_KEY"]),
    )

    # Class-level storage for pending audio (allows retrieval after agent run)
    _pending_audio: dict[str, bytes] = {}

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self._instance_id = id(self)

    def get_langchain_tool(self) -> Any:
        """Return configured TTS tool as a LangChain StructuredTool."""
        try:
            from langchain_core.tools import StructuredTool
        except ImportError as e:
            raise ImportError(
                "langchain-core is required for ElevenLabs TTS. "
                "Install with: pip install langchain-core"
            ) from e

        async def generate_speech(text: str, voice_id: str | None = None) -> str:
            """Generate speech from text and store for channel delivery.

            Args:
                text: The text to convert to speech.
                voice_id: Optional voice ID override.

            Returns:
                Confirmation message about the generated audio.
            """
            try:
                audio_bytes = await self._generate_audio(text, voice_id)
                # Store audio for later retrieval
                ElevenLabsTTSTool._pending_audio[str(self._instance_id)] = audio_bytes
                return f"[Audio generated: {len(audio_bytes):,} bytes, ready to send]"
            except Exception as e:
                logger.error(f"Failed to generate speech: {e}")
                return f"[Failed to generate audio: {e}]"

        return StructuredTool.from_function(
            func=lambda text, voice_id=None: generate_speech(text, voice_id),
            name="text_to_speech",
            description=(
                "Convert text to spoken audio. Use this when you want to send a voice message "
                "or when the user requests audio output. The audio will be attached to your response."
            ),
            args_schema=TTSInput,
            coroutine=generate_speech,
        )

    async def _generate_audio(self, text: str, voice_id: str | None = None) -> bytes:
        """Generate audio bytes from text using ElevenLabs API.

        Args:
            text: Text to convert to speech.
            voice_id: Optional voice ID override.

        Returns:
            Audio bytes.
        """
        try:
            from elevenlabs.client import AsyncElevenLabs
        except ImportError as e:
            raise ImportError(
                "elevenlabs is required for TTS. Install with: pip install elevenlabs"
            ) from e

        api_key = os.environ.get("ELEVENLABS_API_KEY", "")
        client = AsyncElevenLabs(api_key=api_key)

        resolved_voice_id = voice_id or self.config.get("voice_id", "21m00Tcm4TlvDq8ikWAM")
        model_id = self.config.get("model_id", "eleven_monolingual_v1")
        output_format = self.config.get("output_format", "mp3_44100_128")

        logger.debug(f"Generating speech: voice={resolved_voice_id}, model={model_id}")

        audio_generator = await client.generate(
            text=text,
            voice=resolved_voice_id,
            model=model_id,
            output_format=output_format,
        )

        # Collect audio bytes from async generator
        chunks: list[bytes] = []
        async for chunk in audio_generator:
            chunks.append(chunk)

        return b"".join(chunks)

    def get_pending_audio(self) -> bytes | None:
        """Retrieve and clear pending audio data.

        Returns:
            Audio bytes if available, None otherwise.
        """
        return ElevenLabsTTSTool._pending_audio.pop(str(self._instance_id), None)

    @classmethod
    def get_any_pending_audio(cls) -> bytes | None:
        """Retrieve any pending audio (for simpler single-agent scenarios).

        Returns:
            Audio bytes if available, None otherwise.
        """
        if cls._pending_audio:
            # Return first available
            key = next(iter(cls._pending_audio))
            return cls._pending_audio.pop(key)
        return None

    @classmethod
    def clear_pending_audio(cls) -> None:
        """Clear all pending audio data."""
        cls._pending_audio.clear()
