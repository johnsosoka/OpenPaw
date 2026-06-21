"""Session TTL (time-to-live) checking and conversation rotation."""

import logging
from typing import Any

from openpaw.channels.base import ChannelAdapter
from openpaw.model.message import Message
from openpaw.runtime.session.manager import SessionManager


class SessionTTLChecker:
    """Checks if a session has expired and rotates the conversation when needed.

    TTL only applies to group sessions (not DMs). This class encapsulates the
    TTL detection, archiving, rotation, and notification logic.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        conversation_archiver: Any | None,
        session_ttl_minutes: int,
        lifecycle_config: Any | None,
        logger: logging.Logger,
    ) -> None:
        """Initialize the TTL checker.

        Args:
            session_manager: Session tracking.
            conversation_archiver: Optional archiver for expired conversations.
            session_ttl_minutes: Auto-reset conversation after N minutes of
                inactivity. 0 disables TTL checking.
            lifecycle_config: LifecycleConfig instance for notification flags.
            logger: Logger instance.
        """
        self._session_manager = session_manager
        self._conversation_archiver = conversation_archiver
        self._session_ttl_minutes = session_ttl_minutes
        self._lifecycle_config = lifecycle_config
        self._logger = logger

    @staticmethod
    def is_group_session(messages: list[Message] | None) -> bool:
        """Determine if the current session is a group chat (not a DM).

        Checks message metadata for platform-specific group indicators:
        - Telegram: ``chat_type`` is not ``"private"``
        - Discord: ``guild_id`` is not None
        """
        if not messages:
            return False
        for msg in messages:
            meta = msg.metadata or {}
            # Discord: guild_id present means server (group) message
            if meta.get("guild_id") is not None:
                return True
            # Telegram: chat_type "group" or "supergroup"
            chat_type = meta.get("chat_type")
            if chat_type and chat_type != "private":
                return True
        return False

    async def check(
        self,
        session_key: str,
        thread_id: str,
        channel: ChannelAdapter | None,
        messages: list[Message] | None = None,
        agent_runner: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> str | None:
        """Check if the session TTL has expired and rotate the conversation if so.

        TTL only applies to group sessions (not DMs). A session is considered
        a group session if any message has ``guild_id`` (Discord) or a
        ``chat_type`` other than ``"private"`` (Telegram).

        When TTL triggers, the current conversation is archived (tagged
        "ttl_expired"), a fresh conversation is started, and an optional
        notification is sent to the user.

        Args:
            session_key: The session identifier.
            thread_id: The current thread identifier.
            channel: Channel adapter for sending notifications.
            messages: Optional message batch for group-session detection.
            agent_runner: Optional AgentRunner with checkpointer for archiving.
            logger: Optional logger override. Defaults to the instance logger.

        Returns:
            New thread_id if the conversation was rotated, None otherwise.
        """
        log = logger or self._logger

        if self._session_ttl_minutes <= 0:
            return None

        # TTL only applies to group sessions — skip for DMs
        if not self.is_group_session(messages):
            return None

        if not self._session_manager.is_session_expired(
            session_key, self._session_ttl_minutes
        ):
            return None

        # Retrieve current conversation metadata for archiving
        old_state = self._session_manager.get_state(session_key)
        old_conv_id = old_state.conversation_id if old_state else "unknown"

        # Archive the expired conversation (best-effort)
        if self._conversation_archiver and agent_runner and getattr(
            agent_runner, "checkpointer", None
        ):
            try:
                await self._conversation_archiver.archive(
                    checkpointer=agent_runner.checkpointer,
                    thread_id=thread_id,
                    session_key=session_key,
                    conversation_id=old_conv_id,
                    tags=["ttl_expired"],
                )
            except Exception as e:
                log.warning(f"Failed to archive TTL-expired conversation: {e}")

        # Rotate to a fresh conversation
        self._session_manager.new_conversation(session_key)
        new_thread_id = self._session_manager.get_thread_id(session_key)

        # Notify user if channel is available and notifications are enabled
        notify = getattr(self._lifecycle_config, "notify_session_ttl", True)
        if channel and notify:
            try:
                await channel.send_message(
                    session_key,
                    "Session expired after inactivity — starting fresh conversation.",
                )
            except Exception as e:
                log.debug(f"Failed to send TTL notification for {session_key}: {e}")

        log.info(f"Session TTL expired for {session_key}, conversation rotated")
        return new_thread_id
