"""Status update middleware for automatic agent progress reporting.

Hooks into LangGraph's AgentMiddleware protocol to emit status messages:
- abefore_agent: "Starting work..." when agent run begins
- aafter_model: Detect tool_calls in AIMessage, report "Using tools: X, Y..."
- awrap_tool_call: Report "Running tool: X..." / "Completed: X" and sub-agent dispatch

Throttling prevents spam during rapid tool-call sequences. Agent-driven
report_progress tool calls bypass throttling.

Hermes Pattern (default):
- Sends one initial status message
- Edits that same message on subsequent updates
- Deletes the status message when the agent run completes
"""

import logging
import time
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage

from openpaw.builtins.tools._channel_context import get_channel_context
from openpaw.core.config.models.status_updates import StatusUpdatesConfig

logger = logging.getLogger(__name__)


class StatusUpdateMiddleware(AgentMiddleware):
    """Middleware that emits automatic status updates to the user channel.

    Uses the AgentMiddleware async hooks (abefore_agent, aafter_model,
    awrap_tool_call) since OpenPaw uses astream() for async execution.

    Status messages are sent directly to the channel, bypassing the agent state
    to avoid causing additional LLM calls.

    Throttling:
    - Time-based: min_interval_seconds between auto-detected updates.
    - Budget-based: max_updates_per_run total auto-updates per agent invocation.
    - Deduplication: if the same set of tools is detected twice, only report once.
    - Agent-driven report_progress bypasses all throttling.

    Hermes Pattern:
    - When hermes_mode is True (default), a single status message is maintained
      and edited in place. This prevents chat clutter.
    - When False, each update sends a separate message (legacy behavior).
    """

    def __init__(self, config: StatusUpdatesConfig) -> None:
        """Initialize the middleware.

        Args:
            config: StatusUpdatesConfig instance controlling which events
                to report and throttling parameters.
        """
        self._config = config
        self._channel: Any | None = None
        self._session_key: str | None = None
        self._last_update_time: float = 0.0
        self._updates_sent: int = 0
        self._last_reported_tools: frozenset[str] = frozenset()
        self._status_message_id: str | None = None

    def set_context(self, channel: Any, session_key: str) -> None:
        """Set the active channel and session for the current agent run.

        Called by MessageProcessor before each agent run.

        Args:
            channel: The channel adapter instance for sending messages.
            session_key: The session identifier (e.g., 'telegram:123456').
        """
        self._channel = channel
        self._session_key = session_key
        self._last_update_time = 0.0
        self._updates_sent = 0
        self._last_reported_tools = frozenset()
        self._status_message_id = None

    def reset(self) -> None:
        """Reset per-invocation state. Called by MessageProcessor after each run."""
        self._channel = None
        self._session_key = None
        self._last_update_time = 0.0
        self._updates_sent = 0
        self._last_reported_tools = frozenset()
        self._status_message_id = None

    async def delete_status(self) -> None:
        """Delete the tracked status message if one exists.

        Called by MessageProcessor after the final response is delivered
        to clean up the status message.
        """
        if not self._status_message_id or not self._channel or not self._session_key:
            return
        try:
            deleted = await self._channel.delete_message(
                self._session_key, self._status_message_id
            )
            if deleted:
                logger.debug("Deleted status message %s", self._status_message_id)
            self._status_message_id = None
        except Exception as e:
            logger.debug("Failed to delete status message: %s", e)

    async def abefore_agent(
        self, state: Any, runtime: Any
    ) -> dict[str, Any] | None:
        """Send 'Starting work...' when agent run begins (if enabled).

        Args:
            state: LangGraph agent state.
            runtime: LangGraph runtime context.

        Returns:
            None (no state modifications).
        """
        if not self._config.enabled or not self._config.agent_start:
            return None

        await self._send_status("Starting work...")
        return None

    async def aafter_model(
        self, state: Any, runtime: Any
    ) -> dict[str, Any] | None:
        """Detect tool_calls in the latest AIMessage and report tool usage.

        Only reports when the agent decides to call tools (not on the final
        text response). Deduplicates repeated reports of the same tool set.

        Args:
            state: LangGraph agent state containing "messages".
            runtime: LangGraph runtime context.

        Returns:
            None (no state modifications).
        """
        if not self._config.enabled or not self._config.tool_calls_detected:
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last = messages[-1]
        if not isinstance(last, AIMessage):
            return None

        tool_calls = getattr(last, "tool_calls", None)
        if not tool_calls:
            return None

        tool_names = [tc.get("name", "") for tc in tool_calls if tc.get("name")]
        if not tool_names:
            return None

        current_tools = frozenset(tool_names)
        if current_tools == self._last_reported_tools:
            return None

        self._last_reported_tools = current_tools
        names_str = ", ".join(tool_names)
        await self._send_status(f"Using tools: {names_str}...")
        return None

    async def awrap_tool_call(
        self, request: Any, handler: Any
    ) -> Any:
        """Intercept tool execution to report sub-agent dispatch and per-tool status.

        Args:
            request: ToolCallRequest with tool_call (name, args, id).
            handler: Async callable to execute the tool.

        Returns:
            Tool result from the handler.
        """
        if not self._config.enabled:
            return await handler(request)

        tool_name = request.tool_call.get("name", "unknown")

        # Report sub-agent dispatch
        if tool_name == "spawn_agent" and self._config.subagent_spawned:
            args = request.tool_call.get("args", {})
            label = args.get("label", "sub-agent")
            await self._send_status(f"Dispatched sub-agent: {label}")

        # Tool start notification
        if self._config.tool_start:
            await self._send_status(f"Running tool: {tool_name}...")

        result = await handler(request)

        # Tool complete notification
        if self._config.tool_complete:
            await self._send_status(f"Completed: {tool_name}")

        return result

    async def _send_status(self, text: str) -> None:
        """Send or edit a status message to the channel with throttling.

        In Hermes mode (default), the first status message is sent normally and
        subsequent updates edit that same message. In non-Hermes mode, each
        update sends a separate message.

        Args:
            text: The status message text to send.
        """
        channel = self._channel
        session_key = self._session_key

        if not channel or not session_key:
            # Fallback: try the context variable set by send_message tool
            channel, session_key = get_channel_context()
            if not channel or not session_key:
                return

        # Budget throttle
        if self._updates_sent >= self._config.max_updates_per_run:
            logger.debug(
                "Status update throttled (budget exhausted): %s", text
            )
            return

        # Time throttle
        now = time.monotonic()
        if now - self._last_update_time < self._config.min_interval_seconds:
            logger.debug(
                "Status update throttled (min_interval): %s", text
            )
            return

        try:
            if self._config.hermes_mode and self._status_message_id:
                # Hermes: edit existing message
                edited = await channel.edit_message(
                    session_key, self._status_message_id, text
                )
                if edited:
                    self._updates_sent += 1
                    self._last_update_time = now
                    logger.debug("Status message edited: %s", text)
                    return
                # Edit failed — fall through to sending a new message
                logger.debug("Edit failed, falling back to new message")

            # Send new message
            sent_message = await channel.send_message(session_key, text)
            self._updates_sent += 1
            self._last_update_time = now
            if sent_message and hasattr(sent_message, "id"):
                self._status_message_id = str(sent_message.id)
            logger.debug("Status update sent: %s", text)
        except Exception as e:
            logger.debug("Failed to send status update: %s", e)
