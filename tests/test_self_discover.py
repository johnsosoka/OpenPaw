"""Tests for SelfDiscoverPlanner and StructureCache (ADR-102 §3, ADR-109 §2)."""

import asyncio
import json
import logging
from pathlib import Path
from typing import TypedDict, cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

import openpaw.agent.harness.modules.self_discover.cache as cache_mod
from openpaw.agent.harness.modules.base import (
    ModuleKind,
    ReasoningContext,
    ToolSummary,
    WorkspaceInfo,
)
from openpaw.agent.harness.modules.direct import _PlanSchema
from openpaw.agent.harness.modules.self_discover import SelfDiscoverPlanner, StructureCache
from openpaw.agent.harness.modules.self_discover.planner import (
    _DEFAULT_SELECTED_INDICES,
    _AdaptSchema,
    _ImplementSchema,
    _SelectSchema,
    _StructureStep,
)
from openpaw.agent.harness.modules.self_discover.seed_modules import SEED_REASONING_MODULES
from openpaw.model.status_event import StatusEvent
from tests.test_reasoning_modules import FakeStructuredModel, fake_model, make_ctx, run_streamed

TASK = "Ship the quarterly report"
STRUCTURE = {"identify_inputs": "List required data", "sequence_work": "Order the steps"}


def make_planner(tmp_path: Path) -> tuple[SelfDiscoverPlanner, StructureCache]:
    cache = StructureCache(tmp_path)
    return SelfDiscoverPlanner(cache), cache


def discovery_outputs() -> list[object]:
    """SELECT, ADAPT, IMPLEMENT structured outputs followed by the structured plan."""
    return [
        _SelectSchema(selected_indices=[9, 16, 39]),
        _AdaptSchema(adapted_modules=["Break the report into data-gathering and writing."]),
        _ImplementSchema(
            steps=[
                _StructureStep(name="identify_inputs", instruction="List required data"),
                _StructureStep(name="sequence_work", instruction="Order the steps"),
            ]
        ),
        _PlanSchema(steps=["Gather data", "Write report"]),
    ]


def ws_ctx(model: BaseChatModel, tmp_path: Path) -> ReasoningContext:
    return make_ctx(
        model,
        workspace=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=tmp_path),
    )


# ---------------------------------------------------------------------------
# Ultra: discovery + solve flow
# ---------------------------------------------------------------------------


async def test_cache_miss_runs_three_discovery_calls_plus_solve(tmp_path: Path):
    planner, cache = make_planner(tmp_path)
    model = fake_model(*discovery_outputs())
    ctx = ws_ctx(model, tmp_path)

    artifact = await planner.run(ctx)

    fake = cast(FakeStructuredModel, model)
    assert fake.call_count == 4  # SELECT, ADAPT, IMPLEMENT, solve
    assert fake.schemas == [_SelectSchema, _AdaptSchema, _ImplementSchema, _PlanSchema]

    # SELECT: verbatim meta-prompt over all 39 numbered seed modules.
    assert "which of the following reasoning modules are relevant" in fake.prompts[0]
    assert all(module in fake.prompts[0] for module in SEED_REASONING_MODULES)
    assert TASK in fake.prompts[0]
    # ADAPT gets the texts of the selected modules (indices 9, 16, 39).
    assert SEED_REASONING_MODULES[8] in fake.prompts[1]
    assert SEED_REASONING_MODULES[15] in fake.prompts[1]
    assert SEED_REASONING_MODULES[38] in fake.prompts[1]
    # IMPLEMENT chains the adapted modules.
    assert "Break the report into data-gathering" in fake.prompts[2]
    # Solve follows the structure and gets the tools context.
    assert "Follow the step-by-step reasoning plan in JSON" in fake.prompts[3]
    assert "identify_inputs" in fake.prompts[3]
    assert "- web_search: Search the web" in fake.prompts[3]

    assert artifact.kind == ModuleKind.PLANNING
    assert artifact.plan is not None
    assert [s.id for s in artifact.plan.steps] == ["1", "2"]
    assert [s.description for s in artifact.plan.steps] == ["Gather data", "Write report"]
    assert artifact.reasoning_structure == STRUCTURE
    # Step order preserved: the structure dict is insertion-ordered.
    assert list(artifact.reasoning_structure) == ["identify_inputs", "sequence_work"]
    assert "identify_inputs" in artifact.raw and "Gather data" in artifact.raw
    assert artifact.ideation is None and artifact.verdict is None

    # Discovery persisted the structure for the next run.
    assert cache.get(cache.key_for(TASK)) == STRUCTURE


async def test_cache_hit_is_single_solve_call(tmp_path: Path):
    planner, cache = make_planner(tmp_path)
    cached = {"reuse_me": "cached instruction"}
    cache.put(cache.key_for(TASK), cached)
    model = fake_model(_PlanSchema(steps=["Do it"]))

    artifact = await planner.run(ws_ctx(model, tmp_path))

    fake = cast(FakeStructuredModel, model)
    assert fake.call_count == 1  # discovery nodes skipped entirely
    assert fake.schemas == [_PlanSchema]
    assert "reuse_me" in fake.prompts[0]
    assert artifact.reasoning_structure == cached


async def test_old_shape_cache_entry_still_solves(tmp_path: Path):
    """Pre-structured-output cache entries (text fallback shape) stay valid."""
    planner, cache = make_planner(tmp_path)
    legacy = {"structure_text": "First think about inputs, then order the work."}
    cache.put(cache.key_for(TASK), legacy)
    model = fake_model(_PlanSchema(steps=["Do it"]))

    artifact = await planner.run(ws_ctx(model, tmp_path))

    assert artifact.plan is not None
    assert [s.description for s in artifact.plan.steps] == ["Do it"]
    assert artifact.reasoning_structure == legacy
    assert "First think about inputs" in cast(FakeStructuredModel, model).prompts[0]


async def test_discovery_prompts_are_task_only(tmp_path: Path):
    """Structures must transfer across toolsets: no tools in discovery prompts."""
    planner, _ = make_planner(tmp_path)
    model = fake_model(*discovery_outputs())

    await planner.run(ws_ctx(model, tmp_path))

    prompts = cast(FakeStructuredModel, model).prompts
    assert all("web_search" not in p for p in prompts[:3])
    assert "web_search" in prompts[3]


async def test_empty_plan_steps_raises(tmp_path: Path):
    planner, _ = make_planner(tmp_path)
    outputs = discovery_outputs()
    outputs[3] = _PlanSchema(steps=[])
    model = fake_model(*outputs)

    with pytest.raises(ValueError, match="empty plan"):
        await planner.run(ws_ctx(model, tmp_path))


async def test_empty_implement_steps_raises(tmp_path: Path):
    planner, cache = make_planner(tmp_path)
    outputs = discovery_outputs()
    outputs[2] = _ImplementSchema(steps=[])
    model = fake_model(*outputs)

    with pytest.raises(ValueError, match="no reasoning steps"):
        await planner.run(ws_ctx(model, tmp_path))
    assert cache.get(cache.key_for(TASK)) is None  # nothing cached on failure


# ---------------------------------------------------------------------------
# SELECT index validation (ADR-109 §2)
# ---------------------------------------------------------------------------


async def test_select_drops_out_of_range_indices(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    planner, _ = make_planner(tmp_path)
    outputs = discovery_outputs()
    outputs[0] = _SelectSchema(selected_indices=[2, 0, 99])
    model = fake_model(*outputs)

    with caplog.at_level(logging.WARNING):
        await planner.run(ws_ctx(model, tmp_path))

    assert "out-of-range" in caplog.text
    adapt_prompt = cast(FakeStructuredModel, model).prompts[1]
    assert SEED_REASONING_MODULES[1] in adapt_prompt  # index 2 survives
    assert SEED_REASONING_MODULES[0] not in adapt_prompt  # 0 and 99 dropped


async def test_select_empty_selection_falls_back_to_default_set(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    planner, _ = make_planner(tmp_path)
    outputs = discovery_outputs()
    outputs[0] = _SelectSchema(selected_indices=[])
    model = fake_model(*outputs)

    with caplog.at_level(logging.WARNING):
        await planner.run(ws_ctx(model, tmp_path))

    assert "no valid module indices" in caplog.text
    adapt_prompt = cast(FakeStructuredModel, model).prompts[1]
    for index in _DEFAULT_SELECTED_INDICES:
        assert SEED_REASONING_MODULES[index - 1] in adapt_prompt


async def test_select_all_invalid_indices_falls_back_to_default_set(tmp_path: Path):
    planner, _ = make_planner(tmp_path)
    outputs = discovery_outputs()
    outputs[0] = _SelectSchema(selected_indices=[0, 40, -3])
    model = fake_model(*outputs)

    await planner.run(ws_ctx(model, tmp_path))

    adapt_prompt = cast(FakeStructuredModel, model).prompts[1]
    for index in _DEFAULT_SELECTED_INDICES:
        assert SEED_REASONING_MODULES[index - 1] in adapt_prompt


# ---------------------------------------------------------------------------
# Status events (Tier 1 progress + Tier 2 structure snapshot, ADR-106).
# Events ride the custom stream (ADR-110), so the module runs inside a
# minimal streamed parent graph here.
# ---------------------------------------------------------------------------


def _kinds_and_phases(events: list[StatusEvent]) -> list[tuple[str, str]]:
    return [(str(e.kind), str(e.payload.get("phase", ""))) for e in events]


async def test_cache_miss_emits_discovery_phases_and_structure_insight(tmp_path: Path):
    planner, _ = make_planner(tmp_path)
    ctx = ws_ctx(fake_model(*discovery_outputs()), tmp_path)

    _, events = await run_streamed(lambda: planner.run(ctx))

    assert _kinds_and_phases(events) == [
        ("module.phase", "discovering"),
        ("module.phase", "select"),
        ("module.phase", "adapt"),
        ("module.phase", "implement"),
        ("module.insight", ""),
        ("module.phase", "solving"),
    ]
    insight = next(e for e in events if str(e.kind) == "module.insight")
    assert insight.payload["label"] == "Reasoning structure"
    assert insight.payload["headline"] == "identify_inputs · sequence_work"
    assert insight.node == "planning"
    assert insight.payload["module"] == "self_discover"


async def test_cache_hit_emits_reuse_phase_and_skips_discovery_phases(tmp_path: Path):
    planner, cache = make_planner(tmp_path)
    cache.put(cache.key_for(TASK), {"reuse_me": "cached instruction"})
    ctx = ws_ctx(fake_model(_PlanSchema(steps=["Do it"])), tmp_path)

    _, events = await run_streamed(lambda: planner.run(ctx))

    assert _kinds_and_phases(events) == [
        ("module.phase", "structure_reused"),
        ("module.insight", ""),
        ("module.phase", "solving"),
    ]


async def test_legacy_text_structure_emits_no_insight(tmp_path: Path):
    planner, cache = make_planner(tmp_path)
    cache.put(cache.key_for(TASK), {"structure_text": "just think hard about it"})
    ctx = ws_ctx(fake_model(_PlanSchema(steps=["Do it"])), tmp_path)

    _, events = await run_streamed(lambda: planner.run(ctx))

    insights = [e for e in events if str(e.kind) == "module.insight"]
    assert insights == []  # structure_text-only fallback has no useful labels


# ---------------------------------------------------------------------------
# Concurrency: module instances are shared across sessions (the harness
# builds them once; main_concurrency defaults to 4). Run-varying data must
# come from graph state — never from self._ctx, which a second run rebinds
# mid-flight (ReasoningModule invariant).
# ---------------------------------------------------------------------------


class _GatedSharedModel:
    """One model instance for two overlapping runs (workspace-constant, as in
    production). Dispatches on schema; the SELECT call blocks until released
    so the test can interleave a complete second run mid-discovery."""

    def __init__(self) -> None:
        self.solve_prompts: list[str] = []
        self.in_select = asyncio.Event()
        self.release_select = asyncio.Event()

    def with_structured_output(self, schema: type) -> "_BoundSchema":
        return _BoundSchema(self, schema)


class _BoundSchema:
    """Per-call schema binding — safe under concurrent with_structured_output."""

    def __init__(self, model: _GatedSharedModel, schema: type) -> None:
        self._model = model
        self._schema = schema

    async def ainvoke(self, messages: list[BaseMessage]) -> object:
        prompt = str(messages[0].content)
        if self._schema is _SelectSchema:
            self._model.in_select.set()
            await self._model.release_select.wait()
            return _SelectSchema(selected_indices=[1])
        if self._schema is _AdaptSchema:
            return _AdaptSchema(adapted_modules=["adapted for the task"])
        if self._schema is _ImplementSchema:
            return _ImplementSchema(
                steps=[_StructureStep(name="discovered_step", instruction="do the work")]
            )
        self._model.solve_prompts.append(prompt)
        return _PlanSchema(steps=["one step"])


async def test_concurrent_runs_on_one_instance_do_not_cross_contaminate(tmp_path: Path):
    """Run B rebinding self._ctx mid-run-A must not leak B's task, brief,
    digest, or tools into A's solve prompt (they travel in graph state)."""
    planner, cache = make_planner(tmp_path)
    model = _GatedSharedModel()
    task_a, task_b = "alpha: audit the logs", "beta: build the report"
    # B is a cache hit (single solve); A does full discovery and is held at
    # SELECT so B's entire run — including the self._ctx rebind — happens
    # mid-run-A. Deterministic: pure event gating, no sleeps.
    cache.put(cache.key_for(task_b), {"beta_cached_step": "beta instruction"})

    def ctx_for(task: str, tag: str) -> ReasoningContext:
        return make_ctx(
            cast(BaseChatModel, model),
            task=task,
            context_brief=f"{tag} brief",
            conversation_digest=f"{tag} digest",
            tools_summary=[ToolSummary(name=f"{tag}_tool", description=f"{tag} tool")],
            workspace=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=tmp_path),
        )

    run_a = asyncio.create_task(planner.run(ctx_for(task_a, "alpha")))
    await model.in_select.wait()  # A is mid-discovery with ctx_A bound

    artifact_b = await planner.run(ctx_for(task_b, "beta"))  # rebinds self._ctx

    model.release_select.set()  # A resumes AFTER the rebind
    artifact_a = await run_a

    solve_b, solve_a = model.solve_prompts  # B solved while A was held
    assert task_b in solve_b and "beta_cached_step" in solve_b
    assert "beta brief" in solve_b and "beta digest" in solve_b and "beta_tool" in solve_b
    assert "alpha" not in solve_b

    assert task_a in solve_a and "discovered_step" in solve_a
    assert "alpha brief" in solve_a and "alpha digest" in solve_a and "alpha_tool" in solve_a
    assert "beta" not in solve_a  # the cross-session leak the state seeding prevents

    assert artifact_a.plan is not None and artifact_a.plan.objective == task_a
    assert artifact_b.plan is not None and artifact_b.plan.objective == task_b


# ---------------------------------------------------------------------------
# Subgraph runs are unpersisted (ADR-109 §1 canary, mirrors
# test_execute_step_inner_run_is_unpersisted)
# ---------------------------------------------------------------------------


async def test_module_subgraph_run_is_unpersisted(tmp_path: Path):
    """run() disables checkpointing even under a checkpointed parent graph."""
    planner, _ = make_planner(tmp_path)
    ctx = ws_ctx(fake_model(*discovery_outputs()), tmp_path)
    saver = MemorySaver()

    class _State(TypedDict, total=False):
        done: bool

    async def node(state: _State) -> _State:
        await planner.run(ctx)
        return {"done": True}

    builder: StateGraph[_State, None, _State, _State] = StateGraph(_State)
    builder.add_node("mod", node)
    builder.add_edge(START, "mod")
    builder.add_edge("mod", END)
    graph = builder.compile(checkpointer=saver)

    await graph.ainvoke({}, config={"configurable": {"thread_id": "t1"}})

    # Only root-namespace (parent) checkpoints exist — the module subgraph
    # would otherwise inherit the parent checkpointer under a nested ns.
    namespaces = {
        c.config["configurable"].get("checkpoint_ns", "") for c in saver.list(None)
    }
    assert namespaces == {""}


# ---------------------------------------------------------------------------
# StructureCache
# ---------------------------------------------------------------------------


def test_cache_round_trip_across_instances(tmp_path: Path):
    cache = StructureCache(tmp_path)
    key = cache.key_for(TASK)
    cache.put(key, {"step": "value"})

    assert StructureCache(tmp_path).get(key) == {"step": "value"}
    assert cache.get("no-such-key") is None


def test_cache_key_normalizes_whitespace_and_case(tmp_path: Path):
    cache = StructureCache(tmp_path)
    assert cache.key_for("Ship  the\nQuarterly report") == cache.key_for("ship the quarterly report")
    assert cache.key_for("a different task") != cache.key_for(TASK)


def test_cache_corruption_is_a_miss_and_recovers(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    cache = StructureCache(tmp_path)
    cache_file = tmp_path / "data" / "reasoning_structures.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{not valid json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert cache.get("anything") is None
    assert "unreadable" in caplog.text

    cache.put("k", {"a": "b"})  # put overwrites the corrupt file
    assert cache.get("k") == {"a": "b"}


def test_cache_version_bump_invalidates_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache = StructureCache(tmp_path)
    old_key = cache.key_for(TASK)
    cache.put(old_key, {"a": "b"})

    monkeypatch.setattr(cache_mod, "MODULE_VERSION", cache_mod.MODULE_VERSION + 1)
    assert cache.key_for(TASK) != old_key
    assert cache.get(cache.key_for(TASK)) is None  # bumped version misses


def test_cache_evicts_oldest_past_cap(tmp_path: Path):
    cache = StructureCache(tmp_path)
    for i in range(cache_mod.MAX_ENTRIES + 1):
        cache.put(f"key-{i}", {"n": i})

    assert cache.get("key-0") is None  # oldest evicted
    assert cache.get("key-1") == {"n": 1}
    assert cache.get(f"key-{cache_mod.MAX_ENTRIES}") == {"n": cache_mod.MAX_ENTRIES}
    data = json.loads((tmp_path / "data" / "reasoning_structures.json").read_text())
    assert len(data) == cache_mod.MAX_ENTRIES


def test_cache_put_refreshes_existing_key_age(tmp_path: Path):
    cache = StructureCache(tmp_path)
    for i in range(cache_mod.MAX_ENTRIES):
        cache.put(f"key-{i}", {"n": i})
    cache.put("key-0", {"n": "refreshed"})  # re-insert at the end
    cache.put("one-more", {"n": "new"})  # evicts key-1, not key-0

    assert cache.get("key-0") == {"n": "refreshed"}
    assert cache.get("key-1") is None
