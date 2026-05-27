"""Per-workspace configuration models for OpenPaw."""

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from openpaw.core.config.models.builtin import WorkspaceBuiltinsConfig
from openpaw.core.config.models.channel import WorkspaceChannelConfig
from openpaw.core.config.models.cron import HeartbeatConfig
from openpaw.core.config.models.lifecycle import LifecycleConfig, StatusReminderConfig
from openpaw.core.config.models.memory import AutoCompactConfig, MemoryConfig
from openpaw.core.config.models.security import ApprovalGatesConfig, ToolTimeoutsConfig


class WorkspaceModelConfig(BaseModel):
    """LLM configuration for a workspace agent."""

    provider: str | None = Field(default=None, description="Model provider (anthropic, openai, bedrock_converse, etc.)")
    model: str | None = Field(default=None, description="Model identifier")
    api_key: str | None = Field(default=None, description="API key for the model provider")
    temperature: float | None = Field(default=None, description="Model temperature")
    max_turns: int | None = Field(default=None, description="Max agent turns per run")
    region: str | None = Field(default=None, description="AWS region for Bedrock models (e.g., us-east-1)")
    max_output_tokens: int | None = Field(
        default=None,
        description="Maximum output tokens per LLM call (None = provider default). Applied to all agent types.",
    )
    max_retries: int | None = Field(
        default=3,
        description=(
            "Max retry attempts on transient API errors (504, 429, connection errors). "
            "None or 0 disables retries. Bedrock is excluded (boto3 manages its own retries)."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def split_combined_model_string(cls, data: Any) -> Any:
        """Auto-split 'provider:model_id' into separate fields.

        Supports combined format like "anthropic:claude-sonnet-4-20250514"
        when provider is not explicitly set. Only splits on the first colon
        to handle Bedrock IDs like "us.anthropic.claude-haiku:v1:0".
        """
        if not isinstance(data, dict):
            return data
        model_val = data.get("model")
        provider_val = data.get("provider")
        if model_val and provider_val is None and isinstance(model_val, str) and ":" in model_val:
            provider, _, model_id = model_val.partition(":")
            data["provider"] = provider
            data["model"] = model_id
        return data

    model_config = {"extra": "allow"}


class WorkspaceQueueConfig(BaseModel):
    """Queue configuration overrides for a workspace agent."""

    mode: str | None = Field(default=None, description="Queue mode: steer, followup, collect")
    debounce_ms: int | None = Field(default=None, description="Debounce delay in milliseconds")

    model_config = {"extra": "allow"}


class WorkspaceToolsConfig(BaseModel):
    """Allow/deny list for workspace tools loaded from tools/ directory."""

    allow: list[str] = Field(default_factory=list, description="Allowed tool names (empty = allow all)")
    deny: list[str] = Field(default_factory=list, description="Denied tool names")


class WorkspaceConfig(BaseModel):
    """Configuration for a workspace agent (loaded from agent.yaml).

    Supports shorthand ``model: "provider:model_id"`` in agent.yaml, which is
    coerced to ``model: {provider: ..., model: ...}`` before validation.

    Channels can be configured as a single ``channel:`` block (backward compat)
    or as a ``channels:`` list for multi-channel workspaces. The model_validator
    normalizes both forms into the ``channels`` list.
    """

    @model_validator(mode="before")
    @classmethod
    def normalize_channel_config(cls, data: Any) -> Any:
        """Normalize channel/channels config and coerce model shorthand.

        Handles:
        - ``model: 'provider:model_id'`` shorthand → dict
        - ``channel:`` (singular) → ``channels: [channel]``
        - ``channels:`` (list) → used as-is
        - Both present → ValueError
        """
        if not isinstance(data, dict):
            return data

        # Coerce model shorthand
        if isinstance(data.get("model"), str):
            model_str = data["model"]
            if ":" in model_str:
                p, _, m = model_str.partition(":")
                data["model"] = {"provider": p, "model": m}
            else:
                data["model"] = {"model": model_str}

        # Normalize channel → channels
        has_channel = "channel" in data and data["channel"]
        has_channels = "channels" in data and data["channels"]

        if has_channel and has_channels:
            raise ValueError(
                "Cannot specify both 'channel' and 'channels' in workspace config. "
                "Use 'channels' (list) for multi-channel or 'channel' (dict) for single."
            )

        if has_channel:
            data["channels"] = [data.pop("channel")]
        else:
            data.pop("channel", None)

        return data

    timezone: str = Field(default="UTC", description="Workspace timezone (e.g., 'America/Los_Angeles')")
    model: WorkspaceModelConfig = Field(default_factory=WorkspaceModelConfig, description="LLM configuration")
    channels: list[WorkspaceChannelConfig] = Field(
        default_factory=list,
        description="Channel bindings (list). Use singular 'channel:' in YAML for backward compat.",
    )
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
    auto_compact: AutoCompactConfig = Field(
        default_factory=AutoCompactConfig,
        description="Auto-compact configuration",
    )
    session_ttl_minutes: int = Field(
        default=180,
        description="Auto-reset conversation after N minutes of inactivity (0 to disable)",
    )
    checkpoint_retention_days: int = Field(
        default=7,
        description="Prune orphaned checkpoint data older than N days at startup (0 to disable)",
    )
    lifecycle: LifecycleConfig = Field(
        default_factory=LifecycleConfig,
        description="Lifecycle notification configuration",
    )
    status_reminder: StatusReminderConfig = Field(
        default_factory=StatusReminderConfig,
        description="Status reminder middleware configuration",
    )

    @field_validator("session_ttl_minutes")
    @classmethod
    def validate_session_ttl_minutes(cls, v: int) -> int:
        if v < 0:
            raise ValueError("session_ttl_minutes must be >= 0")
        return v

    @field_validator("checkpoint_retention_days")
    @classmethod
    def validate_checkpoint_retention_days(cls, v: int) -> int:
        if v < 0:
            raise ValueError("checkpoint_retention_days must be >= 0")
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate timezone is a valid IANA timezone identifier."""
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, KeyError):
            raise ValueError(
                f"Invalid timezone '{v}'. Use IANA timezone identifiers "
                f"(e.g., 'America/Denver', 'Europe/London', 'UTC')."
            )
        return v

    model_config = {"extra": "allow"}
