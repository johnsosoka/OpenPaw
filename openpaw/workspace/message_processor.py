"""Message processing logic for WorkspaceRunner."""

import logging
import time
from collections.abc import Callable
from typing import Any

from openpaw.agent.harness import AgentHarness
from openpaw.agent.middleware import (
    ApprovalRequiredError,
    InterruptSignalError,
)
from openpaw.builtins.loader import BuiltinLoader
from openpaw.builtins.tools.cron.scheduler_bridge import _add_to_live_scheduler
from openpaw.channels.base import ChannelAdapter
from openpaw.core.prompts.system_events import (
    COLLECT_USER_NOTIFICATION,
    FOLLOWUP_TEMPLATE,
    INTERRUPT_USER_NOTIFICATION,
    TOOL_DENIED_TEMPLATE,
)
from openpaw.core.utils import is_context_overflow_error, resolve_user_name, sanitize_error_for_user
from openpaw.model.message import Message, MessageDirection
from openpaw.runtime.approval import ApprovalGateManager
from openpaw.runtime.queue.lane import QueueMode
from openpaw.runtime.queue.manager import QueueManager
from openpaw.runtime.session.manager import SessionManager


class MessageProcessor:
    """Handles message processing with queue awareness, approval, and followup support."""

    def __init__(
        self,
        agent_runner: AgentHarness,
        session_manager: SessionManager,
        queue_manager: QueueManager,
        builtin_loader: BuiltinLoader,
        queue_middleware: Any,
        approval_middleware: Any,
        approval_manager: ApprovalGateManager | None,
        workspace_name: str,
        token_logger: Any,
        logger: logging.Logger,
        conversation_archiver: Any = None,
        auto_compact_config: Any = None,
        user_aliases: dict[int, str] | None = None,
        session_ttl_minutes: int = 0,
        lifecycle_config: Any = None,
        status_reminder_middleware: Any = None,
        status_update_middleware: Any = None,
        learning_recorder: Callable[[str, str], None] | None = None,
    ):
        """Initialize message processor.

        Args:
            agent_runner: The agent runner instance.
            session_manager: Session tracking.
            queue_manager: Queue management.
            builtin_loader: Builtin tool/processor loader.
            queue_middleware: Queue-aware middleware instance.
            approval_middleware: Approval middleware instance.
            approval_manager: Optional approval gate manager.
            workspace_name: Name of the workspace.
            token_logger: Token usage logger.
            logger: Logger instance.
            conversation_archiver: ConversationArchiver instance.
            auto_compact_config: AutoCompactConfig instance.
            user_aliases: Optional mapping of user IDs to display names.
            session_ttl_minutes: Auto-reset conversation after N minutes of
                inactivity. 0 disables TTL checking.
            lifecycle_config: LifecycleConfig instance for notification flags.
            status_reminder_middleware: Optional StatusReminderMiddleware instance.
                When provided, its reset() is called alongside queue/approval resets.
            status_update_middleware: Optional StatusUpdateMiddleware instance.
                When provided, its set_context() is called before agent runs and
                reset() is called in the finally block.
            learning_recorder: Optional fire-and-forget callable invoked with
                (user_content, response) after each successful non-system
                agent run (PRD-001 F2.1). Must never raise.
        """
        self._agent_runner = agent_runner
        self._session_manager = session_manager
        self._queue_manager = queue_manager
        self._builtin_loader = builtin_loader
        self._queue_middleware = queue_middleware
        self._approval_middleware = approval_middleware
        self._approval_manager = approval_manager
        self._workspace_name = workspace_name
        self._token_logger = token_logger
        self._logger = logger
        self._conversation_archiver = conversation_archiver
        self._auto_compact_config = auto_compact_config
        self._user_aliases = user_aliases or {}
        self._session_ttl_minutes = session_ttl_minutes
        self._lifecycle_config = lifecycle_config
        self._status_reminder_middleware = status_reminder_middleware
        self._status_update_middleware = status_update_middleware
        self._learning_recorder = learning_recorder

    def set_learning_recorder(
        self, recorder: Callable[[str, str], None] | None
    ) -> None:
        """Wire the learning-loop run recorder (set post-construction).

        Args:
            recorder: Callable invoked with (user_content, response) after
                each successful non-system agent run, or None to disable.
        """
        self._learning_recorder = recorder

    def update_agent_runner(self, runner: "AgentHarness") -> None:
        """Update the agent harness instance.

        Used when the agent is rebuilt (e.g., after removing broken tools).

        Args:
            runner: The new AgentHarness instance.
        """
        self._agent_runner = runner

    def _resolve_user_name(self, message: Message) -> str | None:
        """Resolve display name for a message's user."""
        return resolve_user_name(message.user_id, message.metadata, self._user_aliases)

    def _build_combined_content(self, messages: list[Message]) -> str:
        """Build combined content from messages with optional user name prefixes.

        Args:
            messages: List of messages to combine.

        Returns:
            Combined message content with optional [Name] prefixes.
        """
        lines = []
        for msg in messages:
            name = self._resolve_user_name(msg)
            if name:
                lines.append(f"[{name}]: {msg.content}")
            else:
                lines.append(msg.content)
        return "\n".join(lines)

    def _build_combined_content_from_tuples(self, tuples: list[tuple[str, Any]]) -> str:
        """Build combined content from (channel_name, msg) tuples.

        Args:
            tuples: List of (channel_name, msg) tuples where msg is Message or str.

        Returns:
            Combined message content with optional [Name] prefixes.
        """
        lines = []
        for _channel_name, msg in tuples:
            if hasattr(msg, 'content'):
                # It's a Message object
                name = self._resolve_user_name(msg)
                if name:
                    lines.append(f"[{name}]: {msg.content}")
                else:
                    lines.append(msg.content)
            else:
                # Raw string
                lines.append(str(msg))
        return "\n".join(lines)

    def _get_original_message_id(self, messages: list[Message]) -> str | None:
        """Find the first non-system inbound message ID for reaction targeting.

        Reactions are applied to the user's original message. System events
        (cron, heartbeat) do not have a user message to react to.

        Args:
            messages: The message batch to inspect.

        Returns:
            The original inbound message ID, or None if no suitable message exists.
        """
        for msg in messages:
            if msg.direction == MessageDirection.INBOUND and msg.user_id != "system":
                return msg.id
        return None

    async def _add_reaction(
        self,
        channel: ChannelAdapter | None,
        session_key: str,
        message_id: str | None,
        emoji: str,
    ) -> None:
        """Best-effort add a reaction to a message."""
        if not channel or not message_id:
            return
        try:
            ok = await channel.add_reaction(session_key, message_id, emoji)
            if ok:
                self._logger.info(
                    "Added reaction %s to message %s", emoji, message_id
                )
            else:
                self._logger.info(
                    "Failed to add reaction %s to message %s (channel returned False)",
                    emoji, message_id,
                )
        except Exception:
            self._logger.info(
                "Failed to add reaction %s to message %s", emoji, message_id,
                exc_info=True,
            )

    async def _remove_reaction(
        self,
        channel: ChannelAdapter | None,
        session_key: str,
        message_id: str | None,
        emoji: str,
    ) -> None:
        """Best-effort remove a reaction from a message."""
        if not channel or not message_id:
            return
        try:
            ok = await channel.remove_reaction(session_key, message_id, emoji)
            if ok:
                self._logger.info(
                    "Removed reaction %s from message %s", emoji, message_id,
                )
            else:
                self._logger.info(
                    "Failed to remove reaction %s from message %s (channel returned False)",
                    emoji, message_id,
                )
        except Exception:
            self._logger.info(
                "Failed to remove reaction %s from message %s", emoji, message_id,
                exc_info=True,
            )

    async def _replace_reaction(
        self,
        channel: ChannelAdapter | None,
        session_key: str,
        message_id: str | None,
        old_emoji: str,
        new_emoji: str,
    ) -> None:
        """Best-effort replace a reaction on a message.

        Uses the channel's replace_reaction if available (avoids double API
        calls on Telegram). Falls back to remove + add for other platforms.
        """
        if not channel or not message_id:
            return
        try:
            ok = await channel.replace_reaction(
                session_key, message_id, old_emoji, new_emoji,
            )
            if ok:
                self._logger.info(
                    "Replaced reaction %s with %s on message %s",
                    old_emoji, new_emoji, message_id,
                )
            else:
                self._logger.info(
                    "Failed to replace reaction %s with %s on message %s (channel returned False)",
                    old_emoji, new_emoji, message_id,
                )
        except Exception:
            self._logger.info(
                "Failed to replace reaction %s with %s on message %s",
                old_emoji, new_emoji, message_id,
                exc_info=True,
            )

    def _reactions_enabled(self) -> bool:
        """Check whether reactions are enabled in the status update config."""
        if not self._status_update_middleware:
            return False
        config = getattr(self._status_update_middleware, "_config", None)
        if not config:
            return False
        return getattr(config, "reactions", False)

    def _typing_enabled(self) -> bool:
        """Check whether typing indicator is enabled in the status update config."""
        if not self._status_update_middleware:
            return False
        config = getattr(self._status_update_middleware, "_config", None)
        if not config:
            return False
        return getattr(config, "typing_indicator", False)

    async def process_messages(
        self,
        session_key: str,
        messages: list[Message],
        channel: ChannelAdapter | None,
    ) -> None:
        """Process collected messages for a session with followup, steer, and interrupt support.

        Args:
            session_key: The session identifier.
            messages: List of messages to process.
            channel: Channel adapter for sending responses.
        """
        combined_content = self._build_combined_content(messages)
        thread_id = self._session_manager.get_thread_id(session_key)
        followup_depth = 0
        max_followup_depth = 5
        is_system_batch = self._is_system_event_batch(messages)
        self._logger.info(
            f"MessageProcessor entering for session {session_key} "
            f"({len(messages)} message(s), system_batch={is_system_batch})"
        )

        # Check session TTL first — may rotate conversation before any further checks
        # TTL only applies to group sessions (not DMs)
        ttl_thread_id = await self._check_session_ttl(session_key, thread_id, channel, messages)
        if ttl_thread_id:
            thread_id = ttl_thread_id

        # Check if auto-compact should trigger
        new_thread_id = await self._check_auto_compact(session_key, thread_id, channel)
        if new_thread_id:
            thread_id = new_thread_id

        original_message_id = self._get_original_message_id(messages)
        self._logger.info(
            "Reaction diagnostics: enabled=%s, original_message_id=%s",
            self._reactions_enabled(),
            original_message_id,
        )

        # Send typing indicator
        if self._typing_enabled() and channel:
            try:
                await channel.send_typing(session_key)
            except Exception:
                self._logger.debug("Typing indicator failed", exc_info=True)

        # Add start reaction
        if self._reactions_enabled() and original_message_id:
            await self._add_reaction(channel, session_key, original_message_id, "👀")

        run_count = 0
        _run_outcome = "success"
        while True:
            run_count += 1
            # Capture steer state before finally block resets it
            steered = False
            steer_messages = None

            try:
                # Set queue awareness on middleware before each run
                session_mode = await self._queue_manager.get_session_mode(session_key)
                self._queue_middleware.set_queue_awareness(
                    queue_manager=self._queue_manager,
                    session_key=session_key,
                    queue_mode=session_mode,
                )

                # Set approval context on middleware before each run
                if self._approval_manager:
                    self._approval_middleware.set_context(
                        manager=self._approval_manager,
                        session_key=session_key,
                        thread_id=thread_id,
                    )

                # Set session context for send_message tool
                if channel:
                    self._connect_send_message_tool(channel, session_key)

                # Set context for status update middleware
                if self._status_update_middleware:
                    self._status_update_middleware.set_context(
                        channel, session_key, run_count, is_system_batch
                    )

                # Set followup chain depth
                followup_tool = self._builtin_loader.get_tool_instance("followup")
                if followup_tool:
                    followup_tool.set_chain_depth(followup_depth)

                content_preview = combined_content[:100].replace("\n", " ")
                self._logger.info(
                    f"Processing message for {session_key} "
                    f"(depth={followup_depth}): {content_preview}..."
                )
                run_start = time.monotonic()

                response = await self._agent_runner.run(
                    message=combined_content,
                    thread_id=thread_id,
                )

                # Capture steer state BEFORE reset
                steered = self._queue_middleware.was_steered
                steer_messages = self._queue_middleware.pending_steer_message

                # Post-run steer/interrupt check
                if not steered and session_mode in (QueueMode.STEER, QueueMode.INTERRUPT):
                    has_post_run_pending = await self._queue_manager.peek_pending(session_key)
                    if has_post_run_pending:
                        pending = await self._queue_manager.consume_pending(session_key)
                        if pending:
                            if session_mode == QueueMode.STEER:
                                steered = True
                                steer_messages = pending
                                self._logger.info(
                                    f"Post-run steer: {len(pending)} pending message(s) "
                                    f"detected after agent run"
                                )
                            elif session_mode == QueueMode.INTERRUPT:
                                self._logger.info(
                                    f"Post-run interrupt: {len(pending)} pending message(s) "
                                    f"detected after agent run"
                                )
                                steered = True
                                steer_messages = pending

                # Collect mode: notify user if messages were batched while running
                if (
                    not steered
                    and session_mode == QueueMode.COLLECT
                    and self._status_update_middleware
                    and self._status_update_middleware._config.collect_queued
                ):
                    has_pending = await self._queue_manager.peek_pending(session_key)
                    if has_pending:
                        await self._status_update_middleware.send_forced_status(
                            COLLECT_USER_NOTIFICATION
                        )

                # Log token usage and processing summary
                run_duration_ms = (time.monotonic() - run_start) * 1000
                metrics = self._agent_runner.last_metrics
                if metrics:
                    self._token_logger.log(
                        metrics=metrics,
                        workspace=self._workspace_name,
                        invocation_type="user",
                        session_key=session_key,
                    )
                    tools_used = self._agent_runner.last_tools_used
                    tools_summary = f", tools: {tools_used}" if tools_used else ""
                    self._logger.info(
                        f"Agent run complete in {run_duration_ms:.0f}ms — "
                        f"tokens: {metrics.input_tokens}in/{metrics.output_tokens}out "
                        f"({metrics.llm_calls} LLM calls{tools_summary})"
                    )
                else:
                    self._logger.info(
                        f"Agent run complete in {run_duration_ms:.0f}ms (no metrics)"
                    )

                # Send response if not steered
                if not steered and channel:
                    if is_system_batch:
                        # Suppress-by-default for [SYSTEM] events (cron/heartbeat/sub-agent/
                        # dynamic-task injections). The agent surfaces anything user-facing via
                        # send_message DURING the run. The terminal text is intentionally NOT
                        # channel-delivered, but it IS still recorded in conversation history by
                        # the checkpointer inside agent_runner.run() — so the agent stays aware of
                        # what it did. This makes user-bombardment structurally impossible.
                        ack_tool = self._builtin_loader.get_tool_instance("acknowledge")
                        ack = ack_tool.get_pending_ack() if ack_tool else None
                        ack_note = f" (agent note: {ack.reason})" if ack else ""
                        self._logger.info(
                            f"System event for {session_key}: terminal text suppressed "
                            f"({len(response or '')} chars){ack_note}"
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

                # Learning loop hook (PRD-001 F2.1): count successful
                # non-system agent invocations. Fire-and-forget — the
                # recorder owns its own error containment.
                if self._learning_recorder and not is_system_batch:
                    self._learning_recorder(combined_content, response or "")

            except ApprovalRequiredError as e:
                # Log partial metrics if available
                if self._agent_runner.last_metrics:
                    self._token_logger.log(
                        metrics=self._agent_runner.last_metrics,
                        workspace=self._workspace_name,
                        invocation_type="user",
                        session_key=session_key,
                    )

                # Send approval request to user
                if channel and self._approval_manager:
                    tool_config = self._approval_manager.get_tool_config(e.tool_name)
                    show_args = tool_config.show_args if tool_config else True
                    await channel.send_approval_request(
                        session_key=session_key,
                        approval_id=e.approval_id,
                        tool_name=e.tool_name,
                        tool_args=e.tool_args,
                        show_args=show_args,
                    )

                    # Wait for user approval
                    approved = await self._approval_manager.wait_for_resolution(
                        e.approval_id
                    )

                    if approved:
                        self._logger.info(f"Tool {e.tool_name} approved, resuming")
                        # Fix orphaned tool_calls before re-running
                        try:
                            await self._agent_runner.resolve_orphaned_tool_calls(
                                thread_id,
                                responses={e.tool_call_id: f"Tool '{e.tool_name}' was approved. Please call it again."},
                            )
                        except Exception as resolve_err:
                            self._logger.error(f"Failed to resolve orphaned tool calls: {resolve_err}", exc_info=True)
                        continue  # Re-enter loop with same message
                    else:
                        self._logger.info(f"Tool {e.tool_name} denied")
                        # Fix orphaned tool_calls before re-running
                        try:
                            await self._agent_runner.resolve_orphaned_tool_calls(
                                thread_id,
                                responses={e.tool_call_id: f"Tool '{e.tool_name}' was denied by user."},
                            )
                        except Exception as resolve_err:
                            self._logger.error(f"Failed to resolve orphaned tool calls: {resolve_err}", exc_info=True)
                        await channel.send_message(
                            session_key,
                            f"Tool '{e.tool_name}' was denied. "
                            f"The agent will be informed.",
                        )
                        combined_content = TOOL_DENIED_TEMPLATE.format(tool_name=e.tool_name)
                        continue  # Re-enter with denial message

                # No channel available, deny by default
                _run_outcome = "failure"
                break

            except InterruptSignalError as e:
                # Log partial metrics if available
                if self._agent_runner.last_metrics:
                    self._token_logger.log(
                        metrics=self._agent_runner.last_metrics,
                        workspace=self._workspace_name,
                        invocation_type="user",
                        session_key=session_key,
                    )

                # Notify user that run was interrupted.
                # Skip direct send if the status update middleware already handled it.
                should_notify = True
                if self._status_update_middleware:
                    config = self._status_update_middleware._config
                    if config.enabled and config.run_interrupted:
                        should_notify = False

                if channel and should_notify:
                    await channel.send_message(session_key, INTERRUPT_USER_NOTIFICATION)

                # Use the pending messages as the new input
                pending_msgs = e.pending_messages
                if pending_msgs:
                    combined_content = self._build_combined_content_from_tuples(pending_msgs)

                followup_depth = 0  # Reset followup depth on interrupt
                continue  # Re-enter loop with new message

            except Exception as e:
                self._logger.error(f"Error processing messages for {session_key}: {e}", exc_info=True)

                if is_context_overflow_error(e):
                    new_tid = await self._recover_context_overflow(
                        session_key, thread_id, channel
                    )
                    if new_tid:
                        thread_id = new_tid
                        combined_content = (
                            "[SYSTEM] The previous conversation was too long and has been archived. "
                            "A fresh conversation has started. Please continue from where you left off."
                        )
                        continue

                if channel:
                    await channel.send_message(session_key, sanitize_error_for_user(e))
                _run_outcome = "failure"
                break  # Don't continue followup chain on error

            finally:
                self._disconnect_send_message_tool()
                self._queue_middleware.reset()
                if self._approval_manager:
                    self._approval_middleware.reset()
                if self._status_reminder_middleware:
                    self._status_reminder_middleware.reset()
                if self._status_update_middleware:
                    await self._status_update_middleware.delete_status()
                    self._status_update_middleware.reset()

            # Check steer (captured before reset)
            if steered and steer_messages:
                combined_content = self._build_combined_content_from_tuples(steer_messages)
                followup_depth = 0  # Reset followup depth on steer
                self._logger.info(f"Steer redirect: processing {len(steer_messages)} new message(s)")
                continue

            # Check for followup request
            if followup_tool:
                followup = followup_tool.get_pending_followup()
                if followup and followup.delay_seconds == 0:
                    followup_depth += 1
                    if followup_depth > max_followup_depth:
                        self._logger.warning(
                            f"Followup chain depth exceeded ({max_followup_depth}) "
                            f"for session {session_key}"
                        )
                        break

                    self._logger.info(
                        f"Processing immediate followup (depth={followup_depth}): "
                        f"{followup.prompt[:100]}"
                    )
                    combined_content = FOLLOWUP_TEMPLATE.format(
                        depth=followup_depth, prompt=followup.prompt
                    )
                    continue
                elif followup and followup.delay_seconds > 0:
                    self._logger.info(
                        f"Scheduling delayed followup ({followup.delay_seconds}s): "
                        f"{followup.prompt[:100]}"
                    )
                    self._schedule_delayed_followup(followup, session_key)

            break  # No followup or delayed followup scheduled, exit loop

        # Final reaction lifecycle
        if self._reactions_enabled() and original_message_id:
            if _run_outcome == "success":
                await self._replace_reaction(channel, session_key, original_message_id, "👀", "👍")
            elif _run_outcome == "failure":
                await self._replace_reaction(channel, session_key, original_message_id, "👀", "👎")

        # Reset followup state after loop exits
        followup_tool = self._builtin_loader.get_tool_instance("followup")
        if followup_tool:
            followup_tool.reset()

        # Reset acknowledge state after loop exits
        ack_tool = self._builtin_loader.get_tool_instance("acknowledge")
        if ack_tool:
            ack_tool.reset()

    @staticmethod
    def _is_system_event_batch(messages: list[Message]) -> bool:
        """Check if all messages in the batch are system events.

        System events have user_id == "system" and are injected by the
        framework (cron results, heartbeat injections, sub-agent completions).
        For system-only batches, the terminal agent reply is suppressed by default;
        for mixed batches (any real user message present), delivery proceeds normally.

        Args:
            messages: The message batch to inspect.

        Returns:
            True only if the list is non-empty and every message has user_id "system".
        """
        if not messages:
            return False
        return all(msg.user_id == "system" for msg in messages)

    @staticmethod
    def _is_group_session(messages: list[Message] | None) -> bool:
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

    async def _check_session_ttl(
        self,
        session_key: str,
        thread_id: str,
        channel: ChannelAdapter | None,
        messages: list[Message] | None = None,
    ) -> str | None:
        """Check if the session TTL has expired and rotate the conversation if so.

        TTL only applies to group sessions (not DMs). A session is considered
        a group session if any message has ``guild_id`` (Discord) or a
        ``chat_type`` other than ``"private"`` (Telegram).

        When TTL triggers, the current conversation is archived (tagged
        "ttl_expired"), a fresh conversation is started, and an optional
        notification is sent to the user.

        Returns:
            New thread_id if the conversation was rotated, None otherwise.
        """
        if self._session_ttl_minutes <= 0:
            return None

        # TTL only applies to group sessions — skip for DMs
        if not self._is_group_session(messages):
            return None

        if not self._session_manager.is_session_expired(session_key, self._session_ttl_minutes):
            return None

        # Retrieve current conversation metadata for archiving
        old_state = self._session_manager.get_state(session_key)
        old_conv_id = old_state.conversation_id if old_state else "unknown"

        # Archive the expired conversation (best-effort)
        if self._conversation_archiver and self._agent_runner.checkpointer:
            try:
                await self._conversation_archiver.archive(
                    checkpointer=self._agent_runner.checkpointer,
                    thread_id=thread_id,
                    session_key=session_key,
                    conversation_id=old_conv_id,
                    tags=["ttl_expired"],
                )
            except Exception as e:
                self._logger.warning(f"Failed to archive TTL-expired conversation: {e}")

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
                self._logger.debug(f"Failed to send TTL notification for {session_key}: {e}")

        self._logger.info(f"Session TTL expired for {session_key}, conversation rotated")
        return new_thread_id

    async def _check_auto_compact(
        self,
        session_key: str,
        thread_id: str,
        channel: ChannelAdapter | None,
    ) -> str | None:
        """Check if auto-compact should trigger and perform it if needed.

        Returns:
            New thread_id if compaction occurred, None otherwise.
        """
        if not self._auto_compact_config or not self._auto_compact_config.enabled:
            return None
        if not self._conversation_archiver:
            return None

        try:
            context_info = await self._agent_runner.get_context_info(thread_id)
            utilization = context_info.get("utilization", 0.0)

            if utilization < self._auto_compact_config.trigger:
                return None

            self._logger.info(
                f"Auto-compact triggered: {utilization:.1%} utilization "
                f"(threshold: {self._auto_compact_config.trigger:.0%}) "
                f"for session {session_key}"
            )

            # Flush turn: let the agent save durable context before it is lost
            from openpaw.workspace.processors.compactor import run_flush_turn

            flush_path: str | None = None
            if getattr(self._auto_compact_config, "flush", True):
                flush_path = await run_flush_turn(
                    self._agent_runner, thread_id, self._logger
                )

            # Parse conversation_id from thread_id (format: "{session_key}:{conversation_id}")
            # session_key contains one colon (e.g., "telegram:123"), so split from the right
            parts = thread_id.rsplit(":", 1)
            conversation_id = parts[-1] if len(parts) == 2 else thread_id

            # Archive the current conversation (includes the flush exchange)
            await self._conversation_archiver.archive(
                checkpointer=self._agent_runner.checkpointer,
                thread_id=thread_id,
                session_key=session_key,
                conversation_id=conversation_id,
                tags=["auto-compact"],
            )

            # Generate summary using agent
            from openpaw.core.prompts.commands import SUMMARIZE_PROMPT
            summary = await self._agent_runner.run(
                message=SUMMARIZE_PROMPT,
                thread_id=thread_id,
            )

            # Rotate to new conversation
            new_conversation_id = self._session_manager.new_conversation(session_key)
            new_thread_id = f"{session_key}:{new_conversation_id}"

            # Inject summary into new thread
            from openpaw.core.prompts.commands import AUTO_COMPACT_TEMPLATE, FLUSH_NOTE_TEMPLATE
            summary_message = AUTO_COMPACT_TEMPLATE.format(summary=summary)
            if flush_path:
                summary_message += FLUSH_NOTE_TEMPLATE.format(flush_path=flush_path)
            await self._agent_runner.run(
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
                    f"Summary preserved in new conversation."
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

    async def _recover_context_overflow(
        self,
        session_key: str,
        thread_id: str,
        channel: ChannelAdapter | None,
    ) -> str | None:
        """Recover from a context window overflow by force-rotating the conversation.

        Unlike _check_auto_compact (preventive, pre-run), this is an emergency
        recovery triggered after a context overflow error. It always rotates,
        regardless of auto_compact config, because the alternative is a
        permanently stuck workspace.

        Best-effort: archives the old conversation if possible, rotates to
        a fresh thread, and notifies the user.

        Args:
            session_key: The session identifier.
            thread_id: The current (overflowed) thread ID.
            channel: Channel adapter for sending notifications.

        Returns:
            New thread_id if recovery succeeded, None on failure.
        """
        self._logger.warning(
            f"Context overflow detected for {session_key}, "
            f"force-rotating conversation"
        )

        try:
            # Best-effort archive of the overflowed conversation
            if self._conversation_archiver and self._agent_runner.checkpointer:
                try:
                    parts = thread_id.rsplit(":", 1)
                    conversation_id = parts[-1] if len(parts) == 2 else thread_id
                    await self._conversation_archiver.archive(
                        checkpointer=self._agent_runner.checkpointer,
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

    async def _send_pending_audio(self, channel: ChannelAdapter, session_key: str) -> None:
        """Check for and send any pending TTS audio."""
        if not hasattr(channel, "send_audio"):
            return

        try:
            from openpaw.builtins.tools._audio_context import clear_pending_audio, get_pending_audio

            audio_data = get_pending_audio()
            if audio_data:
                await channel.send_audio(session_key, audio_data, filename="response.mp3")
                clear_pending_audio()
                self._logger.info(f"Sent TTS audio to {session_key}")
        except ImportError:
            pass  # Audio context not available
        except Exception as e:
            self._logger.error(f"Failed to send TTS audio: {e}")

    def _schedule_delayed_followup(self, followup: Any, session_key: str) -> None:
        """Schedule a delayed followup via the cron system."""
        from datetime import UTC, datetime, timedelta

        cron_tool = self._builtin_loader.get_tool_instance("cron")
        if not cron_tool or not cron_tool.scheduler:
            self._logger.warning("Cannot schedule delayed followup: no cron tool/scheduler available")
            return

        if not cron_tool.default_chat_id:
            self._logger.warning("Cannot schedule delayed followup: cron tool has no default_chat_id")
            return

        run_at = datetime.now(UTC) + timedelta(seconds=followup.delay_seconds)
        from openpaw.stores.cron import create_once_task

        task = create_once_task(
            prompt=followup.prompt,
            run_at=run_at,
            channel=cron_tool.default_channel,
            chat_id=cron_tool.default_chat_id,
        )
        cron_tool.store.add_task(task)
        _add_to_live_scheduler(cron_tool.scheduler, task)
        self._logger.info(f"Delayed followup scheduled as cron task {task.id}")

    def _connect_send_message_tool(self, channel: Any, session_key: str) -> None:
        """Connect send_message tool to active session context."""
        try:
            send_message_tool = self._builtin_loader.get_tool_instance("send_message")
            if send_message_tool:
                send_message_tool.set_session_context(channel, session_key)
                self._logger.debug(f"Connected send_message tool for session: {session_key}")
        except Exception as e:
            self._logger.debug(f"Failed to connect send_message tool: {e}")

    def _disconnect_send_message_tool(self) -> None:
        """Disconnect send_message tool from session context."""
        try:
            send_message_tool = self._builtin_loader.get_tool_instance("send_message")
            if send_message_tool:
                send_message_tool.clear_session_context()
                self._logger.debug("Disconnected send_message tool")
        except Exception as e:
            self._logger.debug(f"Failed to disconnect send_message tool: {e}")
