"""Tests for the context brief (ADR-108): config, token windowing, digest
hardening, route-conditional topology, fail-open posture, and per-consumer
prompt plumbing.

Graph-level tests reuse the fakes from test_planner_graph; module-level
consumer tests call run() directly (module events are dropped outside a
streaming graph context by design — emit_status is tolerant).
"""

from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from pydantic import ValidationError

from openpaw.agent.harness.modules.base import (
    ReasoningContext,
    ToolSummary,
    WorkspaceInfo,
    render_context_block,
)
from openpaw.agent.harness.modules.direct import DirectPlanner, _PlanSchema
from openpaw.agent.harness.modules.ideonomy.module import (
    IdeonomyModule,
    _LensSchema,
    _SynthesisSchema,
)
from openpaw.agent.harness.modules.self_discover.cache import StructureCache
from openpaw.agent.harness.modules.self_discover.planner import (
    SelfDiscoverPlanner,
    _AdaptSchema,
    _ImplementSchema,
    _SelectSchema,
    _StructureStep,
)
from openpaw.agent.harness.planner.brief import (
    _BRIEF_HEADROOM,
    ContextBrief,
    render_brief,
    resolve_brief_budget,
    window_dialogue,
)
from openpaw.agent.harness.planner.equipment import EquipDecision
from openpaw.agent.harness.planner.graph import (
    PlannerNodeModels,
    TriageDecision,
    _conversation_digest,
    build_planner_graph,
)
from openpaw.agent.harness.planner.state import PlannerRunContext
from openpaw.core.config.models import BriefNodeConfig, HarnessConfig
from tests.test_planner_graph import (
    CaptureEmitter,
    FakeModel,
    advance,
    build,
    default_candidates,
    fake,
    make_fake_react,
    plan_decision,
)
from tests.test_tool_equipping import make_equipment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BRIEF = ContextBrief(
    situation="We are mid-refactor of the auth module.",
    constraints=["No emails today"],
    prior_attempts=["Tried JWT rotation; it broke sessions"],
    preferences=["Prefers short answers"],
)


def make_ctx(model: BaseChatModel, context_brief: str = "") -> ReasoningContext:
    return ReasoningContext(
        task="Ship the quarterly report",
        conversation_digest="user: asked for the report",
        tools_summary=[ToolSummary(name="web_search", description="Search the web")],
        model=model,
        workspace=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=Path("/tmp/ws")),
        context_brief=context_brief,
    )


class ProfiledFake(FakeModel):
    """FakeModel with a LangChain-style model profile."""

    def __init__(self, *outputs: object, max_input_tokens: int | None = None) -> None:
        super().__init__(*outputs)
        self.profile = {"max_input_tokens": max_input_tokens} if max_input_tokens else None


# ---------------------------------------------------------------------------
# Config (BriefNodeConfig, HarnessConfig.brief)
# ---------------------------------------------------------------------------


def test_brief_config_defaults() -> None:
    config = BriefNodeConfig()
    assert config.enabled is True
    assert config.model is None
    assert config.max_input_tokens is None


def test_brief_config_rejects_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        BriefNodeConfig.model_validate({"enabled": True, "budget": 5000})


def test_brief_config_max_input_tokens_floor() -> None:
    assert BriefNodeConfig(max_input_tokens=1024).max_input_tokens == 1024
    with pytest.raises(ValidationError):
        BriefNodeConfig(max_input_tokens=1023)


def test_zero_config_harness_validates_with_brief_enabled() -> None:
    """H6.2/ADR-108 §7: bare harness: {type: planner} validates, brief on."""
    config = HarnessConfig.model_validate({"type": "planner"})
    assert config.brief.enabled is True
    assert config.brief.max_input_tokens is None


# ---------------------------------------------------------------------------
# Token budget (resolve_brief_budget)
# ---------------------------------------------------------------------------


def test_budget_is_model_window_minus_headroom() -> None:
    model = cast(BaseChatModel, ProfiledFake(max_input_tokens=50_000))
    assert resolve_brief_budget(model, None) == 50_000 - _BRIEF_HEADROOM


def test_budget_falls_back_to_200k_without_profile() -> None:
    assert resolve_brief_budget(fake(), None) == 200_000 - _BRIEF_HEADROOM


def test_budget_configured_cap_wins_when_lower() -> None:
    model = cast(BaseChatModel, ProfiledFake(max_input_tokens=50_000))
    assert resolve_brief_budget(model, 8_000) == 8_000


def test_budget_ignores_configured_cap_when_higher() -> None:
    model = cast(BaseChatModel, ProfiledFake(max_input_tokens=50_000))
    assert resolve_brief_budget(model, 500_000) == 50_000 - _BRIEF_HEADROOM


def test_budget_never_drops_below_one() -> None:
    model = cast(BaseChatModel, ProfiledFake(max_input_tokens=1_000))  # < headroom
    assert resolve_brief_budget(model, None) == 1


# ---------------------------------------------------------------------------
# Token windowing (window_dialogue)
# ---------------------------------------------------------------------------


def test_window_excludes_tool_traces_and_system_messages() -> None:
    messages = [
        SystemMessage("system prompt"),
        HumanMessage("question"),
        AIMessage("", tool_calls=[{"name": "shell", "args": {}, "id": "tc1"}]),
        ToolMessage(content="tool output", tool_call_id="tc1"),
        AIMessage("answer"),
    ]
    window = window_dialogue(messages, budget=10_000)
    assert [type(m).__name__ for m in window] == ["HumanMessage", "AIMessage", "AIMessage"]
    assert not any(isinstance(m, ToolMessage | SystemMessage) for m in window)


def test_window_keeps_newest_within_budget_in_original_order() -> None:
    messages = [HumanMessage(f"message number {i} " + "x" * 200) for i in range(6)]
    # Budget for exactly the newest two messages.
    budget = count_tokens_approximately(messages[-2:])
    window = window_dialogue(messages, budget)
    assert window == messages[-2:]  # newest-first selection, original order


def test_window_always_keeps_the_newest_message() -> None:
    messages = [HumanMessage("old " * 100), HumanMessage("newest " + "y" * 1000)]
    window = window_dialogue(messages, budget=1)
    assert window == [messages[-1]]


def test_window_empty_messages() -> None:
    assert window_dialogue([], budget=1000) == []


# ---------------------------------------------------------------------------
# Brief rendering (render_brief / render_context_block)
# ---------------------------------------------------------------------------


def test_render_brief_full_sections() -> None:
    text = render_brief(BRIEF)
    assert text.startswith("We are mid-refactor of the auth module.")
    assert "Constraints:\n- No emails today" in text
    assert "Prior attempts:\n- Tried JWT rotation; it broke sessions" in text
    assert "Preferences:\n- Prefers short answers" in text


def test_render_brief_empty_sections_render_as_nothing() -> None:
    brief = ContextBrief(situation="Fresh session.", constraints=["  "], prior_attempts=[])
    text = render_brief(brief)
    assert text == "Fresh session."
    assert render_brief(ContextBrief(situation="  ")) == ""


def test_render_context_block_empty_and_nonempty() -> None:
    assert render_context_block("") == ""
    assert render_context_block("   ") == ""
    block = render_context_block("Some brief.")
    assert block == "Session context:\nSome brief.\n\n"


# ---------------------------------------------------------------------------
# Digest hardening (ADR-108 §6)
# ---------------------------------------------------------------------------


def test_digest_role_labels_and_order() -> None:
    digest = _conversation_digest([HumanMessage("hello"), AIMessage("hi there")])
    assert digest == "user: hello\nassistant: hi there"


def test_digest_excludes_tool_traces() -> None:
    digest = _conversation_digest(
        [
            HumanMessage("run it"),
            AIMessage("", tool_calls=[{"name": "shell", "args": {}, "id": "tc1"}]),
            ToolMessage(content="raw tool output", tool_call_id="tc1"),
            SystemMessage("system"),
            AIMessage("done"),
        ]
    )
    assert digest == "user: run it\nassistant: done"


def test_digest_truncates_each_message_individually() -> None:
    long_text = "a" * 600
    digest = _conversation_digest([HumanMessage(long_text), AIMessage("short")])
    assert "assistant: short" in digest  # the earlier long message can't evict it
    assert "a" * 500 + "…" in digest
    assert "a" * 501 not in digest


def test_digest_keeps_at_most_the_newest_twelve_messages() -> None:
    messages: list[Any] = [
        HumanMessage(f"m{i}") if i % 2 == 0 else AIMessage(f"m{i}") for i in range(16)
    ]
    lines = _conversation_digest(messages).splitlines()
    assert len(lines) == 12
    assert lines[-1] == "assistant: m15"  # newest survives
    assert lines[0] == "user: m4"  # oldest four dropped


def test_digest_respects_token_budget_newest_first() -> None:
    # Each message ~150 tokens; 12 would blow the ~1024-token budget.
    messages = [HumanMessage(f"m{i} " + "word " * 150) for i in range(12)]
    digest = _conversation_digest(messages)
    assert "m11 " in digest  # newest kept
    assert "m0 " not in digest  # oldest evicted by the token cap
    assert count_tokens_approximately([HumanMessage(digest)]) <= 1200  # ~budget + slack


def test_digest_empty_messages() -> None:
    assert _conversation_digest([]) == ""


# ---------------------------------------------------------------------------
# Route-conditional topology + state flow
# ---------------------------------------------------------------------------


async def test_plan_route_briefs_and_all_consumers_see_it() -> None:
    calls: list[str] = []
    emitter = CaptureEmitter()
    brief_model = FakeModel(BRIEF)
    graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        synthesize=[AIMessage(content="all done")],
        brief=cast(BaseChatModel, brief_model),
        react=make_fake_react(["did it"], calls),
        emitter=emitter,
    )
    result = await graph.ainvoke({"messages": [HumanMessage("refactor auth")]})

    # Brief node ran once, on the full dialogue, before planning.
    assert brief_model.call_count == 1
    brief_prompt = brief_model.prompts[0]
    assert "Session transcript (oldest first):" in brief_prompt
    assert "user: refactor auth" in brief_prompt

    # Rendered brief stored in state.
    rendered = result["context_brief"]
    assert rendered is not None
    assert "We are mid-refactor of the auth module." in rendered
    assert "Constraints:\n- No emails today" in rendered

    # Step execution prompt carries the session block.
    assert len(calls) == 1
    assert "Session context:" in calls[0]
    assert "No emails today" in calls[0]

    # node.entered for brief + module.insight with the situation line.
    brief_events = [e for e in emitter.events if e.node == "brief"]
    kinds = [str(e.kind) for e in brief_events]
    assert "node.entered" in kinds
    insights = [e for e in brief_events if str(e.kind) == "module.insight"]
    assert insights and insights[0].payload["headline"] == BRIEF.situation

    # Final answer unaffected.
    assert result["messages"][-1].content == "all done"


async def test_planning_and_synthesize_prompts_carry_the_brief() -> None:
    calls: list[str] = []
    planning_model = FakeModel(_PlanSchema(steps=["one"]))
    synthesize_model = FakeModel(AIMessage(content="done"))
    graph = build_planner_graph(
        react_graph=make_fake_react(["did it"], calls),
        node_models=PlannerNodeModels(
            triage=fake(plan_decision()),
            planning=cast(BaseChatModel, planning_model),
            creative=fake(),
            reflection=fake(advance()),
            selector=fake(),
            synthesize=cast(BaseChatModel, synthesize_model),
            brief=fake(BRIEF),
        ),
        harness_config=HarnessConfig(type="planner"),
        candidates=default_candidates(),
        emitter=CaptureEmitter(),
        workspace_info=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=Path("/tmp/ws")),
        tools_summary=[],
        run_context=PlannerRunContext(),
        checkpointer=None,
        inner_recursion_limit=20,
    )
    await graph.ainvoke({"messages": [HumanMessage("refactor auth")]})

    assert "Session context:" in planning_model.prompts[0]  # DirectPlanner (via ctx)
    assert "No emails today" in planning_model.prompts[0]
    assert "Session context:" in synthesize_model.prompts[0]
    assert "No emails today" in synthesize_model.prompts[0]


async def test_react_route_never_enters_brief() -> None:
    emitter = CaptureEmitter()
    brief_model = FakeModel()  # raises if invoked
    graph = build(
        triage=[TriageDecision(route="react", objective="greet", reason="simple")],
        brief=cast(BaseChatModel, brief_model),
        react=make_fake_react(["hi"], []),
        emitter=emitter,
    )
    assert "brief" in graph.nodes  # present, but the react route skips it
    result = await graph.ainvoke({"messages": [HumanMessage("hello")]})

    assert brief_model.call_count == 0
    assert result.get("context_brief") is None  # react routes null stale briefs
    assert not [e for e in emitter.events if e.node == "brief"]


async def test_ideate_route_briefs_before_ideation() -> None:
    emitter = CaptureEmitter()
    brief_model = FakeModel(BRIEF)
    graph = build(
        triage=[TriageDecision(route="ideate", objective="name it", reason="creative")],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        brief=cast(BaseChatModel, brief_model),
        react=make_fake_react(["did it"], []),
        emitter=emitter,
    )
    result = await graph.ainvoke({"messages": [HumanMessage("name the product")]})

    assert brief_model.call_count == 1
    assert result["context_brief"] is not None
    entered = [e.node for e in emitter.events if str(e.kind) == "node.entered"]
    assert entered.index("brief") < entered.index("ideate")  # brief precedes ideate


async def test_brief_disabled_by_config_omits_the_node() -> None:
    config = HarnessConfig.model_validate({"type": "planner", "brief": {"enabled": False}})
    graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        brief=fake(BRIEF),  # model present, config gate must still win
        react=make_fake_react(["did it"], []),
        harness_config=config,
    )
    assert "brief" not in graph.nodes


async def test_brief_absent_without_model_keeps_todays_topology() -> None:
    baseline = build(react=make_fake_react(["r"], []))
    assert "brief" not in baseline.nodes
    assert set(baseline.nodes) == {
        "__start__",
        "triage",
        "react",
        "ideate",
        "plan",
        "execute_step",
        "reflect",
        "synthesize",
    }


async def test_brief_failure_fails_open_to_digest() -> None:
    calls: list[str] = []
    brief_model = FakeModel(RuntimeError("brief model down"))
    graph = build(
        triage=[plan_decision()],
        planning=[_PlanSchema(steps=["one"])],
        reflection=[advance()],
        brief=cast(BaseChatModel, brief_model),
        react=make_fake_react(["did it"], calls),
    )
    result = await graph.ainvoke({"messages": [HumanMessage("do it")]})

    assert result["context_brief"] is None
    assert len(calls) == 1  # the run proceeded
    assert "Session context:" not in calls[0]  # block renders as nothing
    assert result["messages"][-1].content == "final answer"


async def test_brief_with_equipping_routes_brief_then_equip() -> None:
    emitter = CaptureEmitter()
    equipment = make_equipment(EquipDecision(equip=["alpha"], reason="picked"))
    graph = build_planner_graph(
        react_graph=make_fake_react(["did it"], []),
        node_models=PlannerNodeModels(
            triage=fake(plan_decision()),
            planning=fake(_PlanSchema(steps=["one"])),
            creative=fake(),
            reflection=fake(advance()),
            selector=fake(),
            synthesize=fake(AIMessage(content="done")),
            brief=fake(BRIEF),
        ),
        harness_config=HarnessConfig(type="planner"),
        candidates=default_candidates(),
        emitter=emitter,
        workspace_info=WorkspaceInfo(name="testws", timezone="UTC", workspace_path=Path("/tmp/ws")),
        tools_summary=[],
        run_context=PlannerRunContext(),
        checkpointer=None,
        inner_recursion_limit=20,
        equipment=equipment,
    )
    await graph.ainvoke({"messages": [HumanMessage("do it")]})

    entered = [e.node for e in emitter.events if str(e.kind) == "node.entered"]
    assert entered.index("brief") < entered.index("equip")  # brief -> equip -> plan
    equip_prompt = cast(FakeModel, equipment.model).prompts[0]
    assert "Session context:" in equip_prompt  # ADR-108 §4: equip sees constraints
    assert "No emails today" in equip_prompt


# ---------------------------------------------------------------------------
# Per-consumer prompt plumbing (module level)
# ---------------------------------------------------------------------------


async def test_direct_planner_prompt_carries_brief_only_when_set() -> None:
    with_brief = FakeModel(_PlanSchema(steps=["a"]))
    await DirectPlanner().run(make_ctx(cast(BaseChatModel, with_brief), "User prefers brevity."))
    assert "Session context:\nUser prefers brevity." in with_brief.prompts[0]

    without = FakeModel(_PlanSchema(steps=["a"]))
    await DirectPlanner().run(make_ctx(cast(BaseChatModel, without)))
    assert "Session context:" not in without.prompts[0]


async def test_self_discover_brief_reaches_solve_but_not_discovery(tmp_path: Path) -> None:
    model = FakeModel(
        _SelectSchema(selected_indices=[1]),
        _AdaptSchema(adapted_modules=["adapted"]),
        _ImplementSchema(steps=[_StructureStep(name="step", instruction="do")]),
        _PlanSchema(steps=["solve step"]),
    )
    module = SelfDiscoverPlanner(StructureCache(tmp_path))
    await module.run(make_ctx(cast(BaseChatModel, model), "User prefers brevity."))

    select_prompt, adapt_prompt, implement_prompt, solve_prompt = model.prompts
    # Discovery stays task-only — cached structures must transfer (ADR-108 §4).
    for discovery_prompt in (select_prompt, adapt_prompt, implement_prompt):
        assert "Session context:" not in discovery_prompt
    assert "Session context:\nUser prefers brevity." in solve_prompt


async def test_ideonomy_brief_reaches_lens_and_synthesis_prompts() -> None:
    model = FakeModel(
        _LensSchema(headline="h1", exploration="e1"),
        _LensSchema(headline="h2", exploration="e2"),
        _SynthesisSchema(ideas=["i"], evaluations=["e"], recommended_directions=["d"]),
    )
    module = IdeonomyModule(lens_count=2)
    await module.run(make_ctx(cast(BaseChatModel, model), "User prefers brevity."))

    assert len(model.prompts) == 3
    for prompt in model.prompts:  # both lens prompts and the synthesis prompt
        assert "Session context:\nUser prefers brevity." in prompt


async def test_ideonomy_without_brief_keeps_prompts_clean() -> None:
    model = FakeModel(
        _LensSchema(headline="h1", exploration="e1"),
        _LensSchema(headline="h2", exploration="e2"),
        _SynthesisSchema(ideas=["i"], evaluations=["e"], recommended_directions=["d"]),
    )
    await IdeonomyModule(lens_count=2).run(make_ctx(cast(BaseChatModel, model)))
    assert all("Session context:" not in p for p in model.prompts)


# ---------------------------------------------------------------------------
# Reflection modules get the brief for free via ReasoningContext
# ---------------------------------------------------------------------------


def test_reasoning_context_brief_defaults_to_empty() -> None:
    ctx = make_ctx(fake())
    assert ctx.context_brief == ""
    assert make_ctx(fake(), "brief text").context_brief == "brief text"
