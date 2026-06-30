"""Configuration models for cron scheduling and heartbeat."""

from typing import Literal

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator


class HeartbeatConfig(BaseModel):
    """Configuration for the heartbeat scheduler."""

    enabled: bool = Field(default=False, description="Enable periodic heartbeat prompts")
    interval_minutes: int = Field(default=30, description="Minutes between heartbeat checks")
    active_hours: str | None = Field(
        default=None,
        description="Active hours window (e.g., '08:00-22:00'). None = always active",
    )
    suppress_ok: bool = Field(default=True, description="Suppress HEARTBEAT_OK responses from channel")
    target_channel: str = Field(default="telegram", description="Channel name to route heartbeat responses")
    target_id: int | None = Field(default=None, description="Target ID for output routing (preferred)")
    target_chat_id: int | None = Field(default=None, description="Telegram chat ID (deprecated, use target_id)")
    target_channel_id: int | None = Field(default=None, description="Discord channel ID (deprecated, use target_id)")
    delivery: Literal["channel", "agent", "both"] = Field(
        default="channel",
        description="Delivery mode: channel (direct), agent (queue injection), or both",
    )
    max_output_tokens: int | None = Field(
        default=None,
        description="Max output tokens for heartbeat runs (overrides workspace model default)",
    )


class CronOutputConfig(BaseModel):
    """Output routing configuration for a cron job."""

    channel: str = Field(description="Channel name (or type for backward compat)")
    target_id: int | None = Field(default=None, description="Target ID for output routing (preferred)")
    chat_id: int | None = Field(default=None, description="Telegram chat ID (deprecated, use target_id)")
    guild_id: int | None = Field(default=None, description="Discord guild ID")
    channel_id: int | None = Field(default=None, description="Discord channel ID (deprecated, use target_id)")
    delivery: Literal["channel", "agent", "both"] = Field(
        default="both",
        description=(
            "Where to deliver results: channel (direct to user), agent (inject into main agent), "
            "or both. Default 'both': raw output goes to channel AND the main agent receives "
            "the result for context awareness. The agent's terminal reply is suppressed — "
            "use send_message within the agent run to add commentary."
        ),
    )


class CronDefinition(BaseModel):
    """Definition of a single cron job from workspace crons/ directory."""

    name: str = Field(description="Unique job identifier")
    schedule: str = Field(description="Cron expression (e.g., '0 9 * * *')")
    enabled: bool = Field(default=True, description="Whether the job is active")
    prompt: str = Field(description="User prompt to inject when cron triggers")
    output: CronOutputConfig = Field(description="Where to send the response")
    max_output_tokens: int | None = Field(
        default=None,
        description="Max output tokens for this cron job (overrides workspace model default)",
    )

    @field_validator("schedule")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        """Validate cron expression is parseable at config load time."""
        try:
            CronTrigger.from_crontab(v)
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid cron expression '{v}': {e}") from e
        return v
