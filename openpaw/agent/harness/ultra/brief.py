"""Context brief support for the ultra harness (ADR-108).

Schema, prompts, token windowing, and rendering for the ``brief`` graph node:
one structured-output call on the plan/ideate paths that distills the full
session history into a task-relevant brief. The node itself lives in graph.py
(it needs the build-time closures); everything unit-testable lives here.
"""

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.messages.utils import count_tokens_approximately
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Reserved slice of the brief model's window: system prompt, task line, and
# the structured response (ADR-108 §2 — the budget is a physical ceiling on
# the transcript, not a design cutoff).
_BRIEF_HEADROOM = 4096
_FALLBACK_MAX_INPUT_TOKENS = 200_000

BRIEF_SYSTEM_PROMPT = """\
You distill a conversation session into a brief for an AI agent that is \
about to plan a task. From the transcript, extract only what the rest of the \
run needs to know: where the conversation stands and what led here \
(situation), requirements or boundaries the user has stated, however long \
ago (constraints), approaches already tried or discussed and their outcomes \
(prior_attempts), and user preferences relevant to how the task should be \
done (preferences). Leave a list empty when the session offers nothing for \
it. Do not invent details."""

BRIEF_TASK_TEMPLATE = """\
Task about to be worked on: {objective}

Session transcript (oldest first):
{transcript}"""


class ContextBrief(BaseModel):
    """What the rest of this run needs to know about the session so far (ADR-108 §3)."""

    situation: str = Field(
        description="2-4 sentences: where the conversation stands and what led here"
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Requirements or boundaries the user has stated, however long ago",
    )
    prior_attempts: list[str] = Field(
        default_factory=list,
        description="Approaches already tried or discussed, and their outcomes",
    )
    preferences: list[str] = Field(
        default_factory=list,
        description="User preferences relevant to how the task should be done",
    )


def resolve_brief_budget(model: BaseChatModel, configured_cap: int | None) -> int:
    """Token budget for the brief transcript (ADR-108 §2).

    The model's actual context window minus headroom, optionally capped by
    ``harness.brief.max_input_tokens`` for cost control. Window discovery
    uses ``model.profile["max_input_tokens"]`` with the 200K fallback — the
    same pattern auto-compact uses.
    """
    max_input = _FALLBACK_MAX_INPUT_TOKENS
    profile = getattr(model, "profile", None)
    if profile:
        max_input = profile.get("max_input_tokens") or _FALLBACK_MAX_INPUT_TOKENS
    budget = max_input - _BRIEF_HEADROOM
    if configured_cap is not None:
        budget = min(budget, configured_cap)
    return max(budget, 1)


def window_dialogue(messages: list[Any], budget: int) -> list[Any]:
    """Human/AI messages within the token budget, selected newest-first.

    Tool traces are excluded (ADR-108 §2 — they crowd out dialogue and are
    step-execution noise). Messages are accumulated newest-to-oldest until
    the budget is exhausted, then returned in original (oldest-first) order.
    The newest message is always kept so the transcript is never empty.
    """
    dialogue = [m for m in messages if isinstance(m, HumanMessage | AIMessage)]
    kept: list[Any] = []
    total = 0
    for msg in reversed(dialogue):
        tokens = count_tokens_approximately([msg])
        if kept and total + tokens > budget:
            break
        kept.append(msg)
        total += tokens
    kept.reverse()
    return kept


def render_brief(brief: ContextBrief) -> str:
    """Render the structured brief to prompt text; empty sections render as nothing."""
    sections: list[str] = []
    if brief.situation.strip():
        sections.append(brief.situation.strip())
    for title, items in (
        ("Constraints", brief.constraints),
        ("Prior attempts", brief.prior_attempts),
        ("Preferences", brief.preferences),
    ):
        entries = [item.strip() for item in items if item.strip()]
        if entries:
            sections.append(f"{title}:\n" + "\n".join(f"- {entry}" for entry in entries))
    return "\n\n".join(sections)
