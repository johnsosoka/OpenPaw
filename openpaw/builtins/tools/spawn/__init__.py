"""Sub-agent spawning builtin for concurrent task execution."""

import logging
from typing import Any

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools._channel_context import get_current_session_key, get_invocation_origin
from openpaw.builtins.tools.spawn.formatters import (
    format_duration,
    format_spawn_success,
    format_time_ago,
)
from openpaw.builtins.tools.spawn.models import (
    CancelSubagentInput,
    GetSubagentResultInput,
    SpawnAgentInput,
)
from openpaw.builtins.tools.spawn.tools import (
    create_cancel_subagent_tool,
    create_get_subagent_result_tool,
    create_list_subagents_tool,
    create_list_team_profiles_tool,
    create_spawn_agent_tool,
)
from openpaw.model.subagent import SubAgentStatus
from openpaw.runtime.subagent import SubAgentRunner
from openpaw.stores.subagent import create_subagent_request

logger = logging.getLogger(__name__)

__all__ = [
    "SpawnAgentInput",
    "GetSubagentResultInput",
    "CancelSubagentInput",
    "SpawnToolBuiltin",
]


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

        self.max_concurrent = self.config.get("max_concurrent", 8)
        self.default_progress_interval = self.config.get("default_progress_interval", 5)

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
            create_spawn_agent_tool(self),
            create_list_subagents_tool(self),
            create_get_subagent_result_tool(self),
            create_cancel_subagent_tool(self),
            create_list_team_profiles_tool(self),
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

    # Backward-compatible wrappers for formatters (used by existing tests)

    def _format_time_ago(self, seconds: float) -> str:
        """Format elapsed time in human-readable form.

        Deprecated: use openpaw.builtins.tools.spawn.formatters.format_time_ago.
        """
        return format_time_ago(seconds)

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable form.

        Deprecated: use openpaw.builtins.tools.spawn.formatters.format_duration.
        """
        return format_duration(seconds)

    def _format_spawn_success(self, request_id: str, label: str, timeout_minutes: int) -> str:
        """Format the success message after spawning.

        Deprecated: use openpaw.builtins.tools.spawn.formatters.format_spawn_success.
        """
        return format_spawn_success(request_id, label, timeout_minutes)
