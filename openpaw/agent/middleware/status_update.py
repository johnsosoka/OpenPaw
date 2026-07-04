"""Status update middleware for automatic agent progress reporting.

Hooks into LangGraph's AgentMiddleware protocol to emit status messages:
- abefore_agent: "Starting work..." when agent run begins
- aafter_model: Detect tool_calls in AIMessage, report "Using tools: X, Y..."
- awrap_tool_call: Report "Running tool: X..." / "Completed: X" and sub-agent dispatch

Throttling prevents spam during rapid tool-call sequences. Harness plan/
phase events bypass throttling (they are LLM-call-paced and user-meaningful).

Edit-in-place pattern (default):
- Sends one initial status message
- Edits that same message on subsequent updates
- Deletes the status message when the agent run completes
"""

import logging
import time
from typing import Any
from uuid import uuid4

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage

from openpaw.agent.middleware.plan_status import PlanStatusRenderer
from openpaw.agent.middleware.queue_aware import InterruptSignalError
from openpaw.builtins.tools._channel_context import get_channel_context
from openpaw.core.config.models.status_updates import StatusUpdatesConfig
from openpaw.core.prompts.system_events import (
    INTERRUPT_USER_NOTIFICATION,
    STEER_SKIP_MESSAGE,
    STEER_USER_NOTIFICATION,
)
from openpaw.model.status_event import (
    JsonValue,
    StatusEmitter,
    StatusEvent,
    StatusEventKind,
)

logger = logging.getLogger(__name__)

_EMOJI_MAP: dict[str, str] = {
    "spawn_agent": "🤖",
    "memory_search": "🔍",
    "send_message": "📤",
    "send_file": "📎",
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
        raw = args.get(key)
        if raw and isinstance(raw, str):
            cleaned: str = raw.strip()
            if cleaned:
                if len(cleaned) > _MAX_DETAIL_LEN:
                    cleaned = cleaned[: _MAX_DETAIL_LEN - 3] + "..."
                return cleaned
    return None


# One-line renderings for skill lifecycle events (PRD-001 F4.1, ADR-106 §3).
_SKILL_STATUS_VERBS: dict[StatusEventKind, str] = {
    StatusEventKind.SKILL_CREATED: "Skill created",
    StatusEventKind.SKILL_UPDATED: "Skill updated",
    StatusEventKind.SKILL_STAGED: "Skill staged for approval",
    StatusEventKind.SKILL_APPROVED: "Skill approved",
    StatusEventKind.SKILL_EQUIPPED: "Skill equipped",
    StatusEventKind.SKILL_DEPRECATED: "Skill deprecated",
    StatusEventKind.SKILL_REJECTED: "Skill rejected",
}


class StatusUpdateMiddleware(AgentMiddleware):
    """Middleware that emits automatic status updates to the user channel.

    Uses the AgentMiddleware async hooks (abefore_agent, aafter_model,
    awrap_tool_call) since OpenPaw uses astream() for async execution.

    Status messages are sent directly to the channel, bypassing the agent state
    to avoid causing additional LLM calls.

    Throttling:
    - Time-based: min_interval_seconds between auto-detected updates.
    - Deduplication: if the same set of tools is detected twice, only report once.
    - Harness plan/phase events bypass all throttling.

    Edit-in-place pattern:
    - When edit_in_place is True (default), a single status message is maintained
      and edited in place. This prevents chat clutter.
    - When False, each update sends a separate message (legacy behavior).
    """

    def __init__(
        self,
        config: StatusUpdatesConfig,
        emitter: StatusEmitter | None = None,
        workspace: str = "",
    ) -> None:
        """Initialize the middleware.

        Args:
            config: StatusUpdatesConfig instance controlling which events
                to report and throttling parameters.
            emitter: Optional StatusEmitter (ADR-106). When set, hooks emit
                machine-readable StatusEvents alongside channel rendering.
            workspace: Workspace name stamped onto emitted events.
        """
        self._config = config
        self._emitter = emitter
        self._workspace = workspace
        self._run_id: str = uuid4().hex
        self._channel: Any | None = None
        self._session_key: str | None = None
        self._last_update_time: float = 0.0
        self._last_reported_tools: frozenset[str] = frozenset()
        self._status_message_id: str | None = None
        self._steer_notified: bool = False
        # True once an ultra-harness event has rendered for this run: the
        # harness narrates its own phases, so the generic "Starting work..."
        # from inner react runs is suppressed (feedback round 1).
        self._harness_narrating: bool = False
        # Plan checklist rendering (PRD-002 H3.3): its own edited-in-place
        # message, distinct from the tool-status line above.
        self._plan_renderer = PlanStatusRenderer(use_emojis=config.use_emojis)
        # Per-sub-agent status tracking: subagent_id -> (msg_id, label, channel, session_key).
        # Not cleared on reset() — sub-agents may outlive the main agent run.
        self._subagent_status_ids: dict[str, tuple[str, str, Any, str]] = {}

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
        self._run_id = uuid4().hex
        self._last_update_time = 0.0
        self._last_reported_tools = frozenset()
        self._status_message_id = None
        self._steer_notified = False
        self._harness_narrating = False
        self._plan_renderer.reset()

    def reset(self) -> None:
        """Reset per-invocation state. Called by MessageProcessor after each run."""
        self._channel = None
        self._session_key = None
        self._run_count = 1
        self._is_system_batch = False
        self._last_update_time = 0.0
        self._last_reported_tools = frozenset()
        self._status_message_id = None
        self._steer_notified = False
        self._harness_narrating = False
        # Dropping renderer state stops further edits; the plan message
        # itself stays in the channel as the record of what was done.
        self._plan_renderer.reset()
        # _run_id intentionally NOT cleared: late sub-agent events after
        # reset() still correlate with the run that dispatched them.

    async def _emit(
        self, kind: StatusEventKind, payload: dict[str, JsonValue] | None = None
    ) -> None:
        """Emit a StatusEvent to the injected emitter (ADR-106 Phase A).

        Best-effort: emission failures are debug-logged and swallowed so
        status plumbing never breaks an agent run. No-op without an emitter.
        """
        if self._emitter is None:
            return
        try:
            await self._emitter.emit(
                StatusEvent(
                    kind=kind,
                    workspace=self._workspace,
                    session_key=self._session_key,
                    run_id=self._run_id,
                    payload=payload or {},
                )
            )
        except Exception:
            logger.debug("Status event emission failed for %s", kind, exc_info=True)

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

    async def handle_plan_event(self, event: StatusEvent) -> None:
        """Render ultra-harness plan/node events (PRD-002 H3.3, H7.2).

        Called by PlanChannelSink during a graph run — the armed per-run
        context (set_context) is valid because events arrive on the same
        asyncio task chain as the run. Maintains ONE plan checklist message
        per run (created on plan.created, edited in place on step/revision
        events; never deleted at completion) and pushes short node-phase
        lines through the existing tool-status machinery.

        Events for other sessions (mismatched session_key vs the armed
        context) are ignored. All failures are swallowed at debug level —
        plan rendering must never break a run.
        """
        if not self._config.enabled:
            return
        channel = self._channel
        session_key = self._session_key
        if not channel or not session_key:
            logger.debug("Plan event %s ignored: no armed channel context", event.kind)
            return
        if event.session_key != session_key:
            logger.debug(
                "Plan event %s ignored: session %s does not match armed %s",
                event.kind,
                event.session_key,
                session_key,
            )
            return
        self._harness_narrating = True
        try:
            phase_line = await self._plan_renderer.handle(event, channel, session_key)
            if phase_line:
                emoji = None
                if self._config.use_emojis:
                    emoji = (
                        "💡"
                        if event.kind is StatusEventKind.MODULE_INSIGHT
                        else "📋"
                    )
                # Forced: phase transitions are LLM-call-paced (bounded rate)
                # and each one is user-meaningful — throttling here is what
                # made module/routing lines vanish in round-1 testing.
                await self._send_status(phase_line, emoji=emoji, force=True)
        except Exception:
            logger.debug("Plan event rendering failed for %s", event.kind, exc_info=True)

    async def send_skill_status(self, event: StatusEvent) -> None:
        """Render a skill lifecycle event as a forced one-line status (F4.1).

        Called by SkillChannelSink. Skill events carry ``session_key=None``
        when they originate from background paths (learning loop, dream);
        those render to the armed context's channel when one exists. Events
        stamped with a session that does not match the armed context are
        skipped — same gate as :meth:`handle_plan_event`.
        """
        if not self._config.enabled:
            return
        if not self._channel or not self._session_key:
            return  # no armed context (background path) — skip silently
        if event.session_key is not None and event.session_key != self._session_key:
            return
        verb = _SKILL_STATUS_VERBS.get(event.kind)
        if verb is None:
            return
        name = event.payload.get("name", "?")
        created_by = event.payload.get("created_by")
        line = f"{verb}: {name}"
        if created_by:
            line += f" (by {created_by})"
        emoji = "🧠" if self._config.use_emojis else None
        if emoji:
            line = f"{emoji} {line}"
        await self._send_status(line, force=True)

    async def create_subagent_status(self, subagent_id: str, label: str) -> None:
        """Send a new status message for a sub-agent and store its message ID.

        Args:
            subagent_id: Unique identifier for the sub-agent request.
            label: Display name shown in the status header.
        """
        if not self._config.enabled:
            return
        await self._emit(
            StatusEventKind.SUBAGENT_DISPATCHED,
            {"subagent_id": subagent_id, "label": label},
        )
        if not self._config.subagent_status:
            return
        channel = self._channel
        session_key = self._session_key
        if not channel or not session_key:
            return
        text = f"🤖 Sub-agent: {label}\n🟡 Starting work..."
        try:
            sent = await channel.send_message(session_key, text)
            if sent and hasattr(sent, "id"):
                self._subagent_status_ids[subagent_id] = (str(sent.id), label, channel, session_key)
                logger.debug("Created sub-agent status for %s: msg=%s", subagent_id, sent.id)
        except Exception as e:
            logger.debug("Failed to create sub-agent status: %s", e)

    async def update_subagent_status(
        self, subagent_id: str, status: str, emoji: str | None = None
    ) -> None:
        """Edit a sub-agent's status message in place.

        Args:
            subagent_id: Unique identifier for the sub-agent request.
            status: Status text to display below the header line.
            emoji: Optional emoji prefix for the status line.
        """
        if not self._config.enabled:
            return
        await self._emit(
            StatusEventKind.SUBAGENT_TOOL,
            {"subagent_id": subagent_id, "status": status},
        )
        if not self._config.subagent_status:
            return
        entry = self._subagent_status_ids.get(subagent_id)
        if not entry:
            return
        msg_id, label, channel, session_key = entry
        status_line = f"{emoji} {status}" if emoji and self._config.use_emojis else status
        text = f"🤖 Sub-agent: {label}\n{status_line}"
        try:
            await channel.edit_message(session_key, msg_id, text)
            logger.debug("Updated sub-agent status for %s: %s", subagent_id, status)
        except Exception as e:
            logger.debug("Failed to update sub-agent status: %s", e)

    async def finalize_subagent_status(
        self, subagent_id: str, outcome: str
    ) -> None:
        """Edit or delete a sub-agent's status message at lifecycle end.

        Args:
            subagent_id: Unique identifier for the sub-agent request.
            outcome: One of "completed", "failed", or "cancelled".
        """
        if not self._config.enabled:
            return
        await self._emit(
            StatusEventKind.SUBAGENT_COMPLETED,
            {"subagent_id": subagent_id, "outcome": outcome},
        )
        if not self._config.subagent_status:
            return
        entry = self._subagent_status_ids.pop(subagent_id, None)
        if not entry:
            return
        msg_id, label, channel, session_key = entry

        _outcome_emoji = {"completed": "✅", "failed": "❌", "cancelled": "🚫"}
        outcome_emoji = _outcome_emoji.get(outcome, "⚠️")
        outcome_label = outcome.capitalize()

        if self._config.subagent_status_cleanup == "delete":
            try:
                await channel.delete_message(session_key, msg_id)
                logger.debug("Deleted sub-agent status for %s", subagent_id)
            except Exception as e:
                logger.debug("Failed to delete sub-agent status: %s", e)
        else:
            text = f"🤖 Sub-agent: {label}\n{outcome_emoji} {outcome_label}"
            try:
                await channel.edit_message(session_key, msg_id, text)
                logger.debug("Finalized sub-agent status for %s: %s", subagent_id, outcome)
            except Exception as e:
                logger.debug("Failed to finalize sub-agent status: %s", e)

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
        if not self._config.enabled:
            return None

        await self._emit(
            StatusEventKind.RUN_STARTED,
            {
                "run_count": getattr(self, "_run_count", 1),
                "is_system_batch": getattr(self, "_is_system_batch", False),
            },
        )

        if not self._config.agent_start:
            return None

        if getattr(self, "_is_system_batch", False):
            return None

        # Ultra harness runs narrate their own phases (Thinking...,
        # routing, steps); the generic label would stomp them.
        if self._harness_narrating:
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
        if not self._config.enabled:
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

        await self._emit(
            StatusEventKind.TOOL_SELECTED, {"tools": list(tool_names)}
        )

        if not self._config.tool_calls_detected:
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
        notifications via the existing status message.

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

        await self._emit(
            StatusEventKind.TOOL_STARTED,
            {"tool": tool_name, "detail": tool_detail},
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
            await self._emit(StatusEventKind.RUN_INTERRUPTED, {"tool": tool_name})
            if self._config.run_interrupted:
                await self._send_status(
                    INTERRUPT_USER_NOTIFICATION, force=True
                )
            raise

        await self._emit(
            StatusEventKind.TOOL_COMPLETED,
            {"tool": tool_name, "detail": tool_detail},
        )

        # Tool complete notification
        if self._config.tool_complete:
            complete_emoji = tool_emoji if tool_emoji != "🔧" else "✅"
            status = f"Completed: {tool_name}"
            if tool_detail:
                status += f" ({tool_detail})"
            await self._send_status(status, emoji=complete_emoji)

        # Detect steer skip and notify user (fire exactly once per steer event)
        if (
            self._config.steer_redirected
            and isinstance(result, ToolMessage)
            and result.content == STEER_SKIP_MESSAGE
            and not self._steer_notified
        ):
            await self._emit(StatusEventKind.RUN_STEERED, {"tool": tool_name})
            await self._send_status(STEER_USER_NOTIFICATION, force=True)
            self._steer_notified = True

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

        In edit-in-place mode (default), the first status message is sent normally
        and subsequent updates edit that same message. In legacy mode, each
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
            if self._config.edit_in_place and self._status_message_id:
                # Edit-in-place: edit existing message
                edited = await channel.edit_message(
                    session_key, self._status_message_id, text
                )
                if edited:
                    self._last_update_time = now
                    logger.debug("Status message edited: %s", text)
                    await self._retrigger_typing(channel, session_key)
                    return
                # Edit failed — fall through to sending a new message
                logger.debug("Edit failed, falling back to new message")

            # Send new message
            sent_message = await channel.send_message(session_key, text)
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
