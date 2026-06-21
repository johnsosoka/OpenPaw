"""Response sending logic for agent outputs."""

import logging
from typing import Any

from openpaw.channels.base import ChannelAdapter
from openpaw.runtime.session.manager import SessionManager


class ResponseHandler:
    """Handles sending agent responses to channels, including ack suppression and audio."""

    def __init__(
        self,
        builtin_loader: Any,
        session_manager: SessionManager,
        logger: logging.Logger,
    ) -> None:
        """Initialize the response handler.

        Args:
            builtin_loader: BuiltinLoader for accessing acknowledge tool.
            session_manager: Session tracking for message counts.
            logger: Logger instance.
        """
        self._builtin_loader = builtin_loader
        self._session_manager = session_manager
        self._logger = logger

    @staticmethod
    def is_system_event_batch(messages: list[Any]) -> bool:
        """Check if all messages in the batch are system events.

        System events have user_id == "system" and are injected by the
        framework (cron results, heartbeat injections, sub-agent completions).
        Only a system-only batch allows acknowledge_event to suppress delivery —
        this prevents user messages from ever being silently swallowed.

        Args:
            messages: The message batch to inspect.

        Returns:
            True only if the list is non-empty and every message has user_id "system".
        """
        if not messages:
            return False
        return all(
            getattr(msg, "user_id", None) == "system" for msg in messages
        )

    async def send_response(
        self,
        session_key: str,
        response: str | None,
        channel: ChannelAdapter | None,
        messages: list[Any],
    ) -> None:
        """Send the agent response to the channel, handling ack suppression.

        Args:
            session_key: The session identifier.
            response: The agent's response text.
            channel: Channel adapter for sending responses.
            messages: The original message batch for system-event detection.
        """
        if not channel:
            return

        is_system_batch = self.is_system_event_batch(messages)

        # Check for silent acknowledgment on system events
        ack_tool = self._builtin_loader.get_tool_instance("acknowledge")
        ack = ack_tool.get_pending_ack() if ack_tool else None

        if is_system_batch and ack:
            self._logger.info(
                f"System event acknowledged for {session_key}: {ack.reason} "
                f"(suppressing channel delivery, {len(response or '')} chars)"
            )
            self._session_manager.increment_message_count(session_key)
        elif response and response.strip():
            resp_preview = response[:120].replace("\n", " ")
            self._logger.info(
                f"Sending response ({len(response)} chars): {resp_preview}..."
            )
            await channel.send_message(session_key, response)
            self._session_manager.increment_message_count(session_key)
            await self._send_pending_audio(channel, session_key)
        else:
            self._logger.warning(
                f"Agent produced empty response for {session_key}, sending fallback"
            )
            fallback = "I processed your message but my response was empty. Please try again."
            await channel.send_message(session_key, fallback)

    async def _send_pending_audio(
        self, channel: ChannelAdapter, session_key: str
    ) -> None:
        """Check for and send any pending TTS audio."""
        if not hasattr(channel, "send_audio"):
            return

        try:
            from openpaw.builtins.tools._audio_context import (
                clear_pending_audio,
                get_pending_audio,
            )

            audio_data = get_pending_audio()
            if audio_data:
                await channel.send_audio(session_key, audio_data, filename="response.mp3")
                clear_pending_audio()
                self._logger.info(f"Sent TTS audio to {session_key}")
        except ImportError:
            pass  # Audio context not available
        except Exception as e:
            self._logger.error(f"Failed to send TTS audio: {e}")
