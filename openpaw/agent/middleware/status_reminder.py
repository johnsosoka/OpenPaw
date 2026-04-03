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
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

logger = logging.getLogger(__name__)

REMINDER_TEMPLATE = (
    "You have completed {turns} tool-calling turns without sending the user a progress "
    "update. Use send_message() to inform them of your current status. "
    "({remaining} reminders remaining this run)"
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
    ) -> None:
        """Initialize the detector.

        Args:
            threshold: Number of silent tool-calling turns before first reminder.
            max_reminders: Maximum reminders to issue per agent run.
            cooldown_turns: Minimum turns between consecutive reminders.
        """
        self._threshold = threshold
        self._max_reminders = max_reminders
        self._cooldown_turns = cooldown_turns
        self._turns_since_update: int = 0
        self._reminders_issued: int = 0
        # Start high so Gate 3 doesn't block the very first reminder.
        # Cooldown governs spacing between consecutive reminders, not the first one.
        self._turns_since_last_reminder: int = cooldown_turns

    def record_turn(self, tool_calls: list[str]) -> None:
        """Record an agent turn. Resets silent counter if send_message was called.

        Args:
            tool_calls: List of tool names called during this turn.
        """
        if "send_message" in tool_calls:
            self._turns_since_update = 0
        else:
            self._turns_since_update += 1
        self._turns_since_last_reminder += 1

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

    @property
    def turns_since_update(self) -> int:
        """Number of tool-calling turns since the last send_message call."""
        return self._turns_since_update

    def reset(self) -> None:
        """Reset all counters. Called between agent runs to prevent cross-run bleed."""
        self._turns_since_update = 0
        self._reminders_issued = 0
        self._turns_since_last_reminder = self._cooldown_turns


def inject_framework_instruction(state: dict[str, Any], instruction: str) -> dict[str, Any]:
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
            messages[i] = msg.model_copy(update={"content": prefix + (msg.content or "")})
            state["messages"] = messages
            logger.debug("Injected framework instruction into %s", type(msg).__name__)
            return state

    logger.debug("inject_framework_instruction: no suitable message found, state unchanged")
    return state


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
        )

    def before_model(
        self, state: dict[str, Any], runtime: Any
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
        if not self._detector.should_remind():
            return None

        reminder = self._detector.build_reminder()
        self._detector.record_reminder()
        logger.info("Injecting send_message reminder (turns_since_update=%d)", self._detector.turns_since_update)
        return inject_framework_instruction(state, reminder)

    def after_model(
        self, state: dict[str, Any], runtime: Any
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
