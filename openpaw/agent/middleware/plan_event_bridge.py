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

The emitter is injected (same wiring as ``StatusUpdateMiddleware``). One
bridge instance is shared by every concurrent session on the workspace
(main lane concurrency > 1), so event identity is never plain instance
state: ``BalancedHarness.run()`` registers each run's ``run_id`` under its
session key via :meth:`PlanEventBridge.arm`, and the session key itself is
derived per tool call from the call's own graph config (``thread_id``) —
arming session B mid-run can never re-stamp session A's events.
"""

import logging
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from openpaw.agent.middleware.todo_list import Todo
from openpaw.model.status_event import (
    JsonValue,
    StatusEmitter,
    StatusEvent,
    StatusEventKind,
)

if TYPE_CHECKING:
    from openpaw.agent.harness.checkpoint_reflection import (
        CheckpointOutcome,
        CheckpointReflector,
    )

logger = logging.getLogger(__name__)

# Checkpoint-reflection nudge, appended to the write_todos ToolMessage when a
# verdict is not-ok. The tool result already flows back into the
# conversation, so the course-correction rides it — zero new machinery.
_ADVISORY_TEMPLATE = (
    "\n\n[checkpoint reflection — {verdict}] {notes} "
    "Review the todo list and course-correct before proceeding."
)

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


def _append_advisory(result: Any, advisory: str) -> Any:
    """Append the checkpoint advisory to the write_todos ToolMessage.

    Least-invasive injection seam (DESIGN §3): the tool result is already
    headed into conversation history, so the nudge is appended to its
    content in place. Unknown result shapes are left untouched (fail-open).
    """
    messages: Any = None
    if isinstance(result, Command):
        update = result.update
        messages = update.get("messages") if isinstance(update, dict) else None
    elif isinstance(result, ToolMessage):
        messages = [result]
    if not isinstance(messages, list):
        return result
    for message in messages:
        if isinstance(message, ToolMessage) and isinstance(message.content, str):
            message.content += advisory
            break
    return result


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

    def __init__(
        self,
        emitter: StatusEmitter | None,
        workspace: str,
        lens_count: int = 3,
        reflector: "CheckpointReflector | None" = None,
    ) -> None:
        """Initialize the bridge.

        Args:
            emitter: Status event emitter (the workspace StatusBus). None
                makes the bridge a pass-through (plan visibility with no bus).
            workspace: Workspace name stamped onto emitted events.
            lens_count: ``harness.ideation.lens_count`` — used to recompute
                the deterministic lens selection when announcing an
                ``explore_lenses`` call (the tool itself stays pure).
            reflector: Checkpoint reflector when
                ``harness.reflection.mode: checkpoint`` (DESIGN §3); None
                means organic reflection only.
        """
        super().__init__()
        self._emitter = emitter
        self._workspace = workspace
        self._lens_count = lens_count
        self._reflector = reflector
        # Per-session identity and counters: one bridge serves all concurrent
        # sessions, so nothing per-run may live in plain instance attributes.
        # ponytail: maps grow one small entry per distinct session key — fine
        # at chat scale; add eviction if session cardinality ever explodes.
        self._run_ids: dict[str, str] = {}
        # ponytail: cosmetic revision counter, reset on plan.created; a
        # process restart mid-plan restarts the "(rev n)" numbering only.
        self._revisions: dict[str, int] = {}

    @property
    def reflector(self) -> "CheckpointReflector | None":
        """The checkpoint reflector, if configured (BalancedHarness wiring seam)."""
        return self._reflector

    def arm(self, session_key: str | None, run_id: str) -> None:
        """Register the run_id for one session's active run.

        Called by ``BalancedHarness.run()``. Safe under concurrent sessions:
        the run_id is keyed per session and looked up at emit time against
        the session derived from each tool call's own thread config, so
        arming one session never re-stamps another's in-flight events.
        """
        self._run_ids[session_key or ""] = run_id

    @staticmethod
    def _identity(request: Any) -> tuple[str | None, str | None]:
        """Derive (thread_id, session_key) from this call's graph config.

        Mirrors ``BalancedHarness._session_key_from``: a thread_id of
        ``"{channel}:{id}:{conversation_id}"`` yields ``"{channel}:{id}"``;
        a colon-less thread falls back to the configurable ``session_id``.
        Fail-open to (None, None) outside a graph (e.g. unit stubs).
        """
        config = getattr(getattr(request, "runtime", None), "config", None)
        configurable = config.get("configurable") if isinstance(config, dict) else None
        if not isinstance(configurable, dict):
            return None, None
        thread_id = configurable.get("thread_id")
        thread_id = thread_id if isinstance(thread_id, str) else None
        if thread_id and ":" in thread_id:
            return thread_id, thread_id.rsplit(":", 1)[0]
        session_id = configurable.get("session_id")
        return thread_id, session_id if isinstance(session_id, str) else None

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        """Intercept write_todos and explore_lenses. Never raises."""
        tool_name = request.tool_call.get("name")
        if tool_name == "explore_lenses":
            result = await handler(request)
            await self._announce_lenses(request)
            return result
        if tool_name != "write_todos":
            return await handler(request)

        # State snapshot predates the tool's Command update -> previous list.
        prev = _normalize_todos((request.state or {}).get("todos"))
        result = await handler(request)
        if not isinstance(result, Command):
            # Failed or short-circuited call: a successful write_todos always
            # returns a state-updating Command, so anything else (validation
            # error ToolMessage, timeout stub) means state is unchanged —
            # diffing the args would emit spurious events and feed phantom
            # flips to the reflector.
            return result
        thread_id, session_key = self._identity(request)
        events: list[PlanEvent] = []
        try:
            new = _normalize_todos(request.tool_call.get("args", {}).get("todos"))
            revision_key = session_key or ""
            events, self._revisions[revision_key] = compute_plan_events(
                prev, new, self._revisions.get(revision_key, 0)
            )
            for kind, payload in events:
                await self._emit(kind, payload, session_key)
        except Exception:
            logger.debug("Plan event bridging failed", exc_info=True)
            return result
        if self._reflector is not None:
            result = await self._checkpoint(
                events, new, request, result, thread_id, session_key
            )
        return result

    async def _announce_lenses(self, request: Any) -> None:
        """Emit the ideonomy lenses_selected phase for an explore_lenses call.

        Recomputes the deterministic selection (zero cost) so the existing
        module.phase renderer announces "Exploring through N lenses: ...".
        Best-effort — never breaks the tool call.
        """
        try:
            from openpaw.agent.harness.modules.ideonomy.selector import select_lenses

            topic = str(request.tool_call.get("args", {}).get("topic", ""))
            lenses = select_lenses(topic, self._lens_count)
            _, session_key = self._identity(request)
            await self._emit(
                StatusEventKind.MODULE_PHASE,
                {
                    "kind": "creative",
                    "module": "ideonomy",
                    "phase": "lenses_selected",
                    "total": len(lenses),
                    "detail": " · ".join(lens.theme for lens in lenses),
                },
                session_key,
            )
        except Exception:
            logger.debug("Lens announcement failed", exc_info=True)

    async def _checkpoint(
        self,
        events: list[PlanEvent],
        todos: list[Todo],
        request: Any,
        result: Any,
        thread_id: str | None,
        session_key: str | None,
    ) -> Any:
        """Run checkpoint reflection over this write's completed/failed flips.

        Emits ``reflection.verdict`` and, on a not-ok verdict, appends the
        course-correction advisory to the tool result. Fail-open: any error
        logs and returns the result unchanged.
        """
        reflector = self._reflector
        if reflector is None:
            return result
        try:
            flips = [
                payload
                for kind, payload in events
                if kind is StatusEventKind.PLAN_STEP_COMPLETED
            ]
            outcome: CheckpointOutcome | None = await reflector.observe(
                flips, todos, request.state, thread_id=thread_id
            )
            if outcome is None:
                return result
            await self._emit(
                StatusEventKind.REFLECTION_VERDICT,
                {
                    "verdict": outcome.verdict,
                    "reason": outcome.notes,
                    "step_succeeded": outcome.step_succeeded,
                },
                session_key,
            )
            if not outcome.ok:
                advisory = _ADVISORY_TEMPLATE.format(
                    verdict=outcome.verdict, notes=outcome.notes
                ).rstrip()
                result = _append_advisory(result, advisory)
        except Exception:
            logger.debug("Checkpoint reflection failed", exc_info=True)
        return result

    async def _emit(
        self,
        kind: StatusEventKind,
        payload: dict[str, JsonValue],
        session_key: str | None,
    ) -> None:
        """Best-effort emission — status plumbing never breaks an agent run.

        Identity is per-call: the session key comes from the emitting tool
        call's own thread config, the run_id from the arm-time map (unknown
        session -> "").
        """
        if self._emitter is None:
            return
        try:
            await self._emitter.emit(
                StatusEvent(
                    kind=kind,
                    workspace=self._workspace,
                    session_key=session_key,
                    run_id=self._run_ids.get(session_key or "", ""),
                    payload=payload,
                )
            )
        except Exception:
            logger.debug("Status event emission failed for %s", kind, exc_info=True)
