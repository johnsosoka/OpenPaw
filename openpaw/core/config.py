"""Configuration management for OpenPaw."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


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


class Config(BaseModel):
    """Root configuration for OpenPaw."""

    workspaces_path: Path = Field(default=Path("agent_workspaces"), description="Path to agent workspaces")
    queue: QueueConfig = Field(default_factory=QueueConfig)
    lanes: LaneConfig = Field(default_factory=LaneConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    cron_jobs: list[CronJobConfig] = Field(default_factory=list, description="Scheduled agent jobs")

    model_config = {"extra": "allow"}


def load_config(path: Path | str) -> Config:
    """Load configuration from a YAML file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Parsed Config object.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        yaml.YAMLError: If the YAML is malformed.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open() as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    return Config(**data)
