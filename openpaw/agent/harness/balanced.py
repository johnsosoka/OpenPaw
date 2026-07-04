"""BalancedHarness — the react loop plus a live todo-driven plan checklist.

ADR-101's "middleware-only harness" fallback promoted to a peer (DESIGN
§1/§2): one shared context, zero harness LLM calls, plan visibility riding
inside the work turns the model was already taking. The stack is assembled
at construction:

    create_agent react loop
      + PlanEventBridge      (write_todos -> plan.* events, config-gated)
      + TodoListMiddleware   (write_todos tool + recitation guidance)

Like the react harness, balanced IS ``AgentRunner`` — a subclass rather than
the fifteen-member delegation wrapper ``react.py`` already rejected. The only
behavioral deltas are construction-time (extra middleware, timeout override
applied by the factory) and per-run bridge arming, so inheritance is the
honest shape; ``UltraHarness``-style wrapping exists for topology changes,
and there is no topology change here.

Checkpoint-reflection and the ``explore_lenses`` tool (DESIGN §3/§4) are a
later phase; their seams are the middleware stack assembled in
:func:`build_balanced_middleware` and the ``get_todos`` state reader below.
"""

import uuid
from typing import Any

from openpaw.agent.harness.base import AgentHarness, HarnessKind
from openpaw.agent.middleware.plan_event_bridge import PlanEventBridge
from openpaw.agent.middleware.todo_list import Todo, TodoListMiddleware
from openpaw.agent.runner import AgentRunner
from openpaw.model.status_event import StatusEmitter


def build_balanced_middleware(
    emitter: StatusEmitter | None,
    workspace_name: str,
    plan_visibility: bool = True,
) -> list[Any]:
    """The middleware additions that make a runner balanced.

    Order matters: the bridge precedes the todo middleware so its tool
    wrapper is the outer layer around the write_todos handler.
    """
    extras: list[Any] = []
    if plan_visibility:
        extras.append(PlanEventBridge(emitter=emitter, workspace=workspace_name))
    extras.append(TodoListMiddleware())
    return extras


class BalancedHarness(AgentRunner):
    """The balanced agent harness (DESIGN §2, ADR-111).

    Construct via ``AgentFactory.create_harness()`` — the factory appends
    :func:`build_balanced_middleware` to the workspace middleware stack and
    applies the ``harness.execution.timeout_seconds`` override.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the runner and locate the plan bridge in its middleware."""
        super().__init__(*args, **kwargs)
        self._plan_bridge: PlanEventBridge | None = next(
            (m for m in self._middleware if isinstance(m, PlanEventBridge)), None
        )

    @property
    def kind(self) -> HarnessKind:
        """Which harness topology this runner implements."""
        return HarnessKind.BALANCED

    @staticmethod
    def _session_key_from(thread_id: str | None, session_id: str | None) -> str | None:
        """Derive "{channel}:{id}" for event attribution (mirrors UltraHarness)."""
        if thread_id and ":" in thread_id:
            return thread_id.rsplit(":", 1)[0]
        return session_id

    async def run(
        self,
        message: str,
        session_id: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        """Arm the plan bridge with per-run identity, then run the react loop."""
        if self._plan_bridge is not None:
            self._plan_bridge.arm(
                session_key=self._session_key_from(thread_id, session_id),
                run_id=uuid.uuid4().hex[:12],
            )
        return await super().run(message, session_id=session_id, thread_id=thread_id)

    async def get_todos(self, thread_id: str) -> list[Todo]:
        """Read the current todo list from checkpointed thread state.

        Post-compact re-injection seam (DESIGN §2.1 wrinkle): auto-compact
        rotates threads, so the compaction path reads the old thread's todos
        here and re-injects ``render_todo_reminder(...)`` into the new one.
        Wiring into MessageProcessor lands with the next phase.

        Returns:
            The last written todo list, or [] for unknown/stateless threads.
        """
        if self.checkpointer is None:
            return []
        state = await self.agent_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        if not state or not state.values:
            return []
        return list(state.values.get("todos") or [])


def _protocol_conformance(harness: BalancedHarness) -> AgentHarness:
    """Compile-time check that BalancedHarness satisfies AgentHarness.

    mypy strict verifies the structural match here; drift in either surface
    fails type checking rather than exploding at runtime.
    """
    return harness
