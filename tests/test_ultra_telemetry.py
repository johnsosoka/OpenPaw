"""Per-node token/latency telemetry tests (T2.9, PRD-002 H6.3, ADR-103 §5).

Covers: node.completed events with correct token numbers, per-node JSONL
breakdown rows, the run-level record staying intact (no double-count), and
TokenUsageReader skipping breakdown rows during aggregation.
"""

import json
from itertools import cycle
from pathlib import Path
from typing import Any

from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import MemorySaver

from openpaw.agent.harness.modules.base import ModuleKind, WorkspaceInfo
from openpaw.agent.harness.modules.direct import DirectPlanner, _PlanSchema
from openpaw.agent.harness.modules.reflection import LightReflection, _VerdictSchema
from openpaw.agent.harness.ultra import UltraHarness
from openpaw.agent.harness.ultra.graph import UltraNodeModels, TriageDecision, build_ultra_graph
from openpaw.agent.harness.ultra.state import UltraRunContext
from openpaw.agent.metrics import (
    InvocationMetrics,
    NodeUsage,
    TokenUsageLogger,
    TokenUsageReader,
)
from openpaw.agent.runner import AgentRunner
from openpaw.core.config.models import HarnessConfig
from openpaw.core.paths import TOKEN_USAGE_JSONL
from openpaw.model.status_event import StatusEventKind
from tests.test_ultra_graph import CaptureEmitter, fake, make_fake_react
from tests.test_ultra_harness import StubGraph, make_node_resolver, make_workspace

# ---------------------------------------------------------------------------
# Usage-reporting fake model
# ---------------------------------------------------------------------------


class UsageModel(GenericFakeChatModel):
    """Fake chat model that reports usage_metadata and structured outputs.

    Real callback machinery runs (BaseChatModel.agenerate), so per-node
    UsageMetadataCallbackHandlers capture usage exactly as with providers.
    """

    structured: list[Any] = []

    def with_structured_output(self, schema: type, **kwargs: Any) -> Any:
        # Model invocation (usage fires) piped into a parser stand-in.
        return self | RunnableLambda(lambda _msg: self.structured.pop(0))


def usage_model(model_name: str, input_tokens: int, output_tokens: int, *structured: object) -> Any:
    msg = AIMessage(
        content=f"{model_name} reply",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
        response_metadata={"model_name": model_name},
    )
    return UsageModel(messages=cycle([msg]), structured=list(structured))


def build_graph(
    *,
    triage: Any,
    planning: Any,
    reflection: Any,
    synthesize: Any,
    emitter: CaptureEmitter,
    sink: list[NodeUsage],
    react: Any = None,
) -> Any:
    return build_ultra_graph(
        react_graph=react if react is not None else make_fake_react(["step done"], []),
        node_models=UltraNodeModels(
            triage=triage,
            planning=planning,
            creative=fake(),
            reflection=reflection,
            selector=fake(),
            synthesize=synthesize,
        ),
        harness_config=HarnessConfig(type="ultra"),
        candidates={
            ModuleKind.PLANNING: {"direct": DirectPlanner()},
            ModuleKind.CREATIVE: {},
            ModuleKind.REFLECTION: {"light": LightReflection()},
        },
        emitter=emitter,
        workspace_info=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=Path("/tmp/ws")),
        tools_summary=[],
        run_context=UltraRunContext(),
        checkpointer=None,
        inner_recursion_limit=20,
        node_model_ids={
            "triage": "triage-model",
            "plan": "plan-model",
            "reflect": "reflect-model",
            "synthesize": "synth-model",
            "execute": "exec-model",
        },
        node_usage_sink=sink,
    )


def completed_events(emitter: CaptureEmitter) -> dict[str, Any]:
    return {e.node: e for e in emitter.events if e.kind is StatusEventKind.NODE_COMPLETED}


# ---------------------------------------------------------------------------
# node.completed events + sink (plan route)
# ---------------------------------------------------------------------------


async def test_plan_route_emits_node_completed_with_token_numbers() -> None:
    emitter = CaptureEmitter()
    sink: list[NodeUsage] = []
    graph = build_graph(
        triage=usage_model("triage-model", 11, 7, TriageDecision(route="plan", objective="obj", reason="r")),
        planning=usage_model("plan-model", 101, 53, _PlanSchema(steps=["only step"])),
        reflection=usage_model("reflect-model", 23, 13, _VerdictSchema(action="advance", step_succeeded=True)),
        synthesize=usage_model("synth-model", 31, 17),
        emitter=emitter,
        sink=sink,
    )
    run_handler = UsageMetadataCallbackHandler()

    await graph.ainvoke({"messages": [HumanMessage("do it")]}, config={"callbacks": [run_handler]})

    events = completed_events(emitter)
    assert set(events) == {"triage", "plan", "execute", "reflect", "synthesize"}
    expected = {
        "triage": ("triage-model", 11, 7),
        "plan": ("plan-model", 101, 53),
        "reflect": ("reflect-model", 23, 13),
        "synthesize": ("synth-model", 31, 17),
    }
    for node, (model, input_tokens, output_tokens) in expected.items():
        payload = events[node].payload
        assert payload["node"] == node
        assert payload["model"] == model
        assert payload["input_tokens"] == input_tokens
        assert payload["output_tokens"] == output_tokens
        assert payload["total_tokens"] == input_tokens + output_tokens
        assert isinstance(payload["duration_ms"], float) and payload["duration_ms"] > 0

    # Sink mirrors the deliberation nodes; execute never appears (its tokens
    # belong to the run-level record alone).
    assert {u.node for u in sink} == {"triage", "plan", "reflect", "synthesize"}
    by_node = {u.node: u.metrics for u in sink}
    assert by_node["plan"].total_tokens == 154
    assert by_node["plan"].model == "plan-model"
    assert all(u.metrics.duration_ms > 0 for u in sink)

    # No double-count and no capture-stealing: the run-level handler still
    # sees every deliberation call; node handlers are additive.
    run_total = sum(u["total_tokens"] for u in run_handler.usage_metadata.values())
    assert run_total == sum(u.metrics.total_tokens for u in sink)


async def test_execute_node_completed_has_step_id_and_no_token_keys() -> None:
    emitter = CaptureEmitter()
    sink: list[NodeUsage] = []
    graph = build_graph(
        triage=usage_model("triage-model", 1, 1, TriageDecision(route="plan", objective="obj", reason="r")),
        planning=usage_model("plan-model", 1, 1, _PlanSchema(steps=["only step"])),
        reflection=usage_model("reflect-model", 1, 1, _VerdictSchema(action="advance", step_succeeded=True)),
        synthesize=usage_model("synth-model", 1, 1),
        emitter=emitter,
        sink=sink,
    )

    await graph.ainvoke({"messages": [HumanMessage("do it")]})

    payload = completed_events(emitter)["execute"].payload
    assert set(payload) == {"node", "model", "step_id", "duration_ms"}
    assert payload["model"] == "exec-model"
    assert payload["step_id"] == "1"
    assert isinstance(payload["duration_ms"], float) and payload["duration_ms"] > 0


async def test_react_route_tracks_triage_only() -> None:
    emitter = CaptureEmitter()
    sink: list[NodeUsage] = []
    graph = build_graph(
        triage=usage_model("triage-model", 9, 4, TriageDecision(route="react", objective="hi", reason="simple")),
        planning=fake(),
        reflection=fake(),
        synthesize=fake(AIMessage(content="unused")),
        emitter=emitter,
        sink=sink,
        react=make_fake_react(["react reply"], []),
    )

    await graph.ainvoke({"messages": [HumanMessage("hi")]})

    assert set(completed_events(emitter)) == {"triage"}
    assert [u.node for u in sink] == ["triage"]
    assert sink[0].metrics.total_tokens == 13


# ---------------------------------------------------------------------------
# TokenUsageLogger node dimension
# ---------------------------------------------------------------------------


def read_rows(workspace_path: Path) -> list[dict[str, Any]]:
    log_path = workspace_path / str(TOKEN_USAGE_JSONL)
    return [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]


def test_logger_writes_node_and_harness_fields(tmp_path: Path) -> None:
    logger = TokenUsageLogger(tmp_path)
    logger.log(
        InvocationMetrics(input_tokens=10, output_tokens=5, total_tokens=15, model="m"),
        workspace="ws",
        invocation_type="node",
        session_key="telegram:1",
        node="triage",
        harness="ultra",
    )

    (row,) = read_rows(tmp_path)
    assert row["node"] == "triage"
    assert row["harness"] == "ultra"
    assert row["invocation_type"] == "node"
    assert row["total_tokens"] == 15


def test_logger_omits_node_fields_when_unset(tmp_path: Path) -> None:
    """Run-level rows keep exactly today's schema — the extension is additive."""
    logger = TokenUsageLogger(tmp_path)
    logger.log(InvocationMetrics(total_tokens=15, model="m"), workspace="ws", invocation_type="user")

    (row,) = read_rows(tmp_path)
    assert "node" not in row
    assert "harness" not in row


def test_reader_skips_node_breakdown_rows(tmp_path: Path) -> None:
    """Node rows re-slice run-level tokens; summing both would double-count."""
    logger = TokenUsageLogger(tmp_path)
    logger.log(
        InvocationMetrics(input_tokens=60, output_tokens=40, total_tokens=100, llm_calls=3, model="m"),
        workspace="ws",
        invocation_type="user",
        session_key="telegram:1",
    )
    for node, tokens in (("triage", 30), ("plan", 70)):
        logger.log(
            InvocationMetrics(total_tokens=tokens, llm_calls=1, model="m"),
            workspace="ws",
            invocation_type="node",
            session_key="telegram:1",
            node=node,
            harness="ultra",
        )

    reader = TokenUsageReader(tmp_path)
    assert reader.tokens_today().total_tokens == 100
    assert reader.tokens_today().llm_calls == 3
    assert reader.tokens_for_session("telegram:1").total_tokens == 100


def test_reader_tolerates_unknown_extra_fields(tmp_path: Path) -> None:
    log_path = tmp_path / str(TOKEN_USAGE_JSONL)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    from datetime import UTC, datetime

    row = {
        "timestamp": datetime.now(UTC).isoformat(),
        "workspace": "ws",
        "invocation_type": "user",
        "session_key": None,
        "total_tokens": 42,
        "future_field": {"nested": True},
    }
    log_path.write_text(json.dumps(row) + "\n")

    assert TokenUsageReader(tmp_path).tokens_today().total_tokens == 42


# ---------------------------------------------------------------------------
# UltraHarness flush
# ---------------------------------------------------------------------------


def make_harness(tmp_path: Path) -> UltraHarness:
    workspace = make_workspace(tmp_path)
    inner = AgentRunner(workspace=workspace, model="openai:gpt-4o-mini", api_key="test", checkpointer=MemorySaver())
    return UltraHarness(
        workspace=workspace,
        inner=inner,
        harness_config=HarnessConfig(type="ultra"),
        node_resolver=make_node_resolver(),
    )


def test_flush_aggregates_per_node_and_writes_rows(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    harness._node_usage.extend(
        [
            NodeUsage("triage", InvocationMetrics(total_tokens=10, llm_calls=1, duration_ms=5.0, model="fast")),
            NodeUsage("reflect", InvocationMetrics(total_tokens=20, llm_calls=1, duration_ms=8.0, model="strong")),
            NodeUsage("reflect", InvocationMetrics(total_tokens=30, llm_calls=1, duration_ms=9.0, model="strong")),
        ]
    )

    harness._flush_node_usage()

    rows = {row["node"]: row for row in read_rows(tmp_path)}
    assert set(rows) == {"triage", "reflect"}
    assert rows["reflect"]["total_tokens"] == 50  # aggregated across steps
    assert rows["reflect"]["llm_calls"] == 2
    assert rows["reflect"]["duration_ms"] == 17.0
    assert rows["reflect"]["harness"] == "ultra"
    assert rows["reflect"]["invocation_type"] == "node"
    assert harness._node_usage == []  # sink cleared after flush


async def test_run_flushes_node_usage_and_clears_stale_entries(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    # Stale entry from a previous (hypothetical) run must be cleared, not flushed.
    harness._node_usage.append(NodeUsage("stale", InvocationMetrics(total_tokens=999, model="old")))
    stub = StubGraph(
        on_start=lambda: harness._node_usage.append(
            NodeUsage("triage", InvocationMetrics(total_tokens=7, llm_calls=1, duration_ms=1.0, model="fast"))
        )
    )
    harness._graph = stub

    await harness.run("hello")

    rows = read_rows(tmp_path)
    assert [row["node"] for row in rows] == ["triage"]
    assert rows[0]["total_tokens"] == 7
