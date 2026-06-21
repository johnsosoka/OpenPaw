"""Report progress builtin for agent-driven status updates."""

import logging
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools._channel_context import (
    clear_channel_context,
    get_channel_context,
    set_channel_context,
)

logger = logging.getLogger(__name__)


class ReportProgressInput(BaseModel):
    """Input schema for reporting progress."""

    status: str = Field(
        description="Short status label, e.g., 'Analyzing data'"
    )
    detail: str | None = Field(
        default=None, description="Optional longer detail message"
    )
    percent: int | None = Field(
        default=None, ge=0, le=100, description="Optional progress percentage 0-100"
    )
    emoji: str | None = Field(
        default=None, description="Optional emoji prefix, e.g. '📖'"
    )


class ReportProgressTool(BaseBuiltinTool):
    """Tool for agents to explicitly report their current progress.

    Enables agents to send structured status updates (status, detail, percent)
    to the user during long operations. Unlike send_message, this tool signals
    intent to report progress and is not throttled by the middleware.

    Examples:
        - "Reading the codebase to understand the structure..."
        - "Analyzing the data, 50% complete..."
        - "Compiling findings into a report..."

    The tool requires session context to be set by WorkspaceRunner before use.
    Without context (e.g., in cron/heartbeat), it returns a clean error.
    """

    metadata = BuiltinMetadata(
        name="report_progress",
        display_name="Report Progress",
        description="Report your current progress to the user while working",
        builtin_type=BuiltinType.TOOL,
        group="communication",
        prerequisites=BuiltinPrerequisite(),
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)

    def set_session_context(self, channel: Any, session_key: str) -> None:
        """Set the active session context for message routing.

        Called by WorkspaceRunner before each agent run.

        Args:
            channel: The channel instance to send messages through.
            session_key: The session key for routing (e.g., 'telegram:123456').
        """
        set_channel_context(channel, session_key)

    def clear_session_context(self) -> None:
        """Clear the session context after agent run completes.

        Called by WorkspaceRunner after each agent run.
        """
        clear_channel_context()

    def get_langchain_tool(self) -> Any:
        """Return the report_progress tool as a LangChain StructuredTool."""

        def _format_progress(status: str, detail: str | None, percent: int | None, emoji: str | None = None) -> str:
            """Format progress message with optional detail and percentage."""
            resolved_emoji = emoji if emoji is not None else "📊"
            parts = [f"{resolved_emoji} ", status]
            if detail:
                parts.append(f" — {detail}")
            if percent is not None:
                parts.append(f" ({percent}%)")
            return "".join(parts)

        def report_progress_sync(
            status: str,
            detail: str | None = None,
            percent: int | None = None,
            emoji: str | None = None,
        ) -> str:
            """Sync wrapper for report_progress (for LangChain compatibility).

            Args:
                status: Short status label.
                detail: Optional longer detail message.
                percent: Optional progress percentage 0-100.
                emoji: Optional emoji prefix.

            Returns:
                Confirmation message or error.
            """
            channel, session_key = get_channel_context()

            if not channel or not session_key:
                return "[Error: report_progress not available in this context (no active session)]"

            try:
                message = _format_progress(status, detail, percent, emoji)
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    future = asyncio.run_coroutine_threadsafe(
                        channel.send_message(session_key, message),
                        loop,
                    )
                    future.result(timeout=30.0)
                except RuntimeError:
                    asyncio.run(channel.send_message(session_key, message))

                logger.info("Reported progress to %s: %s", session_key, status)
                return f"Progress reported: {status}"
            except Exception as e:
                logger.error("Failed to report progress: %s", e)
                return f"[Error: Failed to report progress: {e}]"

        async def report_progress_async(
            status: str,
            detail: str | None = None,
            percent: int | None = None,
            emoji: str | None = None,
        ) -> str:
            """Report progress to the user while working.

            Args:
                status: Short status label.
                detail: Optional longer detail message.
                percent: Optional progress percentage 0-100.
                emoji: Optional emoji prefix.

            Returns:
                Confirmation message or error.
            """
            channel, session_key = get_channel_context()

            if not channel or not session_key:
                return "[Error: report_progress not available in this context (no active session)]"

            try:
                message = _format_progress(status, detail, percent, emoji)
                await channel.send_message(session_key, message)
                logger.info("Reported progress to %s: %s", session_key, status)
                return f"Progress reported: {status}"
            except Exception as e:
                logger.error("Failed to report progress: %s", e)
                return f"[Error: Failed to report progress: {e}]"

        return StructuredTool.from_function(
            func=report_progress_sync,
            coroutine=report_progress_async,
            name="report_progress",
            description=(
                "Report your current progress to the user while working. "
                "Call this when starting a new phase of work or when you want "
                "to reassure the user that you are still working. "
                "Provide a short status label, optional detail, and optional "
                "percentage (0-100). The user will see the update immediately."
            ),
            args_schema=ReportProgressInput,
        )
