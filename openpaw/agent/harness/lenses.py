"""``explore_lenses`` — zero-LLM ideonomy scaffolding for the balanced harness.

DESIGN §4 / §10.3: ideonomy returned to its roots. The tool wraps the
existing deterministic lens selector (keyword scoring over the 28 curated
divisions — the same one the ultra harness's IdeonomyModule uses) and hands
the model question lenses as an ordinary tool result. The agent thinks them
through in-context in the turn it was already taking: 4 LLM calls -> 0.

Balanced-only: :class:`~openpaw.workspace.agent_factory.AgentFactory`
registers the tool when ``harness.ideation.lens_tool`` is enabled on a
balanced workspace. The full parallel-subgraph IdeonomyModule remains
exclusive to the ultra harness.
"""

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.agent.harness.modules.ideonomy.selector import select_lenses

EXPLORE_LENSES_DESCRIPTION = """\
Explore a task or question through ideonomic reasoning lenses (Gunkel's
"science of ideas"). Returns the most relevant lenses for the topic — each
with a theme, a core question, and guiding questions. Deterministic and
instant: it costs no extra model calls.

Use this for open-ended or creative asks BEFORE planning: think each lens
through against the task and note the strongest ideas it surfaces."""


class ExploreLensesInput(BaseModel):
    """Input schema for the ``explore_lenses`` tool."""

    topic: str = Field(description="The task, question, or problem to explore")


def format_lens_scaffold(topic: str, count: int) -> str:
    """Render the selected lenses as thinking scaffolding (pure, deterministic).

    Args:
        topic: The task text the lenses are selected against.
        count: How many lenses to select.

    Returns:
        Per lens: theme + core question + guiding questions, ending with a
        nudge to think each lens through before proceeding.
    """
    lenses = select_lenses(topic, count)
    sections = [f"Ideonomic lenses selected for: {topic}"]
    for index, lens in enumerate(lenses, start=1):
        guiding = "\n".join(f"  - {question}" for question in lens.guiding_questions)
        sections.append(f"{index}. {lens.theme} — {lens.core_question}\n{guiding}")
    sections.append(
        "Now think each lens through against the task and note the strongest "
        "ideas it surfaces before proceeding."
    )
    return "\n\n".join(sections)


def create_explore_lenses_tool(lens_count: int) -> StructuredTool:
    """Build the ``explore_lenses`` tool with the configured lens count.

    Args:
        lens_count: ``harness.ideation.lens_count`` — lenses per call.

    Returns:
        A StructuredTool wrapping :func:`format_lens_scaffold`.
    """

    def explore(topic: str) -> str:
        return format_lens_scaffold(topic, lens_count)

    async def aexplore(topic: str) -> str:
        return explore(topic)

    return StructuredTool.from_function(
        name="explore_lenses",
        description=EXPLORE_LENSES_DESCRIPTION,
        func=explore,
        coroutine=aexplore,
        args_schema=ExploreLensesInput,
        infer_schema=False,
    )
