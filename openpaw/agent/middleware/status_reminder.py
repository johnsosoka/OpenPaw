"""Middleware for reminding agents to use send_message() during long silent runs.

Detects when an agent has completed multiple tool-calling turns without sending
the user a progress update, and injects a framework instruction to nudge it.

Uses a three-gate decision model to avoid nagging:
- Gate 1: turns_since_update >= threshold
- Gate 2: reminders_issued < max_reminders
- Gate 3: turns_since_last_reminder >= cooldown_turns

The StatusReminderDetector is a pure Python class with no LangChain dependencies.
StatusReminderMiddleware wraps it in the AgentMiddleware protocol.
"""

import logging
from typing import Any, cast

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

# Tools that actually DELIVER something user-facing to the channel. A turn that
# calls any of these resets the silent counter. Note: text_to_speech is
# deliberately absent — it only STAGES audio ("ready to send"), it does not
# deliver. Staging without a following delivery tool leaves the user
# uninformed, so the reminder should still fire.
USER_DELIVERY_TOOLS = frozenset({"send_message", "send_file", "request_followup"})

REMINDER_TEMPLATE = (
    "You have completed {turns} tool-calling turns without sending the user a progress "
    "update. Use send_message() to inform them of your current status. "
    "({remaining} reminders remaining this run)"
)

REPEAT_GUARD_TEMPLATE = (
    "You have called '{tool}' {n} times in a row without progressing the task or "
    "updating the user. Stop repeating this tool. Either take a different concrete "
    "action to complete the task, or call send_message to tell the user your status "
    "or blocker, then end your turn."
)


class StatusReminderDetector:
    """Pure detection logic — tracks turns and decides when to intervene.

    Maintains counters per agent run. All state is reset between runs via
    reset(), which is called from MessageProcessor's finally block.

    Three-gate decision logic prevents nagging:
    - Gate 1: agent has been silent long enough (threshold)
    - Gate 2: reminder budget not exhausted (max_reminders)
    - Gate 3: enough turns since the last reminder (cooldown_turns)
    """

    def __init__(
        self,
        threshold: int = 5,
        max_reminders: int = 3,
        cooldown_turns: int = 1,
        repeat_tool_limit: int = 6,
        repeat_guard_max: int = 2,
    ) -> None:
        """Initialize the detector.

        Args:
            threshold: Number of silent tool-calling turns before first reminder.
            max_reminders: Maximum reminders to issue per agent run.
            cooldown_turns: Minimum turns between consecutive reminders.
            repeat_tool_limit: Consecutive identical single-tool turns before the
                anti-spin guard fires.
            repeat_guard_max: Maximum anti-spin guard injections per agent run.
        """
        self._threshold = threshold
        self._max_reminders = max_reminders
        self._cooldown_turns = cooldown_turns
        self._repeat_tool_limit = repeat_tool_limit
        self._repeat_guard_max = repeat_guard_max
        self._turns_since_update: int = 0
        self._reminders_issued: int = 0
        # Start high so Gate 3 doesn't block the very first reminder.
        # Cooldown governs spacing between consecutive reminders, not the first one.
        self._turns_since_last_reminder: int = cooldown_turns
        # Anti-spin guard state (independent of the send_message reminder gates).
        self._last_tool_signature: str | None = None
        self._repeat_count: int = 0
        self._repeat_guards_issued: int = 0

    def record_turn(self, tool_calls: list[str]) -> None:
        """Record an agent turn.

        Resets the silent counter if the turn delivered anything user-facing
        (any tool in USER_DELIVERY_TOOLS), and updates the repeated-tool spin
        tracker.

        Args:
            tool_calls: List of tool names called during this turn.
        """
        tool_set = set(tool_calls)
        if tool_set & USER_DELIVERY_TOOLS:
            self._turns_since_update = 0
        else:
            self._turns_since_update += 1
        self._turns_since_last_reminder += 1
        self._record_repeat(tool_set)

    def _record_repeat(self, tool_set: set[str]) -> None:
        """Update the repeated-single-tool spin tracker.

        A repeat-eligible turn calls exactly one distinct tool that is not a
        user-delivery tool. Consecutive such turns with the same tool name build
        _repeat_count; anything else (multiple tools, a delivery tool, or a
        different tool) breaks the pattern and resets it.
        """
        if len(tool_set) == 1 and not (tool_set & USER_DELIVERY_TOOLS):
            signature: str | None = next(iter(tool_set))
        else:
            signature = None

        if signature is not None and signature == self._last_tool_signature:
            self._repeat_count += 1
        elif signature is not None:
            self._last_tool_signature = signature
            self._repeat_count = 1
        else:
            self._last_tool_signature = None
            self._repeat_count = 0

    def should_remind(self) -> bool:
        """Check all three gates and return True if a reminder should be injected."""
        if self._turns_since_update < self._threshold:
            return False
        if self._reminders_issued >= self._max_reminders:
            return False
        if self._turns_since_last_reminder < self._cooldown_turns:
            return False
        return True

    def record_reminder(self) -> None:
        """Record that a reminder was issued and reset the cooldown counter."""
        self._reminders_issued += 1
        self._turns_since_last_reminder = 0

    def build_reminder(self) -> str:
        """Build the reminder text using current counter state."""
        return REMINDER_TEMPLATE.format(
            turns=self._turns_since_update,
            remaining=self._max_reminders - self._reminders_issued,
        )

    def should_guard(self) -> bool:
        """Return True if the repeated-tool anti-spin guard should fire.

        Independent of the send_message reminder gates: a tool-spin can happen
        even while under the silence threshold. Bounded by repeat_guard_max so it
        nudges rather than nags — the recursion_limit remains the hard backstop.
        """
        if self._repeat_count < self._repeat_tool_limit:
            return False
        if self._repeat_guards_issued >= self._repeat_guard_max:
            return False
        return True

    def record_guard(self) -> None:
        """Record that a guard fired and re-arm by clearing the repeat tracker.

        Clearing the tracker means the spin must rebuild for repeat_tool_limit
        more turns before firing again, so the guard is not injected every turn.
        """
        self._repeat_guards_issued += 1
        self._repeat_count = 0
        self._last_tool_signature = None

    def build_guard(self) -> str:
        """Build the anti-spin guard instruction using current tracker state."""
        return REPEAT_GUARD_TEMPLATE.format(
            tool=self._last_tool_signature,
            n=self._repeat_count,
        )

    @property
    def turns_since_update(self) -> int:
        """Number of tool-calling turns since the last user-delivery call."""
        return self._turns_since_update

    @property
    def repeat_count(self) -> int:
        """Consecutive turns that called the same single non-delivery tool."""
        return self._repeat_count

    @property
    def last_tool_signature(self) -> str | None:
        """Name of the tool currently driving the repeat counter, if any."""
        return self._last_tool_signature

    def reset(self) -> None:
        """Reset all counters. Called between agent runs to prevent cross-run bleed."""
        self._turns_since_update = 0
        self._reminders_issued = 0
        self._turns_since_last_reminder = self._cooldown_turns
        self._last_tool_signature = None
        self._repeat_count = 0
        self._repeat_guards_issued = 0


def inject_framework_instruction(state: AgentState[Any], instruction: str) -> dict[str, Any]:
    """Prepend a framework instruction to the last suitable message in state.

    Walks backward through state["messages"] looking for the last ToolMessage
    or HumanMessage, then prepends the instruction wrapped in
    <framework_instruction> tags. Uses model_copy() to avoid mutating the
    original message object.

    Args:
        state: LangGraph agent state dict containing "messages".
        instruction: Instruction text to inject.

    Returns:
        Modified state dict, or the original state if no suitable message found.
    """
    messages = list(state.get("messages", []))
    prefix = f"<framework_instruction>{instruction}</framework_instruction>\n\n"

    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, ToolMessage | HumanMessage):
            content = msg.content or ""
            if isinstance(content, list):
                content = "\n".join(str(c) for c in content)
            messages[i] = msg.model_copy(update={"content": prefix + content})
            state["messages"] = messages
            logger.debug("Injected framework instruction into %s", type(msg).__name__)
            return cast(dict[str, Any], state)

    logger.debug("inject_framework_instruction: no suitable message found, state unchanged")
    return cast(dict[str, Any], state)


class StatusReminderMiddleware(AgentMiddleware):
    """Middleware that reminds agents to use send_message() during long silent runs.

    Hooks into the agent graph via before_model and after_model:
    - after_model: Inspects tool_calls in the latest AIMessage, records the turn.
      Only turns where tools were actually called are counted.
    - before_model: If the detector says it's time to remind, prepends a
      <framework_instruction> to the last ToolMessage or HumanMessage.

    reset() is called from MessageProcessor's finally block between agent runs
    to prevent state from bleeding across separate user messages.
    """

    def __init__(self, config: Any) -> None:
        """Initialize the middleware.

        Args:
            config: StatusReminderConfig instance.
        """
        self._enabled: bool = config.enabled
        self._detector = StatusReminderDetector(
            threshold=config.threshold,
            max_reminders=config.max_reminders,
            cooldown_turns=config.cooldown_turns,
            repeat_tool_limit=config.repeat_tool_limit,
            repeat_guard_max=config.repeat_guard_max,
        )

    def before_model(
        self, state: AgentState[Any], runtime: Any
    ) -> dict[str, Any] | None:
        """Inject reminder into state if detector gates are all open.

        Args:
            state: LangGraph agent state.
            runtime: LangGraph runtime context (unused).

        Returns:
            Modified state if a reminder is injected, None otherwise.
        """
        if not self._enabled:
            return None

        # Anti-spin guard takes precedence: it targets a stronger failure mode
        # (repeating one tool forever) and can trip even under the silence
        # threshold. Fire at most one injection per before_model call.
        if self._detector.should_guard():
            guard = self._detector.build_guard()
            logger.info(
                "Injecting repeated-tool guard (tool=%s, repeat_count=%d)",
                self._detector.last_tool_signature,
                self._detector.repeat_count,
            )
            self._detector.record_guard()
            return inject_framework_instruction(state, guard)

        if not self._detector.should_remind():
            return None

        reminder = self._detector.build_reminder()
        self._detector.record_reminder()
        logger.info("Injecting send_message reminder (turns_since_update=%d)", self._detector.turns_since_update)
        return inject_framework_instruction(state, reminder)

    def after_model(
        self, state: AgentState[Any], runtime: Any
    ) -> dict[str, Any] | None:
        """Inspect tool_calls in the latest AIMessage and record the turn.

        Only counts turns where the agent actually called tools — turns with
        no tool calls (plain text responses) are ignored since they indicate
        the agent is already responding to the user.

        Args:
            state: LangGraph agent state.
            runtime: LangGraph runtime context (unused).

        Returns:
            Always None (this hook is read-only).
        """
        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None

        tool_names = [tc.get("name", "") for tc in (last.tool_calls or [])]
        if not tool_names:
            # No tools called — don't count this turn
            return None

        self._detector.record_turn(tool_names)
        return None

    def reset(self) -> None:
        """Reset detector state. Called from MessageProcessor's finally block."""
        self._detector.reset()
