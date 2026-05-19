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
    channel: str | None = Field(
        default=None,
        description=(
            "Target channel name for cross-channel messaging. "
            "Omit to send to the current channel."
        ),
    )
    target_id: int | None = Field(
        default=None,
        description=(
            "Target user/chat/channel ID on the target channel. "
            "Omit to use the channel's default target."
        ),
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
        # Registry for cross-channel messaging (channel_name -> ChannelAdapter)
        self._channel_registry: dict[str, Any] = {}
        # Default target IDs per channel (channel_name -> target_id)
        self._channel_targets: dict[str, int] = {}
        # Optional async callback for injecting [SYSTEM] events into a session
        self._system_event_callback: Any = None

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

    def set_channel_registry(
        self,
        channels: dict[str, Any],
        targets: dict[str, int],
        system_event_callback: Any = None,
    ) -> None:
        """Wire in the full channel registry for cross-channel messaging.

        Called by WorkspaceRunner after channels are set up. Only wired when
        two or more channels are present.

        Args:
            channels: Mapping of channel_name -> ChannelAdapter instance.
            targets: Mapping of channel_name -> default target_id.
            system_event_callback: Optional async callable(session_key, content)
                that injects a [SYSTEM] event into the target session queue.
        """
        self._channel_registry = channels
        self._channel_targets = targets
        self._system_event_callback = system_event_callback

    def get_langchain_tool(self) -> Any:
        """Return the send_message tool as a LangChain StructuredTool."""

        # Capture self so closures can access instance attributes without
        # relying on contextvars (which are invisible across LangGraph threads).
        tool_instance = self

        def send_message_sync(
            content: str,
            channel: str | None = None,
            target_id: int | None = None,
        ) -> str:
            """Sync wrapper for send_message (for LangChain compatibility).

            Args:
                content: The message text to send.
                channel: Optional target channel name for cross-channel send.
                target_id: Optional target ID on the remote channel.

            Returns:
                Confirmation message or error.
            """
            if channel is not None:
                # Cross-channel path
                registry = tool_instance._channel_registry
                if not registry:
                    return "[Error: Cross-channel messaging is not available in this context]"

                target_channel = registry.get(channel)
                if target_channel is None:
                    available = ", ".join(sorted(registry.keys()))
                    return (
                        f"[Error: Unknown channel '{channel}'. "
                        f"Available channels: {available}]"
                    )

                resolved_target = next(
                        (v for v in (target_id, tool_instance._channel_targets.get(channel)) if v is not None),
                        None,
                    )
                if resolved_target is None:
                    return (
                        f"[Error: No target_id for channel '{channel}'. "
                        f"Provide target_id explicitly.]"
                    )

                session_key = target_channel.build_session_key(str(resolved_target))

                try:
                    try:
                        loop = asyncio.get_running_loop()
                        future = asyncio.run_coroutine_threadsafe(
                            target_channel.send_message(session_key, content),
                            loop,
                        )
                        future.result(timeout=30.0)
                    except RuntimeError:
                        asyncio.run(target_channel.send_message(session_key, content))

                    # Inject a [SYSTEM] event into the target session if callback available
                    if tool_instance._system_event_callback is not None:
                        source_channel_name = _extract_channel_name_from_context()
                        system_content = _build_cross_channel_system_event(
                            source_channel_name, content
                        )
                        try:
                            loop = asyncio.get_running_loop()
                            future = asyncio.run_coroutine_threadsafe(
                                tool_instance._system_event_callback(
                                    session_key, system_content
                                ),
                                loop,
                            )
                            future.result(timeout=10.0)
                        except RuntimeError:
                            asyncio.run(
                                tool_instance._system_event_callback(
                                    session_key, system_content
                                )
                            )
                        except Exception as e:
                            logger.warning(f"Failed to inject cross-channel system event: {e}")

                    return f"Message sent to {channel}: {content[:50]}{'...' if len(content) > 50 else ''}"
                except Exception as e:
                    logger.error(f"Failed to send cross-channel message: {e}")
                    return f"[Error: Failed to send message to channel '{channel}': {e}]"

            # Default path — current session via contextvars
            ctx_channel, ctx_session_key = get_channel_context()

            if not ctx_channel or not ctx_session_key:
                return "[Error: send_message not available in this context (no active session)]"

            try:
                try:
                    loop = asyncio.get_running_loop()
                    future = asyncio.run_coroutine_threadsafe(
                        ctx_channel.send_message(ctx_session_key, content),
                        loop
                    )
                    future.result(timeout=30.0)
                except RuntimeError:
                    # No running loop - safe to use asyncio.run
                    asyncio.run(ctx_channel.send_message(ctx_session_key, content))

                return f"Message sent: {content[:50]}{'...' if len(content) > 50 else ''}"
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                return f"[Error: Failed to send message: {e}]"

        async def send_message_async(
            content: str,
            channel: str | None = None,
            target_id: int | None = None,
        ) -> str:
            """Send a message to the user mid-execution.

            Args:
                content: The message text to send.
                channel: Optional target channel name for cross-channel send.
                target_id: Optional target ID on the remote channel.

            Returns:
                Confirmation message or error.
            """
            if channel is not None:
                # Cross-channel path
                registry = tool_instance._channel_registry
                if not registry:
                    return "[Error: Cross-channel messaging is not available in this context]"

                target_channel = registry.get(channel)
                if target_channel is None:
                    available = ", ".join(sorted(registry.keys()))
                    return (
                        f"[Error: Unknown channel '{channel}'. "
                        f"Available channels: {available}]"
                    )

                resolved_target = next(
                        (v for v in (target_id, tool_instance._channel_targets.get(channel)) if v is not None),
                        None,
                    )
                if resolved_target is None:
                    return (
                        f"[Error: No target_id for channel '{channel}'. "
                        f"Provide target_id explicitly.]"
                    )

                session_key = target_channel.build_session_key(str(resolved_target))

                try:
                    await target_channel.send_message(session_key, content)
                    logger.info(
                        f"Sent cross-channel message to {channel}:{resolved_target}"
                    )

                    # Inject [SYSTEM] event into the target session if callback available
                    if tool_instance._system_event_callback is not None:
                        source_channel_name = _extract_channel_name_from_context()
                        system_content = _build_cross_channel_system_event(
                            source_channel_name, content
                        )
                        try:
                            await tool_instance._system_event_callback(
                                session_key, system_content
                            )
                        except Exception as e:
                            logger.warning(f"Failed to inject cross-channel system event: {e}")

                    return (
                        f"Message sent to {channel}: "
                        f"{content[:50]}{'...' if len(content) > 50 else ''}"
                    )
                except Exception as e:
                    logger.error(f"Failed to send cross-channel message: {e}")
                    return f"[Error: Failed to send message to channel '{channel}': {e}]"

            # Default path — current session via contextvars
            ctx_channel, ctx_session_key = get_channel_context()

            if not ctx_channel or not ctx_session_key:
                return "[Error: send_message not available in this context (no active session)]"

            try:
                await ctx_channel.send_message(ctx_session_key, content)
                logger.info(f"Sent mid-execution message to {ctx_session_key}")
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
                "immediately, and you can continue with additional tool calls or work. "
                "Specify the optional channel parameter to send to a different channel."
            ),
            args_schema=SendMessageInput,
        )


def _extract_channel_name_from_context() -> str:
    """Extract the source channel name from the current session context.

    Returns:
        Channel name string, or 'unknown' if no session context is set.
    """
    _, session_key = get_channel_context()
    if session_key:
        # Session key format: "{channel_name}:{id}" or "{channel_name}:{id}:{conv_id}"
        return session_key.split(":")[0]
    return "unknown"


def _build_cross_channel_system_event(source_channel: str, content: str) -> str:
    """Build the [SYSTEM] event content for cross-channel escalation injection.

    Args:
        source_channel: Name of the originating channel.
        content: The message that was sent cross-channel.

    Returns:
        Formatted system event string.
    """
    return (
        f"[SYSTEM] Cross-channel escalation from '{source_channel}':\n\n"
        f"{content}\n\n"
        f"Source channel logs: memory/logs/channel/ (use grep_files to search)"
    )
