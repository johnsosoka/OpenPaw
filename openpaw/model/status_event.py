"""Unified status event schema (ADR-106).

One event object between "something happened" and "channel message text".
Producers (middleware, harness nodes, SkillStore) emit ``StatusEvent`` through
a ``StatusEmitter``; sinks render, log, or feed the future web portal.
Emission is best-effort and must never block or fail an agent run.

This module is pure model layer: stdlib only, no framework imports.
Payload shapes are a compatibility surface — additive-only evolution within
a minor version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, Union, runtime_checkable

# JSON-serializable payload values. Payload schemas are documented next to
# the enum; evolution policy is additive-only within a minor version.
JsonValue = Union[  # noqa: UP007 — recursive alias reads clearer as Union
    None, bool, int, float, str, list["JsonValue"], dict[str, "JsonValue"]
]


class StatusEventKind(StrEnum):
    """Every observable happening in the 0.5.0 kind set (ADR-106 §1).

    Payload schema per kind (keys are the payload dict contents):

    Run lifecycle:
        run.started      — {run_count: int, is_system_batch: bool}
        run.completed    — {} (reserved; not yet emitted in Phase A)
        run.failed       — {error: str} (reserved; not yet emitted in Phase A)

    Tools:
        tool.selected    — {tools: list[str]} (model turn chose these tools)
        tool.started     — {tool: str, detail: str | None}
        tool.completed   — {tool: str, detail: str | None}
        tool.timeout     — {tool: str} (reserved; not yet emitted in Phase A)

    Sub-agents:
        subagent.dispatched — {subagent_id: str, label: str}
        subagent.tool       — {subagent_id: str, status: str}
        subagent.completed  — {subagent_id: str, outcome: str}
                              (outcome: completed | failed | cancelled)

    Steer / interrupt:
        run.steered      — {tool: str} (queued user message redirected the
                           run; tool is the skipped tool that surfaced it)
        run.interrupted  — {tool: str} (interrupt signal stopped the run
                           during this tool)

    Harness (ADR-101/ADR-102; emitted by 0.5.0 harness nodes):
        node.entered        — {node: str}
        node.completed      — {node: str, model: str, input_tokens: int,
                              output_tokens: int, total_tokens: int,
                              duration_ms: float} (per-node token/latency
                              attribution, H6.3/ADR-103 §5; the module-selector
                              call is folded into its parent node's numbers).
                              The execute node instead carries {node, model,
                              step_id: str, duration_ms} — token keys are
                              omitted because the inner run's tokens are
                              attributed at run level (no double-count).
        module.selected     — {kind: str, module: str, reason: str}
        plan.created        — {plan: dict} (full serialized Plan: objective,
                              revision, steps[{id, description, status}])
        plan.step_started   — {step_id: str, description: str}
        plan.step_completed — {step_id: str, description: str}
        plan.revised        — {plan: dict} (full serialized Plan)
        reflection.verdict  — {verdict: str, reason: str}
        tools.equipped      — {tools: list[str]}

    Skills / learning (ADR-105/PRD-001; emitted by SkillStore + dream loop):
        skill.created / skill.updated / skill.staged / skill.approved /
        skill.equipped / skill.deprecated / skill.rejected
                            — {skill: str, version: int | None}
        learning.evaluation.started / learning.evaluation.completed
                            — {evaluation_id: str}
        dream.started / dream.completed
                            — {dream_id: str}
    """

    # -- Run lifecycle --------------------------------------------------------
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"

    # -- Tools (existing capability, re-expressed as events) ------------------
    TOOL_SELECTED = "tool.selected"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_TIMEOUT = "tool.timeout"

    # -- Sub-agents (existing) -------------------------------------------------
    SUBAGENT_DISPATCHED = "subagent.dispatched"
    SUBAGENT_TOOL = "subagent.tool"
    SUBAGENT_COMPLETED = "subagent.completed"

    # -- Steer / interrupt (existing) -------------------------------------------
    RUN_STEERED = "run.steered"
    RUN_INTERRUPTED = "run.interrupted"

    # -- Harness (new, ADR-101 / ADR-102) ----------------------------------------
    NODE_ENTERED = "node.entered"
    NODE_COMPLETED = "node.completed"
    MODULE_SELECTED = "module.selected"
    PLAN_CREATED = "plan.created"
    PLAN_STEP_STARTED = "plan.step_started"
    PLAN_STEP_COMPLETED = "plan.step_completed"
    PLAN_REVISED = "plan.revised"
    REFLECTION_VERDICT = "reflection.verdict"
    TOOLS_EQUIPPED = "tools.equipped"

    # -- Skills / learning (new, ADR-105 / PRD-001) --------------------------------
    SKILL_CREATED = "skill.created"
    SKILL_UPDATED = "skill.updated"
    SKILL_STAGED = "skill.staged"
    SKILL_APPROVED = "skill.approved"
    SKILL_EQUIPPED = "skill.equipped"
    SKILL_DEPRECATED = "skill.deprecated"
    SKILL_REJECTED = "skill.rejected"
    LEARNING_EVALUATION_STARTED = "learning.evaluation.started"
    LEARNING_EVALUATION_COMPLETED = "learning.evaluation.completed"
    DREAM_STARTED = "dream.started"
    DREAM_COMPLETED = "dream.completed"


@dataclass(frozen=True)
class StatusEvent:
    """One observable happening, machine-readable and channel-agnostic.

    Attributes:
        kind: What happened (payload schema is keyed by this — see
            :class:`StatusEventKind`).
        workspace: Owning workspace name.
        session_key: "{channel}:{id}", or None for workspace-scoped events
            (e.g. a dream run with no active session).
        run_id: Correlates all events within one agent run.
        node: Harness node that emitted this (triage | plan | execute |
            reflect | equip | synthesize), or None on the react path.
        payload: Kind-specific data; plan.* payloads carry the serialized
            Plan so renderers can draw the full to-do list.
        ts: Event time, UTC.
    """

    kind: StatusEventKind
    workspace: str
    session_key: str | None
    run_id: str
    node: str | None = None
    payload: dict[str, JsonValue] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class StatusEmitter(Protocol):
    """What event producers (harness nodes, SkillStore, middleware) depend on.

    Injected — via constructor params, node closures, or store constructors —
    never imported from channel machinery (stability contract: producers
    live in agent/ and stores/, channels above them).
    """

    async def emit(self, event: StatusEvent) -> None:
        """Deliver an event. Must never raise into the caller."""
        ...


class StatusSink(Protocol):
    """A consumer of the event stream (channel renderer, JSONL log, portal)."""

    async def handle(self, event: StatusEvent) -> None:
        """Process one event. Exceptions are contained by the bus."""
        ...
