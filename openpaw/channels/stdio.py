"""Stdio channel adapter for local CLI testing."""

import asyncio
import base64
import logging
import os
import sys
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from openpaw.channels.base import ChannelAdapter
from openpaw.model.channel import ChannelEvent
from openpaw.model.message import Attachment, Message, MessageDirection

logger = logging.getLogger(__name__)


class StdioChannel(ChannelAdapter):
    """Stdio channel adapter for local CLI testing.

    Reads lines from stdin and prints agent responses to stdout.
    Supports file path detection, message splitting, and approval gates.
    """

    name = "stdio"
    MAX_MESSAGE_LENGTH = 2000

    def __init__(self, workspace_name: str = "unknown") -> None:
        """Initialize the stdio channel.

        Args:
            workspace_name: Workspace name for error messages.
        """
        self.workspace_name = workspace_name
        self._running = False
        self._reader_task: asyncio.Task[None] | None = None
        self._message_callback: Callable[[Message], Coroutine[Any, Any, None]] | None = None
        self._approval_callback: Callable[[str, bool], Coroutine[Any, Any, None]] | None = None
        self._channel_event_callback: Callable[[ChannelEvent], Coroutine[Any, Any, None]] | None = None
        self._pending_approval_id: str | None = None

    async def start(self) -> None:
        """Start the async stdin reader loop."""
        self._running = True
        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info("Stdio channel started")

    async def stop(self) -> None:
        """Stop the stdin reader loop gracefully."""
        self._running = False
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        logger.info("Stdio channel stopped")

    async def _read_loop(self) -> None:
        """Read lines from stdin and dispatch messages."""
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Stdio read error", exc_info=True)
                break

            if not line:
                # EOF reached
                break

            line = line.rstrip("\n")
            if not line:
                # Empty line signals shutdown
                break

            # Check for approval response first
            if self._pending_approval_id is not None and self._approval_callback is not None:
                lower = line.strip().lower()
                if lower in ("y", "yes"):
                    approval_id = self._pending_approval_id
                    self._pending_approval_id = None
                    try:
                        await self._approval_callback(approval_id, True)
                    except Exception:
                        logger.debug("Approval callback error", exc_info=True)
                    continue
                elif lower in ("n", "no"):
                    approval_id = self._pending_approval_id
                    self._pending_approval_id = None
                    try:
                        await self._approval_callback(approval_id, False)
                    except Exception:
                        logger.debug("Approval callback error", exc_info=True)
                    continue

            # Normal message processing
            message = self._line_to_message(line)
            if message and self._message_callback is not None:
                try:
                    await self._message_callback(message)
                except Exception:
                    logger.debug("Message callback error", exc_info=True)

        self._running = False

    def _line_to_message(self, line: str) -> Message | None:
        """Convert a stdin line to a unified Message."""
        content = line
        attachments: list[Attachment] = []

        # Detect file paths
        file_path = self._detect_file_path(line)
        if file_path and os.path.isfile(file_path):
            try:
                with open(file_path, "rb") as f:
                    data = f.read()
                filename = os.path.basename(file_path)
                mime_type = self._guess_mime_type(filename)
                attachments.append(
                    Attachment(
                        type="document",
                        data=data,
                        filename=filename,
                        mime_type=mime_type,
                        metadata={"file_path": file_path},
                    )
                )
                content = f"[File: {filename}]"
            except Exception:
                logger.debug("Failed to read file %s", file_path, exc_info=True)

        return Message(
            id=f"stdio_{datetime.now(UTC).timestamp()}",
            channel=self.name,
            session_key=self.build_session_key("local_user"),
            user_id="local_user",
            content=content,
            direction=MessageDirection.INBOUND,
            timestamp=datetime.now(UTC),
            attachments=attachments,
        )

    def _detect_file_path(self, line: str) -> str | None:
        """Detect if a line looks like a file path."""
        stripped = line.strip()
        # Path-like prefixes
        if stripped.startswith(("/", "./", "~/")):
            return stripped
        if len(stripped) > 2 and stripped[1:3] == ":\\":
            # Windows drive letter path
            return stripped
        # Known extensions
        known_exts = (".py", ".md", ".txt", ".pdf")
        if stripped.lower().endswith(known_exts):
            return stripped
        return None

    def _guess_mime_type(self, filename: str) -> str | None:
        """Rough MIME type guess from filename extension."""
        ext = os.path.splitext(filename)[1].lower()
        mapping = {
            ".py": "text/x-python",
            ".md": "text/markdown",
            ".txt": "text/plain",
            ".pdf": "application/pdf",
        }
        return mapping.get(ext)

    def on_message(self, callback: Callable[[Message], Coroutine[Any, Any, None]]) -> None:
        """Register a callback for incoming messages."""
        self._message_callback = callback

    async def send_message(self, session_key: str, content: str, **kwargs: Any) -> Message:
        """Send a message to stdout.

        Automatically splits messages that exceed the character limit.
        """
        chunks = self._split_message(content)
        for i, chunk in enumerate(chunks):
            if i > 0:
                print("--- (continued) ---")
            print(f"[agent]: {chunk}")

        return Message(
            id=f"stdio_out_{datetime.now(UTC).timestamp()}",
            channel=self.name,
            session_key=session_key,
            user_id="agent",
            content=content,
            direction=MessageDirection.OUTBOUND,
            timestamp=datetime.now(UTC),
        )

    def _split_message(self, text: str) -> list[str]:
        """Split text into chunks that fit the message limit.

        Tries to break at paragraph boundaries (double newline), falls back
        to single newlines, then hard-splits as a last resort.
        """
        if len(text) <= self.MAX_MESSAGE_LENGTH:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= self.MAX_MESSAGE_LENGTH:
                chunks.append(remaining)
                break

            split_at = remaining.rfind("\n\n", 0, self.MAX_MESSAGE_LENGTH)

            if split_at == -1:
                split_at = remaining.rfind("\n", 0, self.MAX_MESSAGE_LENGTH)

            if split_at == -1:
                split_at = self.MAX_MESSAGE_LENGTH

            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

        return chunks

    def on_approval(
        self, callback: Callable[[str, bool], Coroutine[Any, Any, None]]
    ) -> None:
        """Register a callback for approval resolutions."""
        self._approval_callback = callback

    async def send_approval_request(
        self,
        session_key: str,
        approval_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        show_args: bool = True,
    ) -> None:
        """Send an approval request to stdout."""
        self._pending_approval_id = approval_id
        message = f"🔒 Approval Required: {tool_name}\n"
        if show_args and tool_args:
            args_str = str(tool_args)
            if len(args_str) > 500:
                args_str = args_str[:500] + "..."
            message += f"Args: {args_str}\n"
        message += "Approve? [y/n]: "
        print(message, end="", flush=True)

    async def send_file(
        self,
        session_key: str,
        file_data: bytes,
        filename: str,
        mime_type: str | None = None,
        caption: str | None = None,
    ) -> None:
        """Acknowledge a file send on stdout."""
        b64 = base64.b64encode(file_data).decode("utf-8")
        print(f"[agent]: Sending file '{filename}' ({len(file_data)} bytes)")
        if caption:
            print(f"[agent]: {caption}")
        # Print truncated base64 so stdout isn't flooded
        print(f"[agent]: Base64: {b64[:100]}...")
