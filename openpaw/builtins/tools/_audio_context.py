"""Shared audio context for ElevenLabs TTS pending audio delivery."""

import contextvars

_pending_audio_var: contextvars.ContextVar[bytes | None] = contextvars.ContextVar(
    "_pending_audio", default=None
)


def set_pending_audio(audio: bytes) -> None:
    """Store pending audio for delivery after agent response.

    Args:
        audio: Raw audio bytes to deliver.
    """
    _pending_audio_var.set(audio)


def get_pending_audio() -> bytes | None:
    """Retrieve pending audio data.

    Returns:
        Audio bytes if available, None otherwise.
    """
    return _pending_audio_var.get()


def clear_pending_audio() -> None:
    """Clear pending audio data."""
    _pending_audio_var.set(None)
