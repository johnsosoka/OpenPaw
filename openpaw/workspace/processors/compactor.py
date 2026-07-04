"""Auto-compaction and context-overflow recovery logic."""

import logging
from datetime import UTC, datetime
from typing import Any

from openpaw.channels.base import ChannelAdapter
from openpaw.core.config.models import AutoCompactConfig
from openpaw.core.prompts.commands import (
    AUTO_COMPACT_TEMPLATE,
    FLUSH_NOOP_MARKER,
    FLUSH_NOTE_TEMPLATE,
    FLUSH_PROMPT_TEMPLATE,
    SUMMARIZE_PROMPT,
)
from openpaw.core.utils import is_context_overflow_error
from openpaw.runtime.session.manager import SessionManager


async def run_flush_turn(
    agent_runner: Any,
    thread_id: str,
    logger: logging.Logger,
) -> str | None:
    """Give the agent one turn to persist working context before compaction.

    Injects a flush instruction into the conversation that is about to be
    compacted. The agent writes anything it must not lose (task state,
    decisions, gathered facts, open threads) to a workspace file, or replies
    with a no-op marker if nothing needs saving.

    Fail-open by design: a failing or timed-out flush turn never blocks
    compaction — the error is logged and compaction proceeds without a flush.

    Args:
        agent_runner: Agent runner used for the flush turn (same thread).
        thread_id: The thread that is about to be compacted.
        logger: Logger for the fail-open warning path.

    Returns:
        The workspace-relative flush file path if the agent saved context,
        None if nothing was saved or the flush turn failed.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    flush_path = f"memory/compact-flush-{timestamp}.md"
    try:
        reply = await agent_runner.run(
            message=FLUSH_PROMPT_TEMPLATE.format(flush_path=flush_path),
            thread_id=thread_id,
        )
        if reply and FLUSH_NOOP_MARKER in reply:
            logger.debug(f"Pre-compact flush: nothing to save for {thread_id}")
            return None
        logger.info(f"Pre-compact flush saved to {flush_path} for {thread_id}")
        return flush_path
    except Exception as e:
        logger.warning(
            f"Pre-compact flush turn failed for {thread_id}, "
            f"proceeding to compact: {e}"
        )
        return None


class AutoCompactor:
    """Handles preventive auto-compaction (pre-run) and emergency context-overflow recovery.

    Preventive compaction runs before agent invocation when context utilization
    exceeds the configured threshold. Emergency recovery runs after a context
    overflow error to force-rotate the conversation.
    """

    def __init__(
        self,
        session_manager: SessionManager,
        conversation_archiver: Any | None,
        auto_compact_config: AutoCompactConfig | None,
        lifecycle_config: Any | None,
        logger: logging.Logger,
    ) -> None:
        """Initialize the compactor.

        Args:
            session_manager: Session tracking.
            conversation_archiver: Archiver for conversation exports.
            auto_compact_config: Configuration for preventive compaction.
            lifecycle_config: LifecycleConfig for notification flags.
            logger: Logger instance.
        """
        self._session_manager = session_manager
        self._conversation_archiver = conversation_archiver
        self._auto_compact_config = auto_compact_config
        self._lifecycle_config = lifecycle_config
        self._logger = logger

    async def check_compact(
        self,
        session_key: str,
        thread_id: str,
        channel: ChannelAdapter | None,
        agent_runner: Any,
    ) -> str | None:
        """Check if auto-compact should trigger and perform it if needed.

        Args:
            session_key: The session identifier.
            thread_id: The current thread identifier.
            channel: Channel adapter for sending notifications.
            agent_runner: The agent runner instance for context info and agent runs.

        Returns:
            New thread_id if compaction occurred, None otherwise.
        """
        if not self._auto_compact_config or not self._auto_compact_config.enabled:
            return None
        if not self._conversation_archiver:
            return None

        try:
            context_info = await agent_runner.get_context_info(thread_id)
            utilization = context_info.get("utilization", 0.0)

            if utilization < self._auto_compact_config.trigger:
                return None

            self._logger.info(
                f"Auto-compact triggered: {utilization:.1%} utilization "
                f"(threshold: {self._auto_compact_config.trigger:.0%}) "
                f"for session {session_key}"
            )

            # Flush turn: let the agent save durable context before it is lost
            flush_path: str | None = None
            if self._auto_compact_config.flush:
                flush_path = await run_flush_turn(agent_runner, thread_id, self._logger)

            # Parse conversation_id from thread_id (format: "{session_key}:{conversation_id}")
            # session_key contains one colon (e.g., "telegram:123"), so split from the right
            parts = thread_id.rsplit(":", 1)
            conversation_id = parts[-1] if len(parts) == 2 else thread_id

            # Archive the current conversation (includes the flush exchange)
            await self._conversation_archiver.archive(
                checkpointer=agent_runner.checkpointer,
                thread_id=thread_id,
                session_key=session_key,
                conversation_id=conversation_id,
                tags=["auto-compact"],
            )

            # Generate summary using agent
            summary = await agent_runner.run(
                message=SUMMARIZE_PROMPT,
                thread_id=thread_id,
            )

            # Rotate to new conversation
            new_conversation_id = self._session_manager.new_conversation(session_key)
            new_thread_id = f"{session_key}:{new_conversation_id}"

            # Inject summary into new thread
            summary_message = AUTO_COMPACT_TEMPLATE.format(summary=summary)
            if flush_path:
                summary_message += FLUSH_NOTE_TEMPLATE.format(flush_path=flush_path)
            await agent_runner.run(
                message=summary_message,
                thread_id=new_thread_id,
            )

            # Notify user if configured
            if channel:
                msg_count = context_info.get("message_count", 0)
                approx_tokens = context_info.get("approximate_tokens", 0)
                await channel.send_message(
                    session_key,
                    f"Conversation auto-compacted ({msg_count} messages, ~{approx_tokens:,} tokens). "
                    f"Summary preserved in new conversation.",
                )

            self._logger.info(
                f"Auto-compact complete: {conversation_id} -> {new_conversation_id} "
                f"({context_info.get('message_count', 0)} messages, "
                f"~{context_info.get('approximate_tokens', 0):,} tokens)"
            )

            return new_thread_id

        except Exception as e:
            self._logger.error(f"Auto-compact failed for {session_key}: {e}", exc_info=True)
            return None

    async def recover_overflow(
        self,
        session_key: str,
        thread_id: str,
        channel: ChannelAdapter | None,
        agent_runner: Any,
    ) -> str | None:
        """Recover from a context window overflow by force-rotating the conversation.

        Unlike check_compact (preventive, pre-run), this is an emergency
        recovery triggered after a context overflow error. It always rotates,
        regardless of auto_compact config, because the alternative is a
        permanently stuck workspace.

        Args:
            session_key: The session identifier.
            thread_id: The current (overflowed) thread ID.
            channel: Channel adapter for sending notifications.
            agent_runner: The agent runner instance.

        Returns:
            New thread_id if recovery succeeded, None on failure.
        """
        self._logger.warning(
            f"Context overflow detected for {session_key}, "
            f"force-rotating conversation"
        )

        try:
            # Best-effort archive of the overflowed conversation
            if self._conversation_archiver and getattr(agent_runner, "checkpointer", None):
                try:
                    parts = thread_id.rsplit(":", 1)
                    conversation_id = parts[-1] if len(parts) == 2 else thread_id
                    await self._conversation_archiver.archive(
                        checkpointer=agent_runner.checkpointer,
                        thread_id=thread_id,
                        session_key=session_key,
                        conversation_id=conversation_id,
                        tags=["context_overflow"],
                    )
                except Exception as archive_err:
                    self._logger.warning(
                        f"Failed to archive overflowed conversation: {archive_err}"
                    )

            # Rotate to fresh conversation
            self._session_manager.new_conversation(session_key)
            new_thread_id = self._session_manager.get_thread_id(session_key)

            # Notify user
            if channel:
                try:
                    notify = getattr(
                        self._lifecycle_config, "notify_auto_compact", True
                    )
                    if notify:
                        await channel.send_message(
                            session_key,
                            "The conversation grew too long and has been archived. "
                            "Starting a fresh conversation.",
                        )
                except Exception as e:
                    self._logger.debug(
                        f"Failed to send overflow recovery notification: {e}"
                    )

            self._logger.info(
                f"Context overflow recovery: rotated {thread_id} -> {new_thread_id}"
            )
            return new_thread_id

        except Exception as e:
            self._logger.error(
                f"Context overflow recovery failed for {session_key}: {e}",
                exc_info=True,
            )
            return None

    def is_context_overflow(self, error: Exception) -> bool:
        """Check if an exception is a context window overflow error.

        Args:
            error: The exception to check.

        Returns:
            True if the error indicates a context window overflow.
        """
        return is_context_overflow_error(error)
