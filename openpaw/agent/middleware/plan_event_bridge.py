"""PlanEventBridge — todo writes become plan.* status events (DESIGN §2.1).

Intercepts the ``write_todos`` tool (the balanced harness's whole plan
surface) and diffs each new list against the previous state to emit the
EXISTING plan event kinds — ``plan.created`` / ``plan.step_started`` /
``plan.step_completed`` / ``plan.revised`` — so the ultra harness's live
checklist UX (``PlanChannelSink`` -> ``PlanStatusRenderer``) works unchanged,
at zero extra LLM calls.

Todos have no stable step ids, so ids are synthesized positionally
("1".."n") and diffing is by content: identical content sequences produce
per-step events; any content/order change produces an authoritative
``plan.revised`` (spurious revisions are acceptable, spurious completions
are not). A todo flipping to ``failed`` maps to ``plan.step_completed`` with
additive ``failed``/``note`` payload keys (ADR-106 additive evolution,
DESIGN §10.1).

The emitter is injected (same wiring as ``StatusUpdateMiddleware``) and the
per-run identity is armed by ``BalancedHarness.run()`` — instance state
re-armed per run, never contextvars (invisible across LangGraph task
boundaries).
"""

import logging
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware

from openpaw.agent.middleware.todo_list import Todo
from openpaw.model.status_event import (
    JsonValue,
    StatusEmitter,
    StatusEvent,
    StatusEventKind,
)

logger = logging.getLogger(__name__)

# One diffed happening: the event kind plus its renderer-ready payload.
PlanEvent = tuple[StatusEventKind, dict[str, JsonValue]]

# Todo statuses -> serialized Plan step statuses (openpaw/model/plan.py
# vocabulary, which PlanStatusRenderer._MARKS keys on).
_STATUS_TO_PLAN: dict[str, str] = {
    "pending": "pending",
    "in_progress": "in_progress",
    "completed": "done",
    "failed": "failed",
}

# Forward transitions that map to step events; anything else (a status
# regression such as completed -> pending) falls back to plan.revised.
_FORWARD_SOURCES = ("pending", "in_progress")


def serialize_plan(todos: list[Todo], revision: int) -> dict[str, JsonValue]:
    """Build a plan.* payload matching what PlanStatusRenderer expects."""
    steps: list[JsonValue] = []
    for step_id, todo in enumerate(todos, start=1):
        step: dict[str, JsonValue] = {
            "id": str(step_id),
            "description": todo.get("content", ""),
            "status": _STATUS_TO_PLAN.get(str(todo.get("status", "pending")), "pending"),
        }
        note = str(todo.get("note", "")).strip()
        if note:
            step["note"] = note
        steps.append(step)
    # Todos carry no objective; the renderer omits the header suffix when empty.
    return {"objective": "", "revision": revision, "steps": steps}


def _step_payload(step_id: int, todo: Todo) -> dict[str, JsonValue]:
    """The plan.step_started / plan.step_completed payload for one todo."""
    return {"step_id": str(step_id), "description": todo.get("content", "")}


def _failed_payload(step_id: int, todo: Todo) -> dict[str, JsonValue]:
    """plan.step_completed payload with the additive failure keys (§10.1)."""
    payload = _step_payload(step_id, todo)
    payload["failed"] = True
    payload["note"] = str(todo.get("note", "")).strip()
    return payload


def _started_events(todos: list[Todo], previously_in_progress: set[str]) -> list[PlanEvent]:
    """step_started for items in_progress now but not before (by content)."""
    return [
        (StatusEventKind.PLAN_STEP_STARTED, _step_payload(idx, todo))
        for idx, todo in enumerate(todos, start=1)
        if todo.get("status") == "in_progress"
        and todo.get("content", "") not in previously_in_progress
    ]


def _status_flip_events(prev: list[Todo], new: list[Todo]) -> tuple[list[PlanEvent], bool]:
    """Per-step events for a pure status diff (identical content sequences).

    Returns:
        (events, needs_revision) — needs_revision is True when any flip is
        not a recognized forward transition, in which case the caller emits
        an authoritative plan.revised instead.
    """
    events: list[PlanEvent] = []
    for idx, (old, cur) in enumerate(zip(prev, new, strict=True), start=1):
        old_status = str(old.get("status", "pending"))
        new_status = str(cur.get("status", "pending"))
        if old_status == new_status:
            continue
        if new_status == "in_progress" and old_status == "pending":
            events.append((StatusEventKind.PLAN_STEP_STARTED, _step_payload(idx, cur)))
        elif new_status == "completed" and old_status in _FORWARD_SOURCES:
            events.append((StatusEventKind.PLAN_STEP_COMPLETED, _step_payload(idx, cur)))
        elif new_status == "failed" and old_status in _FORWARD_SOURCES:
            events.append((StatusEventKind.PLAN_STEP_COMPLETED, _failed_payload(idx, cur)))
        else:
            return [], True
    return events, False


def compute_plan_events(
    prev: list[Todo], new: list[Todo], revision: int
) -> tuple[list[PlanEvent], int]:
    """Diff two todo lists into plan.* events.

    Args:
        prev: The todo list before this write (from checkpointed state).
        new: The full replacement list from the write_todos call.
        revision: Current plan revision counter.

    Returns:
        (events, new_revision). Pure function — the bridge owns emission.
    """
    if not new:
        # Cleared list: nothing renderable; the stale checklist stays as the
        # record (same convention as run completion).
        return [], revision

    if not prev:
        events: list[PlanEvent] = [
            (StatusEventKind.PLAN_CREATED, {"plan": serialize_plan(new, 0)})
        ]
        events.extend(_started_events(new, previously_in_progress=set()))
        return events, 0

    if [t.get("content", "") for t in prev] == [t.get("content", "") for t in new]:
        step_events, needs_revision = _status_flip_events(prev, new)
        if not needs_revision:
            return step_events, revision
        revision += 1
        return [(StatusEventKind.PLAN_REVISED, {"plan": serialize_plan(new, revision)})], revision

    # Content/order changed: authoritative full-plan revision, plus phase
    # events for content-matched items that flipped in the same write. The
    # matching is deliberately simple (first occurrence by content); a
    # reworded step reads as remove+add and gets no step event — the revised
    # payload already carries its status.
    revision += 1
    events = [(StatusEventKind.PLAN_REVISED, {"plan": serialize_plan(new, revision)})]
    prev_status: dict[str, str] = {}
    for todo in prev:
        prev_status.setdefault(todo.get("content", ""), str(todo.get("status", "pending")))
    in_progress_before = {c for c, s in prev_status.items() if s == "in_progress"}
    events.extend(_started_events(new, previously_in_progress=in_progress_before))
    for idx, todo in enumerate(new, start=1):
        old_status = prev_status.get(todo.get("content", ""))
        if (
            todo.get("status") == "failed"
            and old_status is not None
            and old_status != "failed"
        ):
            events.append((StatusEventKind.PLAN_STEP_COMPLETED, _failed_payload(idx, todo)))
    return events, revision


def _normalize_todos(raw: Any) -> list[Todo]:
    """Coerce tool args / state values into a clean list of Todo dicts."""
    if not isinstance(raw, list):
        return []
    todos: list[Todo] = []
    for item in raw:
        if isinstance(item, dict) and "content" in item:
            todos.append(item)  # type: ignore[arg-type]
    return todos


class PlanEventBridge(AgentMiddleware):
    """Middleware that turns write_todos calls into plan.* status events.

    Placed BEFORE TodoListMiddleware in the middleware list so its tool
    wrapper is the outer layer around the write_todos handler.
    """

    def __init__(self, emitter: StatusEmitter | None, workspace: str) -> None:
        """Initialize the bridge.

        Args:
            emitter: Status event emitter (the workspace StatusBus). None
                makes the bridge a pass-through (plan visibility with no bus).
            workspace: Workspace name stamped onto emitted events.
        """
        super().__init__()
        self._emitter = emitter
        self._workspace = workspace
        self._session_key: str | None = None
        self._run_id: str = ""
        # ponytail: cosmetic revision counter, reset on plan.created; a
        # process restart mid-plan restarts the "(rev n)" numbering only.
        self._revision: int = 0

    def arm(self, session_key: str | None, run_id: str) -> None:
        """Set per-run event identity. Called by BalancedHarness.run()."""
        self._session_key = session_key
        self._run_id = run_id

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        """Intercept write_todos: execute, then diff-and-emit. Never raises."""
        if request.tool_call.get("name") != "write_todos":
            return await handler(request)

        # State snapshot predates the tool's Command update -> previous list.
        prev = _normalize_todos((request.state or {}).get("todos"))
        result = await handler(request)
        try:
            new = _normalize_todos(request.tool_call.get("args", {}).get("todos"))
            events, self._revision = compute_plan_events(prev, new, self._revision)
            for kind, payload in events:
                await self._emit(kind, payload)
        except Exception:
            logger.debug("Plan event bridging failed", exc_info=True)
        return result

    async def _emit(self, kind: StatusEventKind, payload: dict[str, JsonValue]) -> None:
        """Best-effort emission — status plumbing never breaks an agent run."""
        if self._emitter is None:
            return
        try:
            await self._emitter.emit(
                StatusEvent(
                    kind=kind,
                    workspace=self._workspace,
                    session_key=self._session_key,
                    run_id=self._run_id,
                    payload=payload,
                )
            )
        except Exception:
            logger.debug("Status event emission failed for %s", kind, exc_info=True)
