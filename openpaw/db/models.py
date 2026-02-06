"""SQLAlchemy ORM models for OpenPaw database."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


# ============================================================================
# Enumerations
# ============================================================================


class AgentState(StrEnum):
    """Agent state enumeration."""

    IDLE = "idle"
    ACTIVE = "active"
    STUCK = "stuck"
    ERROR = "error"
    STOPPED = "stopped"


class ListType(StrEnum):
    """Builtin allow/deny list type."""

    ALLOW = "allow"
    DENY = "deny"


class ChannelType(StrEnum):
    """Supported channel types."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"


# ============================================================================
# Settings Table
# ============================================================================


class Setting(Base):
    """Global key-value settings with category grouping.

    Stores configuration that was previously in config.yaml:
    - agent.model, agent.max_turns, agent.temperature
    - queue.mode, queue.debounce_ms, queue.cap, queue.drop_policy
    - lanes.main_concurrency, lanes.subagent_concurrency, lanes.cron_concurrency
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)
    category: Mapped[str] = mapped_column(String(50), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (Index("ix_settings_category_key", "category", "key"),)


# ============================================================================
# Workspace Tables
# ============================================================================


class Workspace(Base):
    """Workspace registry - metadata for filesystem workspaces.

    The actual workspace files (AGENT.md, USER.md, etc.) remain on filesystem.
    This table tracks:
    - Workspace existence and enabled state
    - References to per-workspace configuration
    """

    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships (one-to-one and one-to-many)
    config: Mapped["WorkspaceConfig | None"] = relationship(
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
    )
    channel_binding: Mapped["ChannelBinding | None"] = relationship(
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
    )
    cron_jobs: Mapped[list["CronJob"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    builtin_configs: Mapped[list["BuiltinConfig"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    builtin_allowlist: Mapped[list["BuiltinAllowlist"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    metrics: Mapped[list["AgentMetric"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    errors: Mapped[list["AgentError"]] = relationship(
        back_populates="workspace",
        cascade="all, delete-orphan",
    )


class WorkspaceConfig(Base):
    """Per-workspace LLM and queue configuration.

    Replaces agent.yaml model and queue sections.
    """

    __tablename__ = "workspace_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        unique=True,
    )

    # Model configuration
    model_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Queue configuration
    queue_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    debounce_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="config")


# ============================================================================
# Channel Tables
# ============================================================================


class ChannelBinding(Base):
    """Channel configuration per workspace.

    Replaces agent.yaml channel section.
    Token is encrypted at rest.
    """

    __tablename__ = "channel_bindings"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        unique=True,
    )
    channel_type: Mapped[str] = mapped_column(String(50))
    config_encrypted: Mapped[str] = mapped_column(Text)  # JSON with token, encrypted
    allowed_users: Mapped[list[int]] = mapped_column(JSON, default=list)
    allowed_groups: Mapped[list[int]] = mapped_column(JSON, default=list)
    allow_all: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="channel_binding")


# ============================================================================
# Cron Tables
# ============================================================================


class CronJob(Base):
    """Scheduled task definitions.

    Replaces crons/*.yaml files.
    """

    __tablename__ = "cron_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    schedule: Mapped[str] = mapped_column(String(100))  # Cron expression
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    prompt: Mapped[str] = mapped_column(Text)
    output_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="cron_jobs")
    executions: Mapped[list["CronExecution"]] = relationship(
        back_populates="cron_job",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_cron_workspace_name"),
    )


class CronExecution(Base):
    """Cron execution history for tracking."""

    __tablename__ = "cron_executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    cron_job_id: Mapped[int] = mapped_column(
        ForeignKey("cron_jobs.id", ondelete="CASCADE"),
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # success, failed, timeout
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    cron_job: Mapped["CronJob"] = relationship(back_populates="executions")


# ============================================================================
# API Keys Table
# ============================================================================


class ApiKey(Base):
    """Encrypted API key storage.

    Centralizes API keys that were previously in environment variables
    or scattered across config files.
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    service: Mapped[str] = mapped_column(String(50))
    key_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


# ============================================================================
# Builtin Tables
# ============================================================================


class BuiltinConfig(Base):
    """Per-builtin configuration.

    workspace_id NULL = global configuration
    workspace_id set = workspace-specific override
    """

    __tablename__ = "builtin_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    builtin_name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    workspace: Mapped["Workspace | None"] = relationship(
        back_populates="builtin_configs"
    )

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "builtin_name",
            name="uq_builtin_workspace_name",
        ),
    )


class BuiltinAllowlist(Base):
    """Allow/deny list entries for builtins.

    workspace_id NULL = global list
    workspace_id set = workspace-specific list
    """

    __tablename__ = "builtin_allowlist"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    entry: Mapped[str] = mapped_column(String(100))  # name or "group:x"
    list_type: Mapped[str] = mapped_column(String(10))  # allow, deny

    workspace: Mapped["Workspace | None"] = relationship(
        back_populates="builtin_allowlist"
    )


# ============================================================================
# Monitoring Tables
# ============================================================================


class AgentMetric(Base):
    """Runtime metrics for agent sessions.

    Tracks per-session statistics for monitoring and debugging.
    """

    __tablename__ = "agent_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    session_key: Mapped[str] = mapped_column(String(255), index=True)
    state: Mapped[str] = mapped_column(String(20), default=AgentState.IDLE.value)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    messages_processed: Mapped[int] = mapped_column(Integer, default=0)
    last_activity: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    queue_depth: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="metrics")

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "session_key",
            name="uq_metrics_workspace_session",
        ),
    )


class AgentError(Base):
    """Error log for agent failures."""

    __tablename__ = "agent_errors"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    session_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_type: Mapped[str] = mapped_column(String(100))
    error_message: Mapped[str] = mapped_column(Text)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="errors")


# ============================================================================
# Aggregate Metrics View (optional, for efficient queries)
# ============================================================================


class DailyMetrics(Base):
    """Daily aggregated metrics for efficient historical queries."""

    __tablename__ = "daily_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    date: Mapped[datetime] = mapped_column(DateTime, index=True)
    messages_processed: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    cron_executions: Mapped[int] = mapped_column(Integer, default=0)
    unique_sessions: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "date",
            name="uq_daily_metrics_workspace_date",
        ),
    )
