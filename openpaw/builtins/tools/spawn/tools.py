"""LangChain tool factories for spawn builtin."""

import asyncio
import logging
from typing import Any

from langchain_core.tools import StructuredTool

from openpaw.builtins.tools.spawn.formatters import format_spawn_success
from openpaw.builtins.tools.spawn.models import (
    CancelSubagentInput,
    GetSubagentResultInput,
    SpawnAgentInput,
)
from openpaw.model.subagent import SubAgentStatus

logger = logging.getLogger(__name__)


def create_spawn_agent_tool(builtin: Any) -> StructuredTool:
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
        result = builtin._build_spawn_request(
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
                    builtin._runner.spawn(request), loop
                )
                request_id = future.result(timeout=5.0)
            except RuntimeError:
                request_id = asyncio.run(builtin._runner.spawn(request))

            logger.info(f"Spawned sub-agent: {request_id} ('{label}')")
            return format_spawn_success(request_id, label, timeout_minutes)
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
        result = builtin._build_spawn_request(
            task, label, timeout_minutes, notify,
            progress_interval_minutes, allowed_tools, denied_tools, profile,
        )
        if isinstance(result, str):
            return result
        request = result

        try:
            request_id = await builtin._runner.spawn(request)
            logger.info(f"Spawned sub-agent: {request_id} ('{label}')")
            return format_spawn_success(request_id, label, timeout_minutes)
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


def create_list_team_profiles_tool(builtin: Any) -> StructuredTool:
    """Create the list_team_profiles tool."""

    def list_team_profiles() -> str:
        """List available spawn profiles for sub-agent specialization."""
        if builtin._runner is None:
            return "[Error: Spawn profiles not available (runner not initialized)]"

        resolver = builtin._runner._profile_resolver
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


def create_list_subagents_tool(builtin: Any) -> StructuredTool:
    """Create the list_subagents tool."""

    from openpaw.builtins.tools.spawn.formatters import format_duration, format_time_ago

    def list_subagents() -> str:
        """List all sub-agents (active and recent)."""
        if builtin._runner is None:
            return "[Error: Sub-agent listing not available (runner not initialized)]"

        active = builtin._runner.list_active()
        recent = builtin._runner.list_recent(limit=10)

        if not active and not recent:
            return "No sub-agents found."

        lines = []
        from datetime import UTC, datetime

        now = datetime.now(UTC)

        if active:
            lines.append("Active Sub-agents:")
            for request in active:
                start_time = request.started_at or request.created_at
                elapsed = now - start_time
                time_ago = format_time_ago(elapsed.total_seconds())
                lines.append(
                    f"- {request.id} | {request.label} | {request.status.value} | started {time_ago}"
                )
            lines.append("")

        completed = [r for r in recent if r.status not in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING)]
        if completed:
            lines.append("Recent (completed):")
            for request in completed:
                if request.completed_at and request.started_at:
                    duration = request.completed_at - request.started_at
                    duration_str = format_duration(duration.total_seconds())
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


def create_get_subagent_result_tool(builtin: Any) -> StructuredTool:
    """Create the get_subagent_result tool."""

    from datetime import UTC, datetime

    from openpaw.builtins.tools.spawn.formatters import format_duration, format_time_ago

    def get_subagent_result(id: str) -> str:
        """Get the result of a sub-agent by ID."""
        if builtin._runner is None:
            return "[Error: Sub-agent results not available (runner not initialized)]"

        request = builtin._runner.get_status(id)
        if not request:
            return f"Sub-agent not found: {id}"

        if request.status == SubAgentStatus.RUNNING:
            start_time = request.started_at or request.created_at
            elapsed = datetime.now(UTC) - start_time
            time_ago = format_time_ago(elapsed.total_seconds())
            return f"Sub-agent '{request.label}' is still running (started {time_ago})"

        if request.status == SubAgentStatus.PENDING:
            return f"Sub-agent '{request.label}' is pending (not started yet)"

        result = builtin._runner.get_result(id)
        if not result:
            return f"Sub-agent '{request.label}' has no result (status: {request.status.value})"

        lines = [
            f"Sub-agent: {request.label} ({id[:8]})",
            f"Status: {request.status.value}",
            f"Duration: {format_duration(result.duration_ms / 1000)}",
        ]

        if result.token_count > 0:
            lines.append(f"Tokens: {result.token_count}")

        if result.session_log_path:
            lines.append(f"Session log: {result.session_log_path}")

        if result.error:
            lines.append(f"\nError: {result.error}")
        else:
            lines.append("\nOutput:")
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


def create_cancel_subagent_tool(builtin: Any) -> StructuredTool:
    """Create the cancel_subagent tool."""

    def cancel_subagent_sync(id: str) -> str:
        """Sync wrapper for cancel_subagent."""
        if builtin._runner is None:
            return "[Error: Sub-agent cancellation not available (runner not initialized)]"

        try:
            try:
                loop = asyncio.get_running_loop()
                future = asyncio.run_coroutine_threadsafe(
                    builtin._runner.cancel(id), loop
                )
                success = future.result(timeout=5.0)
            except RuntimeError:
                success = asyncio.run(builtin._runner.cancel(id))

            if success:
                logger.info(f"Cancelled sub-agent: {id}")
                return f"Sub-agent {id} cancelled successfully."
            else:
                return f"Sub-agent {id} not found or already completed."
        except Exception as e:
            logger.error(f"Failed to cancel sub-agent: {e}")
            return f"[Error: Failed to cancel sub-agent: {e}]"

    async def cancel_subagent_async(id: str) -> str:
        """Cancel a running sub-agent."""
        if builtin._runner is None:
            return "[Error: Sub-agent cancellation not available (runner not initialized)]"

        try:
            success = await builtin._runner.cancel(id)
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
