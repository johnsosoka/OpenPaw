"""Sub-agent lifecycle manager for OpenPaw."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from copy import copy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from openpaw.agent import AgentRunner
from openpaw.agent.metrics import TokenUsageLogger
from openpaw.agent.session_logger import SessionLogger
from openpaw.builtins.registry import BuiltinRegistry
from openpaw.channels.base import ChannelAdapter
from openpaw.core.prompts.system_events import (
    SUBAGENT_COMPLETED_SHORT_TEMPLATE,
    SUBAGENT_COMPLETED_TEMPLATE,
    SUBAGENT_FAILED_TEMPLATE,
    SUBAGENT_PROGRESS_TEMPLATE,
    SUBAGENT_TIMED_OUT_TEMPLATE,
)
from openpaw.model.spawn_profile import SpawnProfile
from openpaw.model.subagent import SubAgentRequest, SubAgentResult, SubAgentStatus
from openpaw.stores.subagent import SubAgentStore
from openpaw.workspace.profile_resolver import SpawnProfileResolver

if TYPE_CHECKING:
    from openpaw.workspace.agent_factory import AgentFactory

logger = logging.getLogger(__name__)


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as a human-readable string.

    Args:
        seconds: Elapsed time in seconds.

    Returns:
        Human-readable string such as "45s", "5m 30s", or "1h 2m 30s".
    """
    minutes, secs = divmod(int(seconds), 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


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
    # Prevent orphaned browser sessions (subagents have no session key for cleanup)
    "browser_navigate",
    "browser_snapshot",
    "browser_click",
    "browser_type",
    "browser_select",
    "browser_scroll",
    "browser_back",
    "browser_screenshot",
    "browser_close",
    "browser_tabs",
    "browser_switch_tab",
    # Prevent persistent cron jobs that outlive the subagent lifecycle
    "create_cron",
    "list_crons",
    "update_cron",
    "delete_cron",
    # Plan tool requires a session key (undefined in subagent execution context)
    "write_plan",
    "read_plan",
}


def filter_subagent_tools(
    tools: list[Any],
    allowed_tools: list[str] | None = None,
    denied_tools: list[str] | None = None,
    group_resolver: Callable[[str], list[str]] | None = None,
) -> list[Any]:
    """Filter tools for a sub-agent based on allowed/denied lists.

    Filtering order:
    1. SUBAGENT_EXCLUDED_TOOLS floor (always applied, never overridable)
    2. allowed_tools whitelist (if specified, only matching tools survive)
    3. denied_tools blocklist (removes additional tools)

    The group: prefix is resolved via group_resolver (e.g., "group:web" → ["browser_navigate", "browser_click", ...]).
    Unknown tool names in allowed/denied produce a warning log, not an error.

    Args:
        tools: List of LangChain tools to filter.
        allowed_tools: Optional whitelist of tool names (supports group: prefix).
        denied_tools: Optional additional deny list (supports group: prefix).
        group_resolver: Callable that resolves group names to tool name lists.
            Defaults to BuiltinRegistry.get_instance().get_group_members.

    Returns:
        Filtered list of tools.
    """
    if group_resolver is None:
        group_resolver = BuiltinRegistry.get_instance().get_group_members

    def _resolve_tool_names(names: list[str] | None) -> set[str]:
        """Expand group: prefixes and return a set of tool names."""
        if not names:
            return set()

        resolved = set()
        for name in names:
            if name.startswith("group:"):
                group_name = name[6:]  # Strip "group:" prefix
                try:
                    group_tools = group_resolver(group_name)
                    resolved.update(group_tools)
                except Exception as e:
                    logger.warning(f"Failed to resolve group '{group_name}': {e}")
            else:
                resolved.add(name)
        return resolved

    # Get tool names from the tools list
    tool_names = {getattr(tool, "name", str(tool)) for tool in tools}

    # Step 1: Always remove SUBAGENT_EXCLUDED_TOOLS
    filtered = [
        tool
        for tool in tools
        if getattr(tool, "name", str(tool)) not in SUBAGENT_EXCLUDED_TOOLS
    ]

    # Step 2: Apply allowed_tools whitelist (if specified)
    if allowed_tools is not None:
        allowed_set = _resolve_tool_names(allowed_tools)
        # Warn about unknown tools in allowed list
        unknown_allowed = allowed_set - tool_names - SUBAGENT_EXCLUDED_TOOLS
        if unknown_allowed:
            logger.warning(
                f"Unknown tools in allowed_tools list: {sorted(unknown_allowed)}"
            )
        filtered = [
            tool for tool in filtered if getattr(tool, "name", str(tool)) in allowed_set
        ]

    # Step 3: Apply denied_tools blocklist (if specified)
    if denied_tools is not None:
        denied_set = _resolve_tool_names(denied_tools)
        # Warn about unknown tools in denied list
        unknown_denied = denied_set - tool_names
        if unknown_denied:
            logger.warning(
                f"Unknown tools in denied_tools list: {sorted(unknown_denied)}"
            )
        filtered = [
            tool for tool in filtered if getattr(tool, "name", str(tool)) not in denied_set
        ]

    return filtered


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
            True if the task was cancelled, False if not found or already terminal.
        """
        task = self._active_tasks.get(request_id)
        if not task:
            logger.warning(f"Cannot cancel: sub-agent {request_id} not active")
            return False

        # Guard against cancel-after-complete race: don't overwrite a terminal status.
        current = self._store.get(request_id)
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

                # --- Profile resolution ---
                # Resolve before creating the agent so we can route to the right factory.
                profile: SpawnProfile | None = None
                if request.profile:
                    if self._profile_resolver is None:
                        error_msg = (
                            f"Spawn profile '{request.profile}' requested but no profiles are configured"
                        )
                        duration_ms = (time.monotonic() - start_time) * 1000
                        result = SubAgentResult(
                            request_id=request.id, output="", error=error_msg, duration_ms=duration_ms,
                        )
                        self._store.update_status(
                            request.id, SubAgentStatus.FAILED, completed_at=datetime.now(UTC)
                        )
                        self._store.save_result(result)
                        if request.notify:
                            await self._send_notification(request, result)
                        logger.warning(f"Sub-agent {request.id} failed: {error_msg}")
                        return

                    profile = self._profile_resolver.resolve(request.profile)
                    if profile is None:
                        available = ", ".join(self._profile_resolver.list_profile_names()) or "none"
                        error_msg = (
                            f"Spawn profile '{request.profile}' not found. "
                            f"Available profiles: {available}"
                        )
                        duration_ms = (time.monotonic() - start_time) * 1000
                        result = SubAgentResult(
                            request_id=request.id, output="", error=error_msg, duration_ms=duration_ms,
                        )
                        self._store.update_status(
                            request.id, SubAgentStatus.FAILED, completed_at=datetime.now(UTC)
                        )
                        self._store.save_result(result)
                        if request.notify:
                            await self._send_notification(request, result)
                        logger.warning(f"Sub-agent {request.id} failed: {error_msg}")
                        return

                # Create agent — use profiled factory when profile has model-level overrides
                if profile and self._agent_factory_instance and (
                    profile.model is not None
                    or profile.temperature is not None
                    or profile.max_turns is not None
                ):
                    runner = self._agent_factory_instance.create_profiled_agent(profile)
                else:
                    runner = self._agent_factory()

                # Inject sub-agent label so logs distinguish sub-agent from main agent.
                # Prefer profile name (e.g., "devin:homelab-specialist"), fall back to task label.
                sub_label = request.profile or request.label
                runner._log_label = f"{self._workspace_name}:{sub_label}"

                # --- Profile workspace overrides (prompt + skills) ---
                # Copy workspace before ANY mutation to avoid shared-state corruption.
                needs_copy = profile and (
                    profile.system_prompt
                    or profile.allowed_skills is not None
                    or profile.denied_skills
                )
                if needs_copy:
                    runner.workspace = copy(runner.workspace)

                if profile and profile.system_prompt:
                    role_block = (
                        f'<team_role profile="{profile.name}">\n'
                        f"{profile.system_prompt.strip()}\n"
                        f"</team_role>\n\n"
                    )
                    runner.workspace.agent_md = role_block + runner.workspace.agent_md

                # --- Profile skill filtering ---
                if profile and runner.workspace.skills:
                    if profile.allowed_skills is not None:
                        # Whitelist: only keep named skills (empty list = no skills)
                        allowed = set(profile.allowed_skills)
                        original_count = len(runner.workspace.skills)
                        runner.workspace.skills = [
                            s for s in runner.workspace.skills if s.name in allowed
                        ]
                        filtered = original_count - len(runner.workspace.skills)
                        if filtered > 0:
                            logger.debug(
                                f"Profile '{profile.name}' filtered {filtered} skill(s) "
                                f"via allowed_skills"
                            )
                    if profile.denied_skills:
                        # Blocklist: remove named skills
                        denied = set(profile.denied_skills)
                        runner.workspace.skills = [
                            s for s in runner.workspace.skills if s.name not in denied
                        ]

                # --- Profile tool injection ---
                if profile:
                    if not profile.inherit_tools:
                        # Replace: sub-agent gets ONLY profile tools (no parent tools)
                        parent_count = len(runner.additional_tools)
                        runner.additional_tools = list(profile.tools)
                        logger.debug(
                            "Profile '%s' inherit_tools=False: replaced %d parent tools "
                            "with %d profile tools",
                            profile.name,
                            parent_count,
                            len(profile.tools),
                        )
                        if not profile.tools:
                            logger.warning(
                                "Profile '%s' has inherit_tools=False but no profile tools "
                                "— sub-agent will have only filesystem tools",
                                profile.name,
                            )
                    elif profile.tools:
                        # Append: sub-agent gets parent tools + profile tools
                        parent_names = {
                            getattr(t, "name", "") for t in runner.additional_tools
                        }
                        profile_names = {t.name for t in profile.tools}
                        collisions = parent_names & profile_names
                        if collisions:
                            logger.warning(
                                "Profile '%s' tools override parent tools with same name: %s",
                                profile.name,
                                sorted(collisions),
                            )
                            # Remove parent tools that are overridden by profile tools
                            runner.additional_tools = [
                                t for t in runner.additional_tools
                                if getattr(t, "name", "") not in collisions
                            ]
                        runner.additional_tools = (
                            list(runner.additional_tools) + list(profile.tools)
                        )
                        logger.debug(
                            "Profile '%s': added %d profile tool(s) to %d parent tools",
                            profile.name,
                            len(profile.tools),
                            len(runner.additional_tools) - len(profile.tools),
                        )

                # Filter tools — two-pass: profile restricts first, per-spawn second
                original_tool_count = len(runner.additional_tools)

                if profile and (profile.allowed_tools or profile.denied_tools):
                    runner.additional_tools = filter_subagent_tools(
                        runner.additional_tools,
                        allowed_tools=profile.allowed_tools,
                        denied_tools=profile.denied_tools,
                    )

                runner.additional_tools = filter_subagent_tools(
                    runner.additional_tools,
                    allowed_tools=request.allowed_tools,
                    denied_tools=request.denied_tools,
                )

                filtered_count = original_tool_count - len(runner.additional_tools)

                if filtered_count > 0:
                    logger.debug(
                        f"Filtered {filtered_count} tool(s) from sub-agent {request.id}"
                    )

                # Rebuild agent with filtered tools
                runner._agent = runner._build_agent()

                # Apply timeout: prefer profile default when per-spawn is still the default (30)
                effective_timeout = request.timeout_minutes
                if profile and profile.timeout_minutes and request.timeout_minutes == 30:
                    effective_timeout = profile.timeout_minutes

                # Override agent's internal timeout to defer to SubAgentRunner's
                # outer timeout. AgentRunner.run() catches TimeoutError internally
                # and returns a string, which would be misclassified as success.
                # By setting the inner timeout higher, only the outer fires.
                runner.timeout_seconds = (effective_timeout * 60) + 30

                # Start periodic progress timer if configured.
                # The task is cancelled in the finally block regardless of outcome.
                progress_task: asyncio.Task | None = None
                if request.progress_interval_minutes > 0:
                    progress_task = asyncio.create_task(
                        self._progress_timer(request, runner, start_time)
                    )

                try:
                    # Run the agent with timeout
                    try:
                        async with asyncio.timeout(effective_timeout * 60):
                            response = await runner.run(message=request.task)

                        # Check if we were cancelled during execution
                        # (cancel() sets status to CANCELLED before task.cancel())
                        current_request = self._store.get(request.id)
                        if current_request and current_request.status == SubAgentStatus.CANCELLED:
                            logger.info(
                                f"Sub-agent {request.id} completed but was cancelled - "
                                "discarding result"
                            )
                            return  # Don't save result or send notification

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

                        # Write session log even on timeout
                        if self._session_logger:
                            try:
                                log_path = self._session_logger.write_session(
                                    name=f"subagent_{request.label}",
                                    prompt=request.task,
                                    response="(timed out)",
                                    tools_used=[],
                                    metrics=None,
                                    duration_ms=duration_ms,
                                )
                                result.session_log_path = log_path
                                self._store.save_result(result)
                            except Exception as e:
                                logger.warning(f"Failed to write timeout session log for sub-agent {request.id}: {e}")

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

                    # Write session log
                    if self._session_logger:
                        try:
                            log_path = self._session_logger.write_session(
                                name=f"subagent_{request.label}",
                                prompt=request.task,
                                response=response,
                                tools_used=runner.last_tools_used or [],
                                metrics=runner.last_metrics,
                                duration_ms=duration_ms,
                            )
                            if log_path:
                                result.session_log_path = log_path
                                self._store.save_result(result)
                        except Exception as e:
                            logger.warning(f"Failed to write session log for sub-agent {request.id}: {e}")

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

                finally:
                    # Cancel the progress timer regardless of success/timeout/exception
                    if progress_task is not None:
                        progress_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await progress_task

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
                    self._store.save_result(result)
                except Exception as log_err:
                    logger.warning(f"Failed to write cancel session log for sub-agent {request.id}: {log_err}")

            logger.info(f"Sub-agent {request.id} was cancelled")

            # Notify parent — must happen before re-raise; suppress secondary CancelledError
            if request.notify:
                with contextlib.suppress(asyncio.CancelledError):
                    await self._send_notification(request, result)

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
                    self._store.save_result(result)
                except Exception as log_err:
                    logger.warning(f"Failed to write failure session log for sub-agent {request.id}: {log_err}")

            logger.error(f"Sub-agent {request.id} failed: {e}", exc_info=True)

            # Notify parent of failure
            if request.notify:
                await self._send_notification(request, result)

    @staticmethod
    def _build_origin_suffix(request: SubAgentRequest) -> str:
        """Build the origin annotation string for notification/progress messages.

        Args:
            request: The sub-agent request to read the origin from.

        Returns:
            Empty string when no origin is set, otherwise a parenthetical
            such as " (spawned by session: telegram:123456)".
        """
        if not request.origin:
            return ""
        parts = request.origin.split(":", 1)
        if len(parts) == 2:
            return f" (spawned by {parts[0]}: {parts[1]})"
        return f" (spawned by {request.origin})"

    async def _progress_timer(
        self,
        request: SubAgentRequest,
        runner: AgentRunner,
        start_time: float,
    ) -> None:
        """Emit periodic progress updates for a running sub-agent.

        Runs as a concurrent asyncio task alongside the agent execution. Reads
        runner state (tools used, current tool) which is safe because Python's
        GIL ensures atomic reads of list/string attributes.

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
                origin_suffix=self._build_origin_suffix(request),
            )

            try:
                await self._result_callback(request.session_key, content)
                logger.debug(f"Sent progress update for sub-agent {request.id}")
            except Exception as e:
                logger.warning(f"Failed to send progress for {request.id}: {e}")

    def _format_notification(self, request: SubAgentRequest, result: SubAgentResult) -> str:
        """Format a notification message for sub-agent completion.

        Args:
            request: The original sub-agent request.
            result: The execution result.

        Returns:
            Formatted notification content with [SYSTEM] prefix.
        """
        origin_suffix = self._build_origin_suffix(request)

        log_suffix = (
            f"\nFull session log: {result.session_log_path}"
            if result.session_log_path
            else ""
        )

        # Determine status and format message
        if result.error:
            if "timed out" in result.error.lower():
                return SUBAGENT_TIMED_OUT_TEMPLATE.format(
                    label=request.label,
                    timeout_minutes=request.timeout_minutes,
                    origin_suffix=origin_suffix,
                ) + log_suffix
            else:
                return SUBAGENT_FAILED_TEMPLATE.format(
                    label=request.label,
                    error=result.error,
                    origin_suffix=origin_suffix,
                ) + log_suffix
        else:
            output = result.output
            if len(output) > 500:
                output = output[:500]
                return SUBAGENT_COMPLETED_TEMPLATE.format(
                    label=request.label,
                    output=output,
                    request_id=request.id,
                    origin_suffix=origin_suffix,
                ) + log_suffix
            else:
                return SUBAGENT_COMPLETED_SHORT_TEMPLATE.format(
                    label=request.label,
                    output=output,
                    origin_suffix=origin_suffix,
                ) + log_suffix

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
