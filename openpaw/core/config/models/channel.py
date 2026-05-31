"""Configuration models for channel bindings and logging."""

from pydantic import BaseModel, Field, field_validator


class ChannelLogConfig(BaseModel):
    """Configuration for persistent channel message logging."""

    enabled: bool = Field(default=True, description="Enable channel message logging to JSONL")
    retention_days: int = Field(default=30, description="Days before logs are archived")

    @field_validator("retention_days")
    @classmethod
    def validate_retention(cls, v: int) -> int:
        """Validate retention_days is at least 1."""
        if v < 1:
            raise ValueError("retention_days must be at least 1")
        return v


class WorkspaceChannelConfig(BaseModel):
    """Channel binding configuration for a workspace agent."""

    name: str | None = Field(
        default=None,
        description="Unique channel name (defaults to type). Required when multiple channels share a type.",
    )
    type: str | None = Field(default=None, description="Channel type (telegram, discord, etc.)")
    token: str | None = Field(default=None, description="Channel bot token")
    allowed_users: list[int] = Field(default_factory=list, description="Allowed user IDs")
    allowed_groups: list[int] = Field(default_factory=list, description="Allowed group IDs")
    allow_all: bool = Field(default=False, description="Allow all users (insecure, use with caution)")
    mention_required: bool = Field(
        default=False,
        description="Only respond in group chats when the bot is @mentioned. DMs always pass through.",
    )
    triggers: list[str] = Field(
        default_factory=list,
        description=(
            "Trigger keywords for group chat filtering. If set, messages must contain"
            " at least one keyword (case-insensitive). Uses OR logic with mention_required."
        ),
    )
    user_aliases: dict[int, str] = Field(
        default_factory=dict,
        description="Map user IDs to display names for message attribution",
    )
    context_messages: int = Field(
        default=25,
        description=(
            "Number of recent channel messages to fetch as context on trigger"
            " (0 = disabled, max 100)"
        ),
    )
    channel_log: ChannelLogConfig = Field(
        default_factory=ChannelLogConfig,
        description="Persistent channel message logging configuration",
    )

    @field_validator("context_messages")
    @classmethod
    def validate_context_messages(cls, v: int) -> int:
        """Validate context_messages is between 0 and 100."""
        if v < 0 or v > 100:
            raise ValueError("context_messages must be between 0 and 100")
        return v

    model_config = {"extra": "allow"}
