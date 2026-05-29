"""Root / global configuration models for OpenPaw."""

from pathlib import Path

from pydantic import BaseModel, Field

from openpaw.core.config.models.builtin import BuiltinsConfig
from openpaw.core.config.models.security import ApprovalGatesConfig, ToolTimeoutsConfig


class QueueConfig(BaseModel):
    """Configuration for the command queue system."""

    mode: str = Field(default="collect", description="Default queue mode: steer, followup, collect")
    debounce_ms: int = Field(default=1000, description="Debounce delay in milliseconds")
    cap: int = Field(default=20, description="Max queued messages per session")
    drop_policy: str = Field(default="summarize", description="Overflow policy: old, new, summarize")


class LaneConfig(BaseModel):
    """Configuration for queue lanes."""

    main_concurrency: int = Field(default=4, description="Max concurrent runs in main lane")
    subagent_concurrency: int = Field(default=8, description="Max concurrent runs in subagent lane")
    cron_concurrency: int = Field(default=2, description="Max concurrent runs in cron lane")


class AgentConfig(BaseModel):
    """Configuration for agent defaults."""

    model: str = Field(default="anthropic:claude-sonnet-4-20250514", description="Default model identifier")
    api_key: str | None = Field(default=None, description="API key for the model provider")
    max_turns: int = Field(default=50, description="Max agent turns per run")
    temperature: float = Field(default=0.7, description="Model temperature")


class ProviderDefinition(BaseModel):
    """Named provider in the global catalog.

    Defines connection details (type, api_key, base_url, region) that can be
    referenced by name from workspace model configurations.
    """

    type: str | None = Field(default=None, description="LangChain provider type. Defaults to catalog key name.")
    api_key: str | None = Field(default=None, description="API key for the provider")
    base_url: str | None = Field(default=None, description="Custom API endpoint URL")
    region: str | None = Field(default=None, description="AWS region for Bedrock models")

    model_config = {"extra": "allow"}


class LoggingConfig(BaseModel):
    """Configuration for logging system."""

    level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    directory: str = Field(default="logs", description="Directory for log files")
    max_size_mb: int = Field(default=10, description="Maximum log file size in MB before rotation")
    backup_count: int = Field(default=5, description="Number of backup log files to keep")
    per_workspace: bool = Field(default=True, description="Create separate log files per workspace")


class Config(BaseModel):
    """Root configuration for OpenPaw."""

    workspaces_path: Path = Field(default=Path("agent_workspaces"), description="Path to agent workspaces")
    logging: LoggingConfig = Field(default_factory=LoggingConfig, description="Logging configuration")
    providers: dict[str, ProviderDefinition] = Field(
        default_factory=dict,
        description="Named provider catalog for reusable connection details",
    )
    queue: QueueConfig = Field(default_factory=QueueConfig)
    lanes: LaneConfig = Field(default_factory=LaneConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    builtins: BuiltinsConfig = Field(default_factory=BuiltinsConfig, description="Builtin capabilities config")
    approval_gates: ApprovalGatesConfig = Field(
        default_factory=ApprovalGatesConfig,
        description="Default approval gates configuration",
    )
    tool_timeouts: ToolTimeoutsConfig = Field(
        default_factory=ToolTimeoutsConfig,
        description="Default tool timeout configuration",
    )
    team_profiles_path: str | None = Field(
        default=None,
        description="Path to system-level spawn profiles directory (available to all workspaces)",
    )

    model_config = {"extra": "allow"}
