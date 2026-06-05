"""Sub-agent core execution loop.

Encapsulates the agent run, timeout handling, success/error result creation,
session logging, and periodic progress updates.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from openpaw.agent.metrics import TokenUsageLogger
from openpaw.agent.session_logger import SessionLogger
from openpaw.core.prompts.system_events import SUBAGENT_PROGRESS_TEMPLATE
from openpaw.model.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus
from openpaw.stores.subagent import SubAgentStore

from .formatter import _format_elapsed, build_origin_suffix

if TYPE_CHECKING:
    from openpaw.agent import AgentRunner

logger = logging.getLogger(__name__)


class SubAgentExecutor:
    """Runs a sub-agent to completion and returns a SubAgentResult.

    Handles semaphore acquisition is performed by the caller (facade); this
    class focuses on the agent invocation, timeout, cancellation, error,
    success, and logging paths.
    """

    def __init__(
        self,
        store: SubAgentStore,
        token_logger: TokenUsageLogger | None,
        session_logger: SessionLogger | None,
        workspace_name: str,
        result_callback: Callable[[str, str], Awaitable[None]] | None,
    ):
        """Initialize the executor.

        Args:
            store: SubAgentStore for persisting status and results.
            token_logger: Optional token usage logger.
            session_logger: Optional SessionLogger for writing JSONL logs.
            workspace_name: Workspace name for logging context.
            result_callback: Optional callback for progress updates.
        """
        self._store = store
        self._token_logger = token_logger
        self._session_logger = session_logger
        self._workspace_name = workspace_name
        self._result_callback = result_callback

    async def execute(
        self,
        request: SubAgentRequest,
        runner: AgentRunner,
        start_time: float,
        effective_timeout: float,
    ) -> SubAgentResult:
        """Run the agent and return a result for all terminal paths.

        Args:
            request: The sub-agent request.
            runner: Configured AgentRunner instance.
            start_time: Monotonic start time for duration calculation.
            effective_timeout: Timeout in minutes.

        Returns:
            SubAgentResult with status reflected in the store.
        """
        try:
            async with asyncio.timeout(effective_timeout * 60):
                response = await runner.run(message=request.task)
        except TimeoutError:
            return await self._handle_timeout(request, runner, start_time)
        except Exception as e:
            return await self._handle_error(request, runner, start_time, e)

        # Check if we were cancelled during execution
        # (cancel() sets status to CANCELLED before task.cancel())
        current_request = await self._store.get(request.id)
        if current_request and current_request.status == SubAgentStatus.CANCELLED:
            logger.info(
                f"Sub-agent {request.id} completed but was cancelled — "
                "discarding result"
            )
            return SubAgentResult(
                request_id=request.id,
                output="",
                error="Sub-agent was cancelled",
                duration_ms=(time.monotonic() - start_time) * 1000,
            )

        return await self._handle_success(request, runner, start_time, response)

    async def _handle_success(
        self,
        request: SubAgentRequest,
        runner: AgentRunner,
        start_time: float,
        response: str,
    ) -> SubAgentResult:
        """Handle successful agent completion.

        Args:
            request: The sub-agent request.
            runner: The agent runner that produced the response.
            start_time: Monotonic start time.
            response: The agent's output string.

        Returns:
            SubAgentResult in COMPLETED state.
        """
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
        await self._store.save_result(result)

        # Write session log
        log_path = await self._write_session_log(
            request=request,
            response=response,
            tools_used=runner.last_tools_used or [],
            metrics=runner.last_metrics,
            duration_ms=duration_ms,
        )
        if log_path:
            result.session_log_path = log_path
            await self._store.save_result(result)

        # Update status to COMPLETED
        await self._store.update_status(
            request.id, SubAgentStatus.COMPLETED, completed_at=datetime.now(UTC)
        )

        logger.info(
            f"Sub-agent {request.id} completed successfully "
            f"(duration: {duration_ms:.0f}ms, tokens: {token_count})"
        )

        # Log token usage
        if self._token_logger and runner.last_metrics:
            self._token_logger.log(
                metrics=runner.last_metrics,
                workspace=self._workspace_name,
                invocation_type="subagent",
                session_key=request.session_key,
            )

        return result

    async def _finalize_failure(
        self,
        request: SubAgentRequest,
        start_time: float,
        status: SubAgentStatus,
        error_msg: str,
        response: str,
        log_level: int,
        tools_used: list[str] | None = None,
    ) -> SubAgentResult:
        """Common failure path for timeout and error handling.

        Args:
            request: The sub-agent request.
            start_time: Monotonic start time.
            status: Final status (TIMED_OUT or FAILED).
            error_msg: Human-readable error message.
            response: Session log response text.
            log_level: Logging level for the failure message.
            tools_used: Optional list of tool names invoked before failure.

        Returns:
            SubAgentResult in the specified terminal state.
        """
        duration_ms = (time.monotonic() - start_time) * 1000
        await self._store.update_status(
            request.id, status, completed_at=datetime.now(UTC)
        )

        result = SubAgentResult(
            request_id=request.id,
            output="",
            error=error_msg,
            duration_ms=duration_ms,
        )
        await self._store.save_result(result)

        log_path = await self._write_session_log(
            request=request,
            response=response,
            tools_used=tools_used or [],
            metrics=None,
            duration_ms=duration_ms,
        )
        if log_path:
            result.session_log_path = log_path
            await self._store.save_result(result)

        logger.log(
            log_level,
            f"Sub-agent {request.id} {status.value}: {error_msg}",
            exc_info=(log_level >= logging.ERROR),
        )
        return result

    async def _handle_timeout(
        self, request: SubAgentRequest, runner: "AgentRunner", start_time: float
    ) -> SubAgentResult:
        """Handle agent timeout.

        Args:
            request: The sub-agent request.
            runner: The agent runner that timed out.
            start_time: Monotonic start time.

        Returns:
            SubAgentResult in TIMED_OUT state.
        """
        last_tool = getattr(runner, "_current_tool_name", None) or "unknown"
        tools_used = list(getattr(runner, "_last_tools_used", []) or [])
        error_msg = (
            f"Sub-agent timed out after {request.timeout_minutes} minutes "
            f"(last tool: {last_tool}, tools used: {tools_used})"
        )
        return await self._finalize_failure(
            request,
            start_time,
            SubAgentStatus.TIMED_OUT,
            error_msg,
            f"(timed out; last tool: {last_tool})",
            logging.WARNING,
            tools_used=tools_used,
        )

    async def _handle_error(
        self, request: SubAgentRequest, runner: "AgentRunner", start_time: float, error: Exception
    ) -> SubAgentResult:
        """Handle generic agent failure.

        Args:
            request: The sub-agent request.
            runner: The agent runner that failed.
            start_time: Monotonic start time.
            error: The exception that was raised.

        Returns:
            SubAgentResult in FAILED state.
        """
        last_tool = getattr(runner, "_current_tool_name", None) or "unknown"
        tools_used = list(getattr(runner, "_last_tools_used", []) or [])
        error_msg = (
            f"Sub-agent failed: {error!s} "
            f"(last tool: {last_tool}, tools used: {tools_used})"
        )
        return await self._finalize_failure(
            request,
            start_time,
            SubAgentStatus.FAILED,
            error_msg,
            f"(failed: {error!s}; last tool: {last_tool})",
            logging.ERROR,
            tools_used=tools_used,
        )

    async def _progress_timer(
        self,
        request: SubAgentRequest,
        runner: AgentRunner,
        start_time: float,
    ) -> None:
        """Emit periodic progress updates for a running sub-agent.

        Runs as a concurrent asyncio task alongside the agent execution.

        Args:
            request: The sub-agent request being executed.
            runner: The AgentRunner instance to read state from.
            start_time: Monotonic start time for elapsed calculation.
        """
        if not self._result_callback:
            logger.debug("Progress timer started but no result_callback — exiting")
            return

        interval_seconds = request.progress_interval_minutes * 60

        while True:
            await asyncio.sleep(interval_seconds)

            elapsed_seconds = time.monotonic() - start_time
            tools_used = list(runner._last_tools_used) if runner._last_tools_used else []
            current_tool = runner._current_tool_name or "thinking"

            content = SUBAGENT_PROGRESS_TEMPLATE.format(
                label=request.label,
                elapsed=_format_elapsed(elapsed_seconds),
                tools_summary=", ".join(tools_used[-5:]) if tools_used else "none yet",
                current_activity=current_tool,
                total_tools=len(tools_used),
                origin_suffix=build_origin_suffix(request),
            )

            try:
                await self._result_callback(request.session_key, content)
                logger.debug(f"Sent progress update for sub-agent {request.id}")
            except Exception as e:
                logger.warning(
                    f"Failed to send progress for {request.id}: {e}", exc_info=True
                )

    async def _write_session_log(
        self,
        request: SubAgentRequest,
        response: str,
        tools_used: list[str],
        metrics: Any | None,
        duration_ms: float,
        label_suffix: str = "",
    ) -> str | None:
        """Write a session log entry for the sub-agent run.

        Args:
            request: The sub-agent request.
            response: The response text to log.
            tools_used: List of tool names used during the run.
            metrics: Optional invocation metrics.
            duration_ms: Duration of the run in milliseconds.
            label_suffix: Optional suffix appended to the log name.

        Returns:
            Relative path to the log file, or None if logging is disabled.
        """
        if not self._session_logger:
            return None

        try:
            log_path = self._session_logger.write_session(
                name=f"subagent_{request.label}{label_suffix}",
                prompt=request.task,
                response=response,
                tools_used=tools_used,
                metrics=metrics,
                duration_ms=duration_ms,
            )
            return log_path
        except Exception as e:
            logger.warning(
                f"Failed to write session log for sub-agent {request.id}: {e}",
                exc_info=True,
            )
            return None
