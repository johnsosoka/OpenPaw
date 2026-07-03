"""Planner harness StateGraph assembly (ADR-101 §1).

ponytail: this module is over the 700-line smell threshold by design — the
node functions are closures over shared build-time state (emitter, config,
run context, node models); splitting them into free functions would mean
threading that state through every signature. Split only if a node grows
beyond a screen or gains an independent reason to change.

Topology::

    START -> triage --Command(goto)--> react | ideate | plan | execute_step
    ideate -> plan
    plan -> execute_step
    execute_step -> reflect -> (execute_step | synthesize)   [reflection on]
    execute_step -> (execute_step | synthesize)              [reflection off]
    react -> END
    synthesize -> END

With tool equipping enabled (ADR-104; ``equipment`` passed)::

    triage plan-route  -> equip -> plan            (selection before planning)
    triage ideate-route -> ideate -> plan          (unchanged: full-catalog
                                                    planning; equip sits on the
                                                    plan path only, per the ADR
                                                    diagram — creative flows
                                                    keep every capability)
    execute_step --request_tools detected--> equip -> execute_step  (re-equip,
                                                    max once per step)

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
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal, cast

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables.config import (
    ensure_config,
    merge_configs,
    var_child_runnable_config,
)
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
from openpaw.agent.harness.planner.equipment import (
    EQUIP_REQUEST_BLOCK,
    EQUIP_SYSTEM_PROMPT,
    EQUIP_TASK_TEMPLATE,
    REQUEST_TOOLS_NAME,
    EquipDecision,
    EquipmentContext,
    detect_tool_request,
    render_catalog,
)
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
from openpaw.agent.metrics import NodeUsage, extract_metrics_from_callback
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
    node_model_ids: dict[str, str] | None = None,
    node_usage_sink: list[NodeUsage] | None = None,
    equipment: EquipmentContext | None = None,
    step_executor_factory: Callable[[list[str] | None], Any] | None = None,
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
        node_model_ids: Resolved model id per graph node name, for telemetry
            attribution (H6.3). Missing entries attribute as "".
        node_usage_sink: Mutable list per-node NodeUsage entries are appended
            to during a run; the harness flushes it to TokenUsageLogger.
            None discards the entries (events still emit).
        equipment: Tool-equipping context (ADR-104). None (the default)
            omits the equip node entirely — identical topology to today.
        step_executor_factory: Maps an equipped-tool-name list to a compiled
            executor graph for step runs; called with None for the full set
            (must return the shared react graph — zero behavior change when
            equipping is off). None falls back to ``react_graph`` directly.

    Returns:
        The compiled StateGraph.
    """
    reflection_off = harness_config.reflection.module == "off"
    max_steps = harness_config.execution.max_steps
    model_ids = node_model_ids or {}
    usage_sink = node_usage_sink if node_usage_sink is not None else []
    equipping = equipment is not None

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

    @asynccontextmanager
    async def _track_node(node: str) -> AsyncIterator[None]:
        """Per-node token/latency capture (H6.3, ADR-103 §5).

        Adds a node-scoped UsageMetadataCallbackHandler via the ambient
        runnable-config contextvar: merge_configs ADDS the handler to the
        inherited callbacks (the run-level handler keeps capturing), and
        every LLM call inside the scope — direct, structured-output, or
        module — picks it up through ensure_config() with zero changes to
        module code. Selector calls fold into their parent node's numbers.
        """
        handler = UsageMetadataCallbackHandler()
        token = var_child_runnable_config.set(
            merge_configs(ensure_config(), {"callbacks": [handler]})
        )
        start = time.monotonic()
        try:
            yield
        finally:
            var_child_runnable_config.reset(token)
            duration_ms = (time.monotonic() - start) * 1000
            model_id = model_ids.get(node, "")
            metrics = extract_metrics_from_callback(handler, duration_ms, model_id)
            usage_sink.append(NodeUsage(node=node, metrics=metrics))
            await _emit(
                StatusEventKind.NODE_COMPLETED,
                node,
                {
                    "node": node,
                    "model": model_id,
                    "input_tokens": metrics.input_tokens,
                    "output_tokens": metrics.output_tokens,
                    "total_tokens": metrics.total_tokens,
                    "duration_ms": metrics.duration_ms,
                },
            )

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

        # Entry event (no "route" key) — renders the "Thinking..." status
        # while the triage model decides; the post-decision event below
        # carries the chosen route (feedback round 1).
        await _emit(StatusEventKind.NODE_ENTERED, "triage", {})
        async with _track_node("triage"):
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
        objective = decision.objective or last_text[:500]
        update: dict[str, Any] = {"route": decision.route, "objective": objective}
        # goto is Any on purpose: "equip" is outside the declared Literal
        # (annotating it would create a static edge that breaks compile when
        # the node is absent); LangGraph resolves Command targets at runtime.
        goto: Any = decision.route
        if equipping:
            if decision.route == "plan":
                # ADR-104: equip sits on the plan path, before planning.
                goto = "equip"
                # Only execute_step sets requested_tools; clear any stale
                # marker from a timed-out previous run on this thread.
                update["requested_tools"] = None
            elif decision.route == "ideate":
                # Ideate route plans with the full catalog (no equip node in
                # the path); drop any stale selection from a prior plan run.
                update["equipped_tools"] = None
        return Command(update=update, goto=goto)

    # --- ideate ---------------------------------------------------------------

    async def ideate(state: PlannerState) -> dict[str, Any]:
        """Run the creative module; failure skips ideation (fail-open)."""
        await _emit(StatusEventKind.NODE_ENTERED, "ideate", {})
        objective = _objective(state)
        async with _track_node("ideate"):
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
        async with _track_node("plan"):
            new_plan = await _plan_with_fallback(state, objective)
            await _emit(
                StatusEventKind.PLAN_CREATED,
                "plan",
                {"plan": cast(JsonValue, new_plan.to_payload())},
            )
        first = new_plan.next_pending()
        update: dict[str, Any] = {
            "plan": plan_to_state(new_plan),
            "current_step_id": first.id if first else None,
            "step_results": [],
            "resume_step_id": None,
            "abort_reason": None,
        }
        if equipping:
            # Fresh plan, fresh recovery budget; equipped_tools was just set
            # by the equip node and is deliberately left alone.
            update["requested_tools"] = None
            update["reequipped_steps"] = []
        return update

    # --- equip (ADR-104; node only added when equipment is provided) -------------

    async def equip(state: PlannerState) -> Command[Literal["plan", "execute_step"]]:
        """Select the tool subset for this task (H5.1) or re-equip (H5.3).

        Entered from triage (plan route) before planning, or from
        execute_step when the executor called request_tools. Any failure
        fails open to the full toolset (equipped_tools=None) — equipping
        must never make the harness less capable than it is today.
        """
        assert equipment is not None  # node exists only when equipping is on
        requested = state.get("requested_tools")
        goto: Literal["plan", "execute_step"] = "execute_step" if requested else "plan"
        await _emit(StatusEventKind.NODE_ENTERED, "equip", {"requested": requested})

        catalog_names = {entry.name for entry in equipment.catalog}
        equipped: list[str] | None
        async with _track_node("equip"):
            try:
                content = EQUIP_TASK_TEMPLATE.format(
                    objective=_objective(state), catalog=render_catalog(equipment.catalog)
                )
                if requested:
                    content += EQUIP_REQUEST_BLOCK.format(requested=requested)
                decision = await equipment.model.with_structured_output(EquipDecision).ainvoke(
                    [
                        SystemMessage(EQUIP_SYSTEM_PROMPT.format(max_tools=equipment.max_tools)),
                        HumanMessage(content),
                    ]
                )
                if not isinstance(decision, EquipDecision):
                    raise TypeError(f"equip returned {type(decision).__name__}")
                unknown = [n for n in decision.equip if n not in catalog_names]
                if unknown:
                    logger.warning("Equip selected unknown tools (dropped): %s", sorted(unknown))
                known = [n for n in decision.equip if n in catalog_names]
                if len(known) > equipment.max_tools:
                    logger.warning(
                        "Equip selection over max_tools (%d > %d); clamping",
                        len(known),
                        equipment.max_tools,
                    )
                equipped = sorted(set(known[: equipment.max_tools]) | equipment.floor | {REQUEST_TOOLS_NAME})
                reason = decision.reason
            except Exception:
                # Fail-open (ADR-104): everything stays equipped.
                logger.warning("Equip selection failed; equipping all tools", exc_info=True)
                equipped = None
                reason = "equip failed; all tools equipped"

        kept = len(equipped) if equipped is not None else len(catalog_names)
        dropped = len(catalog_names - set(equipped)) if equipped is not None else 0
        await _emit(
            StatusEventKind.TOOLS_EQUIPPED,
            "equip",
            {
                "kept": kept,
                "dropped": dropped,
                "tools": cast(JsonValue, equipped if equipped is not None else sorted(catalog_names)),
                "reason": reason,
            },
        )
        return Command(update={"equipped_tools": equipped, "requested_tools": None}, goto=goto)

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
        # Equipped runs get a step-scoped executor built for the subset;
        # None (equipping off, or equip fail-open) is the shared react graph.
        executor = (
            step_executor_factory(state.get("equipped_tools"))
            if step_executor_factory is not None
            else react_graph
        )
        step_start = time.monotonic()
        result = await executor.ainvoke({"messages": [HumanMessage(prompt)]}, config=step_config)
        run_context.executing_step_id = None
        # Duration only — token keys omitted: the inner run's tokens are
        # captured by the run-level usage callback (no double-count, H6.3).
        await _emit(
            StatusEventKind.NODE_COMPLETED,
            "execute",
            {
                "node": "execute",
                "model": model_ids.get("execute", ""),
                "step_id": step.id,
                "duration_ms": (time.monotonic() - step_start) * 1000,
            },
        )

        result_messages = result.get("messages", []) if isinstance(result, dict) else []
        summary = extract_message_text(result_messages[-1].content) if result_messages else ""
        for msg in result_messages:
            for tc in getattr(msg, "tool_calls", None) or []:
                if name := tc.get("name"):
                    run_context.tools_used.append(name)

        if equipping:
            requested = detect_tool_request(result_messages)
            already_reequipped = state.get("reequipped_steps", [])
            if requested and step.id not in already_reequipped:
                # H5.3 recovery: route back to equip; the step stays
                # in-progress and re-executes with the rebuilt subset.
                # Max one re-equip per step — a second request falls
                # through to the normal reflect/advance path.
                logger.info("Step %s requested tools (%s); re-equipping", step.id, requested)
                return {
                    "plan": plan_to_state(working),
                    "requested_tools": requested,
                    "reequipped_steps": [*already_reequipped, step.id],
                    "resume_step_id": None,
                }

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
        await _emit(StatusEventKind.NODE_ENTERED, "reflect", {})
        step_results = state.get("step_results", [])
        last_result = step_results[-1] if step_results else ""
        objective = _objective(state)

        async with _track_node("reflect"):
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
                verdict = ReflectionVerdict(
                    action="advance", step_succeeded=True, notes="reflection failed; advancing"
                )
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
            {
                "verdict": verdict.action,
                "reason": verdict.notes,
                "step_succeeded": verdict.step_succeeded,
            },
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
        async with _track_node("synthesize"):
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

    def route_after_execute(state: PlannerState) -> Literal["equip", "execute_step", "synthesize", "reflect"]:
        """Equipping only: intercept a pending request_tools ask (H5.3)."""
        if state.get("requested_tools"):
            return "equip"
        return "reflect" if not reflection_off else route_after_step(state)

    builder: StateGraph[PlannerState, None, PlannerState, PlannerState] = StateGraph(PlannerState)
    builder.add_node("triage", triage)
    builder.add_node("react", react_graph)  # CompiledStateGraph embeds as a namespaced subgraph
    builder.add_node("ideate", ideate)
    builder.add_node("plan", plan_node)
    builder.add_node("execute_step", execute_step)
    builder.add_node("synthesize", synthesize)
    if equipping:
        builder.add_node("equip", equip)  # entered via triage/execute_step routing

    builder.add_edge(START, "triage")
    builder.add_edge("ideate", "plan")
    builder.add_edge("plan", "execute_step")
    if reflection_off:
        if equipping:
            builder.add_conditional_edges(
                "execute_step", route_after_execute, ["equip", "execute_step", "synthesize"]
            )
        else:
            builder.add_conditional_edges("execute_step", route_after_step, ["execute_step", "synthesize"])
    else:
        builder.add_node("reflect", reflect)
        if equipping:
            builder.add_conditional_edges("execute_step", route_after_execute, ["equip", "reflect"])
        else:
            builder.add_edge("execute_step", "reflect")
        builder.add_conditional_edges("reflect", route_after_step, ["execute_step", "synthesize"])
    builder.add_edge("react", END)
    builder.add_edge("synthesize", END)

    return builder.compile(checkpointer=checkpointer, name="planner")
