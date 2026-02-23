"""Pydantic configuration models for OpenPaw.

This module defines all configuration dataclasses used throughout OpenPaw.
For loading and merging logic, see loader.py.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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




class WorkspaceModelConfig(BaseModel):
    """LLM configuration for a workspace agent."""

    provider: str | None = Field(default=None, description="Model provider (anthropic, openai, bedrock_converse, etc.)")
    model: str | None = Field(default=None, description="Model identifier")
    api_key: str | None = Field(default=None, description="API key for the model provider")
    temperature: float | None = Field(default=None, description="Model temperature")
    max_turns: int | None = Field(default=None, description="Max agent turns per run")
    region: str | None = Field(default=None, description="AWS region for Bedrock models (e.g., us-east-1)")

    model_config = {"extra": "allow"}


class WorkspaceChannelConfig(BaseModel):
    """Channel binding configuration for a workspace agent."""

    type: str | None = Field(default=None, description="Channel type (telegram, slack, etc.)")
    token: str | None = Field(default=None, description="Channel bot token")
    allowed_users: list[int] = Field(default_factory=list, description="Allowed user IDs")
    allowed_groups: list[int] = Field(default_factory=list, description="Allowed group IDs")
    allow_all: bool = Field(default=False, description="Allow all users (insecure, use with caution)")

    model_config = {"extra": "allow"}


class WorkspaceQueueConfig(BaseModel):
    """Queue configuration overrides for a workspace agent."""

    mode: str | None = Field(default=None, description="Queue mode: steer, followup, collect")
    debounce_ms: int | None = Field(default=None, description="Debounce delay in milliseconds")

    model_config = {"extra": "allow"}


class BuiltinItemConfig(BaseModel):
    """Configuration for a single builtin capability."""

    enabled: bool = Field(default=True, description="Whether this builtin is active")
    config: dict[str, Any] = Field(default_factory=dict, description="Builtin-specific settings")

    model_config = {"extra": "allow"}


class CronBuiltinConfig(BuiltinItemConfig):
    """Configuration for the cron scheduling tool."""

    max_tasks: int = Field(default=50, description="Maximum scheduled tasks per workspace")
    min_interval_seconds: int = Field(
        default=300, description="Minimum interval between recurring tasks (5 min default, can be lowered)"
    )


class SendFileBuiltinConfig(BuiltinItemConfig):
    """Configuration for the send_file tool."""

    max_file_size: int = Field(
        default=50 * 1024 * 1024,
        description="Maximum file size in bytes (default 50MB for Telegram)"
    )


class DoclingBuiltinConfig(BuiltinItemConfig):
    """Configuration for the Docling document processor."""

    max_file_size: int = Field(
        default=50 * 1024 * 1024,
        description="Maximum file size in bytes (default 50MB)"
    )
    ocr_backend: str = Field(
        default="auto",
        description="OCR backend: 'auto', 'mac', 'easyocr', 'tesseract', 'rapidocr'"
    )
    ocr_languages: list[str] = Field(
        default_factory=lambda: ["en"],
        description="OCR languages as ISO 639-1 codes (auto-mapped per backend)"
    )
    force_full_page_ocr: bool = Field(
        default=True,
        description="Force full-page OCR (recommended for scanned docs)"
    )
    document_timeout: float | None = Field(
        default=None,
        description="Per-document timeout in seconds (None = no limit)"
    )
    do_ocr: bool = Field(default=True, description="Enable OCR processing")
    do_table_structure: bool = Field(default=True, description="Enable table structure detection")


class BuiltinsConfig(BaseModel):
    """Global builtins configuration.

    Supports OpenClaw-style allow/deny lists with group prefixes (e.g., "group:voice").
    Deny takes precedence over allow. Empty allow list means allow all available.
    """

    allow: list[str] = Field(
        default_factory=list,
        description="Allowed builtins/groups (empty = allow all available)",
    )
    deny: list[str] = Field(
        default_factory=list,
        description="Denied builtins/groups (takes precedence over allow)",
    )

    # Per-builtin configuration
    brave_search: BuiltinItemConfig = Field(default_factory=BuiltinItemConfig)
    whisper: BuiltinItemConfig = Field(default_factory=BuiltinItemConfig)
    elevenlabs: BuiltinItemConfig = Field(default_factory=BuiltinItemConfig)
    shell: BuiltinItemConfig = Field(default_factory=BuiltinItemConfig)
    ssh: BuiltinItemConfig = Field(default_factory=BuiltinItemConfig)
    cron: CronBuiltinConfig = Field(default_factory=CronBuiltinConfig)
    send_file: SendFileBuiltinConfig = Field(default_factory=SendFileBuiltinConfig)
    docling: DoclingBuiltinConfig = Field(default_factory=DoclingBuiltinConfig)

    model_config = {"extra": "allow"}


class WorkspaceBuiltinsConfig(BaseModel):
    """Per-workspace builtins configuration (overrides global)."""

    allow: list[str] = Field(
        default_factory=list,
        description="Additional allowed builtins for this workspace",
    )
    deny: list[str] = Field(
        default_factory=list,
        description="Builtins to disable for this workspace",
    )

    # Per-builtin overrides
    brave_search: BuiltinItemConfig | None = None
    whisper: BuiltinItemConfig | None = None
    elevenlabs: BuiltinItemConfig | None = None
    shell: BuiltinItemConfig | None = None
    ssh: BuiltinItemConfig | None = None
    cron: CronBuiltinConfig | None = None
    send_file: SendFileBuiltinConfig | None = None
    docling: DoclingBuiltinConfig | None = None

    model_config = {"extra": "allow"}


class WorkspaceToolsConfig(BaseModel):
    """Allow/deny list for workspace tools loaded from tools/ directory."""

    allow: list[str] = Field(default_factory=list, description="Allowed tool names (empty = allow all)")
    deny: list[str] = Field(default_factory=list, description="Denied tool names")


class HeartbeatConfig(BaseModel):
    """Configuration for the heartbeat scheduler."""

    enabled: bool = Field(default=False, description="Enable periodic heartbeat prompts")
    interval_minutes: int = Field(default=30, description="Minutes between heartbeat checks")
    active_hours: str | None = Field(
        default=None,
        description="Active hours window (e.g., '08:00-22:00'). None = always active",
    )
    suppress_ok: bool = Field(default=True, description="Suppress HEARTBEAT_OK responses from channel")
    target_channel: str = Field(default="telegram", description="Channel to route heartbeat responses")
    target_chat_id: int | None = Field(default=None, description="Default chat ID for heartbeat output")
    delivery: Literal["channel", "agent", "both"] = Field(
        default="channel",
        description="Where to deliver results: channel (direct), agent (queue injection), both",
    )


class ToolApprovalConfig(BaseModel):
    """Configuration for a single tool's approval requirements."""

    require_approval: bool = Field(
        default=True,
        description="Whether this tool requires user approval before execution",
    )
    show_args: bool = Field(
        default=True,
        description="Whether to show tool arguments in the approval prompt",
    )


class ApprovalGatesConfig(BaseModel):
    """Root configuration for the approval gates system."""

    enabled: bool = Field(
        default=False,
        description="Whether approval gates are active for this workspace",
    )
    timeout_seconds: int = Field(
        default=120,
        description="Seconds to wait for user approval before applying default action",
    )
    default_action: str = Field(
        default="deny",
        description="Action when approval times out: 'deny' or 'approve'",
    )
    tools: dict[str, ToolApprovalConfig] = Field(
        default_factory=dict,
        description="Per-tool approval configuration (tool_name -> config)",
    )


class EmbeddingConfig(BaseModel):
    """Configuration for the embedding provider."""

    provider: str = Field(default="openai", description="Embedding provider (openai)")
    model: str = Field(default="text-embedding-3-small", description="Embedding model name")
    api_key: str | None = Field(default=None, description="API key for embedding provider")


class VectorStoreConfig(BaseModel):
    """Configuration for the vector store backend."""

    provider: str = Field(
        default="sqlite_vec", description="Vector store provider (sqlite_vec)"
    )
    dimensions: int = Field(default=1536, description="Embedding dimensions")


class MemoryConfig(BaseModel):
    """Configuration for conversation memory and vector search."""

    enabled: bool = Field(default=False, description="Enable conversation vector search")
    vector_store: VectorStoreConfig = Field(
        default_factory=VectorStoreConfig, description="Vector store backend config"
    )
    embedding: EmbeddingConfig = Field(
        default_factory=EmbeddingConfig, description="Embedding provider config"
    )


class ToolTimeoutsConfig(BaseModel):
    """Configuration for per-tool-call timeouts."""

    default_seconds: int = Field(
        default=120,
        description="Default timeout for tool calls in seconds",
    )
    overrides: dict[str, int] = Field(
        default_factory=dict,
        description="Per-tool timeout overrides (tool_name -> timeout_seconds)",
    )


class WorkspaceConfig(BaseModel):
    """Configuration for a workspace agent (loaded from agent.yaml)."""

    timezone: str = Field(default="UTC", description="Workspace timezone (e.g., 'America/Los_Angeles')")
    model: WorkspaceModelConfig = Field(default_factory=WorkspaceModelConfig, description="LLM configuration")
    channel: WorkspaceChannelConfig = Field(default_factory=WorkspaceChannelConfig, description="Channel binding")
    queue: WorkspaceQueueConfig = Field(default_factory=WorkspaceQueueConfig, description="Queue overrides")
    builtins: WorkspaceBuiltinsConfig = Field(
        default_factory=WorkspaceBuiltinsConfig,
        description="Builtin capability overrides",
    )
    heartbeat: HeartbeatConfig | None = Field(default=None, description="Per-workspace heartbeat config")
    workspace_tools: WorkspaceToolsConfig = Field(
        default_factory=WorkspaceToolsConfig,
        description="Allow/deny list for workspace tools",
    )
    approval_gates: ApprovalGatesConfig = Field(
        default_factory=ApprovalGatesConfig,
        description="Approval gates configuration",
    )
    tool_timeouts: ToolTimeoutsConfig = Field(
        default_factory=ToolTimeoutsConfig,
        description="Per-tool-call timeout configuration",
    )
    memory: MemoryConfig = Field(
        default_factory=MemoryConfig,
        description="Conversation memory and vector search configuration",
    )

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate timezone is a valid IANA timezone identifier."""
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, KeyError):
            raise ValueError(
                f"Invalid timezone '{v}'. Use IANA timezone identifiers "
                f"(e.g., 'America/Denver', 'Europe/London', 'UTC')."
            )
        return v

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

    model_config = {"extra": "allow"}
