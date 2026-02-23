"""Tests for audio context (contextvars-based pending audio)."""

from openpaw.builtins.tools._audio_context import (
    clear_pending_audio,
    get_pending_audio,
    set_pending_audio,
)


def test_default_is_none():
    """Default audio context should be None."""
    clear_pending_audio()  # Ensure clean state
    assert get_pending_audio() is None


def test_set_and_get():
    """Setting audio should be retrievable."""
    audio = b"fake audio data"
    set_pending_audio(audio)
    assert get_pending_audio() == audio
    clear_pending_audio()


def test_clear():
    """Clearing should reset to None."""
    set_pending_audio(b"data")
    clear_pending_audio()
    assert get_pending_audio() is None


def test_overwrite():
    """Setting audio twice should overwrite."""
    set_pending_audio(b"first")
    set_pending_audio(b"second")
    assert get_pending_audio() == b"second"
    clear_pending_audio()
