"""Sub-agent lifecycle manager for OpenPaw."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime

from openpaw.channels.base import ChannelAdapter
from openpaw.core.agent import AgentRunner
from openpaw.core.metrics import TokenUsageLogger
from openpaw.subagent.store import SubAgentRequest, SubAgentResult, SubAgentStatus, SubAgentStore

logger = logging.getLogger(__name__)

# Tools excluded from sub-agents to prevent recursion and unwanted side effects
SUBAGENT_EXCLUDED_TOOLS = {
    # Prevent sub-sub-agents
    "spawn_agent",
    "list_subagents",
    "get_subagent_result",
    "cancel_subagent",
    # Prevent self-continuation (sub-agents are one-shot)
    "request_followup",
    # Prevent unsolicited user messaging (SubAgentRunner handles result delivery)
    "send_message",
    "send_file",
    # Prevent persistence mechanisms that outlive sub-agent lifecycle
    "schedule_at",
    "schedule_every",
    "list_scheduled",
    "cancel_scheduled",
}


class SubAgentRunner:
    """Manages spawned sub-agent lifecycles with concurrency control.

    Sub-agents are background workers that execute tasks concurrently with
    the main agent. They use fresh AgentRunner instances (stateless, no checkpointer)
    with filtered tools to prevent recursion and unsolicited user communication.

    Example:
        >>> runner = SubAgentRunner(
        ...     agent_factory=create_agent_factory(),
        ...     store=SubAgentStore(workspace_path),
        ...     channels={"telegram": telegram_channel},
        ...     token_logger=token_logger,
        ...     workspace_name="gilfoyle",
        ...     max_concurrent=8,
        ... )
        >>> request_id = await runner.spawn(request)
        >>> status = runner.get_status(request_id)
        >>> result = runner.get_result(request_id)
    """

    def __init__(
        self,
        agent_factory: Callable[[], AgentRunner],
        store: SubAgentStore,
        channels: Mapping[str, ChannelAdapter],
        token_logger: TokenUsageLogger | None = None,
        workspace_name: str = "unknown",
        max_concurrent: int = 8,
        result_callback: Callable[[str, str], Awaitable[None]] | None = None,
    ):
        """Initialize the sub-agent runner.

        Args:
            agent_factory: Factory function to create fresh agent instances.
            store: SubAgentStore for persisting sub-agent state.
            channels: Mapping of channel names to channel instances for notifications.
            token_logger: Optional token usage logger for tracking invocations.
            workspace_name: Workspace name for logging context.
            max_concurrent: Maximum simultaneous sub-agents (default: 8).
            result_callback: Optional callback for queue injection of results.
                If provided, called with (session_key, content) instead of direct channel send.
        """
        self._agent_factory = agent_factory
        self._store = store
        self._channels = channels
        self._token_logger = token_logger
        self._workspace_name = workspace_name
        self._max_concurrent = max_concurrent
        self._result_callback = result_callback
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: dict[str, asyncio.Task] = {}

    async def spawn(self, request: SubAgentRequest) -> str:
        """Spawn a new sub-agent to handle a request.

        Args:
            request: SubAgentRequest to execute.

        Returns:
            Request ID for tracking.

        Raises:
            ValueError: If max concurrent limit is reached.
        """
        # Check if we're at capacity
        if len(self._active_tasks) >= self._max_concurrent:
            raise ValueError(
                f"Cannot spawn sub-agent: max concurrent limit reached "
                f"({self._max_concurrent})"
            )

        # Update status to RUNNING
        self._store.update_status(
            request.id, SubAgentStatus.RUNNING, started_at=datetime.now(UTC)
        )

        # Create background task
        task = asyncio.create_task(self._execute_subagent(request))

        # Store strong reference to prevent GC
        self._active_tasks[request.id] = task

        # Add done callback to clean up
        task.add_done_callback(lambda _: self._active_tasks.pop(request.id, None))

        logger.info(
            f"Spawned sub-agent: {request.id} ('{request.label}') "
            f"[{len(self._active_tasks)}/{self._max_concurrent}]"
        )

        return request.id

    async def cancel(self, request_id: str) -> bool:
        """Cancel a running sub-agent.

        Args:
            request_id: ID of the request to cancel.

        Returns:
            True if the task was cancelled, False if not found.
        """
        task = self._active_tasks.get(request_id)
        if not task:
            logger.warning(f"Cannot cancel: sub-agent {request_id} not active")
            return False

        # Cancel the task
        task.cancel()

        # Update store status
        self._store.update_status(
            request_id, SubAgentStatus.CANCELLED, completed_at=datetime.now(UTC)
        )

        logger.info(f"Cancelled sub-agent: {request_id}")
        return True

    def list_active(self) -> list[SubAgentRequest]:
        """List all active sub-agent requests (pending or running).

        Returns:
            List of SubAgentRequest instances.
        """
        return self._store.list_active()

    def list_recent(self, limit: int = 10) -> list[SubAgentRequest]:
        """List recent sub-agent requests (all statuses, sorted by created_at desc).

        Args:
            limit: Maximum number of requests to return.

        Returns:
            List of SubAgentRequest instances, most recent first.
        """
        return self._store.list_recent(limit=limit)

    def get_status(self, request_id: str) -> SubAgentRequest | None:
        """Get the status of a sub-agent request.

        Args:
            request_id: Unique request identifier.

        Returns:
            SubAgentRequest if found, None otherwise.
        """
        return self._store.get(request_id)

    def get_result(self, request_id: str) -> SubAgentResult | None:
        """Get the result of a completed sub-agent.

        Args:
            request_id: Unique request identifier.

        Returns:
            SubAgentResult if found, None otherwise.
        """
        return self._store.get_result(request_id)

    async def shutdown(self) -> None:
        """Shutdown the runner, cancelling all active sub-agents."""
        if not self._active_tasks:
            logger.info("No active sub-agents to shutdown")
            return

        logger.info(f"Shutting down {len(self._active_tasks)} active sub-agent(s)")

        # Cancel all active tasks
        for request_id, task in list(self._active_tasks.items()):
            if not task.done():
                task.cancel()
                # Update store status
                self._store.update_status(
                    request_id, SubAgentStatus.CANCELLED, completed_at=datetime.now(UTC)
                )

        # Wait for tasks to complete with timeout
        if self._active_tasks:
            try:
                async with asyncio.timeout(5.0):
                    await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
            except TimeoutError:
                logger.warning("Some sub-agents did not shutdown cleanly within 5s timeout")

        logger.info("Sub-agent runner shutdown complete")

    async def _execute_subagent(self, request: SubAgentRequest) -> None:
        """Execute a sub-agent request in the background.

        This is the main execution loop for a sub-agent. It:
        1. Acquires semaphore for concurrency control
        2. Creates fresh AgentRunner with filtered tools
        3. Runs the agent with the request task
        4. Saves result to store
        5. Sends notification if requested
        6. Logs token usage
        7. Always releases semaphore in finally block

        Args:
            request: SubAgentRequest to execute.
        """
        start_time = time.monotonic()

        try:
            # Acquire semaphore for concurrency control
            async with self._semaphore:
                logger.info(f"Executing sub-agent: {request.id} ('{request.label}')")

                # Create fresh agent instance
                runner = self._agent_factory()

                # Filter out excluded tools (prevent recursion and unsolicited messaging)
                original_tool_count = len(runner.additional_tools)
                runner.additional_tools = [
                    tool
                    for tool in runner.additional_tools
                    if getattr(tool, "name", str(tool)) not in SUBAGENT_EXCLUDED_TOOLS
                ]
                filtered_count = original_tool_count - len(runner.additional_tools)

                if filtered_count > 0:
                    logger.debug(
                        f"Filtered {filtered_count} tool(s) from sub-agent {request.id}"
                    )

                # Rebuild agent with filtered tools
                runner._agent = runner._build_agent()

                # Override agent's internal timeout to defer to SubAgentRunner's
                # outer timeout. AgentRunner.run() catches TimeoutError internally
                # and returns a string, which would be misclassified as success.
                # By setting the inner timeout higher, only the outer fires.
                runner.timeout_seconds = (request.timeout_minutes * 60) + 30

                # Run the agent with timeout
                try:
                    async with asyncio.timeout(request.timeout_minutes * 60):
                        response = await runner.run(message=request.task)
                except TimeoutError:
                    # Handle timeout
                    duration_ms = (time.monotonic() - start_time) * 1000
                    self._store.update_status(
                        request.id, SubAgentStatus.TIMED_OUT, completed_at=datetime.now(UTC)
                    )

                    error_msg = f"Sub-agent timed out after {request.timeout_minutes} minutes"
                    result = SubAgentResult(
                        request_id=request.id,
                        output="",
                        error=error_msg,
                        duration_ms=duration_ms,
                    )
                    self._store.save_result(result)

                    logger.warning(f"Sub-agent {request.id} timed out")

                    # Send timeout notification if requested
                    if request.notify:
                        await self._send_notification(request, result)

                    return

                # Success: save result
                duration_ms = (time.monotonic() - start_time) * 1000

                # Get token count from runner
                token_count = 0
                if runner.last_metrics:
                    token_count = runner.last_metrics.total_tokens

                result = SubAgentResult(
                    request_id=request.id,
                    output=response,
                    token_count=token_count,
                    duration_ms=duration_ms,
                )
                self._store.save_result(result)

                # Update status to COMPLETED
                self._store.update_status(
                    request.id, SubAgentStatus.COMPLETED, completed_at=datetime.now(UTC)
                )

                logger.info(
                    f"Sub-agent {request.id} completed successfully "
                    f"(duration: {duration_ms:.0f}ms, tokens: {token_count})"
                )

                # Send notification if requested
                if request.notify:
                    await self._send_notification(request, result)

                # Log token usage
                if self._token_logger and runner.last_metrics:
                    self._token_logger.log(
                        metrics=runner.last_metrics,
                        workspace=self._workspace_name,
                        invocation_type="subagent",
                        session_key=request.session_key,
                    )

        except asyncio.CancelledError:
            # Handle cancellation
            duration_ms = (time.monotonic() - start_time) * 1000
            self._store.update_status(
                request.id, SubAgentStatus.CANCELLED, completed_at=datetime.now(UTC)
            )

            result = SubAgentResult(
                request_id=request.id,
                output="",
                error="Sub-agent was cancelled",
                duration_ms=duration_ms,
            )
            self._store.save_result(result)

            logger.info(f"Sub-agent {request.id} was cancelled")
            raise  # Re-raise to propagate cancellation

        except Exception as e:
            # Handle failure
            duration_ms = (time.monotonic() - start_time) * 1000
            self._store.update_status(
                request.id, SubAgentStatus.FAILED, completed_at=datetime.now(UTC)
            )

            error_msg = f"Sub-agent failed: {e!s}"
            result = SubAgentResult(
                request_id=request.id,
                output="",
                error=error_msg,
                duration_ms=duration_ms,
            )
            self._store.save_result(result)

            logger.error(f"Sub-agent {request.id} failed: {e}", exc_info=True)

    def _format_notification(self, request: SubAgentRequest, result: SubAgentResult) -> str:
        """Format a notification message for sub-agent completion.

        Args:
            request: The original sub-agent request.
            result: The execution result.

        Returns:
            Formatted notification content with [SYSTEM] prefix.
        """
        # Determine status and format message
        if result.error:
            # Check if it's a timeout error
            if "timed out" in result.error.lower():
                return (
                    f"[SYSTEM] Sub-agent '{request.label}' timed out "
                    f"after {request.timeout_minutes} minutes."
                )
            else:
                return f"[SYSTEM] Sub-agent '{request.label}' failed.\nError: {result.error}"
        else:
            # Success case - truncate output if too long
            output = result.output
            if len(output) > 500:
                output = output[:500]
                return (
                    f"[SYSTEM] Sub-agent '{request.label}' completed.\n\n"
                    f"{output}\n\n"
                    f"Use get_subagent_result(id=\"{request.id}\") to read the full output."
                )
            else:
                return f"[SYSTEM] Sub-agent '{request.label}' completed.\n\n{output}"

    async def _send_notification(self, request: SubAgentRequest, result: SubAgentResult) -> None:
        """Send completion notification to the requesting session.

        Args:
            request: The original sub-agent request.
            result: The execution result.
        """
        try:
            # Format the notification content
            content = self._format_notification(request, result)

            # Use result callback if provided (queue injection)
            if self._result_callback:
                await self._result_callback(request.session_key, content)
                logger.debug(f"Queued notification for sub-agent {request.id}")
            else:
                # Fallback: direct channel send (backwards compatibility)
                parts = request.session_key.split(":", 1)
                if len(parts) != 2:
                    logger.warning(
                        f"Invalid session_key format for notification: {request.session_key}"
                    )
                    return

                channel_name = parts[0]
                channel = self._channels.get(channel_name)

                if not channel:
                    logger.warning(f"Channel not found for notification: {channel_name}")
                    return

                await channel.send_message(session_key=request.session_key, content=content)
                logger.debug(f"Sent notification for sub-agent {request.id}")

        except Exception as e:
            logger.warning(f"Failed to send notification for sub-agent {request.id}: {e}")
