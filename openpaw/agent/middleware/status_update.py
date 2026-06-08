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
from langchain_core.messages import AIMessage, ToolMessage

from openpaw.agent.middleware.queue_aware import InterruptSignalError
from openpaw.builtins.tools._channel_context import get_channel_context
from openpaw.core.config.models.status_updates import StatusUpdatesConfig
from openpaw.core.prompts.system_events import (
    INTERRUPT_USER_NOTIFICATION,
    STEER_SKIP_MESSAGE,
    STEER_USER_NOTIFICATION,
)

logger = logging.getLogger(__name__)

_EMOJI_MAP: dict[str, str] = {
    "spawn_agent": "🤖",
    "memory_search": "🔍",
    "send_message": "📤",
    "send_file": "📎",
    "report_progress": "📊",
    "shell": "💻",
    "browser": "🌐",
    "read_file": "📖",
    "list_dir": "📖",
    "grep": "📖",
    "write_file": "📝",
    "edit_file": "📝",
    "plan": "📋",
    "task": "📅",
    "cron": "📅",
    "acknowledge": "👍",
    "followup": "⏳",
    "email": "📧",
    "gmail": "📧",
    "channel_history": "📜",
    "md2pdf": "📄",
    "brave_search": "🔎",
    "elevenlabs_tts": "🔊",
    "gpt_researcher": "🔬",
    "describe_image": "🖼️",
    "calendar": "📆",
}


def _resolve_emoji(tool_names: list[str]) -> str:
    """Return the emoji for the first matching tool, or 🔧 if none match."""
    for name in tool_names:
        if name in _EMOJI_MAP:
            return _EMOJI_MAP[name]
    return "🔧"


# Tool detail extraction — maps tool names to the argument key(s) that
# provide the most useful context for a status update.
_TOOL_DETAIL_KEYS: dict[str, list[str]] = {
    "read_file": ["file_path", "path"],
    "write_file": ["file_path", "path"],
    "edit_file": ["file_path", "path"],
    "overwrite_file": ["file_path", "path"],
    "ls": ["directory", "path"],
    "glob_files": ["pattern"],
    "grep_files": ["pattern"],
    "shell": ["command"],
    "browser_navigate": ["url"],
    "browser_click": ["selector"],
    "browser_type": ["selector"],
    "brave_search": ["query"],
    "research": ["query"],
    "deep_research": ["query"],
    "send_email": ["recipient", "to"],
    "create_task": ["title"],
    "schedule_at": ["task", "description"],
    "spawn_agent": ["label"],
}

_MAX_DETAIL_LEN: int = 60


def _extract_tool_detail(tool_name: str, args: dict[str, Any]) -> str | None:
    """Extract a human-readable detail string from tool arguments.

    Args:
        tool_name: Name of the tool being called.
        args: The arguments dict passed to the tool.

    Returns:
        A concise detail string (e.g., file path, URL, query), or None
        if no relevant detail is found.
    """
    keys = _TOOL_DETAIL_KEYS.get(tool_name, [])
    for key in keys:
        value = args.get(key)
        if value and isinstance(value, str):
            value = value.strip()
            if value:
                if len(value) > _MAX_DETAIL_LEN:
                    value = value[: _MAX_DETAIL_LEN - 3] + "..."
                return value
    return None


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

    def set_context(
        self,
        channel: Any,
        session_key: str,
        run_count: int = 1,
        is_system_batch: bool = False,
    ) -> None:
        """Set the active channel and session for the current agent run.

        Called by MessageProcessor before each agent run.

        Args:
            channel: The channel adapter instance for sending messages.
            session_key: The session identifier (e.g., 'telegram:123456').
            run_count: Which agent run this is within the current process_messages
                loop (1 for first run, 2+ for follow-ups, steer, etc.).
            is_system_batch: Whether the current batch is a system event (cron,
                heartbeat, sub-agent completion). Skips "Starting work..." to
                avoid confusing the user mid-task.
        """
        self._channel = channel
        self._session_key = session_key
        self._run_count = run_count
        self._is_system_batch = is_system_batch
        self._last_update_time = 0.0
        self._updates_sent = 0
        self._last_reported_tools = frozenset()
        self._status_message_id = None

    def reset(self) -> None:
        """Reset per-invocation state. Called by MessageProcessor after each run."""
        self._channel = None
        self._session_key = None
        self._run_count = 1
        self._is_system_batch = False
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
        """Send status when agent run begins (if enabled).

        First run: "Starting work..."
        Subsequent runs: "Continuing work..."
        System events: skipped to avoid confusing the user mid-task.

        Args:
            state: LangGraph agent state.
            runtime: LangGraph runtime context.

        Returns:
            None (no state modifications).
        """
        if not self._config.enabled or not self._config.agent_start:
            return None

        if getattr(self, "_is_system_batch", False):
            return None

        label = (
            "Starting work..."
            if getattr(self, "_run_count", 1) == 1
            else "Continuing work..."
        )
        emoji = "🚀" if self._config.use_emojis else None
        await self._send_status(label, emoji=emoji)
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

        # Build a detail-rich list: "tool_name (detail)" when detail is available
        tool_parts: list[str] = []
        for tc in tool_calls:
            name = tc.get("name", "")
            if not name:
                continue
            detail = _extract_tool_detail(name, tc.get("args", {}))
            if detail:
                tool_parts.append(f"{name} ({detail})")
            else:
                tool_parts.append(name)

        names_str = ", ".join(tool_parts)
        emoji = _resolve_emoji(tool_names) if self._config.use_emojis else None
        await self._send_status(f"Using tools: {names_str}...", emoji=emoji)
        return None

    async def awrap_tool_call(
        self, request: Any, handler: Any
    ) -> Any:
        """Intercept tool execution to report sub-agent dispatch and per-tool status.

        Also detects steer and interrupt signals to send user-facing status
        notifications via the existing Hermes message.

        Args:
            request: ToolCallRequest with tool_call (name, args, id).
            handler: Async callable to execute the tool.

        Returns:
            Tool result from the handler.
        """
        if not self._config.enabled:
            return await handler(request)

        tool_name = request.tool_call.get("name", "unknown")
        tool_args = request.tool_call.get("args", {})
        tool_emoji = _resolve_emoji([tool_name]) if self._config.use_emojis else None
        tool_detail = _extract_tool_detail(tool_name, tool_args)
        logger.debug(
            "[STATUS_UPDATE] tool_name=%s tool_args=%s tool_detail=%s",
            tool_name,
            tool_args,
            tool_detail,
        )

        # Report sub-agent dispatch
        if tool_name == "spawn_agent" and self._config.subagent_spawned:
            label = tool_args.get("label", "sub-agent")
            emoji = tool_emoji if tool_emoji != "🔧" else "🤖"
            status = f"Dispatched sub-agent: {label}"
            if tool_detail and tool_detail != label:
                status += f" ({tool_detail})"
            await self._send_status(status, emoji=emoji)

        # Tool start notification
        if self._config.tool_start:
            start_emoji = tool_emoji if tool_emoji != "🔧" else "⚙️"
            status = f"Running tool: {tool_name}"
            if tool_detail:
                status += f" ({tool_detail})"
            status += "..."
            await self._send_status(status, emoji=start_emoji)

        try:
            result = await handler(request)
        except InterruptSignalError:
            if self._config.run_interrupted:
                await self._send_status(
                    INTERRUPT_USER_NOTIFICATION, force=True
                )
            raise

        # Tool complete notification
        if self._config.tool_complete:
            complete_emoji = tool_emoji if tool_emoji != "🔧" else "✅"
            status = f"Completed: {tool_name}"
            if tool_detail:
                status += f" ({tool_detail})"
            await self._send_status(status, emoji=complete_emoji)

        # Detect steer skip and notify user
        if (
            self._config.steer_redirected
            and isinstance(result, ToolMessage)
            and result.content == STEER_SKIP_MESSAGE
        ):
            await self._send_status(STEER_USER_NOTIFICATION, force=True)

        return result

    async def send_forced_status(self, text: str) -> None:
        """Send a status update that bypasses throttling.

        Public entry point for external callers (e.g., MessageProcessor) that
        need to send a status notification for one-time events like steer or
        collect. This delegates to _send_status with force=True.

        Args:
            text: The status message text to send.
        """
        await self._send_status(text, force=True)

    async def _send_status(
        self, text: str, emoji: str | None = None, force: bool = False
    ) -> None:
        """Send or edit a status message to the channel with throttling.

        In Hermes mode (default), the first status message is sent normally and
        subsequent updates edit that same message. In non-Hermes mode, each
        update sends a separate message.

        Args:
            text: The status message text to send.
            emoji: Optional emoji to prefix the text when use_emojis is enabled.
            force: When True, bypass time and budget throttling. Used for
                one-time events like steer or interrupt notifications.
        """
        channel = self._channel
        session_key = self._session_key

        if not channel or not session_key:
            # Fallback: try the context variable set by send_message tool
            channel, session_key = get_channel_context()
            if not channel or not session_key:
                return

        # Budget throttle
        if not force and self._updates_sent >= self._config.max_updates_per_run:
            logger.debug(
                "Status update throttled (budget exhausted): %s", text
            )
            return

        # Time throttle
        now = time.monotonic()
        if not force and now - self._last_update_time < self._config.min_interval_seconds:
            logger.debug(
                "Status update throttled (min_interval): %s", text
            )
            return

        if self._config.use_emojis and emoji:
            text = f"{emoji} {text}"

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
                    await self._retrigger_typing(channel, session_key)
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
            await self._retrigger_typing(channel, session_key)
        except Exception as e:
            logger.debug("Failed to send status update: %s", e)

    async def _retrigger_typing(self, channel: Any, session_key: str) -> None:
        """Re-trigger typing indicator after a status message is sent.

        Platforms auto-clear typing when the bot sends a message. Re-triggering
        keeps the indicator alive for long multi-step operations.
        """
        if not self._config.typing_indicator:
            return
        try:
            await channel.send_typing(session_key)
        except Exception:
            logger.debug("Failed to retrigger typing indicator", exc_info=True)
