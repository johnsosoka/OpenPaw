"""Send file builtin for agent-to-user file transfers."""

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.agent.tools import resolve_sandboxed_path
from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools._channel_context import get_channel_context

logger = logging.getLogger(__name__)

# Default max file size (50MB for Telegram)
DEFAULT_MAX_FILE_SIZE = 50 * 1024 * 1024


class SendFileInput(BaseModel):
    """Input schema for sending a file."""

    file_path: str = Field(
        description="Relative path to the file within the workspace to send"
    )
    caption: str | None = Field(
        default=None,
        description="Optional caption/message to accompany the file"
    )
    filename: str | None = Field(
        default=None,
        description="Optional display filename (defaults to actual filename)"
    )
    channel: str | None = Field(
        default=None,
        description=(
            "Target channel name for cross-channel file sending. "
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


class SendFileTool(BaseBuiltinTool):
    """Tool for agents to send workspace files to users.

    Enables agents to share generated reports, logs, images, or other files
    with users mid-execution. Files must be within the workspace sandbox.

    Examples:
        - "Here's the report you requested" → send_file('reports/daily-summary.pdf')
        - "Generated visualization saved" → send_file('charts/trends.png')
        - "Log file attached for review" → send_file('logs/debug.log')

    The tool requires session context to be set by WorkspaceRunner before use.
    Without context (e.g., in cron/heartbeat), it returns a clean error.

    Files are validated against the workspace sandbox and size limits.
    """

    metadata = BuiltinMetadata(
        name="send_file",
        display_name="Send File",
        description="Send files from workspace to users",
        builtin_type=BuiltinType.TOOL,
        group="communication",
        prerequisites=BuiltinPrerequisite(),
    )

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        # Extract workspace_path from config (injected by loader)
        self.workspace_path = config.get("workspace_path") if config else None
        if self.workspace_path:
            self.workspace_path = Path(self.workspace_path).resolve()
        # Extract max file size from config (defaults to 50MB)
        self.max_file_size = config.get("max_file_size", DEFAULT_MAX_FILE_SIZE) if config else DEFAULT_MAX_FILE_SIZE
        # Registry for cross-channel file sending (channel_name -> ChannelAdapter)
        self._channel_registry: dict[str, Any] = {}
        # Default target IDs per channel (channel_name -> target_id)
        self._channel_targets: dict[str, int] = {}

    def set_channel_registry(
        self,
        channels: dict[str, Any],
        targets: dict[str, int],
    ) -> None:
        """Wire in the full channel registry for cross-channel file sending.

        Called by WorkspaceRunner after channels are set up. Only wired when
        two or more channels are present.

        Args:
            channels: Mapping of channel_name -> ChannelAdapter instance.
            targets: Mapping of channel_name -> default target_id.
        """
        self._channel_registry = channels
        self._channel_targets = targets

    def get_langchain_tool(self) -> Any:
        """Return the send_file tool as a LangChain StructuredTool."""

        # Capture self so closures can access instance attributes without
        # relying on contextvars (which are invisible across LangGraph threads).
        tool_instance = self

        def _resolve_file(file_path: str) -> tuple[bytes, int, str] | str:
            """Validate and read file bytes.

            Returns:
                Tuple of (file_data, file_size, resolved_name) on success, or
                an error string on failure.
            """
            if not tool_instance.workspace_path:
                return "[Error: send_file not available (workspace_path not configured)]"

            try:
                resolved_path = resolve_sandboxed_path(tool_instance.workspace_path, file_path)
            except ValueError as e:
                return f"[Error: Invalid file path: {e}]"

            if not resolved_path.exists():
                return f"[Error: File not found: {file_path}]"

            if not resolved_path.is_file():
                return f"[Error: Path is not a file: {file_path}]"

            try:
                file_data = resolved_path.read_bytes()
            except Exception as e:
                return f"[Error: Failed to read file: {e}]"

            file_size = len(file_data)
            if file_size > tool_instance.max_file_size:
                size_mb = file_size / (1024 * 1024)
                max_mb = tool_instance.max_file_size / (1024 * 1024)
                return f"[Error: File size ({size_mb:.1f} MB) exceeds maximum size of {max_mb:.1f} MB]"

            return (file_data, file_size, resolved_path.name)

        def send_file_sync(
            file_path: str,
            caption: str | None = None,
            filename: str | None = None,
            channel: str | None = None,
            target_id: int | None = None,
        ) -> str:
            """Sync wrapper for send_file (for LangChain compatibility).

            Args:
                file_path: Relative path to file within workspace.
                caption: Optional caption/message.
                filename: Optional display filename override.
                channel: Optional target channel name for cross-channel send.
                target_id: Optional target ID on the remote channel.

            Returns:
                Confirmation message or error.
            """
            if not tool_instance.workspace_path:
                return "[Error: send_file not available (workspace_path not configured)]"

            file_result = _resolve_file(file_path)
            if isinstance(file_result, str):
                return file_result

            file_data, file_size, default_name = file_result
            display_name = filename or default_name
            mime_type, _ = mimetypes.guess_type(display_name)

            if channel is not None:
                # Cross-channel path
                registry = tool_instance._channel_registry
                if not registry:
                    return "[Error: Cross-channel file sending is not available in this context]"

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

                if not hasattr(target_channel, "send_file"):
                    return f"[Error: Channel '{channel}' does not support file sending]"

                session_key = target_channel.build_session_key(str(resolved_target))

                try:
                    try:
                        loop = asyncio.get_running_loop()
                        future = asyncio.run_coroutine_threadsafe(
                            target_channel.send_file(
                                session_key, file_data, display_name, mime_type, caption
                            ),
                            loop,
                        )
                        future.result(timeout=30.0)
                    except RuntimeError:
                        asyncio.run(
                            target_channel.send_file(
                                session_key, file_data, display_name, mime_type, caption
                            )
                        )
                    size_kb = file_size / 1024
                    return f"File sent to {channel}: {display_name} ({size_kb:.1f} KB)"
                except NotImplementedError:
                    return f"[Error: Channel '{channel}' does not support file sending]"
                except Exception as e:
                    logger.error(f"Failed to send file cross-channel: {e}")
                    return f"[Error: Failed to send file to channel '{channel}': {e}]"

            # Default path — current session via contextvars
            ctx_channel, ctx_session_key = get_channel_context()

            if not ctx_channel or not ctx_session_key:
                return "[Error: send_file not available in this context (no active session)]"

            if not hasattr(ctx_channel, "send_file"):
                return "[Error: This channel does not support file sending]"

            try:
                try:
                    loop = asyncio.get_running_loop()
                    future = asyncio.run_coroutine_threadsafe(
                        ctx_channel.send_file(
                            ctx_session_key,
                            file_data,
                            display_name,
                            mime_type,
                            caption,
                        ),
                        loop
                    )
                    future.result(timeout=30.0)
                except RuntimeError:
                    # No running loop - safe to use asyncio.run
                    asyncio.run(
                        ctx_channel.send_file(
                            ctx_session_key,
                            file_data,
                            display_name,
                            mime_type,
                            caption,
                        )
                    )

                size_kb = file_size / 1024
                return f"File sent: {display_name} ({size_kb:.1f} KB)"
            except NotImplementedError:
                return "[Error: This channel does not support file sending]"
            except Exception as e:
                logger.error(f"Failed to send file: {e}")
                return f"[Error: Failed to send file: {e}]"

        async def send_file_async(
            file_path: str,
            caption: str | None = None,
            filename: str | None = None,
            channel: str | None = None,
            target_id: int | None = None,
        ) -> str:
            """Send a file from the workspace to the user.

            Args:
                file_path: Relative path to file within workspace.
                caption: Optional caption/message.
                filename: Optional display filename override.
                channel: Optional target channel name for cross-channel send.
                target_id: Optional target ID on the remote channel.

            Returns:
                Confirmation message or error.
            """
            if not tool_instance.workspace_path:
                return "[Error: send_file not available (workspace_path not configured)]"

            file_result = _resolve_file(file_path)
            if isinstance(file_result, str):
                return file_result

            file_data, file_size, default_name = file_result
            display_name = filename or default_name
            mime_type, _ = mimetypes.guess_type(display_name)

            if channel is not None:
                # Cross-channel path
                registry = tool_instance._channel_registry
                if not registry:
                    return "[Error: Cross-channel file sending is not available in this context]"

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

                if not hasattr(target_channel, "send_file"):
                    return f"[Error: Channel '{channel}' does not support file sending]"

                session_key = target_channel.build_session_key(str(resolved_target))

                try:
                    await target_channel.send_file(
                        session_key, file_data, display_name, mime_type, caption
                    )
                    logger.info(
                        f"Sent file '{display_name}' to {channel}:{resolved_target}"
                    )
                    size_kb = file_size / 1024
                    return f"File sent to {channel}: {display_name} ({size_kb:.1f} KB)"
                except NotImplementedError:
                    return f"[Error: Channel '{channel}' does not support file sending]"
                except Exception as e:
                    logger.error(f"Failed to send file cross-channel: {e}")
                    return f"[Error: Failed to send file to channel '{channel}': {e}]"

            # Default path — current session via contextvars
            ctx_channel, ctx_session_key = get_channel_context()

            if not ctx_channel or not ctx_session_key:
                return "[Error: send_file not available in this context (no active session)]"

            if not hasattr(ctx_channel, "send_file"):
                return "[Error: This channel does not support file sending]"

            try:
                await ctx_channel.send_file(
                    ctx_session_key,
                    file_data,
                    display_name,
                    mime_type,
                    caption,
                )
                logger.info(f"Sent file '{display_name}' to {ctx_session_key}")
                size_kb = file_size / 1024
                return f"File sent: {display_name} ({size_kb:.1f} KB)"
            except NotImplementedError:
                return "[Error: This channel does not support file sending]"
            except Exception as e:
                logger.error(f"Failed to send file: {e}")
                return f"[Error: Failed to send file: {e}]"

        return StructuredTool.from_function(
            func=send_file_sync,
            coroutine=send_file_async,
            name="send_file",
            description=(
                "Send a file from your workspace to the user. "
                "Use this to share generated reports, logs, images, charts, or any "
                "other files you've created or have access to in your workspace. "
                "The file must exist within your workspace directory. "
                "You can optionally include a caption to explain what the file contains."
            ),
            args_schema=SendFileInput,
        )
