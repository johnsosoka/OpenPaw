"""Tests for the custom TodoListMiddleware (balanced harness, ADR-111 §10.1).

Covers the deltas from stock (failed status + note in the tool schema, the
recitation guidance block) and the mirrored stock mechanics (whole-list
replacement Command, parallel-call rejection, todos as a checkpointable
state key).
"""

from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from openpaw.agent.middleware.todo_list import (
    TODO_SYSTEM_PROMPT,
    Todo,
    TodoListMiddleware,
    WriteTodosInput,
    _write_todos,
    render_todo_reminder,
)


def make_todos() -> list[Todo]:
    return [
        {"content": "Research the API", "status": "completed"},
        {"content": "Write the client", "status": "in_progress"},
        {"content": "Add tests", "status": "pending"},
    ]


# ---------------------------------------------------------------------------
# Tool schema (the §10.1 deltas)
# ---------------------------------------------------------------------------


def test_schema_accepts_failed_status_and_note() -> None:
    parsed = WriteTodosInput.model_validate(
        {"todos": [{"content": "Deploy", "status": "failed", "note": "no SSH access"}]}
    )
    todo = parsed.todos[0]
    assert todo["status"] == "failed"
    assert todo["note"] == "no SSH access"


def test_schema_note_is_optional() -> None:
    parsed = WriteTodosInput.model_validate(
        {"todos": [{"content": "Deploy", "status": "pending"}]}
    )
    assert "note" not in parsed.todos[0]


def test_schema_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        WriteTodosInput.model_validate(
            {"todos": [{"content": "Deploy", "status": "blocked"}]}
        )


def test_middleware_contributes_write_todos_tool() -> None:
    mw = TodoListMiddleware()
    assert [t.name for t in mw.tools] == ["write_todos"]
    assert mw.tools[0].args_schema is WriteTodosInput


def test_write_todos_replaces_whole_list_and_echoes() -> None:
    todos = make_todos()
    runtime: Any = SimpleNamespace(tool_call_id="call-1")

    command = _write_todos(runtime, todos)

    assert command.update["todos"] == todos
    echo = command.update["messages"][0]
    assert isinstance(echo, ToolMessage)
    assert echo.tool_call_id == "call-1"
    assert "Write the client" in str(echo.content)


# ---------------------------------------------------------------------------
# Recitation guidance (model-call hook)
# ---------------------------------------------------------------------------


def _guidance_request(system_message: Any) -> Any:
    request = SimpleNamespace(system_message=system_message)
    request.override = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    return request


def test_guidance_appended_to_existing_system_message() -> None:
    existing = SimpleNamespace(content_blocks=[{"type": "text", "text": "You are Gilfoyle."}])
    out = TodoListMiddleware()._with_guidance(_guidance_request(existing))

    rendered = str(out["system_message"].content)
    assert "You are Gilfoyle." in rendered
    assert "exactly ONE item in_progress" in rendered
    assert "Offload bulky tool results to workspace files" in rendered


def test_guidance_creates_system_message_when_absent() -> None:
    out = TodoListMiddleware()._with_guidance(_guidance_request(None))
    blocks = out["system_message"].content
    assert blocks == [{"type": "text", "text": TODO_SYSTEM_PROMPT}]


def test_recitation_prompt_covers_the_discipline() -> None:
    """The §2.2 recitation rules are all present in the guidance block."""
    for phrase in (
        "write your todo list FIRST",
        "exactly ONE item in_progress",
        "IMMEDIATELY",
        "`failed`",
        "rewrite the remaining todos",
        "Offload bulky tool results",
        "parallel",
    ):
        assert phrase in TODO_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Parallel-call rejection
# ---------------------------------------------------------------------------


def _ai_with_calls(names: list[str]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": {"todos": []}, "id": f"call-{i}"}
            for i, name in enumerate(names)
        ],
    )


async def test_parallel_write_todos_rejected() -> None:
    mw = TodoListMiddleware()
    state = {"messages": [_ai_with_calls(["write_todos", "write_todos"])]}

    result = await mw.aafter_model(state, None)  # type: ignore[arg-type]

    assert result is not None
    errors = result["messages"]
    assert len(errors) == 2
    assert all(isinstance(m, ToolMessage) and m.status == "error" for m in errors)


async def test_single_write_todos_allowed() -> None:
    mw = TodoListMiddleware()
    state = {"messages": [_ai_with_calls(["write_todos", "read_file"])]}
    assert await mw.aafter_model(state, None) is None  # type: ignore[arg-type]


async def test_after_model_tolerates_empty_state() -> None:
    mw = TodoListMiddleware()
    assert await mw.aafter_model({"messages": []}, None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Post-compact reminder seam
# ---------------------------------------------------------------------------


def test_reminder_renders_marks_and_notes() -> None:
    todos: list[Todo] = [
        {"content": "Research the API", "status": "completed"},
        {"content": "Write the client", "status": "in_progress"},
        {"content": "Deploy", "status": "failed", "note": "no SSH access"},
        {"content": "Add tests", "status": "pending"},
    ]

    reminder = render_todo_reminder(todos)

    assert reminder is not None
    assert "[x] Research the API" in reminder
    assert "[~] Write the client" in reminder
    assert "[✗] Deploy — no SSH access" in reminder
    assert "[ ] Add tests" in reminder
    assert "write_todos" in reminder


def test_reminder_none_when_nothing_to_recite() -> None:
    assert render_todo_reminder([]) is None
    assert render_todo_reminder([{"content": "Done", "status": "completed"}]) is None
