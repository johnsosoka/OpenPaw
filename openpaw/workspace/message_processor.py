"""Message processing logic for WorkspaceRunner."""

import logging
import time
from typing import Any

from openpaw.agent import AgentRunner
from openpaw.agent.middleware import (
    ApprovalRequiredError,
    InterruptSignalError,
)
from openpaw.builtins.loader import BuiltinLoader
from openpaw.channels.base import ChannelAdapter
from openpaw.model.message import Message
from openpaw.runtime.approval import ApprovalGateManager
from openpaw.runtime.queue.lane import QueueMode
from openpaw.runtime.queue.manager import QueueManager
from openpaw.runtime.session.manager import SessionManager
from openpaw.workspace.processors.approval_handler import ApprovalGateHandler
from openpaw.workspace.processors.combiner import ContentCombiner
from openpaw.workspace.processors.compactor import AutoCompactor
from openpaw.workspace.processors.error_handler import ErrorHandler
from openpaw.workspace.processors.followup_scheduler import FollowupScheduler
from openpaw.workspace.processors.interrupt_handler import InterruptHandler
from openpaw.workspace.processors.response_handler import ResponseHandler
from openpaw.workspace.processors.ttl_checker import SessionTTLChecker


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
        conversation_archiver: Any = None,
        auto_compact_config: Any = None,
        user_aliases: dict[int, str] | None = None,
        session_ttl_minutes: int = 0,
        lifecycle_config: Any = None,
        status_reminder_middleware: Any = None,
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

        # Extracted processors
        self._combiner = ContentCombiner(user_aliases=user_aliases)
        self._ttl_checker = SessionTTLChecker(
            session_manager=session_manager,
            conversation_archiver=conversation_archiver,
            session_ttl_minutes=session_ttl_minutes,
            lifecycle_config=lifecycle_config,
            logger=logger,
        )
        self._compactor = AutoCompactor(
            session_manager=session_manager,
            conversation_archiver=conversation_archiver,
            auto_compact_config=auto_compact_config,
            lifecycle_config=lifecycle_config,
            logger=logger,
        )
        self._response_handler = ResponseHandler(
            builtin_loader=builtin_loader,
            session_manager=session_manager,
            logger=logger,
        )

        # New handlers
        self._approval_handler = ApprovalGateHandler(
            approval_manager=approval_manager,
            token_logger=token_logger,
            workspace_name=workspace_name,
            logger=logger,
        )
        self._interrupt_handler = InterruptHandler(
            logger=logger,
            combiner=self._combiner,
        )
        self._error_handler = ErrorHandler(
            logger=logger,
            compactor=self._compactor,
        )
        self._followup_scheduler = FollowupScheduler(
            builtin_loader=builtin_loader,
            logger=logger,
        )

        # Retained direct dependencies (used by process_messages loop)
        self._conversation_archiver = conversation_archiver
        self._auto_compact_config = auto_compact_config
        self._lifecycle_config = lifecycle_config
        self._status_reminder_middleware = status_reminder_middleware

    def update_agent_runner(self, runner: "AgentRunner") -> None:
        """Update the agent runner instance.

        Used when the agent is rebuilt (e.g., after removing broken tools).

        Args:
            runner: The new AgentRunner instance.
        """
        self._agent_runner = runner

    # ------------------------------------------------------------------
    # Main processing loop
    # ------------------------------------------------------------------

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
        combined_content = self._combiner.build_combined_content(messages)
        thread_id = self._session_manager.get_thread_id(session_key)
        followup_depth = 0
        max_followup_depth = 5

        # Check session TTL first — may rotate conversation before any further checks
        # TTL only applies to group sessions (not DMs)
        ttl_thread_id = await self._ttl_checker.check(
            session_key=session_key,
            thread_id=thread_id,
            channel=channel,
            messages=messages,
            agent_runner=self._agent_runner,
            logger=self._logger,
        )
        if ttl_thread_id:
            thread_id = ttl_thread_id

        # Check if auto-compact should trigger
        new_thread_id = await self._compactor.check_compact(
            session_key=session_key,
            thread_id=thread_id,
            channel=channel,
            agent_runner=self._agent_runner,
        )
        if new_thread_id:
            thread_id = new_thread_id

        while True:
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
                    await self._response_handler.send_response(
                        session_key=session_key,
                        response=response,
                        channel=channel,
                        messages=messages,
                    )

            except ApprovalRequiredError as e:
                self._approval_handler.log_partial_metrics(self._agent_runner, session_key)
                result = await self._approval_handler.handle(
                    error=e,
                    channel=channel,
                    agent_runner=self._agent_runner,
                    thread_id=thread_id,
                    session_key=session_key,
                )
                if result.action == "retry":
                    continue
                elif result.action == "deny":
                    combined_content = result.combined_content or ""
                    continue
                else:
                    break

            except InterruptSignalError as e:
                self._log_partial_metrics(session_key)
                combined_content = await self._interrupt_handler.handle(
                    error=e,
                    channel=channel,
                    session_key=session_key,
                )
                followup_depth = 0
                continue

            except Exception as e:
                error_result = await self._error_handler.handle(
                    error=e,
                    channel=channel,
                    session_key=session_key,
                    thread_id=thread_id,
                    agent_runner=self._agent_runner,
                )
                if error_result.action == "continue" and error_result.combined_content:
                    thread_id = self._session_manager.get_thread_id(session_key)
                    combined_content = error_result.combined_content
                    continue
                break

            finally:
                self._disconnect_send_message_tool()
                self._queue_middleware.reset()
                if self._approval_manager:
                    self._approval_middleware.reset()
                if self._status_reminder_middleware:
                    self._status_reminder_middleware.reset()

            # Check steer (captured before reset)
            if steered and steer_messages:
                combined_content = self._combiner.build_combined_content_from_tuples(
                    steer_messages
                )
                followup_depth = 0
                self._logger.info(f"Steer redirect: processing {len(steer_messages)} new message(s)")
                continue

            # Check for followup request
            followup_result = self._followup_scheduler.check(
                session_key=session_key,
                followup_depth=followup_depth,
                max_depth=max_followup_depth,
            )
            if followup_result.action == "continue":
                followup_depth = followup_result.new_depth or followup_depth
                combined_content = followup_result.combined_content or ""
                continue

            break  # No followup or delayed followup scheduled, exit loop

        # Reset followup state after loop exits
        followup_tool = self._builtin_loader.get_tool_instance("followup")
        if followup_tool:
            followup_tool.reset()

        # Reset acknowledge state after loop exits
        ack_tool = self._builtin_loader.get_tool_instance("acknowledge")
        if ack_tool:
            ack_tool.reset()

    def _log_partial_metrics(self, session_key: str) -> None:
        """Log any partial metrics available from an interrupted run.

        Args:
            session_key: The session identifier for the log entry.
        """
        metrics = self._agent_runner.last_metrics
        if metrics:
            self._token_logger.log(
                metrics=metrics,
                workspace=self._workspace_name,
                invocation_type="user",
                session_key=session_key,
            )

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
