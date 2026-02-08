"""Configuration management for OpenPaw."""

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


def expand_env_vars(value: str) -> str:
    """Expand ${VAR} patterns in a string with environment variable values.

    Args:
        value: String potentially containing ${VAR_NAME} patterns.

    Returns:
        String with all ${VAR_NAME} patterns replaced by their values from os.environ.
        If a variable is not found, the pattern is left unchanged.

    Examples:
        >>> os.environ['API_KEY'] = 'secret123'
        >>> expand_env_vars('Token: ${API_KEY}')
        'Token: secret123'
    """
    pattern = r'\$\{([^}]+)\}'

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))

    return re.sub(pattern, replacer, value)


def expand_env_vars_recursive(obj: Any) -> Any:
    """Recursively expand environment variables in nested dicts and lists.

    Args:
        obj: Any Python object (dict, list, str, or other).

    Returns:
        Object with all string values having ${VAR} patterns expanded.

    Examples:
        >>> expand_env_vars_recursive({'key': '${HOME}/path', 'nested': {'val': '${USER}'}})
        {'key': '/home/user/path', 'nested': {'val': 'username'}}
    """
    if isinstance(obj, dict):
        return {key: expand_env_vars_recursive(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [expand_env_vars_recursive(item) for item in obj]
    elif isinstance(obj, str):
        return expand_env_vars(obj)
    else:
        return obj


def merge_configs(global_config: dict[str, Any], workspace_config: dict[str, Any]) -> dict[str, Any]:
    """Deep merge workspace config over global config.

    Args:
        global_config: Base configuration dictionary (defaults).
        workspace_config: Workspace-specific configuration (overrides).

    Returns:
        Merged configuration with workspace values taking precedence.
        Nested dicts are merged recursively.

    Examples:
        >>> global_cfg = {'agent': {'model': 'gpt-4', 'temp': 0.7}}
        >>> workspace_cfg = {'agent': {'model': 'claude-3'}}
        >>> merge_configs(global_cfg, workspace_cfg)
        {'agent': {'model': 'claude-3', 'temp': 0.7}}
    """
    result = copy.deepcopy(global_config)
    for key, value in workspace_config.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


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


class TelegramConfig(BaseModel):
    """Configuration for Telegram channel."""

    token: str | None = Field(default=None, description="Telegram bot token (or use TELEGRAM_BOT_TOKEN env)")
    allowed_users: list[int] = Field(default_factory=list, description="Allowed user IDs (empty = all)")
    allowed_groups: list[int] = Field(default_factory=list, description="Allowed group IDs (empty = all)")


class ChannelsConfig(BaseModel):
    """Configuration for all channels."""

    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


class AgentConfig(BaseModel):
    """Configuration for agent defaults."""

    model: str = Field(default="anthropic:claude-sonnet-4-20250514", description="Default model identifier")
    api_key: str | None = Field(default=None, description="API key for the model provider")
    max_turns: int = Field(default=50, description="Max agent turns per run")
    temperature: float = Field(default=0.7, description="Model temperature")


class CronJobConfig(BaseModel):
    """Configuration for a single cron job."""

    name: str = Field(description="Job identifier")
    agent: str = Field(description="Agent workspace name")
    schedule: str = Field(description="Cron expression (e.g., '0 9 * * *')")
    enabled: bool = Field(default=True, description="Whether the job is active")
    prompt: str | None = Field(default=None, description="Optional prompt to inject")


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
    cron: CronBuiltinConfig | None = None
    send_file: SendFileBuiltinConfig | None = None
    docling: DoclingBuiltinConfig | None = None

    model_config = {"extra": "allow"}


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


class WorkspaceConfig(BaseModel):
    """Configuration for a workspace agent (loaded from agent.yaml)."""

    name: str | None = Field(default=None, description="Agent name")
    description: str | None = Field(default=None, description="Agent description")
    timezone: str = Field(default="UTC", description="Workspace timezone (e.g., 'America/Los_Angeles')")
    model: WorkspaceModelConfig = Field(default_factory=WorkspaceModelConfig, description="LLM configuration")
    channel: WorkspaceChannelConfig = Field(default_factory=WorkspaceChannelConfig, description="Channel binding")
    queue: WorkspaceQueueConfig = Field(default_factory=WorkspaceQueueConfig, description="Queue overrides")
    builtins: WorkspaceBuiltinsConfig = Field(
        default_factory=WorkspaceBuiltinsConfig,
        description="Builtin capability overrides",
    )
    heartbeat: HeartbeatConfig | None = Field(default=None, description="Per-workspace heartbeat config")

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
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    builtins: BuiltinsConfig = Field(default_factory=BuiltinsConfig, description="Builtin capabilities config")
    cron_jobs: list[CronJobConfig] = Field(default_factory=list, description="Scheduled agent jobs")

    model_config = {"extra": "allow"}


def load_config(path: Path | str) -> Config:
    """Load configuration from a YAML file with environment variable expansion.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Parsed Config object with all ${VAR} patterns expanded.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        yaml.YAMLError: If the YAML is malformed.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open() as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    # Expand environment variables in all string values
    data = expand_env_vars_recursive(data)

    return Config(**data)
