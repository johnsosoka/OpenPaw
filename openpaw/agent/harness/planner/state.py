"""Planner harness graph state (ADR-101 §3).

``PlannerState`` extends ``langchain.agents.AgentState`` so the embedded
react subgraph shares the ``messages`` key directly.

Serialization choice: ``plan`` and ``ideation`` are stored in graph state as
plain JSON-safe dicts, not as the frozen dataclasses from ``openpaw.model.plan``.
LangGraph's JsonPlusSerializer *can* round-trip the dataclasses today, but it
(a) warns that unregistered types will be blocked in a future version and
(b) reconstructs tuple fields as lists, breaking ``Plan.with_remaining_replaced``
after a restart. Payload dicts sidestep both; the conversion helpers below are
the single (de)serialization point. ``Plan.to_payload()`` (the event form)
omits ``result_summary``, so state uses its own superset payload.
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from langchain.agents import AgentState

from openpaw.model.plan import IdeationResult, Plan, PlanStep, StepStatus

Route = Literal["react", "plan", "ideate"]


class PlannerState(AgentState[Any], total=False):
    """State schema for the planner harness graph.

    Attributes (beyond AgentState's ``messages``):
        route: Triage classification for this run.
        objective: One-sentence restatement of the task (triage output).
        plan: Serialized live plan (see :func:`plan_to_state`), or None.
        current_step_id: The step the execute/reflect loop is working on.
        ideation: Serialized creative-module output, or None.
        step_results: Full executor output per executed step, in order.
        resume_step_id: Approval-resume marker — set when an approval interrupt
            paused a plan step; triage jumps straight back to execute_step.
        abort_reason: Set by reflect on abort_to_user; routes to synthesize.
    """

    route: Route
    objective: str
    plan: dict[str, Any] | None
    current_step_id: str | None
    ideation: dict[str, Any] | None
    step_results: list[str]
    resume_step_id: str | None
    abort_reason: str | None


@dataclass
class PlannerRunContext:
    """Per-run mutable context shared between the harness and graph nodes.

    Node closures hold this object; ``PlannerHarness.run()`` re-arms it per
    run — the same singleton-re-armed-per-run pattern as the workspace
    middleware (contextvars are invisible across LangGraph task boundaries).

    Attributes:
        session_key: "{channel}:{id}" derived from the thread id, for events.
        run_id: Correlates all status events within one run.
        executing_step_id: Set while execute_step's inner run is in flight;
            read by the approval-resume path, cleared on step completion.
        tools_used: Tool names invoked by execute_step inner runs (the outer
            update stream cannot see them).
        current_tool_name: Last tool dispatched, for timeout reporting.
    """

    session_key: str | None = None
    run_id: str = ""
    executing_step_id: str | None = None
    tools_used: list[str] = field(default_factory=list)
    current_tool_name: str | None = None

    def reset(self, run_id: str, session_key: str | None) -> None:
        """Re-arm for a new run."""
        self.session_key = session_key
        self.run_id = run_id
        self.executing_step_id = None
        self.tools_used = []
        self.current_tool_name = None


# ---------------------------------------------------------------------------
# State (de)serialization helpers — the only place plan/ideation shapes live.
# ---------------------------------------------------------------------------


def plan_to_state(plan: Plan) -> dict[str, Any]:
    """Serialize a Plan for graph state (full fidelity, incl. result_summary)."""
    return {
        "objective": plan.objective,
        "revision": plan.revision,
        "steps": [
            {
                "id": s.id,
                "description": s.description,
                "status": s.status.value,
                "result_summary": s.result_summary,
            }
            for s in plan.steps
        ],
    }


def plan_from_state(state: PlannerState) -> Plan | None:
    """Rebuild the live Plan from graph state, or None when no plan exists."""
    payload = state.get("plan")
    if not isinstance(payload, dict):
        return None
    steps = tuple(
        PlanStep(
            id=str(s["id"]),
            description=str(s["description"]),
            status=StepStatus(s["status"]),
            result_summary=str(s.get("result_summary", "")),
        )
        for s in payload.get("steps", [])
    )
    return Plan(
        objective=str(payload.get("objective", "")),
        steps=steps,
        revision=int(payload.get("revision", 0)),
    )


def ideation_to_state(ideation: IdeationResult | None) -> dict[str, Any] | None:
    """Serialize an IdeationResult for graph state."""
    if ideation is None:
        return None
    return {
        "ideas": list(ideation.ideas),
        "evaluations": list(ideation.evaluations),
        "recommended_directions": list(ideation.recommended_directions),
    }


def ideation_from_state(state: PlannerState) -> IdeationResult | None:
    """Rebuild the IdeationResult from graph state, or None."""
    payload = state.get("ideation")
    if not isinstance(payload, dict):
        return None
    return IdeationResult(
        ideas=tuple(str(i) for i in payload.get("ideas", [])),
        evaluations=tuple(str(e) for e in payload.get("evaluations", [])),
        recommended_directions=tuple(
            str(d) for d in payload.get("recommended_directions", [])
        ),
    )
