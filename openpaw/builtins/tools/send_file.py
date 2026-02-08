"""Send file builtin for agent-to-user file transfers."""

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from openpaw.builtins.base import (
    BaseBuiltinTool,
    BuiltinMetadata,
    BuiltinPrerequisite,
    BuiltinType,
)
from openpaw.builtins.tools._channel_context import get_channel_context
from openpaw.tools.sandbox import resolve_sandboxed_path

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

    def get_langchain_tool(self) -> Any:
        """Return the send_file tool as a LangChain StructuredTool."""

        def send_file_sync(
            file_path: str,
            caption: str | None = None,
            filename: str | None = None,
        ) -> str:
            """Sync wrapper for send_file (for LangChain compatibility).

            Args:
                file_path: Relative path to file within workspace.
                caption: Optional caption/message.
                filename: Optional display filename override.

            Returns:
                Confirmation message or error.
            """
            if not self.workspace_path:
                return "[Error: send_file not available (workspace_path not configured)]"

            channel, session_key = get_channel_context()

            if not channel or not session_key:
                return "[Error: send_file not available in this context (no active session)]"

            try:
                # Validate and resolve file path
                try:
                    resolved_path = resolve_sandboxed_path(self.workspace_path, file_path)
                except ValueError as e:
                    return f"[Error: Invalid file path: {e}]"

                # Check file exists
                if not resolved_path.exists():
                    return f"[Error: File not found: {file_path}]"

                if not resolved_path.is_file():
                    return f"[Error: Path is not a file: {file_path}]"

                # Read file bytes
                try:
                    file_data = resolved_path.read_bytes()
                except Exception as e:
                    return f"[Error: Failed to read file: {e}]"

                # Check file size
                file_size = len(file_data)
                if file_size > self.max_file_size:
                    size_mb = file_size / (1024 * 1024)
                    max_mb = self.max_file_size / (1024 * 1024)
                    return f"[Error: File size ({size_mb:.1f} MB) exceeds maximum size of {max_mb:.1f} MB]"

                # Determine display filename
                display_name = filename or resolved_path.name

                # Infer MIME type
                mime_type, _ = mimetypes.guess_type(display_name)

                # Check if channel supports file sending
                if not hasattr(channel, "send_file"):
                    return "[Error: This channel does not support file sending]"

                # Send file via channel
                try:
                    try:
                        loop = asyncio.get_running_loop()
                        future = asyncio.run_coroutine_threadsafe(
                            channel.send_file(
                                session_key,
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
                            channel.send_file(
                                session_key,
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

            except Exception as e:
                logger.error(f"Unexpected error in send_file: {e}")
                return f"[Error: Unexpected error: {e}]"

        async def send_file_async(
            file_path: str,
            caption: str | None = None,
            filename: str | None = None,
        ) -> str:
            """Send a file from the workspace to the user.

            Args:
                file_path: Relative path to file within workspace.
                caption: Optional caption/message.
                filename: Optional display filename override.

            Returns:
                Confirmation message or error.
            """
            if not self.workspace_path:
                return "[Error: send_file not available (workspace_path not configured)]"

            channel, session_key = get_channel_context()

            if not channel or not session_key:
                return "[Error: send_file not available in this context (no active session)]"

            try:
                # Validate and resolve file path
                try:
                    resolved_path = resolve_sandboxed_path(self.workspace_path, file_path)
                except ValueError as e:
                    return f"[Error: Invalid file path: {e}]"

                # Check file exists
                if not resolved_path.exists():
                    return f"[Error: File not found: {file_path}]"

                if not resolved_path.is_file():
                    return f"[Error: Path is not a file: {file_path}]"

                # Read file bytes
                try:
                    file_data = resolved_path.read_bytes()
                except Exception as e:
                    return f"[Error: Failed to read file: {e}]"

                # Check file size
                file_size = len(file_data)
                if file_size > self.max_file_size:
                    size_mb = file_size / (1024 * 1024)
                    max_mb = self.max_file_size / (1024 * 1024)
                    return f"[Error: File size ({size_mb:.1f} MB) exceeds maximum size of {max_mb:.1f} MB]"

                # Determine display filename
                display_name = filename or resolved_path.name

                # Infer MIME type
                mime_type, _ = mimetypes.guess_type(display_name)

                # Check if channel supports file sending
                if not hasattr(channel, "send_file"):
                    return "[Error: This channel does not support file sending]"

                # Send file via channel
                try:
                    await channel.send_file(
                        session_key,
                        file_data,
                        display_name,
                        mime_type,
                        caption,
                    )
                    logger.info(f"Sent file '{display_name}' to {session_key}")
                    size_kb = file_size / 1024
                    return f"File sent: {display_name} ({size_kb:.1f} KB)"
                except NotImplementedError:
                    return "[Error: This channel does not support file sending]"
                except Exception as e:
                    logger.error(f"Failed to send file: {e}")
                    return f"[Error: Failed to send file: {e}]"

            except Exception as e:
                logger.error(f"Unexpected error in send_file: {e}")
                return f"[Error: Unexpected error: {e}]"

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
