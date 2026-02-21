"""Domain models for cron scheduling."""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator


class CronOutputConfig(BaseModel):
    """Output routing configuration for a cron job."""

    channel: str = Field(description="Channel type (telegram, discord, etc.)")
    chat_id: int | None = Field(default=None, description="Telegram chat ID")
    guild_id: int | None = Field(default=None, description="Discord guild ID")
    channel_id: int | None = Field(default=None, description="Discord channel ID")


class CronDefinition(BaseModel):
    """Definition of a single cron job from workspace crons/ directory."""

    name: str = Field(description="Unique job identifier")
    schedule: str = Field(description="Cron expression (e.g., '0 9 * * *')")
    enabled: bool = Field(default=True, description="Whether the job is active")
    prompt: str = Field(description="User prompt to inject when cron triggers")
    output: CronOutputConfig = Field(description="Where to send the response")

    @field_validator("schedule")
    @classmethod
    def validate_cron_expression(cls, v: str) -> str:
        """Validate cron expression is parseable at config load time."""
        try:
            CronTrigger.from_crontab(v)
        except (ValueError, KeyError) as e:
            raise ValueError(f"Invalid cron expression '{v}': {e}") from e
        return v


@dataclass
class DynamicCronTask:
    """Represents a dynamically scheduled task created by an agent.

    Task Types:
        - once: Executes at a specific datetime (run_at)
        - interval: Executes repeatedly every N seconds (interval_seconds)
    """

    id: str
    task_type: str
    prompt: str
    created_at: datetime
    run_at: datetime | None = None
    interval_seconds: int | None = None
    next_run: datetime | None = None
    channel: str | None = None  # Channel to route response to (e.g., "telegram")
    chat_id: int | None = None  # Chat ID for routing response

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with ISO 8601 datetime strings."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        if self.run_at:
            data["run_at"] = self.run_at.isoformat()
        if self.next_run:
            data["next_run"] = self.next_run.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DynamicCronTask":
        """Create instance from dictionary with ISO 8601 datetime strings."""
        return cls(
            id=data["id"],
            task_type=data["task_type"],
            prompt=data["prompt"],
            created_at=datetime.fromisoformat(data["created_at"]),
            run_at=datetime.fromisoformat(data["run_at"]) if data.get("run_at") else None,
            interval_seconds=data.get("interval_seconds"),
            next_run=datetime.fromisoformat(data["next_run"]) if data.get("next_run") else None,
            channel=data.get("channel"),
            chat_id=data.get("chat_id"),
        )
