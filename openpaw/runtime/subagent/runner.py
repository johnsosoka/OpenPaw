"""Sub-agent lifecycle manager for OpenPaw.

SubAgentRunner is now a thin facade that orchestrates three helper classes:
- SubAgentProfiler: profile resolution and runner configuration
- SubAgentExecutor: core execution loop (run, timeout, error, success)
- SubAgentNotifier: notification formatting and delivery

All public API signatures remain unchanged for backward compatibility.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from openpaw.agent import AgentRunner
from openpaw.agent.metrics import TokenUsageLogger
from openpaw.agent.session_logger import SessionLogger
from openpaw.channels.base import ChannelAdapter
from openpaw.model.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus
from openpaw.stores.subagent import SubAgentStore
from openpaw.workspace.profile_resolver import SpawnProfileResolver

from .executor import SubAgentExecutor
from .filter import SUBAGENT_EXCLUDED_TOOLS, filter_subagent_tools
from .formatter import _format_elapsed, build_origin_suffix
from .notifier import SubAgentNotifier
from .profiler import ProfileNotFoundError, SubAgentProfiler

if TYPE_CHECKING:
    from openpaw.workspace.agent_factory import AgentFactory

logger = logging.getLogger(__name__)

__all__ = [
    "SubAgentRunner",
    "SUBAGENT_EXCLUDED_TOOLS",
    "filter_subagent_tools",
    "_format_elapsed",
    "build_origin_suffix",
]


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
        session_logger: SessionLogger | None = None,
        profile_resolver: SpawnProfileResolver | None = None,
        agent_factory_instance: AgentFactory | None = None,
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
            session_logger: Optional SessionLogger for writing session logs.
            profile_resolver: Optional SpawnProfileResolver for named spawn profiles.
                When provided, sub-agents can request a profile by name to apply
                model overrides, tool filtering, and system prompt injection.
            agent_factory_instance: Optional AgentFactory used to create profiled agents
                via create_profiled_agent(). Required when profiles specify model overrides.
        """
        self._agent_factory = agent_factory
        self._store = store
        self._channels = channels
        self._token_logger = token_logger
        self._workspace_name = workspace_name
        self._max_concurrent = max_concurrent
        self._result_callback = result_callback
        self._session_logger = session_logger
        self._profile_resolver = profile_resolver
        self._agent_factory_instance = agent_factory_instance
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}

        # Delegate helpers
        self._profiler = SubAgentProfiler(
            profile_resolver=profile_resolver,
            agent_factory_instance=agent_factory_instance,
            workspace_name=workspace_name,
        )
        self._executor = SubAgentExecutor(
            store=store,
            token_logger=token_logger,
            session_logger=session_logger,
            workspace_name=workspace_name,
            result_callback=result_callback,
        )
        self._notifier = SubAgentNotifier(
            channels=channels,
            result_callback=result_callback,
        )

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
        await self._store.update_status(
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
            True if the task was cancelled, False if not found or already terminal.
        """
        task = self._active_tasks.get(request_id)
        if not task:
            logger.warning(f"Cannot cancel: sub-agent {request_id} not active")
            return False

        # Guard against cancel-after-complete race: don't overwrite a terminal status.
        current = await self._store.get(request_id)
        if current and current.status in (
            SubAgentStatus.COMPLETED,
            SubAgentStatus.FAILED,
            SubAgentStatus.TIMED_OUT,
        ):
            logger.info(
                f"Cannot cancel: sub-agent {request_id} already in terminal state "
                f"({current.status.value})"
            )
            return False

        # Cancel the task
        task.cancel()

        # Update store status
        await self._store.update_status(
            request_id, SubAgentStatus.CANCELLED, completed_at=datetime.now(UTC)
        )

        logger.info(f"Cancelled sub-agent: {request_id}")
        return True

    async def list_active(self) -> list[SubAgentRequest]:
        """List all active sub-agent requests (pending or running).

        Returns:
            List of SubAgentRequest instances.
        """
        return await self._store.list_active()

    async def list_recent(self, limit: int = 10) -> list[SubAgentRequest]:
        """List recent sub-agent requests (all statuses, sorted by created_at desc).

        Args:
            limit: Maximum number of requests to return.

        Returns:
            List of SubAgentRequest instances, most recent first.
        """
        return await self._store.list_recent(limit=limit)

    async def get_status(self, request_id: str) -> SubAgentRequest | None:
        """Get the status of a sub-agent request.

        Args:
            request_id: Unique request identifier.

        Returns:
            SubAgentRequest if found, None otherwise.
        """
        return await self._store.get(request_id)

    async def get_result(self, request_id: str) -> SubAgentResult | None:
        """Get the result of a completed sub-agent.

        Args:
            request_id: Unique request identifier.

        Returns:
            SubAgentResult if found, None otherwise.
        """
        return await self._store.get_result(request_id)

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
                await self._store.update_status(
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

        This is the main orchestration method. It:
        1. Acquires semaphore for concurrency control
        2. Sets up the runner via the profiler
        3. Runs the agent via the executor
        4. Sends notification if requested
        5. Handles cancellation, timeout, and errors

        Args:
            request: SubAgentRequest to execute.
        """
        start_time = time.monotonic()

        try:
            # Acquire semaphore for concurrency control
            async with self._semaphore:
                logger.info(f"Executing sub-agent: {request.id} ('{request.label}')")

                # --- Profile resolution ---
                try:
                    runner, effective_timeout = self._profiler.setup(
                        request, self._agent_factory
                    )
                except ProfileNotFoundError as e:
                    duration_ms = (time.monotonic() - start_time) * 1000
                    result = SubAgentResult(
                        request_id=request.id,
                        output="",
                        error=str(e),
                        duration_ms=duration_ms,
                    )
                    await self._store.update_status(
                        request.id, SubAgentStatus.FAILED, completed_at=datetime.now(UTC)
                    )
                    await self._store.save_result(result)
                    if request.notify:
                        await self._notifier.send_notification(request, result)
                    logger.warning(f"Sub-agent {request.id} failed: {e}")
                    return

                # Start periodic progress timer if configured.
                # The task is cancelled in the finally block regardless of outcome.
                progress_task: asyncio.Task[Any] | None = None
                if request.progress_interval_minutes > 0:
                    progress_task = asyncio.create_task(
                        self._executor._progress_timer(request, runner, start_time)
                    )

                try:
                    # Execute the agent run
                    result = await self._executor.execute(
                        request, runner, start_time, effective_timeout
                    )
                finally:
                    # Cancel the progress timer regardless of success/timeout/exception
                    if progress_task is not None:
                        progress_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await progress_task

                # Send notification if requested (skip if result is None, which
                # indicates cancelled-after-completion)
                if result is not None and request.notify:
                    await self._notifier.send_notification(request, result)

        except asyncio.CancelledError:
            # Handle cancellation
            duration_ms = (time.monotonic() - start_time) * 1000
            await self._store.update_status(
                request.id, SubAgentStatus.CANCELLED, completed_at=datetime.now(UTC)
            )

            result = SubAgentResult(
                request_id=request.id,
                output="",
                error="Sub-agent was cancelled",
                duration_ms=duration_ms,
            )
            await self._store.save_result(result)

            # Write session log for cancelled path
            if self._session_logger:
                try:
                    log_path = self._session_logger.write_session(
                        name=f"subagent_{request.label}",
                        prompt=request.task,
                        response="(cancelled)",
                        tools_used=[],
                        metrics=None,
                        duration_ms=duration_ms,
                    )
                    result.session_log_path = log_path
                    await self._store.save_result(result)
                except Exception as log_err:
                    logger.warning(
                        f"Failed to write cancel session log for sub-agent {request.id}: {log_err}",
                        exc_info=True,
                    )

            logger.info(f"Sub-agent {request.id} was cancelled")

            # Notify parent — must happen before re-raise; suppress secondary CancelledError
            if request.notify:
                with contextlib.suppress(asyncio.CancelledError):
                    await self._notifier.send_notification(request, result)

            raise  # Re-raise to propagate cancellation

        except Exception as e:
            # Handle failure
            duration_ms = (time.monotonic() - start_time) * 1000
            await self._store.update_status(
                request.id, SubAgentStatus.FAILED, completed_at=datetime.now(UTC)
            )

            error_msg = f"Sub-agent failed: {e!s}"
            result = SubAgentResult(
                request_id=request.id,
                output="",
                error=error_msg,
                duration_ms=duration_ms,
            )
            await self._store.save_result(result)

            # Write session log for failure path
            if self._session_logger:
                try:
                    log_path = self._session_logger.write_session(
                        name=f"subagent_{request.label}",
                        prompt=request.task,
                        response=f"(failed: {error_msg})",
                        tools_used=[],
                        metrics=None,
                        duration_ms=duration_ms,
                    )
                    result.session_log_path = log_path
                    await self._store.save_result(result)
                except Exception as log_err:
                    logger.warning(
                        f"Failed to write failure session log for sub-agent {request.id}: {log_err}",
                        exc_info=True,
                    )

            logger.error(f"Sub-agent {request.id} failed: {e}", exc_info=True)

            # Notify parent of failure
            if request.notify:
                await self._notifier.send_notification(request, result)

    # ------------------------------------------------------------------
    # Backward-compatible delegators for existing tests and call sites
    # ------------------------------------------------------------------

    def _format_notification(
        self, request: SubAgentRequest, result: SubAgentResult
    ) -> str:
        """Format a notification message for sub-agent completion.

        Args:
            request: The original sub-agent request.
            result: The execution result.

        Returns:
            Formatted notification content with [SYSTEM] prefix.
        """
        return self._notifier.format_notification(request, result)

    async def _send_notification(
        self, request: SubAgentRequest, result: SubAgentResult
    ) -> None:
        """Send completion notification to the requesting session.

        Args:
            request: The original sub-agent request.
            result: The execution result.
        """
        await self._notifier.send_notification(request, result)
