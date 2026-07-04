"""Checkpoint reflection for the balanced harness (DESIGN §3, decision §10.2).

Organic reflection (the default) costs nothing: the model sees its own tool
failures and checklist in the shared context and self-corrects next turn.
``harness.reflection.mode: checkpoint`` escalates: :class:`PlanEventBridge`
observes completed/failed todo flips and every N completions (or immediately
on a failed flip — the high-value trigger) this reflector fires ONE
structured verdict call reusing :class:`LightReflection`'s schema and prompt
shape against the current todo list, the flipped step, and recent context.

Fail-open everywhere: a missing model, a slow call (internal 30s timeout —
the write_todos tool call this rides inside is itself under the workspace
ToolTimeoutMiddleware budget), or a malformed verdict logs and skips; a
checkpoint never blocks the run.
"""

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

# Package-internal reuse of LightReflection's verdict schema (DESIGN §3:
# "reusing LightReflection's schema and prompt shape").
from openpaw.agent.harness.modules.reflection import _VerdictSchema

logger = logging.getLogger(__name__)

# Conservative internal budget so a slow verdict model cannot trip the outer
# per-tool timeout on the write_todos call it rides inside (default 120s).
VERDICT_TIMEOUT_SECONDS = 30.0

_MAX_CONTEXT_MESSAGES = 4
_MAX_MESSAGE_CHARS = 400

_STATUS_MARKS: dict[str, str] = {
    "pending": " ",
    "in_progress": "~",
    "completed": "x",
    "failed": "✗",
}


@dataclass(frozen=True)
class CheckpointOutcome:
    """One checkpoint verdict, renderer- and nudge-ready.

    Attributes:
        verdict: The model's ReflectAction (advance / revise_plan /
            insert_step / abort_to_user).
        step_succeeded: Whether the flipped step achieved its intent.
        notes: The model's brief evaluation notes.
    """

    verdict: str
    step_succeeded: bool
    notes: str

    @property
    def ok(self) -> bool:
        """True when no course correction is called for."""
        return self.verdict == "advance" and self.step_succeeded


def _message_text(message: Any) -> str:
    """Best-effort plain text of a LangChain message (fail-open to '')."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(block.get("text", "")) for block in content if isinstance(block, dict)
        )
    return str(content)


def _recent_context(state: Any) -> str:
    """A short tail of the conversation for the verdict prompt."""
    messages = state.get("messages") if isinstance(state, dict) else None
    if not isinstance(messages, list) or not messages:
        return "(none)"
    lines: list[str] = []
    for message in messages[-_MAX_CONTEXT_MESSAGES:]:
        text = _message_text(message).strip()
        if not text:
            continue
        if len(text) > _MAX_MESSAGE_CHARS:
            text = text[: _MAX_MESSAGE_CHARS - 1] + "…"
        lines.append(f"{type(message).__name__}: {text}")
    return "\n".join(lines) or "(none)"


def _render_checklist(todos: Sequence[Mapping[str, Any]]) -> str:
    """Render the todo list as a plain checklist for the verdict prompt."""
    lines: list[str] = []
    for todo in todos:
        mark = _STATUS_MARKS.get(str(todo.get("status", "pending")), " ")
        line = f"[{mark}] {todo.get('content', '')}"
        note = str(todo.get("note", "")).strip()
        if note:
            line += f" — {note}"
        lines.append(line)
    return "\n".join(lines)


def _checkpoint_prompt(
    todos: Sequence[Mapping[str, Any]], flipped: Mapping[str, Any], context: str
) -> str:
    """The verdict prompt — LightReflection's shape over todo-list inputs."""
    outcome = "failed" if flipped.get("failed") else "completed"
    note = str(flipped.get("note", "")).strip()
    note_line = f"\nStep note: {note}" if note else ""
    return (
        f"Current todo list:\n{_render_checklist(todos)}\n\n"
        f"Step just {outcome}: {flipped.get('description', '')}{note_line}\n\n"
        f"Recent context:\n{context}\n\n"
        "Did the step achieve its intent, and do the remaining todos still "
        "fit? Choose an action: advance if work should proceed as planned, "
        "revise_plan if the remaining steps no longer fit, insert_step to "
        "add one corrective step, or abort_to_user if the objective cannot "
        "proceed without the user."
    )


class CheckpointReflector:
    """Counts completed/failed todo flips and fires periodic verdict calls.

    One instance per balanced harness, owned by the PlanEventBridge. The
    verdict model resolves lazily: an explicit factory when
    ``harness.reflection.model`` is set (built by AgentFactory via
    NodeModelResolver, cached after first use), otherwise the workspace
    model instance already on the runner (provider wired by
    ``BalancedHarness.__init__``, read fresh each call so agent rebuilds
    are picked up).
    """

    def __init__(
        self,
        every: int,
        model_factory: Callable[[], BaseChatModel] | None = None,
    ) -> None:
        """Initialize the reflector.

        Args:
            every: Fire a verdict every N completed todos
                (``harness.reflection.every``).
            model_factory: Zero-arg factory for the configured verdict model
                pointer; None falls back to the runner's workspace model.
        """
        self._every = every
        self._model_factory = model_factory
        self._model: BaseChatModel | None = None
        self._default_model_provider: Callable[[], BaseChatModel | None] | None = None
        self._completed_since_verdict = 0

    def set_default_model_provider(
        self, provider: Callable[[], BaseChatModel | None]
    ) -> None:
        """Wire the fallback model source (the runner's live model instance)."""
        self._default_model_provider = provider

    def record_flips(
        self, flips: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Any] | None:
        """Update trigger counters from one write's completed/failed flips.

        Args:
            flips: plan.step_completed payloads emitted for this write
                (a ``failed: True`` key marks a failed flip).

        Returns:
            The flipped-step payload to reflect against when a checkpoint is
            due (a failed flip fires immediately; otherwise every N
            completions), or None.
        """
        if not flips:
            return None
        failed = next((payload for payload in flips if payload.get("failed")), None)
        if failed is not None:
            self._completed_since_verdict = 0
            return failed
        self._completed_since_verdict += len(flips)
        if self._completed_since_verdict >= self._every:
            self._completed_since_verdict = 0
            return flips[-1]
        return None

    async def observe(
        self,
        flips: Sequence[Mapping[str, Any]],
        todos: Sequence[Mapping[str, Any]],
        state: Any,
    ) -> CheckpointOutcome | None:
        """Record this write's flips and reflect when a checkpoint is due.

        Fail-open: any failure in model resolution or the verdict call is
        logged and returns None — a checkpoint never blocks the run.
        """
        trigger = self.record_flips(flips)
        if trigger is None:
            return None
        return await self._reflect(todos, trigger, state)

    def _resolve_model(self) -> BaseChatModel | None:
        """The verdict model: explicit pointer (cached) or runner fallback."""
        if self._model is None and self._model_factory is not None:
            self._model = self._model_factory()
        if self._model is not None:
            return self._model
        if self._default_model_provider is not None:
            return self._default_model_provider()
        return None

    async def _reflect(
        self,
        todos: Sequence[Mapping[str, Any]],
        flipped: Mapping[str, Any],
        state: Any,
    ) -> CheckpointOutcome | None:
        """One structured verdict call under the internal timeout."""
        try:
            model = self._resolve_model()
        except Exception:
            logger.warning("Checkpoint verdict model resolution failed; skipping", exc_info=True)
            return None
        if model is None:
            logger.debug("No verdict model available; skipping checkpoint reflection")
            return None
        prompt = _checkpoint_prompt(todos, flipped, _recent_context(state))
        try:
            async with asyncio.timeout(VERDICT_TIMEOUT_SECONDS):
                result = await model.with_structured_output(_VerdictSchema).ainvoke(
                    [HumanMessage(prompt)]
                )
        except Exception:
            logger.warning("Checkpoint verdict call failed; skipping", exc_info=True)
            return None
        if not isinstance(result, _VerdictSchema):
            logger.warning(
                "Checkpoint verdict returned %s, expected structured output; skipping",
                type(result).__name__,
            )
            return None
        return CheckpointOutcome(
            verdict=result.action,
            step_succeeded=result.step_succeeded,
            notes=result.notes,
        )
