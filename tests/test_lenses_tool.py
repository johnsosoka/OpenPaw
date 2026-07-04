"""Tests for the explore_lenses tool (DESIGN §4/§10.3): determinism,
formatting, lens-count handling, and the tool factory surface."""

from openpaw.agent.harness.lenses import (
    ExploreLensesInput,
    create_explore_lenses_tool,
    format_lens_scaffold,
)
from openpaw.agent.harness.modules.ideonomy.selector import select_lenses

TOPIC = "brainstorm a name for a developer productivity tool"


# ---------------------------------------------------------------------------
# Scaffold formatting
# ---------------------------------------------------------------------------


def test_scaffold_is_deterministic() -> None:
    assert format_lens_scaffold(TOPIC, 3) == format_lens_scaffold(TOPIC, 3)


def test_scaffold_contains_each_lens_theme_core_and_guiding_questions() -> None:
    lenses = select_lenses(TOPIC, 3)
    scaffold = format_lens_scaffold(TOPIC, 3)

    for index, lens in enumerate(lenses, start=1):
        assert f"{index}. {lens.theme} — {lens.core_question}" in scaffold
        for question in lens.guiding_questions:
            assert question in scaffold


def test_scaffold_ends_with_the_think_it_through_nudge() -> None:
    scaffold = format_lens_scaffold(TOPIC, 2)
    assert scaffold.endswith(
        "Now think each lens through against the task and note the strongest "
        "ideas it surfaces before proceeding."
    )


def test_scaffold_respects_lens_count() -> None:
    one = format_lens_scaffold(TOPIC, 1)
    five = format_lens_scaffold(TOPIC, 5)
    assert "2. " not in one
    assert "5. " in five


def test_scaffold_topic_is_echoed() -> None:
    assert f"Ideonomic lenses selected for: {TOPIC}" in format_lens_scaffold(TOPIC, 3)


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def test_tool_name_schema_and_sync_invocation() -> None:
    tool = create_explore_lenses_tool(lens_count=3)

    assert tool.name == "explore_lenses"
    assert tool.args_schema is ExploreLensesInput
    assert tool.invoke({"topic": TOPIC}) == format_lens_scaffold(TOPIC, 3)


async def test_tool_async_invocation_matches_sync() -> None:
    tool = create_explore_lenses_tool(lens_count=2)
    assert await tool.ainvoke({"topic": TOPIC}) == tool.invoke({"topic": TOPIC})


def test_tool_binds_the_configured_lens_count() -> None:
    assert create_explore_lenses_tool(1).invoke({"topic": TOPIC}) == format_lens_scaffold(
        TOPIC, 1
    )
