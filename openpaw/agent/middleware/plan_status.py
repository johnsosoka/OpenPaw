"""Plan checklist rendering for the planner harness (PRD-002 H3.3, ADR-106 §3).

The plan to-do list is its OWN edited-in-place channel message, distinct from
the tool-status line. It is created on ``plan.created``, edited in place as
steps progress and revisions land, and — unlike the tool-status line — is
never deleted at run completion: it stays as the record of what was done.

``StatusUpdateMiddleware`` composes :class:`PlanStatusRenderer`; extraction
keeps the middleware under the module-size smell threshold.
"""

import logging
from typing import Any

from openpaw.model.status_event import StatusEvent, StatusEventKind

logger = logging.getLogger(__name__)

# Checklist marks mirror Plan.render_checklist() (openpaw/model/plan.py).
_MARKS: dict[str, str] = {
    "pending": " ",
    "in_progress": "~",
    "done": "x",
    "skipped": "-",
    "failed": "!",
}

# Node-phase vocabulary for the tool-status line (PRD-002 H7.2; wording per
# feedback round 1 — first-person, self-narrating). Triage entry shows
# "Thinking..." while the route is decided; the post-decision triage event
# (payload carries "route") renders a routing announcement instead.
_PHASE_LINES: dict[str, str] = {
    "triage": "Thinking...",
    "ideate": "Brainstorming...",
    "plan": "Planning...",
    "reflect": "Reflecting on that step...",
    "synthesize": "Putting it all together...",
}

# Routing announcements after triage decides (react stays silent: the react
# path narrates itself through tool statuses).
_ROUTE_LINES: dict[str, str] = {
    "plan": "I need to form a plan for this...",
    "ideate": "I need to think about this creatively...",
}

# Module announcements, keyed by module kind. Reflection is deliberately
# absent — it resolves once per step and would drown the status line.
_MODULE_LINES: dict[str, str] = {
    "creative": "Ideating with the {module} module...",
    "planning": "Using the {module} module to shape the plan...",
}

# Reflection outcomes worth narrating. A clean advance stays silent — the
# checklist tick already tells that story.
_VERDICT_LINES: dict[str, str] = {
    "insert_step": "Hit a snag — adding a recovery step...",
    "revise_plan": "This isn't working — going back to the drawing board...",
}
_FAILED_ADVANCE_LINE = "That step didn't go as planned — pressing on..."

_MAX_STEP_PHASE_LEN = 80


class PlanStatusRenderer:
    """Maintains one plan checklist message per run, edited in place.

    State is re-rendered wholesale from every ``plan.*`` payload (no diffing).
    A local last-event-wins overlay tracks live step transitions between full
    plan payloads: ``plan.step_started`` marks a step in_progress,
    ``plan.step_completed`` optimistically marks it done — the next full plan
    payload (``plan.revised``) is authoritative and clears the overlay.
    """

    def __init__(self, use_emojis: bool = True) -> None:
        """Initialize the renderer.

        Args:
            use_emojis: Mirror of StatusUpdatesConfig.use_emojis for the
                checklist header prefix.
        """
        self._use_emojis = use_emojis
        self._message_id: str | None = None
        self._objective: str = ""
        self._revision: int = 0
        self._steps: list[dict[str, Any]] = []
        self._overlay: dict[str, str] = {}

    def reset(self) -> None:
        """Drop per-run state. The completed run's channel message survives."""
        self._message_id = None
        self._objective = ""
        self._revision = 0
        self._steps = []
        self._overlay = {}

    async def handle(
        self, event: StatusEvent, channel: Any, session_key: str
    ) -> str | None:
        """Render one plan/node event against the given channel.

        Args:
            event: A plan.*, node.entered, reflection.verdict, or
                module.selected event.
            channel: The armed channel adapter.
            session_key: The armed session key.

        Returns:
            A short phase line for the (separate) tool-status message, or
            None when the event needs no status-line update.
        """
        kind = event.kind
        payload = event.payload

        if kind is StatusEventKind.PLAN_CREATED:
            self._message_id = None  # always a fresh message per plan
            self._load_plan(payload.get("plan"))
            await self._send_or_edit(channel, session_key)
            return None

        if kind is StatusEventKind.PLAN_REVISED:
            self._load_plan(payload.get("plan"))
            await self._send_or_edit(channel, session_key)
            return None

        if kind is StatusEventKind.PLAN_STEP_STARTED:
            step_id = str(payload.get("step_id", ""))
            self._overlay[step_id] = "in_progress"
            await self._send_or_edit(channel, session_key)
            return self._step_phase_line(step_id)

        if kind is StatusEventKind.PLAN_STEP_COMPLETED:
            # ponytail: optimistic done — a failed verdict is corrected by
            # the next plan.revised payload (last-event-wins overlay).
            self._overlay[str(payload.get("step_id", ""))] = "done"
            await self._send_or_edit(channel, session_key)
            return None

        if kind is StatusEventKind.NODE_ENTERED:
            if event.node == "triage" and "route" in payload:
                if payload.get("resume_step_id"):
                    return "Resuming the plan..."
                return _ROUTE_LINES.get(str(payload.get("route")))
            return _PHASE_LINES.get(event.node or "")

        if kind is StatusEventKind.MODULE_SELECTED:
            template = _MODULE_LINES.get(str(payload.get("kind")))
            if template:
                return template.format(module=payload.get("module"))
            return None

        if kind is StatusEventKind.REFLECTION_VERDICT:
            verdict = str(payload.get("verdict"))
            if verdict == "advance" and payload.get("step_succeeded") is False:
                return _FAILED_ADVANCE_LINE
            return _VERDICT_LINES.get(verdict)

        return None

    def _load_plan(self, plan: Any) -> None:
        """Replace local plan state from a serialized Plan payload."""
        if not isinstance(plan, dict):
            logger.debug("Plan payload missing or malformed: %r", plan)
            return
        self._objective = str(plan.get("objective", ""))
        try:
            self._revision = int(plan.get("revision") or 0)
        except (TypeError, ValueError):
            self._revision = 0
        steps = plan.get("steps")
        self._steps = (
            [s for s in steps if isinstance(s, dict)]
            if isinstance(steps, list)
            else []
        )
        self._overlay = {}

    def _render(self) -> str:
        """Render the full checklist (header + per-step marks)."""
        prefix = "📋 " if self._use_emojis else ""
        header = f"{prefix}Plan: {self._objective}"
        if self._revision:
            header += f" (rev {self._revision})"
        lines = [header]
        for step in self._steps:
            step_id = str(step.get("id", ""))
            status = self._overlay.get(step_id, str(step.get("status", "pending")))
            mark = _MARKS.get(status, " ")
            lines.append(f"[{mark}] {step_id}. {step.get('description', '')}")
        return "\n".join(lines)

    def _step_phase_line(self, step_id: str) -> str | None:
        """Build a 'Step i/n: description...' line for the status message."""
        for index, step in enumerate(self._steps, start=1):
            if str(step.get("id", "")) == step_id:
                description = str(step.get("description", ""))
                if len(description) > _MAX_STEP_PHASE_LEN:
                    description = description[: _MAX_STEP_PHASE_LEN - 3] + "..."
                return f"Step {index}/{len(self._steps)}: {description}..."
        return None

    async def _send_or_edit(self, channel: Any, session_key: str) -> None:
        """Edit the tracked plan message, or send a new one and track it."""
        if not self._steps:
            return
        text = self._render()
        if self._message_id:
            edited = await channel.edit_message(session_key, self._message_id, text)
            if edited:
                return
            logger.debug("Plan message edit failed; sending a new message")
        sent = await channel.send_message(session_key, text)
        if sent is not None and hasattr(sent, "id"):
            self._message_id = str(sent.id)
