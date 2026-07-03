"""Tests for SelfDiscoverPlanner and StructureCache (ADR-102 §3)."""

import json
import logging
from pathlib import Path
from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

import openpaw.agent.harness.modules.self_discover.cache as cache_mod
from openpaw.agent.harness.modules.base import ModuleKind, ReasoningContext, WorkspaceInfo
from openpaw.agent.harness.modules.direct import _PlanSchema
from openpaw.agent.harness.modules.self_discover import SelfDiscoverPlanner, StructureCache
from openpaw.agent.harness.modules.self_discover.planner import _parse_structure
from openpaw.agent.harness.modules.self_discover.seed_modules import SEED_REASONING_MODULES
from tests.test_reasoning_modules import FakeStructuredModel, fake_model, make_ctx

TASK = "Ship the quarterly report"
STRUCTURE_JSON = '{"identify_inputs": "List required data", "sequence_work": "Order the steps"}'


def make_planner(tmp_path: Path) -> tuple[SelfDiscoverPlanner, StructureCache]:
    cache = StructureCache(tmp_path)
    return SelfDiscoverPlanner(cache), cache


def discovery_outputs() -> list[object]:
    """SELECT, ADAPT, IMPLEMENT responses followed by the structured plan."""
    return [
        AIMessage("Modules 9, 16, 39 are relevant."),
        AIMessage("Adapted: break the report into data-gathering and writing."),
        AIMessage(STRUCTURE_JSON),
        _PlanSchema(steps=["Gather data", "Write report"]),
    ]


def ws_ctx(model: BaseChatModel, tmp_path: Path) -> ReasoningContext:
    return make_ctx(
        model,
        workspace=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=tmp_path),
    )


# ---------------------------------------------------------------------------
# Planner: discovery + solve flow
# ---------------------------------------------------------------------------


async def test_cache_miss_runs_three_discovery_calls_plus_solve(tmp_path: Path):
    planner, cache = make_planner(tmp_path)
    model = fake_model(*discovery_outputs())
    ctx = ws_ctx(model, tmp_path)

    artifact = await planner.run(ctx)

    fake = cast(FakeStructuredModel, model)
    assert fake.call_count == 4  # SELECT, ADAPT, IMPLEMENT, solve
    assert fake.schemas == [_PlanSchema]  # only the solve call is structured

    # SELECT: verbatim meta-prompt over all 39 seed modules.
    assert "which of the following reasoning modules are relevant" in fake.prompts[0]
    assert all(module in fake.prompts[0] for module in SEED_REASONING_MODULES)
    assert TASK in fake.prompts[0]
    # ADAPT and IMPLEMENT chain the previous call's output.
    assert "Modules 9, 16, 39 are relevant." in fake.prompts[1]
    assert "break the report into data-gathering" in fake.prompts[2]
    # Solve follows the structure and gets the tools context.
    assert "Follow the step-by-step reasoning plan in JSON" in fake.prompts[3]
    assert "identify_inputs" in fake.prompts[3]
    assert "- web_search: Search the web" in fake.prompts[3]

    assert artifact.kind == ModuleKind.PLANNING
    assert artifact.plan is not None
    assert [s.id for s in artifact.plan.steps] == ["1", "2"]
    assert [s.description for s in artifact.plan.steps] == ["Gather data", "Write report"]
    assert artifact.reasoning_structure == json.loads(STRUCTURE_JSON)
    assert "identify_inputs" in artifact.raw and "Gather data" in artifact.raw
    assert artifact.ideation is None and artifact.verdict is None

    # Discovery persisted the structure for the next run.
    assert cache.get(cache.key_for(TASK)) == json.loads(STRUCTURE_JSON)


async def test_cache_hit_is_single_solve_call(tmp_path: Path):
    planner, cache = make_planner(tmp_path)
    cached = {"reuse_me": "cached instruction"}
    cache.put(cache.key_for(TASK), cached)
    model = fake_model(_PlanSchema(steps=["Do it"]))

    artifact = await planner.run(ws_ctx(model, tmp_path))

    fake = cast(FakeStructuredModel, model)
    assert fake.call_count == 1
    assert "reuse_me" in fake.prompts[0]
    assert artifact.reasoning_structure == cached


async def test_discovery_prompts_are_task_only(tmp_path: Path):
    """Structures must transfer across toolsets: no tools in discovery prompts."""
    planner, _ = make_planner(tmp_path)
    model = fake_model(*discovery_outputs())

    await planner.run(ws_ctx(model, tmp_path))

    prompts = cast(FakeStructuredModel, model).prompts
    assert all("web_search" not in p for p in prompts[:3])
    assert "web_search" in prompts[3]


async def test_non_json_implement_output_stored_as_text(tmp_path: Path):
    planner, _ = make_planner(tmp_path)
    prose = "First think about inputs, then order the work."
    outputs = discovery_outputs()
    outputs[2] = AIMessage(prose)
    model = fake_model(*outputs)

    artifact = await planner.run(ws_ctx(model, tmp_path))

    assert artifact.reasoning_structure == {"structure_text": prose}


async def test_empty_plan_steps_raises(tmp_path: Path):
    planner, _ = make_planner(tmp_path)
    outputs = discovery_outputs()
    outputs[3] = _PlanSchema(steps=[])
    model = fake_model(*outputs)

    with pytest.raises(ValueError, match="empty plan"):
        await planner.run(ws_ctx(model, tmp_path))


# ---------------------------------------------------------------------------
# Status events (Tier 1 progress + Tier 2 structure snapshot, ADR-106)
# ---------------------------------------------------------------------------


def _kinds_and_phases(ctx: ReasoningContext) -> list[tuple[str, str]]:
    from tests.test_reasoning_modules import CaptureEmitter

    events = cast(CaptureEmitter, ctx.emit).events
    return [(str(e.kind), str(e.payload.get("phase", ""))) for e in events]


async def test_cache_miss_emits_discovery_phases_and_structure_insight(tmp_path: Path):
    from tests.test_reasoning_modules import CaptureEmitter

    planner, _ = make_planner(tmp_path)
    ctx = ws_ctx(fake_model(*discovery_outputs()), tmp_path)

    await planner.run(ctx)

    assert _kinds_and_phases(ctx) == [
        ("module.phase", "discovering"),
        ("module.phase", "select"),
        ("module.phase", "adapt"),
        ("module.phase", "implement"),
        ("module.insight", ""),
        ("module.phase", "solving"),
    ]
    insight = next(
        e for e in cast(CaptureEmitter, ctx.emit).events if str(e.kind) == "module.insight"
    )
    assert insight.payload["label"] == "Reasoning structure"
    # structure keys from STRUCTURE_JSON, joined
    assert insight.payload["headline"] == "identify_inputs · sequence_work"
    assert insight.node == "planning"
    assert insight.payload["module"] == "self_discover"


async def test_cache_hit_emits_reuse_phase_and_insight(tmp_path: Path):
    planner, cache = make_planner(tmp_path)
    cache.put(cache.key_for(TASK), {"reuse_me": "cached instruction"})
    ctx = ws_ctx(fake_model(_PlanSchema(steps=["Do it"])), tmp_path)

    await planner.run(ctx)

    assert _kinds_and_phases(ctx) == [
        ("module.phase", "structure_reused"),
        ("module.insight", ""),
        ("module.phase", "solving"),
    ]


async def test_text_fallback_structure_emits_no_insight(tmp_path: Path):
    from tests.test_reasoning_modules import CaptureEmitter

    planner, _ = make_planner(tmp_path)
    outputs = discovery_outputs()
    outputs[2] = AIMessage("just think hard about it")  # non-JSON IMPLEMENT
    ctx = ws_ctx(fake_model(*outputs), tmp_path)

    await planner.run(ctx)

    insights = [
        e for e in cast(CaptureEmitter, ctx.emit).events if str(e.kind) == "module.insight"
    ]
    assert insights == []  # structure_text-only fallback has no useful labels


# ---------------------------------------------------------------------------
# Structure parsing
# ---------------------------------------------------------------------------


def test_parse_structure_plain_json():
    assert _parse_structure('{"a": "b"}') == {"a": "b"}


def test_parse_structure_fenced_json():
    assert _parse_structure('```json\n{"a": "b"}\n```') == {"a": "b"}


def test_parse_structure_non_dict_json_falls_back():
    assert _parse_structure('["a", "b"]') == {"structure_text": '["a", "b"]'}


def test_parse_structure_prose_falls_back():
    assert _parse_structure("just think hard") == {"structure_text": "just think hard"}


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
