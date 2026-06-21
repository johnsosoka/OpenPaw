"""Tests for StatusReminderDetector, StatusReminderMiddleware, and inject_framework_instruction."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from openpaw.agent.middleware.status_reminder import (
    StatusReminderDetector,
    StatusReminderMiddleware,
    inject_framework_instruction,
)
from openpaw.core.config.models import StatusReminderConfig

# ---------------------------------------------------------------------------
# StatusReminderDetector
# ---------------------------------------------------------------------------


class TestStatusReminderDetectorThreshold:
    """Gate 1: turns_since_update >= threshold."""

    def test_no_reminder_before_threshold(self):
        detector = StatusReminderDetector(threshold=3)
        for _ in range(2):
            detector.record_turn(["read_file"])
        assert detector.should_remind() is False

    def test_reminder_at_threshold(self):
        detector = StatusReminderDetector(threshold=3)
        for _ in range(3):
            detector.record_turn(["read_file"])
        assert detector.should_remind() is True

    def test_reminder_above_threshold(self):
        detector = StatusReminderDetector(threshold=3)
        for _ in range(5):
            detector.record_turn(["brave_search"])
        assert detector.should_remind() is True

    def test_no_reminder_when_threshold_is_one_and_zero_turns(self):
        detector = StatusReminderDetector(threshold=1)
        assert detector.should_remind() is False

    def test_reminder_when_threshold_is_one_and_one_turn(self):
        detector = StatusReminderDetector(threshold=1)
        detector.record_turn(["read_file"])
        assert detector.should_remind() is True


class TestStatusReminderDetectorBudget:
    """Gate 2: reminders_issued < max_reminders."""

    def test_stops_after_max_reminders(self):
        detector = StatusReminderDetector(threshold=1, max_reminders=2, cooldown_turns=0)
        detector.record_turn(["read_file"])

        assert detector.should_remind() is True
        detector.record_reminder()

        detector.record_turn(["write_file"])
        assert detector.should_remind() is True
        detector.record_reminder()

        # Budget exhausted — no more reminders
        detector.record_turn(["glob_files"])
        assert detector.should_remind() is False

    def test_zero_max_reminders_never_reminds(self):
        detector = StatusReminderDetector(threshold=1, max_reminders=0)
        detector.record_turn(["read_file"])
        assert detector.should_remind() is False

    def test_reminder_count_increments_on_record_reminder(self):
        detector = StatusReminderDetector(threshold=1, max_reminders=3, cooldown_turns=0)
        detector.record_turn(["read_file"])

        for i in range(3):
            assert detector.should_remind() is True
            detector.record_reminder()
            # Advance cooldown
            detector.record_turn(["read_file"])

        assert detector.should_remind() is False


class TestStatusReminderDetectorCooldown:
    """Gate 3: turns_since_last_reminder >= cooldown_turns."""

    def test_cooldown_prevents_back_to_back_reminders(self):
        # cooldown_turns=2 means turns_since_last_reminder must be >= 2.
        # _turns_since_last_reminder starts at cooldown_turns so the first
        # reminder is not blocked by cooldown (it governs spacing between
        # consecutive reminders, not the first one).
        detector = StatusReminderDetector(threshold=1, max_reminders=5, cooldown_turns=2)

        # First turn: threshold met, cooldown starts satisfied — first reminder fires
        detector.record_turn(["read_file"])
        assert detector.should_remind() is True
        detector.record_reminder()  # resets turns_since_last_reminder to 0

        # One turn after reminder: turns_since_last_reminder=1 — not >= 2 yet
        detector.record_turn(["glob_files"])
        assert detector.should_remind() is False

        # Two turns after reminder: turns_since_last_reminder=2 — gate open again
        detector.record_turn(["grep_files"])
        assert detector.should_remind() is True

    def test_zero_cooldown_allows_consecutive_reminders(self):
        detector = StatusReminderDetector(threshold=1, max_reminders=5, cooldown_turns=0)
        detector.record_turn(["read_file"])

        assert detector.should_remind() is True
        detector.record_reminder()

        detector.record_turn(["write_file"])
        assert detector.should_remind() is True

    def test_cooldown_resets_on_record_reminder(self):
        detector = StatusReminderDetector(threshold=1, max_reminders=5, cooldown_turns=3)
        detector.record_turn(["read_file"])
        detector.record_reminder()

        # Advance past cooldown
        for _ in range(3):
            detector.record_turn(["read_file"])

        assert detector.should_remind() is True


    def test_first_reminder_not_blocked_by_cooldown(self):
        # With cooldown_turns=5 and threshold=1, the first reminder should still
        # fire after 1 turn — cooldown governs spacing between consecutive
        # reminders, not the first one.
        detector = StatusReminderDetector(threshold=1, max_reminders=5, cooldown_turns=5)
        detector.record_turn(["read_file"])
        assert detector.should_remind() is True

    def test_zero_cooldown_first_reminder_fires_on_first_turn(self):
        detector = StatusReminderDetector(threshold=1, max_reminders=5, cooldown_turns=0)
        detector.record_turn(["read_file"])
        assert detector.should_remind() is True


class TestStatusReminderDetectorSendMessageDetection:
    """send_message in tool_calls resets turns_since_update counter."""

    def test_send_message_resets_counter(self):
        detector = StatusReminderDetector(threshold=3)
        for _ in range(2):
            detector.record_turn(["read_file"])

        # Agent calls send_message — counter should reset
        detector.record_turn(["read_file", "send_message"])
        assert detector.should_remind() is False

    def test_counter_builds_again_after_send_message_reset(self):
        detector = StatusReminderDetector(threshold=3)
        for _ in range(5):
            detector.record_turn(["brave_search"])

        detector.record_turn(["send_message"])

        # Only 1 silent turn since reset — should not remind yet
        detector.record_turn(["read_file"])
        assert detector.should_remind() is False

        # Now 2 more silent turns (total 3 since reset) — should remind
        detector.record_turn(["write_file"])
        detector.record_turn(["glob_files"])
        assert detector.should_remind() is True

    def test_only_send_message_triggers_reset_not_other_tools(self):
        detector = StatusReminderDetector(threshold=2)
        detector.record_turn(["read_file"])
        detector.record_turn(["write_file"])
        assert detector.should_remind() is True  # threshold reached

        # Calling a different tool does not reset the counter
        detector.record_turn(["brave_search"])
        assert detector.should_remind() is True  # still above threshold


class TestStatusReminderDetectorReset:
    """reset() clears all counter state."""

    def test_reset_clears_turns_since_update(self):
        detector = StatusReminderDetector(threshold=2)
        for _ in range(5):
            detector.record_turn(["read_file"])
        assert detector.should_remind() is True

        detector.reset()
        assert detector.should_remind() is False

    def test_reset_clears_reminders_issued(self):
        detector = StatusReminderDetector(threshold=1, max_reminders=1, cooldown_turns=0)
        detector.record_turn(["read_file"])
        detector.record_reminder()
        detector.record_turn(["read_file"])
        assert detector.should_remind() is False  # budget exhausted

        detector.reset()
        detector.record_turn(["read_file"])
        assert detector.should_remind() is True  # budget restored after reset

    def test_reset_clears_cooldown_counter(self):
        # cooldown_turns=2: need turns_since_last_reminder >= 2.
        # After reset, turns_since_last_reminder=0 again.
        detector = StatusReminderDetector(threshold=1, max_reminders=5, cooldown_turns=2)

        # Advance past cooldown once to issue a reminder
        detector.record_turn(["read_file"])
        detector.record_turn(["write_file"])
        assert detector.should_remind() is True
        detector.record_reminder()  # resets cooldown counter

        # Mid-cooldown: only 1 turn since reminder
        detector.record_turn(["glob_files"])
        assert detector.should_remind() is False

        # Reset returns counters to initial state (cooldown starts satisfied)
        detector.reset()

        # After reset, cooldown is pre-satisfied so first reminder fires at threshold
        detector.record_turn(["read_file"])
        assert detector.should_remind() is True  # threshold=1 met, cooldown pre-satisfied after reset


class TestStatusReminderDetectorBuildReminder:
    """build_reminder() returns correctly formatted reminder text."""

    def test_reminder_text_contains_turns_and_remaining(self):
        detector = StatusReminderDetector(threshold=3, max_reminders=5)
        for _ in range(4):
            detector.record_turn(["read_file"])

        reminder = detector.build_reminder()
        assert "4" in reminder  # turns_since_update
        assert "5" in reminder  # max_reminders - reminders_issued (5 - 0 = 5)

    def test_remaining_decrements_after_record_reminder(self):
        detector = StatusReminderDetector(threshold=1, max_reminders=3, cooldown_turns=0)
        detector.record_turn(["read_file"])
        detector.record_reminder()
        detector.record_turn(["read_file"])

        reminder = detector.build_reminder()
        assert "2" in reminder  # 3 - 1 = 2 remaining


# ---------------------------------------------------------------------------
# inject_framework_instruction
# ---------------------------------------------------------------------------


class TestInjectFrameworkInstruction:
    """inject_framework_instruction() prepends instruction to the right message."""

    def _make_state(self, messages: list) -> dict:
        return {"messages": messages}

    def test_injects_into_last_tool_message(self):
        tool_msg = ToolMessage(content="result", tool_call_id="call_1")
        state = self._make_state([
            HumanMessage(content="do a thing"),
            AIMessage(content="", tool_calls=[{"name": "read_file", "id": "call_1", "args": {}}]),
            tool_msg,
        ])

        result = inject_framework_instruction(state, "reminder text")

        modified = result["messages"][-1]
        assert isinstance(modified, ToolMessage)
        assert modified.content.startswith("<framework_instruction>")
        assert "reminder text" in modified.content
        assert "result" in modified.content

    def test_injects_into_last_human_message_when_no_tool_message_after(self):
        human_msg = HumanMessage(content="do something")
        state = self._make_state([human_msg])

        result = inject_framework_instruction(state, "nudge")

        modified = result["messages"][-1]
        assert isinstance(modified, HumanMessage)
        assert "<framework_instruction>nudge</framework_instruction>" in modified.content

    def test_returns_unmodified_state_when_no_suitable_message(self):
        # Only AIMessages — no ToolMessage or HumanMessage
        state = self._make_state([
            AIMessage(content="thinking..."),
        ])
        original_content = state["messages"][0].content
        result = inject_framework_instruction(state, "ignored")

        assert result["messages"][0].content == original_content

    def test_does_not_mutate_original_message_object(self):
        original = HumanMessage(content="original content")
        state = self._make_state([original])

        inject_framework_instruction(state, "instruction")

        # Original object must be unchanged
        assert original.content == "original content"

    def test_tool_message_takes_precedence_over_human_message(self):
        state = self._make_state([
            HumanMessage(content="human text"),
            AIMessage(content="", tool_calls=[{"name": "read_file", "id": "c1", "args": {}}]),
            ToolMessage(content="tool result", tool_call_id="c1"),
        ])

        result = inject_framework_instruction(state, "test")

        # ToolMessage is last suitable message — should be modified
        assert isinstance(result["messages"][-1], ToolMessage)
        assert "test" in result["messages"][-1].content

    def test_injects_earlier_tool_message_skipping_ai_message_at_end(self):
        tool_msg = ToolMessage(content="result", tool_call_id="c1")
        ai_msg = AIMessage(content="final answer")
        state = self._make_state([
            HumanMessage(content="hi"),
            tool_msg,
            ai_msg,
        ])

        result = inject_framework_instruction(state, "instruction")

        # tool_msg is the last ToolMessage/HumanMessage (ai_msg is skipped)
        # messages[-2] should be modified
        modified = result["messages"][-2]
        assert "instruction" in modified.content

    def test_empty_state_returns_unchanged(self):
        state = {"messages": []}
        result = inject_framework_instruction(state, "anything")
        assert result["messages"] == []

    def test_prefix_format_is_xml_wrapped(self):
        state = self._make_state([HumanMessage(content="hello")])
        result = inject_framework_instruction(state, "do the thing")

        content = result["messages"][-1].content
        assert content.startswith("<framework_instruction>do the thing</framework_instruction>")


# ---------------------------------------------------------------------------
# StatusReminderMiddleware
# ---------------------------------------------------------------------------


def _make_middleware(
    enabled: bool = True,
    threshold: int = 3,
    max_reminders: int = 3,
    cooldown_turns: int = 0,
) -> StatusReminderMiddleware:
    config = StatusReminderConfig(
        enabled=enabled,
        threshold=threshold,
        max_reminders=max_reminders,
        cooldown_turns=cooldown_turns,
    )
    return StatusReminderMiddleware(config)


def _ai_with_tool_calls(*tool_names: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "id": f"call_{name}", "args": {}} for name in tool_names],
    )


class TestStatusReminderMiddlewareAfterModel:
    """after_model() records turns from AIMessage tool_calls."""

    def test_records_turn_from_ai_message_with_tool_calls(self):
        middleware = _make_middleware(threshold=1)
        state = {"messages": [_ai_with_tool_calls("read_file")]}

        result = middleware.after_model(state, runtime=None)

        # after_model is read-only, always returns None
        assert result is None
        # detector should now be at threshold
        assert middleware._detector.should_remind() is True

    def test_ignores_ai_message_without_tool_calls(self):
        middleware = _make_middleware(threshold=1)
        state = {"messages": [AIMessage(content="plain text response")]}

        middleware.after_model(state, runtime=None)

        assert middleware._detector.should_remind() is False

    def test_ignores_non_ai_last_message(self):
        middleware = _make_middleware(threshold=1)
        state = {"messages": [ToolMessage(content="result", tool_call_id="c1")]}

        middleware.after_model(state, runtime=None)

        assert middleware._detector.should_remind() is False

    def test_empty_messages_does_not_raise(self):
        middleware = _make_middleware()
        result = middleware.after_model({"messages": []}, runtime=None)
        assert result is None

    def test_send_message_in_tool_calls_resets_silent_counter(self):
        middleware = _make_middleware(threshold=2)
        state = {"messages": [_ai_with_tool_calls("read_file")]}
        middleware.after_model(state, runtime=None)

        state2 = {"messages": [_ai_with_tool_calls("send_message")]}
        middleware.after_model(state2, runtime=None)

        # Counter reset — not at threshold
        assert middleware._detector.should_remind() is False


class TestStatusReminderMiddlewareBeforeModel:
    """before_model() injects reminder when detector gates are open."""

    def test_injects_when_threshold_reached(self):
        middleware = _make_middleware(threshold=2)
        # Record 2 silent turns
        for _ in range(2):
            middleware.after_model({"messages": [_ai_with_tool_calls("read_file")]}, runtime=None)

        state = {
            "messages": [
                HumanMessage(content="do work"),
                _ai_with_tool_calls("read_file"),
                ToolMessage(content="result", tool_call_id="call_read_file"),
            ]
        }
        result = middleware.before_model(state, runtime=None)

        assert result is not None
        last = result["messages"][-1]
        assert "<framework_instruction>" in last.content

    def test_returns_none_before_threshold(self):
        middleware = _make_middleware(threshold=5)
        for _ in range(2):
            middleware.after_model({"messages": [_ai_with_tool_calls("read_file")]}, runtime=None)

        state = {"messages": [HumanMessage(content="hi")]}
        result = middleware.before_model(state, runtime=None)

        assert result is None

    def test_returns_none_when_disabled(self):
        middleware = _make_middleware(enabled=False, threshold=1)
        middleware.after_model({"messages": [_ai_with_tool_calls("read_file")]}, runtime=None)

        state = {"messages": [HumanMessage(content="hi")]}
        result = middleware.before_model(state, runtime=None)

        assert result is None

    def test_does_not_inject_after_budget_exhausted(self):
        middleware = _make_middleware(threshold=1, max_reminders=1)
        middleware.after_model({"messages": [_ai_with_tool_calls("read_file")]}, runtime=None)

        state = {"messages": [HumanMessage(content="hi")]}

        # First reminder — should inject
        first = middleware.before_model(state, runtime=None)
        assert first is not None

        # Advance detector (record another turn)
        middleware.after_model({"messages": [_ai_with_tool_calls("write_file")]}, runtime=None)

        # Budget exhausted — no more injections
        second = middleware.before_model(state, runtime=None)
        assert second is None


class TestStatusReminderMiddlewareReset:
    """reset() clears detector state between runs."""

    def test_reset_clears_turn_counter(self):
        middleware = _make_middleware(threshold=2)
        for _ in range(5):
            middleware.after_model({"messages": [_ai_with_tool_calls("read_file")]}, runtime=None)

        assert middleware._detector.should_remind() is True

        middleware.reset()

        state = {"messages": [HumanMessage(content="hi")]}
        assert middleware.before_model(state, runtime=None) is None

    def test_reset_restores_reminder_budget(self):
        middleware = _make_middleware(threshold=1, max_reminders=1)
        middleware.after_model({"messages": [_ai_with_tool_calls("read_file")]}, runtime=None)

        state = {"messages": [HumanMessage(content="hi")]}
        middleware.before_model(state, runtime=None)  # exhausts budget

        middleware.reset()

        # After reset, budget is restored
        middleware.after_model({"messages": [_ai_with_tool_calls("read_file")]}, runtime=None)
        result = middleware.before_model(state, runtime=None)
        assert result is not None


# ---------------------------------------------------------------------------
# StatusReminderConfig
# ---------------------------------------------------------------------------


class TestStatusReminderConfig:
    """Config model validation."""

    def test_defaults(self):
        config = StatusReminderConfig()
        assert config.enabled is True
        assert config.threshold == 5
        assert config.max_reminders == 3
        assert config.cooldown_turns == 1

    def test_custom_values(self):
        config = StatusReminderConfig(
            enabled=False, threshold=10, max_reminders=0, cooldown_turns=3
        )
        assert config.enabled is False
        assert config.threshold == 10
        assert config.max_reminders == 0
        assert config.cooldown_turns == 3

    def test_threshold_bounds(self):
        with pytest.raises(Exception):
            StatusReminderConfig(threshold=0)  # ge=1

        with pytest.raises(Exception):
            StatusReminderConfig(threshold=51)  # le=50

    def test_max_reminders_bounds(self):
        with pytest.raises(Exception):
            StatusReminderConfig(max_reminders=-1)  # ge=0

        with pytest.raises(Exception):
            StatusReminderConfig(max_reminders=21)  # le=20

    def test_cooldown_turns_bounds(self):
        with pytest.raises(Exception):
            StatusReminderConfig(cooldown_turns=-1)  # ge=0

        with pytest.raises(Exception):
            StatusReminderConfig(cooldown_turns=11)  # le=10
