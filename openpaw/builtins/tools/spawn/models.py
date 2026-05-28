"""Pydantic input schemas for spawn tools."""

from pydantic import BaseModel, Field


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
