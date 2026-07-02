"""Planner harness StateGraph assembly (ADR-101 §1).

Topology::

    START -> triage --Command(goto)--> react | ideate | plan | execute_step
    ideate -> plan
    plan -> execute_step
    execute_step -> reflect -> (execute_step | synthesize)   [reflection on]
    execute_step -> (execute_step | synthesize)              [reflection off]
    react -> END
    synthesize -> END

The react node is the *existing* compiled ``create_agent`` graph embedded
directly (shared ``messages`` key — same middleware, same tools, byte-for-byte
behavior). ``execute_step`` invokes the SAME compiled graph with a fresh,
step-scoped message list and checkpointing disabled — intentionally
unpersisted, fresh context per step (research §5.2). Middleware (steer,
interrupt, approval, timeout, status) applies to every step by construction
because it lives inside the embedded agent.

The compiled react graph is a plain parameter so tests can inject a tiny
fake subgraph.
"""

import logging
from dataclasses import dataclass
from typing import Any, Literal, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import BaseModel, Field

from openpaw.agent.harness.modules.base import (
    ModuleKind,
    ReasoningContext,
    ReasoningModule,
    ReflectionVerdict,
    ToolSummary,
    WorkspaceInfo,
)
from openpaw.agent.harness.modules.direct import DirectPlanner
from openpaw.agent.harness.modules.selector import resolve_module
from openpaw.agent.harness.planner.prompts import (
    FALLBACK_STEP_DESCRIPTION,
    STEP_EXECUTION_TEMPLATE,
    SYNTHESIZE_ABORT_BLOCK,
    SYNTHESIZE_TEMPLATE,
    TRIAGE_SYSTEM_PROMPT,
)
from openpaw.agent.harness.planner.state import (
    PlannerRunContext,
    PlannerState,
    Route,
    ideation_from_state,
    ideation_to_state,
    plan_from_state,
    plan_to_state,
)
from openpaw.core.config.models.harness import HarnessConfig
from openpaw.model.plan import Plan, PlanStep, StepStatus
from openpaw.model.status_event import JsonValue, StatusEmitter, StatusEvent, StatusEventKind

logger = logging.getLogger(__name__)

# Runtime checkpointer-disable for the step-scoped inner invocation. LangGraph
# offers no public per-invoke knob; this private config key is how it disables
# checkpointing for nested runs internally. Covered by
# test_execute_step_inner_run_is_unpersisted so an upgrade break fails loudly.
_CONFIG_KEY_CHECKPOINTER = "__pregel_checkpointer"

# Digest of recent conversation handed to triage/planning prompts.
_DIGEST_MESSAGES = 6
_DIGEST_MAX_CHARS = 1500

# Cap on the result digest stored inside the plan; full text goes to
# state.step_results.
_RESULT_SUMMARY_CHARS = 200


class TriageDecision(BaseModel):
    """Structured triage classification (PRD-002 H2.1)."""

    route: Route = Field(description="react = simple; plan = multi-step; ideate = open-ended creative")
    objective: str = Field(description="One-sentence restatement of the task")
    reason: str = Field(description="Why this route")


@dataclass(frozen=True)
class PlannerNodeModels:
    """Per-node models resolved by NodeModelResolver at harness build time.

    The execution model lives inside the embedded react subgraph and is not
    listed here (runtime /model overrides apply to it alone, ADR-103 §4).
    """

    triage: BaseChatModel
    planning: BaseChatModel
    creative: BaseChatModel
    reflection: BaseChatModel
    selector: BaseChatModel
    synthesize: BaseChatModel


def extract_message_text(content: Any) -> str:
    """Extract text from message content (string or typed-block list)."""
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text" and block.get("text"):
                parts.append(str(block["text"]))
        elif getattr(block, "type", None) == "text" and getattr(block, "text", None):
            parts.append(str(block.text))
    return "\n".join(parts)


def _last_human_text(messages: list[Any]) -> str:
    """Text of the most recent HumanMessage (the current batch)."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return extract_message_text(msg.content)
    return ""


def _conversation_digest(messages: list[Any]) -> str:
    """Compact recent-history digest for triage and module prompts."""
    parts = [extract_message_text(m.content) for m in messages[-_DIGEST_MESSAGES:] if hasattr(m, "content")]
    return "\n".join(p for p in parts if p)[-_DIGEST_MAX_CHARS:]


def build_planner_graph(
    *,
    react_graph: Any,
    node_models: PlannerNodeModels,
    harness_config: HarnessConfig,
    candidates: dict[ModuleKind, dict[str, ReasoningModule]],
    emitter: StatusEmitter,
    workspace_info: WorkspaceInfo,
    tools_summary: list[ToolSummary],
    run_context: PlannerRunContext,
    checkpointer: Any | None,
    inner_recursion_limit: int,
) -> Any:
    """Assemble and compile the planner harness graph.

    Args:
        react_graph: The compiled create_agent graph (AgentRunner.agent_graph).
            Embedded directly as the react node and invoked (unpersisted) per
            plan step. Injectable for tests.
        node_models: Resolved per-node chat models.
        harness_config: The workspace ``harness:`` config group.
        candidates: Instantiated reasoning modules per kind (registry-built).
        emitter: Status event emitter (ADR-106).
        workspace_info: Minimal workspace context for modules and events.
        tools_summary: Tool names + descriptions for planner awareness.
        run_context: Per-run mutable context re-armed by PlannerHarness.run().
        checkpointer: Same instance as the inner runner's (None = stateless).
        inner_recursion_limit: recursion_limit for step-scoped inner runs.

    Returns:
        The compiled StateGraph.
    """
    reflection_off = harness_config.reflection.module == "off"
    max_steps = harness_config.execution.max_steps

    async def _emit(kind: StatusEventKind, node: str, payload: dict[str, JsonValue]) -> None:
        """Best-effort event emission — never fails a run."""
        try:
            await emitter.emit(
                StatusEvent(
                    kind=kind,
                    workspace=workspace_info.name,
                    session_key=run_context.session_key,
                    run_id=run_context.run_id,
                    node=node,
                    payload=payload,
                )
            )
        except Exception:
            logger.debug("Status emit failed for %s", kind, exc_info=True)

    def _module_ctx(state: PlannerState, objective: str, model: BaseChatModel) -> ReasoningContext:
        """Build the ReasoningContext a module needs (ADR-102)."""
        return ReasoningContext(
            task=objective,
            conversation_digest=_conversation_digest(state.get("messages", [])),
            tools_summary=tools_summary,
            model=model,
            emit=emitter,
            workspace=workspace_info,
            run_id=run_context.run_id,
            session_key=run_context.session_key,
            ideation=ideation_from_state(state),
        )

    def _objective(state: PlannerState) -> str:
        return state.get("objective") or _last_human_text(state.get("messages", []))[:500]

    # --- triage -------------------------------------------------------------

    async def triage(state: PlannerState) -> Command[Literal["react", "ideate", "plan", "execute_step"]]:
        """Classify the batch and route (H2.1–H2.4); resume paused plan steps."""
        # Approval-resume path: jump straight back to the paused step. The
        # marker is cleared by execute_step, not here.
        resume_id = state.get("resume_step_id")
        live_plan = plan_from_state(state)
        if resume_id and live_plan is not None:
            step = live_plan.get_step(resume_id)
            if step is not None and step.status in (StepStatus.PENDING, StepStatus.IN_PROGRESS):
                await _emit(
                    StatusEventKind.NODE_ENTERED,
                    "triage",
                    {"route": "plan", "resume_step_id": resume_id},
                )
                return Command(update={"route": "plan", "current_step_id": resume_id}, goto="execute_step")

        last_text = _last_human_text(state.get("messages", []))

        # Belt-and-braces: MessageProcessor short-circuits [SYSTEM]-only
        # batches before the graph, but the harness cannot rely on callers.
        if last_text.lstrip().startswith("[SYSTEM]"):
            await _emit(StatusEventKind.NODE_ENTERED, "triage", {"route": "react", "reason": "system batch"})
            return Command(update={"route": "react", "objective": last_text[:200]}, goto="react")

        try:
            decision = await node_models.triage.with_structured_output(TriageDecision).ainvoke(
                [
                    SystemMessage(TRIAGE_SYSTEM_PROMPT),
                    HumanMessage(_conversation_digest(state.get("messages", []))),
                ]
            )
            if not isinstance(decision, TriageDecision):
                raise TypeError(f"triage returned {type(decision).__name__}")
        except Exception:
            # H2.3: any triage failure falls back to react — the harness must
            # never be less reliable than the current loop.
            logger.warning("Triage failed; falling back to react", exc_info=True)
            decision = TriageDecision(route="react", objective=last_text[:200], reason="triage fallback")

        await _emit(
            StatusEventKind.NODE_ENTERED,
            "triage",
            {"route": decision.route, "reason": decision.reason},
        )
        # TODO(ADR-104): when harness_config.tool_equipping.enabled, route
        # plan -> equip before planning. Equip lands in a later task.
        objective = decision.objective or last_text[:500]
        return Command(update={"route": decision.route, "objective": objective}, goto=decision.route)

    # --- ideate ---------------------------------------------------------------

    async def ideate(state: PlannerState) -> dict[str, Any]:
        """Run the creative module; failure skips ideation (fail-open)."""
        await _emit(StatusEventKind.NODE_ENTERED, "ideate", {})
        objective = _objective(state)
        try:
            module = await resolve_module(
                harness_config.creative.module,
                harness_config.creative.allowed,
                candidates.get(ModuleKind.CREATIVE, {}),
                ModuleKind.CREATIVE,
                objective,
                node_models.selector,
                emitter,
                workspace_info.name,
                run_context.run_id,
                run_context.session_key,
            )
            artifact = await module.run(_module_ctx(state, objective, node_models.creative))
            return {"ideation": ideation_to_state(artifact.ideation)}
        except Exception:
            logger.warning("Ideation failed; planning without ideation", exc_info=True)
            return {"ideation": None}

    # --- plan -----------------------------------------------------------------

    async def _plan_with_fallback(state: PlannerState, objective: str) -> Plan:
        """Module -> DirectPlanner -> synthetic single step. Never dead-ends."""
        ctx = _module_ctx(state, objective, node_models.planning)
        try:
            module = await resolve_module(
                harness_config.planning.module,
                harness_config.planning.allowed,
                candidates.get(ModuleKind.PLANNING, {}),
                ModuleKind.PLANNING,
                objective,
                node_models.selector,
                emitter,
                workspace_info.name,
                run_context.run_id,
                run_context.session_key,
            )
            artifact = await module.run(ctx)
            if artifact.plan is not None and artifact.plan.steps:
                return artifact.plan
            raise ValueError(f"planning module {module.name} produced no plan")
        except Exception:
            logger.warning("Planning module failed; falling back to DirectPlanner", exc_info=True)
        try:
            artifact = await DirectPlanner().run(ctx)
            if artifact.plan is not None and artifact.plan.steps:
                return artifact.plan
        except Exception:
            logger.warning("DirectPlanner fallback failed; using synthetic plan", exc_info=True)
        return Plan(objective=objective, steps=(PlanStep(id="1", description=FALLBACK_STEP_DESCRIPTION),))

    async def plan_node(state: PlannerState) -> dict[str, Any]:
        """Synthesize the plan via the configured module (H3.1–H3.2)."""
        await _emit(StatusEventKind.NODE_ENTERED, "plan", {})
        objective = _objective(state)
        new_plan = await _plan_with_fallback(state, objective)
        await _emit(
            StatusEventKind.PLAN_CREATED,
            "plan",
            {"plan": cast(JsonValue, new_plan.to_payload())},
        )
        first = new_plan.next_pending()
        return {
            "plan": plan_to_state(new_plan),
            "current_step_id": first.id if first else None,
            "step_results": [],
            "resume_step_id": None,
            "abort_reason": None,
        }

    # --- execute_step -----------------------------------------------------------

    async def execute_step(state: PlannerState) -> dict[str, Any]:
        """Run the react subgraph scoped to the current plan step (H4.1).

        The inner run is intentionally unpersisted (fresh context per step);
        ApprovalRequiredError/InterruptSignalError propagate out exactly as
        today — PlannerHarness.run() owns the resume/clear contracts.
        """
        live_plan = plan_from_state(state)
        step_id = state.get("current_step_id")
        step = live_plan.get_step(step_id) if live_plan is not None and step_id is not None else None
        if live_plan is None or step_id is None or step is None:
            logger.error("execute_step reached without an executable step (step_id=%s)", step_id)
            return {"abort_reason": "Internal error: no executable plan step.", "resume_step_id": None}

        run_context.executing_step_id = step_id
        run_context.current_tool_name = None
        await _emit(
            StatusEventKind.PLAN_STEP_STARTED,
            "execute_step",
            {"step_id": step.id, "description": step.description},
        )
        working = live_plan.with_step_status(step_id, StepStatus.IN_PROGRESS)
        prompt = STEP_EXECUTION_TEMPLATE.format(
            objective=_objective(state) or working.objective,
            checklist=working.render_checklist(),
            step_id=step.id,
            description=step.description,
        )
        step_config: dict[str, Any] = {
            "recursion_limit": inner_recursion_limit,
            "configurable": {_CONFIG_KEY_CHECKPOINTER: None},
        }
        result = await react_graph.ainvoke({"messages": [HumanMessage(prompt)]}, config=step_config)
        run_context.executing_step_id = None

        result_messages = result.get("messages", []) if isinstance(result, dict) else []
        summary = extract_message_text(result_messages[-1].content) if result_messages else ""
        for msg in result_messages:
            for tc in getattr(msg, "tool_calls", None) or []:
                if name := tc.get("name"):
                    run_context.tools_used.append(name)

        await _emit(
            StatusEventKind.PLAN_STEP_COMPLETED,
            "execute_step",
            {"step_id": step.id, "description": step.description},
        )
        step_results = [*state.get("step_results", []), summary]
        if reflection_off:
            # No reflect node: mark done and advance here.
            done = live_plan.with_step_status(step_id, StepStatus.DONE, summary[:_RESULT_SUMMARY_CHARS])
            nxt = done.next_pending()
            return {
                "plan": plan_to_state(done),
                "current_step_id": nxt.id if nxt else None,
                "step_results": step_results,
                "resume_step_id": None,
            }
        return {
            "plan": plan_to_state(working),
            "step_results": step_results,
            "resume_step_id": None,
        }

    # --- reflect ------------------------------------------------------------------

    async def reflect(state: PlannerState) -> dict[str, Any]:
        """Evaluate the step outcome and update plan state (H4.2/H4.3)."""
        live_plan = plan_from_state(state)
        step_id = state.get("current_step_id")
        if state.get("abort_reason") or live_plan is None or step_id is None:
            return {"current_step_id": None}
        step_results = state.get("step_results", [])
        last_result = step_results[-1] if step_results else ""
        objective = _objective(state)

        try:
            module = await resolve_module(
                harness_config.reflection.module,
                harness_config.reflection.allowed,
                candidates.get(ModuleKind.REFLECTION, {}),
                ModuleKind.REFLECTION,
                objective,
                node_models.selector,
                emitter,
                workspace_info.name,
                run_context.run_id,
                run_context.session_key,
            )
            ctx = _module_ctx(state, objective, node_models.reflection)
            ctx.plan = live_plan
            ctx.current_step_id = step_id
            ctx.last_step_result = last_result
            artifact = await module.run(ctx)
            verdict = artifact.verdict
            if verdict is None:
                raise ValueError(f"reflection module {module.name} returned no verdict")
            revised_tail = artifact.plan
        except Exception:
            # Fail-open: a broken reflector must not stall the plan loop.
            logger.warning("Reflection failed; advancing", exc_info=True)
            verdict = ReflectionVerdict(action="advance", step_succeeded=True, notes="reflection failed; advancing")
            revised_tail = None

        status = StepStatus.DONE if verdict.step_succeeded else StepStatus.FAILED
        updated = live_plan.with_step_status(step_id, status, last_result[:_RESULT_SUMMARY_CHARS])
        abort_reason: str | None = None

        if verdict.action == "insert_step" and verdict.insert_description:
            updated = updated.with_insertion(step_id, verdict.insert_description)
            await _emit(
                StatusEventKind.PLAN_REVISED,
                "reflect",
                {"plan": cast(JsonValue, updated.to_payload())},
            )
        elif verdict.action == "revise_plan" and revised_tail is not None:
            # Full reflection: artifact.plan holds ONLY the new remaining steps.
            updated = updated.with_remaining_replaced(revised_tail.steps)
            await _emit(
                StatusEventKind.PLAN_REVISED,
                "reflect",
                {"plan": cast(JsonValue, updated.to_payload())},
            )
        elif verdict.action == "abort_to_user":
            abort_reason = verdict.notes or "The plan cannot proceed without user input."

        await _emit(
            StatusEventKind.REFLECTION_VERDICT,
            "reflect",
            {"verdict": verdict.action, "reason": verdict.notes},
        )
        next_step = updated.next_pending() if abort_reason is None else None
        return {
            "plan": plan_to_state(updated),
            "current_step_id": next_step.id if next_step else None,
            "abort_reason": abort_reason,
        }

    # --- plan-loop conditional ------------------------------------------------------

    def route_after_step(state: PlannerState) -> Literal["execute_step", "synthesize"]:
        """Loop while pending steps remain, within budget, and not aborted."""
        if state.get("abort_reason"):
            return "synthesize"
        live_plan = plan_from_state(state)
        if live_plan is None or live_plan.next_pending() is None or state.get("current_step_id") is None:
            return "synthesize"
        executed = sum(1 for s in live_plan.steps if s.status != StepStatus.PENDING)
        if executed >= max_steps:
            logger.warning("Plan step budget reached (%d); synthesizing", max_steps)
            return "synthesize"
        return "execute_step"

    # --- synthesize --------------------------------------------------------------------

    async def synthesize(state: PlannerState) -> dict[str, Any]:
        """Compose the final user-facing response from plan + step results."""
        await _emit(StatusEventKind.NODE_ENTERED, "synthesize", {})
        live_plan = plan_from_state(state)
        step_results = state.get("step_results", [])
        abort_reason = state.get("abort_reason")
        abort_block = SYNTHESIZE_ABORT_BLOCK.format(reason=abort_reason) if abort_reason else ""
        prompt = SYNTHESIZE_TEMPLATE.format(
            objective=_objective(state),
            checklist=live_plan.render_checklist() if live_plan else "-",
            results="\n---\n".join(step_results) or "-",
            abort_block=abort_block,
        )
        try:
            response = await node_models.synthesize.ainvoke([HumanMessage(prompt)])
            text = extract_message_text(response.content)
            if not text.strip():
                raise ValueError("empty synthesis output")
        except Exception:
            # Never dead-end: fall back to the raw step results.
            logger.warning("Synthesis failed; returning raw step results", exc_info=True)
            parts = [p for p in (abort_reason, *step_results) if p]
            text = "\n\n".join(parts) or "The plan completed, but no results were produced."
        return {"messages": [AIMessage(content=text)]}

    # --- assembly -----------------------------------------------------------------------

    builder: StateGraph[PlannerState, None, PlannerState, PlannerState] = StateGraph(PlannerState)
    builder.add_node("triage", triage)
    builder.add_node("react", react_graph)  # CompiledStateGraph embeds as a namespaced subgraph
    builder.add_node("ideate", ideate)
    builder.add_node("plan", plan_node)
    builder.add_node("execute_step", execute_step)
    builder.add_node("synthesize", synthesize)

    builder.add_edge(START, "triage")
    builder.add_edge("ideate", "plan")
    builder.add_edge("plan", "execute_step")
    if reflection_off:
        builder.add_conditional_edges("execute_step", route_after_step, ["execute_step", "synthesize"])
    else:
        builder.add_node("reflect", reflect)
        builder.add_edge("execute_step", "reflect")
        builder.add_conditional_edges("reflect", route_after_step, ["execute_step", "synthesize"])
    builder.add_edge("react", END)
    builder.add_edge("synthesize", END)

    return builder.compile(checkpointer=checkpointer, name="planner")
