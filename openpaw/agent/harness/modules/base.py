"""ReasoningModule contract — pluggable planning/creative/reflection strategies.

One interface, three module kinds (ADR-102). Modules are prompt pipelines
(1–4 sequential LLM calls) behind an async ``run()``; the planner graph — not
the modules — owns composition (ideate may feed plan; modules never call each
other). Modules depend only on ``core/`` and ``model/`` (stability contract):
the resolved per-node model (ADR-103) and the status emitter (ADR-106) arrive
via :class:`ReasoningContext` rather than imports.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from langchain_core.language_models import BaseChatModel

from openpaw.model.plan import IdeationResult, Plan
from openpaw.model.status_event import StatusEmitter


class ModuleKind(StrEnum):
    """What a reasoning module produces."""

    PLANNING = "planning"  # ReasoningArtifact.plan is set
    CREATIVE = "creative"  # ReasoningArtifact.ideation is set
    REFLECTION = "reflection"  # ReasoningArtifact.verdict is set


@dataclass(frozen=True)
class ToolSummary:
    """Name + first-line description of an equipped tool, for planner awareness."""

    name: str
    description: str


@dataclass(frozen=True)
class WorkspaceInfo:
    """Minimal workspace context handed to modules."""

    name: str
    timezone: str
    workspace_path: Path


ReflectAction = Literal["advance", "revise_plan", "insert_step", "abort_to_user"]


@dataclass(frozen=True)
class ReflectionVerdict:
    """Reflection-module output: outcome evaluation for the current step.

    Attributes:
        action: What the plan loop should do next.
        step_succeeded: Whether the step achieved its intent.
        notes: Free-form evaluation notes (session logs).
        insert_description: New-step description when action is insert_step.
    """

    action: ReflectAction
    step_succeeded: bool
    notes: str = ""
    insert_description: str = ""


@dataclass
class ReasoningContext:
    """Everything a module needs, injected by the invoking graph node.

    Attributes:
        task: User ask / triage-summarized objective.
        conversation_digest: Recent history summary.
        tools_summary: Equipped tools (names + descriptions).
        model: Resolved per-node model (ADR-103).
        emit: Status event emitter (ADR-106).
        workspace: Minimal workspace context.
        run_id: Correlates events within one agent run.
        session_key: Session key for event attribution, if any.
        ideation: Set when an ideate node preceded planning.
        plan: REFLECTION modules only — the live plan.
        current_step_id: REFLECTION modules only — the just-executed step.
        last_step_result: REFLECTION modules only — that step's output digest.
    """

    task: str
    conversation_digest: str
    tools_summary: list[ToolSummary]
    model: BaseChatModel
    emit: StatusEmitter
    workspace: WorkspaceInfo
    run_id: str = ""
    session_key: str | None = None
    ideation: IdeationResult | None = None
    plan: Plan | None = None
    current_step_id: str | None = None
    last_step_result: str = ""


@dataclass(frozen=True)
class ReasoningArtifact:
    """Structured module output; exactly one variant is set per kind.

    Attributes:
        kind: Which variant this artifact carries.
        plan: PLANNING modules — the actionable plan. REFLECTION modules
            with revise_plan verdicts — the rewritten remaining steps.
        ideation: CREATIVE modules — expanded/evaluated ideas.
        verdict: REFLECTION modules — the step-outcome evaluation.
        reasoning_structure: Self-Discover JSON structure (cacheable).
        raw: Full module output for session logs.
    """

    kind: ModuleKind
    plan: Plan | None = None
    ideation: IdeationResult | None = None
    verdict: ReflectionVerdict | None = None
    reasoning_structure: dict[str, object] | None = None
    raw: str = ""


@runtime_checkable
class ReasoningModule(Protocol):
    """A pluggable reasoning strategy used by the planner harness.

    Attributes:
        name: Config key (e.g. ``harness.planning.module: <name>``).
        kind: PLANNING, CREATIVE, or REFLECTION.
        tagline: One-line strength description — presented to the selector
            model when ``module: auto`` resolves among candidates (ADR-102 §2).
    """

    name: str
    kind: ModuleKind
    tagline: str

    async def run(self, ctx: ReasoningContext) -> ReasoningArtifact:
        """Produce a plan, ideation, or verdict artifact for the given task."""
        ...
