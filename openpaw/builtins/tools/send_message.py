"""Send message builtin for mid-execution agent communication."""

import asyncio
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


class SendMessageInput(BaseModel):
    """Input schema for sending a message."""

    content: str = Field(
        description="The message text to send to the user"
    )


class SendMessageTool(BaseBuiltinTool):
    """Tool for agents to send messages mid-execution.

    Enables agents to push status updates, progress reports, or partial results
    to the user while continuing to work. This allows for long-running operations
    where the user wants to know the agent is still working.

    Examples:
        - "Starting deployment... this may take a few minutes"
        - "Found 50 files to process, working on batch 1..."
        - "Database backup complete, now running migrations..."

    The tool requires session context to be set by WorkspaceRunner before use.
    Without context (e.g., in cron/heartbeat), it returns a clean error.
    """

    metadata = BuiltinMetadata(
        name="send_message",
        display_name="Send Message",
        description="Send a message to the user mid-execution",
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
        """Return the send_message tool as a LangChain StructuredTool."""

        def send_message_sync(content: str) -> str:
            """Sync wrapper for send_message (for LangChain compatibility).

            Args:
                content: The message text to send.

            Returns:
                Confirmation message or error.
            """
            channel, session_key = get_channel_context()

            if not channel or not session_key:
                return "[Error: send_message not available in this context (no active session)]"

            try:
                try:
                    loop = asyncio.get_running_loop()
                    future = asyncio.run_coroutine_threadsafe(
                        channel.send_message(session_key, content),
                        loop
                    )
                    future.result(timeout=30.0)
                except RuntimeError:
                    # No running loop - safe to use asyncio.run
                    asyncio.run(channel.send_message(session_key, content))

                return f"Message sent: {content[:50]}{'...' if len(content) > 50 else ''}"
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                return f"[Error: Failed to send message: {e}]"

        async def send_message_async(content: str) -> str:
            """Send a message to the user mid-execution.

            Args:
                content: The message text to send.

            Returns:
                Confirmation message or error.
            """
            channel, session_key = get_channel_context()

            if not channel or not session_key:
                return "[Error: send_message not available in this context (no active session)]"

            try:
                await channel.send_message(session_key, content)
                logger.info(f"Sent mid-execution message to {session_key}")
                return f"Message sent: {content[:50]}{'...' if len(content) > 50 else ''}"
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                return f"[Error: Failed to send message: {e}]"

        return StructuredTool.from_function(
            func=send_message_sync,
            coroutine=send_message_async,
            name="send_message",
            description=(
                "Send a message to the user while you continue working. "
                "Use this for status updates, progress reports, or partial results "
                "during long-running operations. The user will receive the message "
                "immediately, and you can continue with additional tool calls or work."
            ),
            args_schema=SendMessageInput,
        )
