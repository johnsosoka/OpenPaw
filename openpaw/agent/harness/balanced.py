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

One harness (and one bridge) serves every concurrent session on the
workspace, so ``run()`` registers the run's identity under its session key
rather than mutating shared per-run state — the bridge re-derives the
session from each tool call's own thread config (see PlanEventBridge).

Checkpoint reflection (DESIGN §3) rides the bridge: when configured, the
factory hands it a :class:`CheckpointReflector` and this harness wires the
runner's model instance in as the default verdict model. The
``explore_lenses`` tool (DESIGN §4) is registered by the factory alongside
this middleware stack.
"""

import uuid
from typing import Any

from openpaw.agent.harness.base import AgentHarness, HarnessKind
from openpaw.agent.harness.checkpoint_reflection import CheckpointReflector
from openpaw.agent.middleware.plan_event_bridge import PlanEventBridge
from openpaw.agent.middleware.todo_list import Todo, TodoListMiddleware
from openpaw.agent.runner import AgentRunner
from openpaw.model.status_event import StatusEmitter


def build_balanced_middleware(
    emitter: StatusEmitter | None,
    workspace_name: str,
    plan_visibility: bool = True,
    lens_guidance: bool = False,
    lens_count: int = 3,
    reflector: CheckpointReflector | None = None,
) -> list[Any]:
    """The middleware additions that make a runner balanced.

    Order matters: the bridge precedes the todo middleware so its tool
    wrapper is the outer layer around the write_todos handler.

    The bridge is included when plan visibility is on OR checkpoint
    reflection is configured (the bridge is reflection's counting seam).
    With visibility off, the bridge gets no emitter — no status events, but
    the checkpoint nudge still lands in the conversation.
    """
    extras: list[Any] = []
    if plan_visibility or reflector is not None:
        extras.append(
            PlanEventBridge(
                emitter=emitter if plan_visibility else None,
                workspace=workspace_name,
                lens_count=lens_count,
                reflector=reflector,
            )
        )
    extras.append(TodoListMiddleware(include_lens_guidance=lens_guidance))
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
        # Checkpoint reflection's default verdict model is the workspace
        # model already on this runner; read fresh per call so agent
        # rebuilds are picked up (an explicit reflection.model wins).
        if self._plan_bridge is not None and self._plan_bridge.reflector is not None:
            self._plan_bridge.reflector.set_default_model_provider(
                lambda: getattr(self, "_model_instance", None)
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
        """Register this run's identity with the plan bridge, then run the react loop."""
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
        MessageProcessor and the /compact handler re-inject these after
        compaction via ``read_todo_reminder`` so the checklist survives.

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
