"""Custom todo-list middleware for the balanced harness (DESIGN §10.1).

A thin fork of langchain's stock ``TodoListMiddleware`` (same mechanics:
``write_todos`` whole-list-replacement tool, ``todos`` state key with
``OmitFromInput``, system-prompt guidance via the model-call hook, parallel
call rejection in ``after_model``) with two schema additions John decided on:

- ``status: "failed"`` — first-class failure rendering (✗ in the checklist)
  instead of the stock "blocked work stays in_progress" convention.
- ``note: str`` — an optional one-line why/what-next per item, surfaced as a
  status line by the plan renderer without any extra LLM call.

Todos live in agent state and checkpoint per thread; every update is an
ordinary tool call, which is what :class:`PlanEventBridge` intercepts to emit
``plan.*`` status events.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, NotRequired, TypedDict, cast

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    OmitFromInput,
)
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel

logger = logging.getLogger(__name__)

TodoStatus = Literal["pending", "in_progress", "completed", "failed"]


class Todo(TypedDict):
    """A single todo item (stock shape + failed status + optional note)."""

    content: str
    status: TodoStatus
    note: NotRequired[str]


class TodoPlanningState(AgentState[Any]):
    """Agent state schema contributed by the todo middleware.

    ``OmitFromInput`` mirrors stock: callers cannot inject todos via input,
    but the key is a normal state channel — checkpointed per thread.
    """

    todos: Annotated[NotRequired[list[Todo]], OmitFromInput]


class WriteTodosInput(BaseModel):
    """Input schema for the ``write_todos`` tool."""

    todos: list[Todo]


WRITE_TODOS_TOOL_DESCRIPTION = """\
Create and manage a structured task list for your current work session. Each call
REPLACES the entire list.

Use this tool for complex multi-step work (3+ distinct steps), when the user provides
multiple tasks, or when a plan may need revision as results come in. Skip it for
trivial or purely conversational requests — for those, just do the task directly.

Task states:
- pending: not yet started
- in_progress: currently working on (keep EXACTLY ONE task in_progress at a time)
- completed: finished successfully — only when FULLY done, never for partial work
- failed: could not be completed — set a short one-line `note` explaining why and
  what happens next

Management rules:
- When you first write the list, mark the first task in_progress immediately.
- Mark tasks completed IMMEDIATELY after finishing them; do not batch updates.
- When a task fails, mark it failed with a note and REWRITE the remaining todos to
  reflect the new reality rather than pushing forward with a stale plan.
- Revise freely: add newly discovered tasks, remove irrelevant ones.
- Never call write_todos multiple times in parallel — each call replaces the whole list."""

TODO_SYSTEM_PROMPT = """## Task planning with `write_todos`

For multi-step work, write your todo list FIRST, then work through it. The user sees
this checklist live — it is your progress report, so keep it truthful in real time:
- Keep exactly ONE item in_progress at a time.
- Update the list IMMEDIATELY when an item's status changes; never batch updates.
- If a step fails, mark it `failed` with a one-line `note` (why / what next) and
  rewrite the remaining todos instead of pushing forward with a stale plan.
- Offload bulky tool results to workspace files and reference them by path instead
  of re-reading them into context.
- Never call `write_todos` multiple times in parallel.

For simple few-step requests, skip the todo list and just do the task."""

_PARALLEL_CALL_ERROR = (
    "Error: The `write_todos` tool should never be called multiple times "
    "in parallel. Please call it only once per model invocation to update "
    "the todo list."
)


def _write_todos(runtime: ToolRuntime[Any, Any], todos: list[Todo]) -> Command[Any]:
    """Replace the todo list in agent state (whole-list semantics, like stock)."""
    return Command(
        update={
            "todos": todos,
            "messages": [
                ToolMessage(
                    f"Updated todo list to {todos}", tool_call_id=runtime.tool_call_id
                )
            ],
        }
    )


async def _awrite_todos(runtime: ToolRuntime[Any, Any], todos: list[Todo]) -> Command[Any]:
    """Async variant of :func:`_write_todos`."""
    return _write_todos(runtime, todos)


_REMINDER_MARKS: dict[str, str] = {
    "pending": " ",
    "in_progress": "~",
    "completed": "x",
    "failed": "✗",
}


def render_todo_reminder(todos: list[Todo]) -> str | None:
    """Format the live todo list as a post-compact system reminder.

    Auto-compact rotates to a fresh thread, stripping the ToolMessage echoes
    the model relies on to remember its plan. This renders the last known
    list so it can be re-injected alongside the compaction summary.

    Public seam for the compaction path (DESIGN §2.1 wrinkle); wiring into
    MessageProcessor lands with the checkpoint-reflection phase.

    Returns:
        The reminder text, or None when there is nothing worth reciting
        (no todos, or everything already completed).
    """
    if not todos or all(t.get("status") == "completed" for t in todos):
        return None
    lines = ["Your current todo list (restored after context compaction):"]
    for todo in todos:
        mark = _REMINDER_MARKS.get(str(todo.get("status", "pending")), " ")
        line = f"[{mark}] {todo.get('content', '')}"
        note = str(todo.get("note", "")).strip()
        if note:
            line += f" — {note}"
        lines.append(line)
    lines.append("Continue from the in_progress item; keep updating with write_todos.")
    return "\n".join(lines)


class TodoListMiddleware(AgentMiddleware):
    """Contributes ``write_todos`` + recitation guidance to the agent.

    Custom variant of the stock middleware (see module docstring for the
    delta). Stateless: all todo state lives in the graph, so one instance is
    safe across rebuilds and threads.
    """

    state_schema = TodoPlanningState  # type: ignore[assignment]

    def __init__(self) -> None:
        """Register the ``write_todos`` tool."""
        super().__init__()
        self.tools = [
            StructuredTool.from_function(
                name="write_todos",
                description=WRITE_TODOS_TOOL_DESCRIPTION,
                func=_write_todos,
                coroutine=_awrite_todos,
                args_schema=WriteTodosInput,
                infer_schema=False,
            )
        ]

    @staticmethod
    def _with_guidance(request: ModelRequest[Any]) -> ModelRequest[Any]:
        """Append the recitation guidance block to the system message."""
        if request.system_message is not None:
            content = [
                *request.system_message.content_blocks,
                {"type": "text", "text": f"\n\n{TODO_SYSTEM_PROMPT}"},
            ]
        else:
            content = [{"type": "text", "text": TODO_SYSTEM_PROMPT}]
        system_message = SystemMessage(content=cast("list[str | dict[str, str]]", content))
        return request.override(system_message=system_message)

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any] | AIMessage:
        """Inject the recitation guidance into the system prompt (sync path)."""
        return handler(self._with_guidance(request))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any] | AIMessage:
        """Inject the recitation guidance into the system prompt (async path)."""
        return await handler(self._with_guidance(request))

    def after_model(self, state: Any, runtime: Runtime[Any]) -> dict[str, Any] | None:
        """Reject parallel ``write_todos`` calls (whole-list replacement is ambiguous)."""
        messages = state.get("messages") if isinstance(state, dict) else None
        if not messages:
            return None
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if last_ai is None or not last_ai.tool_calls:
            return None
        write_calls = [tc for tc in last_ai.tool_calls if tc["name"] == "write_todos"]
        if len(write_calls) > 1:
            return {
                "messages": [
                    ToolMessage(
                        content=_PARALLEL_CALL_ERROR,
                        tool_call_id=tc["id"],
                        status="error",
                    )
                    for tc in write_calls
                ]
            }
        return None

    async def aafter_model(self, state: Any, runtime: Runtime[Any]) -> dict[str, Any] | None:
        """Async variant of :meth:`after_model`."""
        return self.after_model(state, runtime)
