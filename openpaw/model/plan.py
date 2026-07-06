"""Plan models for the ultra harness — first-class, revisable, checkpointed.

Pure dataclass layer (stability contract: no framework imports). The Plan is
the object the status system renders as a live to-do list (ADR-106 plan.*
payloads carry its serialized form) and the ultra graph checkpoints in
state (ADR-101 §3).
"""

from dataclasses import dataclass, field, replace
from enum import StrEnum


class StepStatus(StrEnum):
    """Lifecycle of a single plan step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class PlanStep:
    """One ordered step of a plan.

    Attributes:
        id: Ordinal identifier. Insertions get letter suffixes ("2A" slots
            between "2" and "3") so revisions never renumber history.
        description: What the executor should accomplish for this step.
        status: Current lifecycle state.
        result_summary: Executor outcome digest, filled after execution.
    """

    id: str
    description: str
    status: StepStatus = StepStatus.PENDING
    result_summary: str = ""


@dataclass(frozen=True)
class Plan:
    """An ordered, revisable plan.

    Immutable: every mutation helper returns a new Plan. ``revision``
    increments on structural changes (insertion, rewrite), not on plain
    status transitions.
    """

    objective: str
    steps: tuple[PlanStep, ...] = field(default_factory=tuple)
    revision: int = 0

    def next_pending(self) -> PlanStep | None:
        """Return the first pending step, or None when the plan is done."""
        return next((s for s in self.steps if s.status == StepStatus.PENDING), None)

    def get_step(self, step_id: str) -> PlanStep | None:
        """Return the step with the given id, or None."""
        return next((s for s in self.steps if s.id == step_id), None)

    def with_step_status(
        self, step_id: str, status: StepStatus, result_summary: str = ""
    ) -> "Plan":
        """Return a copy with one step's status (and result digest) updated."""
        steps = tuple(
            replace(s, status=status, result_summary=result_summary or s.result_summary)
            if s.id == step_id
            else s
            for s in self.steps
        )
        return replace(self, steps=steps)

    def with_insertion(self, after_id: str, description: str) -> "Plan":
        """Return a copy with a new step inserted after ``after_id``.

        Insertion ids append "A" to the anchor id ("2" -> "2A"); inserting
        after "2A" yields "2AA" — ids never renumber existing history.
        """
        steps: list[PlanStep] = []
        for s in self.steps:
            steps.append(s)
            if s.id == after_id:
                steps.append(PlanStep(id=f"{after_id}A", description=description))
        return replace(self, steps=tuple(steps), revision=self.revision + 1)

    def with_remaining_replaced(self, new_steps: tuple[PlanStep, ...]) -> "Plan":
        """Return a copy where all still-pending steps are replaced.

        Executed steps (anything not PENDING) are preserved; ``new_steps``
        become the new tail. Used by full reflection's revise_plan verdict.
        """
        executed = tuple(s for s in self.steps if s.status != StepStatus.PENDING)
        return replace(self, steps=executed + new_steps, revision=self.revision + 1)

    def is_complete(self) -> bool:
        """True when no steps remain pending."""
        return self.next_pending() is None

    def render_checklist(self) -> str:
        """Render as a compact checklist for prompts and channel messages."""
        marks = {
            StepStatus.PENDING: " ",
            StepStatus.IN_PROGRESS: "~",
            StepStatus.DONE: "x",
            StepStatus.SKIPPED: "-",
            StepStatus.FAILED: "!",
        }
        return "\n".join(
            f"[{marks[s.status]}] {s.id}. {s.description}" for s in self.steps
        )

    def to_payload(self) -> dict[str, object]:
        """Serialize for plan.* status event payloads (ADR-106)."""
        return {
            "objective": self.objective,
            "revision": self.revision,
            "steps": [
                {"id": s.id, "description": s.description, "status": s.status.value}
                for s in self.steps
            ],
        }


@dataclass(frozen=True)
class IdeationResult:
    """Creative-module output: expanded and evaluated ideas (ADR-102)."""

    ideas: tuple[str, ...]
    evaluations: tuple[str, ...] = ()
    recommended_directions: tuple[str, ...] = ()
