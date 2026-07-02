"""PlannerHarness — the planner-topology implementation of AgentHarness.

Wraps the existing ``AgentRunner`` (the react execution engine) inside the
ADR-101 planner StateGraph. All parity-critical contracts mirror the runner:

- run(): astream(stream_mode="updates"), asyncio.timeout, usage-callback
  metrics, TIMEOUT_NOTIFICATION templates.
- Approval: ApprovalRequiredError re-raises after recording a
  ``resume_step_id`` marker so the approval re-run jumps straight back to
  the paused plan step (the approval middleware's check_recent_approval
  then lets the tool through).
- Interrupt: InterruptSignalError re-raises after clearing plan state — an
  abort abandons the plan. Steer needs no special handling: the follow-up
  run re-enters triage naturally and fresh plan state overwrites the old.
- resolve_orphaned_tool_calls/get_context_info operate on the OUTER graph
  state (the react node owns ``messages`` on the direct route; step-scoped
  inner runs are unpersisted, so there is nothing to repair — a no-op).
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage, ToolMessage

from openpaw.agent.harness.base import AgentHarness, HarnessKind
from openpaw.agent.harness.modules.base import ModuleKind, ReasoningModule, ToolSummary, WorkspaceInfo
from openpaw.agent.harness.modules.direct import DirectPlanner
from openpaw.agent.harness.modules.ideonomy import IdeonomyModule
from openpaw.agent.harness.modules.reflection import FullReflection, LightReflection
from openpaw.agent.harness.modules.self_discover import SelfDiscoverPlanner, StructureCache
from openpaw.agent.harness.planner.equipment import (
    EquipmentContext,
    build_tool_catalog,
    create_request_tools_tool,
    resolve_equip_floor,
)
from openpaw.agent.harness.planner.graph import PlannerNodeModels, build_planner_graph, extract_message_text
from openpaw.agent.harness.planner.state import PlannerRunContext
from openpaw.agent.metrics import (
    InvocationMetrics,
    NodeUsage,
    TokenUsageLogger,
    extract_metrics_from_callback,
)
from openpaw.agent.middleware.approval import ApprovalRequiredError
from openpaw.agent.middleware.queue_aware import InterruptSignalError
from openpaw.agent.runner import AgentRunner
from openpaw.core.config.models.harness import HarnessConfig, NodeModelConfig
from openpaw.core.prompts.system_events import (
    TIMEOUT_NOTIFICATION_GENERIC,
    TIMEOUT_NOTIFICATION_TEMPLATE,
)
from openpaw.core.workspace import AgentWorkspace
from openpaw.model.status_event import StatusEmitter, StatusEvent

if TYPE_CHECKING:
    # Type-only: a runtime import would point upward (agent -> workspace)
    # against the stability contract. The factory (workspace layer) injects
    # the resolver instance.
    from openpaw.workspace.node_model_resolver import NodeModelResolver

logger = logging.getLogger(__name__)


class _NullEmitter:
    """Local no-op default (runtime's NullStatusEmitter is an upward import)."""

    async def emit(self, event: StatusEvent) -> None:
        """Discard the event."""
        return None


class PlannerHarness:
    """Planner agent harness: triage -> (react | plan | ideate) -> execute/reflect.

    Satisfies :class:`AgentHarness`; ``MessageProcessor``/``WorkspaceRunner``
    hold the protocol and never see the graph topology.
    """

    def __init__(
        self,
        workspace: AgentWorkspace,
        inner: AgentRunner,
        harness_config: HarnessConfig,
        node_resolver: "NodeModelResolver",
        emitter: StatusEmitter | None = None,
        module_candidates: dict[ModuleKind, dict[str, ReasoningModule]] | None = None,
        step_agent_builder: Callable[[list[Any]], AgentRunner] | None = None,
    ) -> None:
        """Initialize the harness and compile the graph.

        Args:
            workspace: The loaded agent workspace.
            inner: The react execution engine (constructed by AgentFactory
                exactly as today, checkpointer included).
            harness_config: The workspace ``harness:`` config group.
            node_resolver: Per-node model resolution (ADR-103).
            emitter: Status event emitter; defaults to a no-op.
            module_candidates: Reasoning-module instances per kind. Defaults
                to instantiating everything registered in MODULE_REGISTRY.
            step_agent_builder: Builds an AgentRunner for a filtered
                additional-tools list (tool equipping, ADR-104). Injected by
                AgentFactory — the factory owns all construction params, so
                step-scoped executors are built with the same workspace,
                model, and middleware as the inner runner. None disables
                subset executors (equipped runs fall back to the full set).
        """
        self.workspace = workspace
        self._inner = inner
        self._config = harness_config
        self._node_resolver = node_resolver
        self._emitter: StatusEmitter = emitter if emitter is not None else _NullEmitter()
        self._candidates = module_candidates or self._build_module_candidates()
        self._step_agent_builder = step_agent_builder
        # Step executors per equipped-set, valid until the next recompile.
        self._executor_cache: dict[frozenset[str], Any] = {}

        self.timeout_seconds: float = inner.timeout_seconds
        self._run_context = PlannerRunContext()
        self._last_metrics: InvocationMetrics | None = None
        self._last_tools_used: list[str] = []
        # Per-node telemetry (H6.3): graph nodes append NodeUsage entries to
        # this sink; run() flushes them to the JSONL log as breakdown rows.
        # ponytail: own TokenUsageLogger instance (same append-only file)
        # rather than threading the initializer's through the constructor.
        self._node_usage: list[NodeUsage] = []
        self._token_logger = TokenUsageLogger(workspace.path)
        self._node_models = self._build_node_models()
        self._graph = self._compile()

    # ------------------------------------------------------------------
    # Protocol surface — identity and delegated read-only state
    # ------------------------------------------------------------------

    @property
    def kind(self) -> HarnessKind:
        """Which harness topology this implements."""
        return HarnessKind.PLANNER

    @property
    def model_id(self) -> str:
        """The execution model identifier (the inner runner's model)."""
        return self._inner.model_id

    @property
    def last_metrics(self) -> InvocationMetrics | None:
        """Token usage from the most recent run(), or None before first run."""
        return self._last_metrics

    @property
    def last_tools_used(self) -> list[str]:
        """Tool names invoked during the most recent run."""
        return self._last_tools_used

    @property
    def max_output_tokens(self) -> int | None:
        """The execution model's output token cap."""
        return self._inner.max_output_tokens

    @property
    def checkpointer(self) -> Any | None:
        """The active checkpointer (shared with the inner runner)."""
        return self._inner.checkpointer

    @property
    def additional_tools(self) -> list[Any]:
        """The current non-filesystem tool set."""
        return list(self._inner.additional_tools)

    @property
    def agent_graph(self) -> Any:
        """The compiled outer planner graph (tests and diagnostics)."""
        return self._graph

    @property
    def node_resolver(self) -> "NodeModelResolver":
        """Per-node model resolver, exposed for /harness introspection (C9)."""
        return self._node_resolver

    # ------------------------------------------------------------------
    # Build / rebuild
    # ------------------------------------------------------------------

    def _build_module_candidates(self) -> dict[ModuleKind, dict[str, ReasoningModule]]:
        """Instantiate every registered reasoning module with its dependencies.

        Explicit per-module construction (mirroring MODULE_REGISTRY): modules
        with dependencies (SelfDiscover's structure cache) get them here; a
        registry loop would hide the wiring.
        """
        return {
            ModuleKind.PLANNING: {
                "direct": DirectPlanner(),
                "self_discover": SelfDiscoverPlanner(StructureCache(self.workspace.path)),
            },
            ModuleKind.CREATIVE: {"ideonomy": IdeonomyModule()},
            ModuleKind.REFLECTION: {"light": LightReflection(), "full": FullReflection()},
        }

    def _build_node_models(self) -> PlannerNodeModels:
        """Instantiate the per-node models from config (cached until rebuild)."""
        r = self._node_resolver
        return PlannerNodeModels(
            triage=r.create_node_model(self._config.triage),
            planning=r.create_node_model(self._config.planning),
            creative=r.create_node_model(self._config.creative),
            reflection=r.create_node_model(self._config.reflection),
            selector=r.create_node_model(self._config.selector),
            synthesize=r.create_node_model(self._config.synthesize),
        )

    def _node_model_ids(self) -> dict[str, str]:
        """Resolved model id per graph node, for telemetry attribution (H6.3)."""
        r = self._node_resolver
        ids = {
            "triage": r.resolve_node(self._config.triage).display_str,
            "ideate": r.resolve_node(self._config.creative).display_str,
            "plan": r.resolve_node(self._config.planning).display_str,
            "reflect": r.resolve_node(self._config.reflection).display_str,
            "synthesize": r.resolve_node(self._config.synthesize).display_str,
            "execute": self._inner.model_id,
        }
        if self._config.tool_equipping.enabled:
            ids["equip"] = r.resolve_node(self._equip_node_config()).display_str
        return ids

    def _equip_node_config(self) -> NodeModelConfig:
        """The equip node's model pointer (inherits workspace when unset)."""
        return NodeModelConfig(model=self._config.tool_equipping.model)

    def _build_equipment(self) -> EquipmentContext | None:
        """Assemble the ADR-104 equip context, or None when disabled."""
        cfg = self._config.tool_equipping
        if not cfg.enabled:
            return None
        tools = list(self._inner.additional_tools)
        return EquipmentContext(
            catalog=build_tool_catalog(tools),
            floor=frozenset(resolve_equip_floor(cfg.always_equip, tools)),
            model=self._node_resolver.create_node_model(self._equip_node_config()),
            max_tools=cfg.max_tools,
        )

    def _step_executor_factory(self, tool_names: list[str] | None) -> Any:
        """Compiled executor for one plan step (ADR-104, repo landmine 5).

        None means the full toolset — the shared inner graph, byte-for-byte
        today's path (equipping off, or equip fail-open). A name list builds
        a step-scoped agent whose additional tools are filtered to the
        subset plus the request_tools escape hatch; filesystem tools are
        always present because AgentRunner adds them internally (the floor's
        group:filesystem is structural). Executors are cached per equipped
        set until the next recompile.
        """
        if tool_names is None:
            return self._inner.agent_graph
        key = frozenset(tool_names)
        cached = self._executor_cache.get(key)
        if cached is not None:
            return cached
        if self._step_agent_builder is None:
            logger.warning("Tool equipping selected a subset but no step-agent builder is wired; using full toolset")
            return self._inner.agent_graph
        subset = [
            tool
            for tool in self._inner.additional_tools
            if str(getattr(tool, "name", tool)) in key
        ]
        subset.append(create_request_tools_tool())
        graph = self._step_agent_builder(subset).agent_graph
        self._executor_cache[key] = graph
        return graph

    def _tools_summary(self) -> list[ToolSummary]:
        """Name + first description line per tool, for planner awareness."""
        summary = [
            ToolSummary(
                name="filesystem",
                description="Sandboxed workspace file tools (read, write, edit, list, search)",
            )
        ]
        for tool in self._inner.additional_tools:
            description = str(getattr(tool, "description", "") or "").strip()
            first_line = description.split("\n")[0].split(". ")[0][:150]
            summary.append(ToolSummary(name=str(getattr(tool, "name", tool)), description=first_line))
        return summary

    def _compile(self) -> Any:
        """Compile the outer graph around the inner runner's compiled agent."""
        self._executor_cache.clear()  # tools/model/checkpointer may have changed
        config = self.workspace.config
        workspace_info = WorkspaceInfo(
            name=self.workspace.name,
            timezone=config.timezone if config else "UTC",
            workspace_path=self.workspace.path,
        )
        return build_planner_graph(
            react_graph=self._inner.agent_graph,
            node_models=self._node_models,
            harness_config=self._config,
            candidates=self._candidates,
            emitter=self._emitter,
            workspace_info=workspace_info,
            tools_summary=self._tools_summary(),
            run_context=self._run_context,
            checkpointer=self._inner.checkpointer,
            inner_recursion_limit=self._inner.max_turns * 2,
            node_model_ids=self._node_model_ids(),
            node_usage_sink=self._node_usage,
            equipment=self._build_equipment(),
            step_executor_factory=self._step_executor_factory,
        )

    def rebuild_agent(self) -> None:
        """Reload workspace state, rebuild the inner agent, and recompile."""
        self._inner.rebuild_agent()
        self._node_models = self._build_node_models()
        self._graph = self._compile()

    def update_tools(self, extra_tools: list[Any]) -> None:
        """Replace the additional-tools set on the inner runner and recompile."""
        self._inner.update_tools(extra_tools)
        self._graph = self._compile()

    def update_model(self, model: str, api_key: str | None = None, temperature: float | None = None) -> None:
        """Apply a runtime model override to the EXECUTION engine only.

        Node models keep their configured values (ADR-103 §4).
        """
        self._inner.update_model(model, api_key=api_key, temperature=temperature)
        self._graph = self._compile()

    def update_checkpointer(self, checkpointer: Any) -> None:
        """Swap the checkpointer on the inner runner and recompile the outer graph."""
        self._inner.update_checkpointer(checkpointer)
        self._graph = self._compile()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    @staticmethod
    def _session_key_from(thread_id: str | None, session_id: str | None) -> str | None:
        """Derive the session key ("{channel}:{id}") for event attribution."""
        if thread_id and ":" in thread_id:
            return thread_id.rsplit(":", 1)[0]
        return session_id

    def _build_config(self, session_id: str | None, thread_id: str | None) -> dict[str, Any]:
        """Invocation config, mirroring AgentRunner.run()."""
        config: dict[str, Any] = {
            "recursion_limit": max(self._inner.max_turns * 2, self._config.execution.max_steps * 2 + 8)
        }
        if session_id or thread_id:
            config["configurable"] = {}
            if thread_id:
                config["configurable"]["thread_id"] = thread_id
            if session_id:
                config["configurable"]["session_id"] = session_id
        return config

    def _ingest_update(self, update: dict[str, Any], final_text: str) -> str:
        """Track tool calls and the latest AI response from one stream update."""
        for node_update in update.values():
            if not isinstance(node_update, dict):
                continue
            messages = node_update.get("messages") or []
            for msg in messages:
                tool_calls = getattr(msg, "tool_calls", None) or []
                for tc in tool_calls:
                    if name := tc.get("name"):
                        self._last_tools_used.append(name)
                        self._run_context.current_tool_name = name
                if isinstance(msg, AIMessage) and not tool_calls:
                    text = extract_message_text(msg.content)
                    if text.strip():
                        final_text = text
        return final_text

    async def run(self, message: str, session_id: str | None = None, thread_id: str | None = None) -> str:
        """Execute one turn through the planner graph.

        Raises:
            ApprovalRequiredError: A gated tool needs approval; a resume
                marker is recorded first when a plan step was executing.
            InterruptSignalError: The run was interrupted; plan state is
                cleared first (abort abandons the plan).
        """
        self._last_metrics = None
        self._last_tools_used = []
        self._node_usage.clear()
        self._run_context.reset(
            run_id=uuid.uuid4().hex[:12],
            session_key=self._session_key_from(thread_id, session_id),
        )

        config = self._build_config(session_id, thread_id)
        usage_callback = UsageMetadataCallbackHandler()
        config["callbacks"] = [usage_callback]
        start_time = time.monotonic()

        logger.info(
            "Planner run starting (workspace: %s, model: %s, thread: %s)",
            self.workspace.name,
            self.model_id,
            thread_id or "new",
        )
        final_text = ""
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async for update in self._graph.astream(
                    {"messages": [{"role": "user", "content": message}]},
                    config=config,
                    stream_mode="updates",
                ):
                    final_text = self._ingest_update(update, final_text)
        except InterruptSignalError:
            await self._clear_plan_state(config)
            raise
        except ApprovalRequiredError:
            await self._record_resume_marker(config)
            raise
        except TimeoutError:
            duration_ms = (time.monotonic() - start_time) * 1000
            self._last_metrics = extract_metrics_from_callback(usage_callback, duration_ms, self.model_id)
            self._last_metrics.is_partial = True
            self._last_tools_used.extend(self._run_context.tools_used)
            logger.warning(
                "Planner run timed out after %ss (workspace: %s)", self.timeout_seconds, self.workspace.name
            )
            if self._run_context.current_tool_name:
                return TIMEOUT_NOTIFICATION_TEMPLATE.format(
                    timeout=int(self.timeout_seconds),
                    tool_name=self._run_context.current_tool_name,
                )
            return TIMEOUT_NOTIFICATION_GENERIC.format(timeout=int(self.timeout_seconds))
        finally:
            # Flush per-node telemetry on every exit path — partial runs
            # (timeout, approval, interrupt) still burned those tokens.
            self._flush_node_usage()

        duration_ms = (time.monotonic() - start_time) * 1000
        self._last_metrics = extract_metrics_from_callback(usage_callback, duration_ms, self.model_id)
        self._last_tools_used.extend(self._run_context.tools_used)
        return final_text

    def _flush_node_usage(self) -> None:
        """Write per-node JSONL breakdown rows (H6.3), one per node name.

        These rows are ADDITIONAL to the run-level row MessageProcessor logs
        (same tokens, sliced by node) — TokenUsageReader skips rows with a
        ``node`` field so totals are not double-counted. The execute node
        never appears here: its inner-run tokens belong to the run-level
        record alone.
        """
        if not self._node_usage:
            return
        aggregated: dict[str, InvocationMetrics] = {}
        for entry in self._node_usage:
            agg = aggregated.setdefault(entry.node, InvocationMetrics(model=entry.metrics.model))
            agg.input_tokens += entry.metrics.input_tokens
            agg.output_tokens += entry.metrics.output_tokens
            agg.total_tokens += entry.metrics.total_tokens
            agg.llm_calls += entry.metrics.llm_calls
            agg.duration_ms += entry.metrics.duration_ms
            agg.is_partial = agg.is_partial or entry.metrics.is_partial
        for node, metrics in aggregated.items():
            self._token_logger.log(
                metrics,
                workspace=self.workspace.name,
                invocation_type="node",
                session_key=self._run_context.session_key,
                node=node,
                harness=self.kind.value,
            )
        self._node_usage.clear()

    async def _record_resume_marker(self, config: dict[str, Any]) -> None:
        """Approval contract: remember which plan step was paused.

        The approval re-run submits the same message; triage sees the marker
        and jumps straight back to execute_step, where check_recent_approval
        lets the gated tool through. No-op on the react route (no step was
        executing) or for stateless instances.
        """
        step_id = self._run_context.executing_step_id
        if not step_id or self.checkpointer is None or "configurable" not in config:
            return
        try:
            await self._graph.aupdate_state(config, {"resume_step_id": step_id}, as_node="plan")
            logger.info("Recorded approval-resume marker for plan step %s", step_id)
        except Exception:
            logger.warning("Failed to record approval-resume marker", exc_info=True)

    async def _clear_plan_state(self, config: dict[str, Any]) -> None:
        """Interrupt contract: an aborted run abandons the plan entirely."""
        if self.checkpointer is None or "configurable" not in config:
            return
        try:
            await self._graph.aupdate_state(
                config,
                {
                    "plan": None,
                    "current_step_id": None,
                    "resume_step_id": None,
                    "abort_reason": None,
                    "step_results": [],
                    "equipped_tools": None,
                    "requested_tools": None,
                    "reequipped_steps": [],
                },
                as_node="plan",
            )
            logger.info("Cleared plan state after interrupt")
        except Exception:
            logger.warning("Failed to clear plan state after interrupt", exc_info=True)

    # ------------------------------------------------------------------
    # Checkpoint maintenance (outer graph state)
    # ------------------------------------------------------------------

    async def get_context_info(self, thread_id: str) -> dict[str, Any]:
        """Context-window utilization of the outer thread (auto-compact check).

        Same math as AgentRunner.get_context_info, applied to the outer graph
        (~25 duplicated lines accepted over exposing runner internals).
        """
        from langchain_core.messages.utils import count_tokens_approximately

        config = {"configurable": {"thread_id": thread_id}}
        state = await self._graph.aget_state(config)
        if not state or not state.values:
            return {
                "max_input_tokens": 0,
                "approximate_tokens": 0,
                "utilization": 0.0,
                "message_count": 0,
            }

        messages = state.values.get("messages", [])
        approx_tokens = count_tokens_approximately(messages, use_usage_metadata_scaling=True)

        max_input = 200000  # fallback
        model_instance = self._inner.model_instance
        profile = getattr(model_instance, "profile", None) if model_instance else None
        if profile:
            max_input = profile.get("max_input_tokens", 200000)

        return {
            "max_input_tokens": max_input,
            "approximate_tokens": approx_tokens,
            "utilization": approx_tokens / max_input if max_input > 0 else 0.0,
            "message_count": len(messages),
        }

    async def resolve_orphaned_tool_calls(self, thread_id: str, responses: dict[str, str] | None = None) -> None:
        """Inject synthetic ToolMessages for orphaned tool_calls in OUTER state.

        Orphans only occur on the direct react route (the react node owns
        ``messages``); step-scoped inner runs are unpersisted, so the typical
        execute_step approval case finds nothing to repair — correctly a
        no-op. ``as_node="react"`` mirrors the runner's ``as_node="tools"``
        rationale: the update must come from the node that appends messages.
        """
        if not self.checkpointer:
            return

        config = {"configurable": {"thread_id": thread_id}}
        state = await self._graph.aget_state(config)
        if not state or not state.values:
            return

        messages = state.values.get("messages", [])
        if not messages:
            return

        last_ai_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], AIMessage) and getattr(messages[i], "tool_calls", None):
                last_ai_idx = i
                break
        if last_ai_idx is None:
            return

        resolved_ids = {
            msg.tool_call_id for msg in messages[last_ai_idx + 1 :] if isinstance(msg, ToolMessage)
        }
        orphaned = [tc for tc in messages[last_ai_idx].tool_calls if tc.get("id") not in resolved_ids]
        if not orphaned:
            return

        responses = responses or {}
        synthetic = [
            ToolMessage(
                content=responses.get(tc.get("id", ""), "Tool execution was interrupted."),
                tool_call_id=tc.get("id", ""),
            )
            for tc in orphaned
        ]
        logger.info("Resolving %d orphaned tool call(s) in thread %s", len(synthetic), thread_id)
        await self._graph.aupdate_state(config, {"messages": synthetic}, as_node="react")


def _protocol_conformance(harness: PlannerHarness) -> AgentHarness:
    """Compile-time check that PlannerHarness satisfies AgentHarness.

    mypy strict verifies the structural match here; drift in either surface
    fails type checking rather than exploding at runtime.
    """
    return harness
