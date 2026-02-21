"""Message processing logic for WorkspaceRunner."""

import logging
from typing import Any

from openpaw.agent import AgentRunner
from openpaw.agent.middleware import (
    ApprovalRequiredError,
    InterruptSignalError,
)
from openpaw.builtins.loader import BuiltinLoader
from openpaw.channels.base import ChannelAdapter
from openpaw.model.message import Message
from openpaw.core.prompts.system_events import (
    FOLLOWUP_TEMPLATE,
    INTERRUPT_NOTIFICATION,
    TOOL_DENIED_TEMPLATE,
)
from openpaw.runtime.queue.lane import QueueMode
from openpaw.runtime.queue.manager import QueueManager
from openpaw.runtime.session.manager import SessionManager
from openpaw.stores.approval import ApprovalGateManager


class MessageProcessor:
    """Handles message processing with queue awareness, approval, and followup support."""

    def __init__(
        self,
        agent_runner: AgentRunner,
        session_manager: SessionManager,
        queue_manager: QueueManager,
        builtin_loader: BuiltinLoader,
        queue_middleware: Any,
        approval_middleware: Any,
        approval_manager: ApprovalGateManager | None,
        workspace_name: str,
        token_logger: Any,
        logger: logging.Logger,
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
        combined_content = "\n".join(m.content for m in messages)
        thread_id = self._session_manager.get_thread_id(session_key)
        followup_depth = 0
        max_followup_depth = 5

        while True:
            # Capture steer state before finally block resets it
            steered = False
            steer_messages = None

            try:
                # Set queue awareness on middleware before each run
                session_queue = await self._queue_manager._get_or_create_session(session_key)
                self._queue_middleware.set_queue_awareness(
                    queue_manager=self._queue_manager,
                    session_key=session_key,
                    queue_mode=session_queue.mode,
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

                # Set followup chain depth
                followup_tool = self._builtin_loader.get_tool_instance("followup")
                if followup_tool:
                    followup_tool.set_chain_depth(followup_depth)

                response = await self._agent_runner.run(
                    message=combined_content,
                    thread_id=thread_id,
                )

                # Capture steer state BEFORE reset
                steered = self._queue_middleware.was_steered
                steer_messages = self._queue_middleware.pending_steer_message

                # Post-run steer/interrupt check
                if not steered and session_queue.mode in (QueueMode.STEER, QueueMode.INTERRUPT):
                    has_post_run_pending = await self._queue_manager.peek_pending(session_key)
                    if has_post_run_pending:
                        pending = await self._queue_manager.consume_pending(session_key)
                        if pending:
                            if session_queue.mode == QueueMode.STEER:
                                steered = True
                                steer_messages = pending
                                self._logger.info(
                                    f"Post-run steer: {len(pending)} pending message(s) "
                                    f"detected after agent run"
                                )
                            elif session_queue.mode == QueueMode.INTERRUPT:
                                self._logger.info(
                                    f"Post-run interrupt: {len(pending)} pending message(s) "
                                    f"detected after agent run"
                                )
                                steered = True
                                steer_messages = pending

                # Log token usage
                if self._agent_runner.last_metrics:
                    self._token_logger.log(
                        metrics=self._agent_runner.last_metrics,
                        workspace=self._workspace_name,
                        invocation_type="user",
                        session_key=session_key,
                    )

                # Send response if not steered
                if not steered and channel:
                    if response and response.strip():
                        await channel.send_message(session_key, response)
                        self._session_manager.increment_message_count(session_key)
                        await self._send_pending_audio(channel, session_key)
                    else:
                        self._logger.warning(f"Agent produced empty response for {session_key}, sending fallback")
                        fallback = "I processed your message but my response was empty. Please try again."
                        await channel.send_message(session_key, fallback)

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
                        continue  # Re-enter loop with same message
                    else:
                        self._logger.info(f"Tool {e.tool_name} denied")
                        await channel.send_message(
                            session_key,
                            f"Tool '{e.tool_name}' was denied. "
                            f"The agent will be informed.",
                        )
                        combined_content = TOOL_DENIED_TEMPLATE.format(tool_name=e.tool_name)
                        continue  # Re-enter with denial message

                # No channel available, deny by default
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

                # Notify user that run was interrupted
                if channel:
                    await channel.send_message(session_key, INTERRUPT_NOTIFICATION)

                # Use the pending messages as the new input
                pending_msgs = e.pending_messages
                if pending_msgs:
                    new_contents = []
                    for _channel_name, msg in pending_msgs:
                        if hasattr(msg, 'content'):
                            new_contents.append(msg.content)
                        else:
                            new_contents.append(str(msg))
                    combined_content = "\n".join(new_contents)

                followup_depth = 0  # Reset followup depth on interrupt
                continue  # Re-enter loop with new message

            except Exception as e:
                self._logger.error(f"Error processing messages for {session_key}: {e}", exc_info=True)
                if channel:
                    await channel.send_message(session_key, f"Error: {e}")
                break  # Don't continue followup chain on error

            finally:
                self._disconnect_send_message_tool()
                self._queue_middleware.reset()
                if self._approval_manager:
                    self._approval_middleware.reset()

            # Check steer (captured before reset)
            if steered and steer_messages:
                new_contents = []
                for _channel_name, msg in steer_messages:
                    if hasattr(msg, 'content'):
                        new_contents.append(msg.content)
                    else:
                        new_contents.append(str(msg))
                combined_content = "\n".join(new_contents)
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

        # Reset followup state after loop exits
        followup_tool = self._builtin_loader.get_tool_instance("followup")
        if followup_tool:
            followup_tool.reset()

    async def _send_pending_audio(self, channel: ChannelAdapter, session_key: str) -> None:
        """Check for and send any pending TTS audio."""
        if not hasattr(channel, "send_audio"):
            return

        try:
            from openpaw.builtins.tools.elevenlabs_tts import ElevenLabsTTSTool

            audio_data = ElevenLabsTTSTool.get_any_pending_audio()
            if audio_data:
                await channel.send_audio(session_key, audio_data, filename="response.mp3")
                self._logger.info(f"Sent TTS audio to {session_key}")
        except ImportError:
            pass  # ElevenLabs not available
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
        cron_tool._add_to_live_scheduler(task)
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
