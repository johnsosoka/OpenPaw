"""The ``learning:`` workspace config group (PRD-001 §4.4, ADR-105).

New 0.5.0 config groups use ``extra="forbid"`` so typos fail fast.
``enabled`` gates Phase 1: the framework prompt section, the skill-authoring
framework skill, and the manage_skill tool. Default off framework-wide;
staging workspaces turn it on per the rollout plan (OPEN_QUESTIONS Q17).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ApprovalMode = Literal["immediate", "staged"]


class LearningPhase2Config(BaseModel):
    """Phase 2 — middleware-triggered evaluation (PRD-001 F2.x).

    Disabled by default until proven in staging (F2.5).
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    every_n_runs: int = Field(default=25, ge=1)
    approval: ApprovalMode = "staged"


class DreamConfig(BaseModel):
    """Phase 3 — dream sequence (PRD-001 F3.x; 0.5.1 target).

    Deprecation proposals are always staged regardless of ``approval``.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    schedule: str = "0 3 * * *"  # cron, workspace-local time
    approval: ApprovalMode = "staged"

    @field_validator("schedule")
    @classmethod
    def _looks_like_cron(cls, v: str) -> str:
        if len(v.split()) != 5:
            raise ValueError(f"schedule must be a 5-field cron expression, got {v!r}")
        return v


class LearningBudgetConfig(BaseModel):
    """Token budget; exhaustion halts Phases 2/3 quietly until the next day."""

    model_config = ConfigDict(extra="forbid")

    daily_tokens: int = Field(default=200_000, ge=0)


class LearningLimitsConfig(BaseModel):
    """Skill-quality guardrails enforced by SkillStore gates (ADR-105 §3)."""

    model_config = ConfigDict(extra="forbid")

    max_skills: int = Field(default=30, ge=1)
    max_skill_tokens: int = Field(default=1_200, ge=1)


class LearningConfig(BaseModel):
    """The ``learning:`` workspace config group (PRD-001 §4.4).

    Example:
        learning:
          enabled: true
          approval: immediate
          phase2: {enabled: false, every_n_runs: 25, approval: staged}
          dream:  {enabled: false, schedule: "0 3 * * *", approval: staged}
          budget: {daily_tokens: 200000}
          limits: {max_skills: 30, max_skill_tokens: 1200}
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    approval: ApprovalMode = "immediate"  # Phase 1 default (F1.4)
    phase2: LearningPhase2Config = Field(default_factory=LearningPhase2Config)
    dream: DreamConfig = Field(default_factory=DreamConfig)
    budget: LearningBudgetConfig = Field(default_factory=LearningBudgetConfig)
    limits: LearningLimitsConfig = Field(default_factory=LearningLimitsConfig)
