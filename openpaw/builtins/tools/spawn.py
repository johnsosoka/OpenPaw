"""Sub-agent spawning builtin for concurrent task execution."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools._channel_context import get_current_session_key, get_invocation_origin
from openpaw.model.subagent import SubAgentStatus
from openpaw.runtime.subagent import SubAgentRunner
from openpaw.stores.subagent import create_subagent_request

logger = logging.getLogger(__name__)


class SpawnAgentInput(BaseModel):
    """Input schema for spawning a sub-agent."""

    task: str = Field(description="Detailed instruction for the sub-agent to execute")
    label: str = Field(
        description="Short human-readable label (e.g., 'research-topic-x', 'analyze-report')"
    )
    timeout_minutes: int = Field(
        default=30, ge=1, le=120, description="Maximum runtime in minutes (1-120)"
    )
    notify: bool = Field(
        default=True, description="Whether to send notification when done"
    )
    progress_interval_minutes: int = Field(
        default=0,
        ge=0,
        description=(
            "How often to send progress updates in minutes. "
            "0 disables progress updates. When enabled, sends elapsed time, "
            "tools used, and current activity to the main agent."
        ),
    )
    allowed_tools: list[str] | None = Field(
        default=None,
        description=(
            "Optional whitelist of tool names the sub-agent may use. Supports 'group:' prefix "
            "(e.g., 'group:web'). If specified, only listed tools are available "
            "(plus always-excluded tools are still removed)."
        ),
    )
    denied_tools: list[str] | None = Field(
        default=None,
        description=(
            "Optional additional tools to deny the sub-agent. Supports 'group:' prefix. "
            "Applied after allowed_tools filtering."
        ),
    )
    profile: str | None = Field(
        default=None,
        description=(
            "Optional spawn profile name. Use list_team_profiles to see available profiles. "
            "Profiles provide preset system prompts, tool restrictions, and model overrides. "
            "Per-spawn allowed_tools/denied_tools further restrict the profile's tool set."
        ),
    )


class GetSubagentResultInput(BaseModel):
    """Input schema for getting a sub-agent result."""

    id: str = Field(description="The sub-agent ID returned from spawn_agent")


class CancelSubagentInput(BaseModel):
    """Input schema for canceling a sub-agent."""

    id: str = Field(description="The sub-agent ID to cancel")


class SpawnToolBuiltin(BaseBuiltinTool):
    """Sub-agent spawning for concurrent background task execution.

    Enables agents to:
    - Spawn background sub-agents for concurrent task execution
    - Check status of active sub-agents
    - Retrieve results from completed sub-agents
    - Cancel running sub-agents

    Sub-agents run in isolated contexts with filtered tools (no recursion, no
    unsolicited messaging, no self-continuation). They're ideal for:
    - Parallel research or data gathering
    - Long-running analysis tasks
    - Concurrent API operations
    - Multi-step workflows that don't block the main agent

    Config options:
        max_concurrent: Maximum simultaneous sub-agents (default: 8)
    """

    metadata = BuiltinMetadata(
        name="spawn",
        display_name="Sub-Agent Spawning",
        description="Spawn background sub-agents for concurrent task execution",
        builtin_type=BuiltinType.TOOL,
        group="automation",
        prerequisites=BuiltinPrerequisite(),  # No API key required
    )

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the spawn tool builtin.

        Args:
            config: Configuration dict containing:
                - max_concurrent: Maximum concurrent sub-agents (default: 8)
        """
        super().__init__(config)

        # Extract configuration
        self.max_concurrent = self.config.get("max_concurrent", 8)
        self.default_progress_interval = self.config.get("default_progress_interval", 5)

        # Runner reference (set via set_runner after initialization)
        self._runner: SubAgentRunner | None = None

        logger.info(
            f"SpawnToolBuiltin initialized "
            f"(max_concurrent: {self.max_concurrent}, "
            f"default_progress_interval: {self.default_progress_interval})"
        )

    def set_runner(self, runner: SubAgentRunner) -> None:
        """Set the SubAgentRunner reference for live spawning.

        Called after SubAgentRunner is initialized to enable spawning.

        Args:
            runner: SubAgentRunner instance.
        """
        self._runner = runner
        logger.info("SpawnTool connected to SubAgentRunner")

    def get_langchain_tool(self) -> Any:
        """Return spawn tools as a list of LangChain StructuredTools."""
        return [
            self._create_spawn_agent_tool(),
            self._create_list_subagents_tool(),
            self._create_get_subagent_result_tool(),
            self._create_cancel_subagent_tool(),
            self._create_list_team_profiles_tool(),
        ]

    def _build_spawn_request(
        self,
        task: str,
        label: str,
        timeout_minutes: int,
        notify: bool,
        progress_interval_minutes: int,
        allowed_tools: list[str] | None,
        denied_tools: list[str] | None,
        profile: str | None = None,
    ) -> Any:
        """Validate inputs and build a SubAgentRequest.

        Returns:
            SubAgentRequest on success, or an error string on failure.
        """
        if self._runner is None:
            return "[Error: Sub-agent spawning not available (runner not initialized)]"

        session_key = get_current_session_key()
        if not session_key:
            return "[Error: Cannot spawn sub-agent: no active session context]"

        # Resolve progress interval: apply workspace default, clamp to timeout
        if progress_interval_minutes == 0 and self.default_progress_interval > 0:
            progress_interval_minutes = self.default_progress_interval
        if progress_interval_minutes > 0 and progress_interval_minutes > timeout_minutes:
            progress_interval_minutes = timeout_minutes

        request = create_subagent_request(
            task=task,
            label=label,
            session_key=session_key,
            status=SubAgentStatus.PENDING,
            timeout_minutes=timeout_minutes,
            notify=notify,
            allowed_tools=allowed_tools,
            denied_tools=denied_tools,
            origin=get_invocation_origin(),
            progress_interval_minutes=progress_interval_minutes,
            profile=profile,
        )

        try:
            self._runner._store.create(request)
        except Exception as e:
            logger.error(f"Failed to create sub-agent request: {e}")
            return f"[Error: Failed to create sub-agent request: {e}]"

        return request

    @staticmethod
    def _format_spawn_success(request_id: str, label: str, timeout_minutes: int) -> str:
        """Format the success message after spawning."""
        return (
            f"Sub-agent spawned: {request_id}\n"
            f"Label: {label}\n"
            f"Timeout: {timeout_minutes}min\n"
            f"Use list_subagents to check status."
        )

    def _create_spawn_agent_tool(self) -> StructuredTool:
        """Create the spawn_agent tool."""

        def spawn_agent_sync(
            task: str,
            label: str,
            timeout_minutes: int = 30,
            notify: bool = True,
            progress_interval_minutes: int = 0,
            allowed_tools: list[str] | None = None,
            denied_tools: list[str] | None = None,
            profile: str | None = None,
        ) -> str:
            """Sync wrapper for spawn_agent (for LangChain compatibility)."""
            result = self._build_spawn_request(
                task, label, timeout_minutes, notify,
                progress_interval_minutes, allowed_tools, denied_tools, profile,
            )
            if isinstance(result, str):
                return result
            request = result

            try:
                try:
                    loop = asyncio.get_running_loop()
                    future = asyncio.run_coroutine_threadsafe(
                        self._runner.spawn(request), loop
                    )
                    request_id = future.result(timeout=5.0)
                except RuntimeError:
                    request_id = asyncio.run(self._runner.spawn(request))

                logger.info(f"Spawned sub-agent: {request_id} ('{label}')")
                return self._format_spawn_success(request_id, label, timeout_minutes)
            except Exception as e:
                logger.error(f"Failed to spawn sub-agent: {e}")
                return f"[Error: Failed to spawn sub-agent: {e}]"

        async def spawn_agent_async(
            task: str,
            label: str,
            timeout_minutes: int = 30,
            notify: bool = True,
            progress_interval_minutes: int = 0,
            allowed_tools: list[str] | None = None,
            denied_tools: list[str] | None = None,
            profile: str | None = None,
        ) -> str:
            """Spawn a new sub-agent to execute a task in the background."""
            result = self._build_spawn_request(
                task, label, timeout_minutes, notify,
                progress_interval_minutes, allowed_tools, denied_tools, profile,
            )
            if isinstance(result, str):
                return result
            request = result

            try:
                request_id = await self._runner.spawn(request)
                logger.info(f"Spawned sub-agent: {request_id} ('{label}')")
                return self._format_spawn_success(request_id, label, timeout_minutes)
            except Exception as e:
                logger.error(f"Failed to spawn sub-agent: {e}")
                return f"[Error: Failed to spawn sub-agent: {e}]"

        return StructuredTool.from_function(
            func=spawn_agent_sync,
            coroutine=spawn_agent_async,
            name="spawn_agent",
            description=(
                "Spawn a background sub-agent to execute a task concurrently. "
                "Use this for parallel work that doesn't need to block your response. "
                "Sub-agents run independently and can notify you when complete. "
                "Ideal for: parallel research, long-running analysis, concurrent API calls."
            ),
            args_schema=SpawnAgentInput,
        )

    def _create_list_team_profiles_tool(self) -> StructuredTool:
        """Create the list_team_profiles tool."""

        def list_team_profiles() -> str:
            """List available spawn profiles for sub-agent specialization."""
            if self._runner is None:
                return "[Error: Spawn profiles not available (runner not initialized)]"

            resolver = self._runner._profile_resolver
            if resolver is None or len(resolver) == 0:
                return "No spawn profiles configured."

            profiles = resolver.list_profiles()
            lines = [f"Available spawn profiles ({len(profiles)}):"]
            lines.append("")

            for p in profiles:
                lines.append(f"**{p.name}** ({p.source})")
                if p.description:
                    lines.append(f"  {p.description}")
                if p.model:
                    lines.append(f"  Model: {p.model}")
                if p.allowed_tools:
                    lines.append(f"  Allowed tools: {', '.join(p.allowed_tools)}")
                if p.denied_tools:
                    lines.append(f"  Denied tools: {', '.join(p.denied_tools)}")
                if p.allowed_skills is not None:
                    if p.allowed_skills:
                        lines.append(f"  Allowed skills: {', '.join(p.allowed_skills)}")
                    else:
                        lines.append("  Skills: none (all disabled)")
                if p.denied_skills:
                    lines.append(f"  Denied skills: {', '.join(p.denied_skills)}")
                if p.timeout_minutes:
                    lines.append(f"  Timeout: {p.timeout_minutes}min")
                if p.max_turns:
                    lines.append(f"  Max turns: {p.max_turns}")
                lines.append("")

            return "\n".join(lines)

        return StructuredTool.from_function(
            func=list_team_profiles,
            name="list_team_profiles",
            description=(
                "List available spawn profiles for sub-agent specialization. "
                "Shows profile names, descriptions, model overrides, and tool restrictions. "
                "Use a profile name with spawn_agent(profile='name') for specialized sub-agents."
            ),
        )

    def _create_list_subagents_tool(self) -> StructuredTool:
        """Create the list_subagents tool."""

        def list_subagents() -> str:
            """List all sub-agents (active and recent).

            Returns:
                Formatted list of sub-agents.
            """
            # Guard: check if runner is set
            if self._runner is None:
                return "[Error: Sub-agent listing not available (runner not initialized)]"

            # Get active and recent sub-agents
            active = self._runner.list_active()
            recent = self._runner.list_recent(limit=10)

            if not active and not recent:
                return "No sub-agents found."

            lines = []
            now = datetime.now(UTC)

            # Format active sub-agents
            if active:
                lines.append("Active Sub-agents:")
                for request in active:
                    # Calculate time since start
                    start_time = request.started_at or request.created_at
                    elapsed = now - start_time
                    time_ago = self._format_time_ago(elapsed.total_seconds())

                    lines.append(
                        f"- {request.id} | {request.label} | {request.status.value} | started {time_ago}"
                    )
                lines.append("")

            # Format recent completed sub-agents
            completed = [r for r in recent if r.status not in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING)]
            if completed:
                lines.append("Recent (completed):")
                for request in completed:
                    # Calculate duration
                    if request.completed_at and request.started_at:
                        duration = request.completed_at - request.started_at
                        duration_str = self._format_duration(duration.total_seconds())
                    else:
                        duration_str = "unknown"

                    lines.append(
                        f"- {request.id} | {request.label} | {request.status.value} | {duration_str}"
                    )

            return "\n".join(lines) if lines else "No sub-agents found."

        return StructuredTool.from_function(
            func=list_subagents,
            name="list_subagents",
            description=(
                "List all sub-agents (active and recently completed). "
                "Shows status, labels, and timing information. "
                "Use this to check on spawned background tasks."
            ),
        )

    def _create_get_subagent_result_tool(self) -> StructuredTool:
        """Create the get_subagent_result tool."""

        def get_subagent_result(id: str) -> str:
            """Get the result of a sub-agent by ID.

            Args:
                id: The sub-agent ID.

            Returns:
                Sub-agent result or status message.
            """
            # Guard: check if runner is set
            if self._runner is None:
                return "[Error: Sub-agent results not available (runner not initialized)]"

            # Get request status
            request = self._runner.get_status(id)
            if not request:
                return f"Sub-agent not found: {id}"

            # If still running, return status
            if request.status == SubAgentStatus.RUNNING:
                start_time = request.started_at or request.created_at
                elapsed = datetime.now(UTC) - start_time
                time_ago = self._format_time_ago(elapsed.total_seconds())
                return f"Sub-agent '{request.label}' is still running (started {time_ago})"

            if request.status == SubAgentStatus.PENDING:
                return f"Sub-agent '{request.label}' is pending (not started yet)"

            # Get result
            result = self._runner.get_result(id)
            if not result:
                return f"Sub-agent '{request.label}' has no result (status: {request.status.value})"

            # Format result
            lines = [
                f"Sub-agent: {request.label} ({id[:8]})",
                f"Status: {request.status.value}",
                f"Duration: {self._format_duration(result.duration_ms / 1000)}",
            ]

            if result.token_count > 0:
                lines.append(f"Tokens: {result.token_count}")

            if result.session_log_path:
                lines.append(f"Session log: {result.session_log_path}")

            if result.error:
                lines.append(f"\nError: {result.error}")
            else:
                lines.append("\nOutput:")
                # Truncate if too long
                output = result.output
                if len(output) > 5000:
                    output = output[:5000] + "\n\n[Output truncated - see full result in storage]"
                lines.append(output)

            return "\n".join(lines)

        return StructuredTool.from_function(
            func=get_subagent_result,
            name="get_subagent_result",
            description=(
                "Get the result of a completed sub-agent by ID. "
                "Returns the full output, token count, duration, and any errors. "
                "If the sub-agent is still running, returns status instead."
            ),
            args_schema=GetSubagentResultInput,
        )

    def _create_cancel_subagent_tool(self) -> StructuredTool:
        """Create the cancel_subagent tool."""

        def cancel_subagent_sync(id: str) -> str:
            """Sync wrapper for cancel_subagent.

            Args:
                id: The sub-agent ID to cancel.

            Returns:
                Confirmation message or error.
            """
            # Guard: check if runner is set
            if self._runner is None:
                return "[Error: Sub-agent cancellation not available (runner not initialized)]"

            try:
                # Get or create event loop
                try:
                    loop = asyncio.get_running_loop()
                    future = asyncio.run_coroutine_threadsafe(
                        self._runner.cancel(id), loop
                    )
                    success = future.result(timeout=5.0)
                except RuntimeError:
                    # No running loop - safe to use asyncio.run
                    success = asyncio.run(self._runner.cancel(id))

                if success:
                    logger.info(f"Cancelled sub-agent: {id}")
                    return f"Sub-agent {id} cancelled successfully."
                else:
                    return f"Sub-agent {id} not found or already completed."
            except Exception as e:
                logger.error(f"Failed to cancel sub-agent: {e}")
                return f"[Error: Failed to cancel sub-agent: {e}]"

        async def cancel_subagent_async(id: str) -> str:
            """Cancel a running sub-agent.

            Args:
                id: The sub-agent ID to cancel.

            Returns:
                Confirmation message or error.
            """
            # Guard: check if runner is set
            if self._runner is None:
                return "[Error: Sub-agent cancellation not available (runner not initialized)]"

            try:
                success = await self._runner.cancel(id)
                if success:
                    logger.info(f"Cancelled sub-agent: {id}")
                    return f"Sub-agent {id} cancelled successfully."
                else:
                    return f"Sub-agent {id} not found or already completed."
            except Exception as e:
                logger.error(f"Failed to cancel sub-agent: {e}")
                return f"[Error: Failed to cancel sub-agent: {e}]"

        return StructuredTool.from_function(
            func=cancel_subagent_sync,
            coroutine=cancel_subagent_async,
            name="cancel_subagent",
            description=(
                "Cancel a running sub-agent by ID. "
                "Use this to stop sub-agents that are no longer needed or are taking too long."
            ),
            args_schema=CancelSubagentInput,
        )

    def _format_time_ago(self, seconds: float) -> str:
        """Format elapsed time in human-readable form.

        Args:
            seconds: Seconds elapsed.

        Returns:
            Human-readable string (e.g., "5m ago", "2h ago").
        """
        if seconds < 60:
            return f"{int(seconds)}s ago"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}m ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h ago"
        else:
            days = int(seconds / 86400)
            return f"{days}d ago"

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable form.

        Args:
            seconds: Duration in seconds.

        Returns:
            Human-readable string (e.g., "5m", "2h").
        """
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}m"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h"
        else:
            days = int(seconds / 86400)
            return f"{days}d"
