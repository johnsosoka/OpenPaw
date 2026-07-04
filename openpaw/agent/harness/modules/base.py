"""ReasoningModule contract — pluggable planning/creative/reflection strategies.

One interface, three module kinds (ADR-102). Modules are prompt pipelines or
compiled LangGraph subgraphs (ADR-109) behind an async ``run()`` — ideonomy
fans its lens calls out in parallel via ``Send``; the ultra graph — not
the modules — owns composition (ideate may feed plan; modules never call each
other). Modules depend only on ``core/`` and ``model/`` (stability contract):
the resolved per-node model (ADR-103) arrives via :class:`ReasoningContext`
rather than imports. Progress visibility uses :func:`emit_status` — the
native LangGraph custom stream (ADR-110), no emitter plumbing.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langchain_core.runnables.config import ensure_config, merge_configs
from langgraph.config import get_stream_writer

from openpaw.model.plan import IdeationResult, Plan
from openpaw.model.status_event import JsonValue, StatusEvent, StatusEventKind

logger = logging.getLogger(__name__)

# Runtime checkpointer-disable for nested (module-subgraph / step-scoped)
# invocations. LangGraph offers no public per-invoke knob; this private config
# key is how it disables checkpointing for nested runs internally. Covered by
# test_execute_step_inner_run_is_unpersisted so an upgrade break fails loudly.
CONFIG_KEY_CHECKPOINTER = "__pregel_checkpointer"


def unpersisted_nested_config() -> RunnableConfig:
    """Invocation config for running a module subgraph unpersisted (ADR-109).

    merge_configs over the ambient config: a bare ``configurable`` dict would
    REPLACE the contextvar-inherited one (ensure_config semantics), silently
    severing the parent's custom-stream writer (ADR-110) along with the
    checkpointer. Merging adds the checkpointer-disable key while everything
    else — including the stream writer — keeps flowing to the nested run.
    """
    return merge_configs(ensure_config(), {"configurable": {CONFIG_KEY_CHECKPOINTER: None}})


def emit_status(
    kind: StatusEventKind,
    payload: dict[str, JsonValue],
    *,
    workspace: str,
    node: str | None = None,
) -> None:
    """Write a module status event to the LangGraph custom stream; never raises.

    The in-graph transport leg of ADR-110: module code calls this from
    anywhere inside a graph node's call stack and the event surfaces on the
    harness's ``stream_mode="custom"`` channel, where run identity
    (``session_key``/``run_id``) is stamped centrally before forwarding to
    the status bus — which is why both are left at their defaults here.

    Drop semantics (status is never load-bearing, same posture as StatusBus):

    - Outside a runnable context (e.g. a direct unit-test call to a module),
      ``get_stream_writer`` raises ``RuntimeError``; the event is debug-logged
      and dropped — a no-op.
    - Under a plain ``ainvoke`` (nobody streaming custom mode), the writer
      accepts the event and LangGraph silently discards it.

    Args:
        kind: What happened (payload schema is keyed by this).
        payload: Kind-specific data, byte-identical to the renderer contract.
        workspace: Owning workspace name (the harness cannot stamp this).
        node: Emitting node attribution — the module kind value.
    """
    try:
        writer = get_stream_writer()
    except RuntimeError:
        logger.debug("emit_status(%s) outside runnable context; dropped", kind)
        return
    writer(StatusEvent(kind=kind, workspace=workspace, session_key=None, run_id="", node=node, payload=payload))


def render_context_block(context_brief: str) -> str:
    """Optional "Session context:" prompt block for the ADR-108 brief.

    The single rendering point for every brief consumer (modules, step
    execution, synthesis, equip). Renders to nothing when there is no brief,
    so prompts stay byte-identical to their brief-less form. Non-empty output
    carries a trailing blank line — call sites place the block directly
    before their next prompt section.
    """
    if not context_brief.strip():
        return ""
    return f"Session context:\n{context_brief.strip()}\n\n"


class ModuleKind(StrEnum):
    """What a reasoning module produces."""

    PLANNING = "planning"  # ReasoningArtifact.plan is set
    CREATIVE = "creative"  # ReasoningArtifact.ideation is set
    REFLECTION = "reflection"  # ReasoningArtifact.verdict is set


@dataclass(frozen=True)
class ToolSummary:
    """Name + first-line description of an equipped tool, for ultra awareness."""

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
        workspace: Minimal workspace context.
        context_brief: Rendered session brief (ADR-108), or "" when the brief
            node is disabled, failed, or was skipped (react route) — modules
            fall back to ``conversation_digest``.
        ideation: Set when an ideate node preceded planning.
        plan: REFLECTION modules only — the live plan.
        current_step_id: REFLECTION modules only — the just-executed step.
        last_step_result: REFLECTION modules only — that step's output digest.
    """

    task: str
    conversation_digest: str
    tools_summary: list[ToolSummary]
    model: BaseChatModel
    workspace: WorkspaceInfo
    context_brief: str = ""
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


class ReasoningModule(ABC):
    """A pluggable reasoning strategy used by the ultra harness.

    The extension contract (ADR-102): subclass, set the three class
    attributes, implement ``run()``, and add one ``MODULE_REGISTRY`` entry —
    nothing else in the framework needs touching. Modules whose constructor
    takes dependencies override ``build()`` to assemble them from the
    workspace context; the harness only ever calls ``build()``.

    Concurrency invariant: instances are built once per workspace and shared
    across concurrent sessions — any instance state bound in ``run()`` must
    be workspace-constant (model, workspace identity), never run-specific.
    Run-varying data (task, brief, digest) belongs in subgraph state.

    Attributes:
        name: Config key (e.g. ``harness.planning.module: <name>``).
        kind: PLANNING, CREATIVE, or REFLECTION.
        tagline: One-line strength description — presented to the selector
            model when ``module: auto`` resolves among candidates (ADR-102 §2).
    """

    name: str
    kind: ModuleKind
    tagline: str

    @classmethod
    def build(cls, workspace: WorkspaceInfo) -> "ReasoningModule":
        """Construct this module for a workspace (the uniform entrypoint).

        The default suits dependency-free modules. Modules needing
        workspace-scoped collaborators (caches, stores) override this —
        see SelfDiscoverPlanner.

        Args:
            workspace: Workspace context (name, timezone, path).

        Returns:
            A ready-to-run module instance.
        """
        return cls()

    def _emit(
        self, ctx: ReasoningContext, kind: StatusEventKind, payload: dict[str, JsonValue]
    ) -> None:
        """Stamp module identity onto ``payload`` and write it via :func:`emit_status`.

        Convenience over the ADR-110 transport: every module event carries
        ``{"kind": <module kind>, "module": <name>}`` (renderer contract).
        Tolerant like ``emit_status`` — never raises.
        """
        emit_status(
            kind,
            {"kind": self.kind.value, "module": self.name, **payload},
            workspace=ctx.workspace.name,
            node=self.kind.value,
        )

    @abstractmethod
    async def run(self, ctx: ReasoningContext) -> ReasoningArtifact:
        """Produce a plan, ideation, or verdict artifact for the given task."""
