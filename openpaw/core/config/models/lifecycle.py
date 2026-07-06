"""Configuration models for lifecycle events and status reminders."""

from pydantic import BaseModel, Field


class LifecycleConfig(BaseModel):
    """Configuration for lifecycle event notifications."""

    notify_startup: bool = Field(default=False, description="Send notification when workspace starts")
    notify_shutdown: bool = Field(default=True, description="Send notification when workspace stops")
    notify_auto_compact: bool = Field(default=True, description="Send notification on auto-compact")
    notify_session_ttl: bool = Field(default=True, description="Send notification on session TTL expiry")


class StatusReminderConfig(BaseModel):
    """Configuration for status reminder middleware.

    Controls when and how often the agent is reminded to call send_message()
    during long silent tool-calling runs.
    """

    enabled: bool = Field(default=True, description="Enable silent operation detection")
    threshold: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Turns without send_message before reminding",
    )
    max_reminders: int = Field(
        default=3,
        ge=0,
        le=20,
        description="Max reminders per agent run",
    )
    cooldown_turns: int = Field(
        default=1,
        ge=0,
        le=10,
        description="Min turns between consecutive reminders",
    )
    repeat_tool_limit: int = Field(
        default=6,
        ge=2,
        le=50,
        description="Consecutive identical single-tool turns before the anti-spin guard fires",
    )
    repeat_guard_max: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Max anti-spin guard injections per agent run",
    )
