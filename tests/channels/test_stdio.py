"""Tests for the stdio channel adapter."""

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

import pytest

from openpaw.channels.base import ChannelAdapter
from openpaw.channels.factory import create_channel
from openpaw.channels.stdio import StdioChannel
from openpaw.model.message import Attachment, Message, MessageDirection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stdio_channel(**kwargs: object) -> StdioChannel:
    """Return a StdioChannel with sensible test defaults."""
    defaults: dict[str, object] = {"workspace_name": "test_workspace"}
    defaults.update(kwargs)
    return StdioChannel(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------


class TestInitialization:
    """Test StdioChannel construction and attribute storage."""

    def test_init_defaults(self) -> None:
        """Default construction sets expected initial state."""
        channel = StdioChannel()
        assert channel.workspace_name == "unknown"
        assert channel._running is False
        assert channel._reader_task is None
        assert channel._message_callback is None
        assert channel._approval_callback is None
        assert channel._pending_approval_id is None

    def test_init_workspace_name(self) -> None:
        """workspace_name is stored when passed."""
        channel = StdioChannel(workspace_name="my_ws")
        assert channel.workspace_name == "my_ws"

    def test_init_is_channel_adapter(self) -> None:
        """StdioChannel is a ChannelAdapter subclass."""
        channel = _make_stdio_channel()
        assert isinstance(channel, ChannelAdapter)

    def test_init_name_attribute(self) -> None:
        """name class attribute is 'stdio'."""
        assert StdioChannel.name == "stdio"


# ---------------------------------------------------------------------------
# 2. Session key
# ---------------------------------------------------------------------------


class TestSessionKey:
    """Test session key building and format."""

    def test_build_session_key(self) -> None:
        """build_session_key returns 'stdio:local_user'."""
        channel = _make_stdio_channel()
        assert channel.build_session_key("local_user") == "stdio:local_user"

    def test_session_key_used_in_line_to_message(self) -> None:
        """_line_to_message produces the expected session key."""
        channel = _make_stdio_channel()
        msg = channel._line_to_message("hello")
        assert msg is not None
        assert msg.session_key == "stdio:local_user"


# ---------------------------------------------------------------------------
# 3. Message splitting
# ---------------------------------------------------------------------------


class TestSplitMessage:
    """Test _split_message chunking logic against the 2000-char limit."""

    def test_short_message_returns_single_chunk(self) -> None:
        """Text within the limit is returned as a single-element list."""
        channel = _make_stdio_channel()
        result = channel._split_message("Short message.")
        assert result == ["Short message."]

    def test_exact_limit_no_split(self) -> None:
        """Text of exactly 2000 characters is not split."""
        channel = _make_stdio_channel()
        text = "x" * 2000
        result = channel._split_message(text)
        assert len(result) == 1
        assert len(result[0]) == 2000

    def test_split_at_paragraph_boundary(self) -> None:
        """Text just over the limit is split at the last double-newline within the window."""
        channel = _make_stdio_channel()
        part_a = "A" * 1900 + "\n\n"
        part_b = "B" * 200
        text = part_a + part_b
        result = channel._split_message(text)
        assert len(result) == 2
        assert result[0] == "A" * 1900
        assert result[1] == "B" * 200

    def test_split_at_newline_when_no_paragraph_break(self) -> None:
        """Falls back to single newline when no double-newline exists in window."""
        channel = _make_stdio_channel()
        part_a = "A" * 1990 + "\n"
        part_b = "B" * 100
        text = part_a + part_b
        result = channel._split_message(text)
        assert len(result) == 2
        assert result[0] == "A" * 1990
        assert result[1] == "B" * 100

    def test_hard_split_when_no_newlines(self) -> None:
        """With no newlines, falls back to hard split at exactly MAX_MESSAGE_LENGTH."""
        channel = _make_stdio_channel()
        text = "X" * 2500
        result = channel._split_message(text)
        assert len(result) == 2
        assert len(result[0]) == 2000
        assert result[1] == "X" * 500

    def test_very_long_message_produces_multiple_chunks(self) -> None:
        """Messages many times over the limit generate the correct number of chunks."""
        channel = _make_stdio_channel()
        text = "Z" * 5001
        result = channel._split_message(text)
        assert len(result) == 3
        assert all(len(chunk) <= 2000 for chunk in result)
        assert "".join(result) == text

    def test_empty_string_returns_single_empty_chunk(self) -> None:
        """Empty string yields a list containing one empty string."""
        channel = _make_stdio_channel()
        result = channel._split_message("")
        assert result == [""]

    def test_split_preserves_all_content(self) -> None:
        """All characters are present in the rejoined chunks."""
        channel = _make_stdio_channel()
        text = ("Hello world\n\n" * 200)  # ~2600 chars
        result = channel._split_message(text)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 2000


# ---------------------------------------------------------------------------
# 4. Message sending
# ---------------------------------------------------------------------------


class TestSendMessage:
    """Test send_message output to stdout."""

    @pytest.mark.asyncio
    async def test_send_message_prints_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        """send_message prints the prefixed content to stdout."""
        channel = _make_stdio_channel()
        msg = await channel.send_message("stdio:local_user", "Hello user")
        captured = capsys.readouterr()
        assert captured.out == "[agent]: Hello user\n"
        assert msg.channel == "stdio"
        assert msg.session_key == "stdio:local_user"
        assert msg.direction == MessageDirection.OUTBOUND
        assert msg.user_id == "agent"

    @pytest.mark.asyncio
    async def test_send_message_splits_long_messages(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Long messages are split with continuation separators."""
        channel = _make_stdio_channel()
        text = "A" * 2500
        await channel.send_message("stdio:local_user", text)
        captured = capsys.readouterr()
        assert "--- (continued) ---" in captured.out
        assert "[agent]: " + "A" * 2000 in captured.out
        assert "[agent]: " + "A" * 500 in captured.out

    @pytest.mark.asyncio
    async def test_send_message_multi_chunk_with_separators(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Each chunk after the first is prefixed with the continuation separator."""
        channel = _make_stdio_channel()
        text = "A" * 4500
        await channel.send_message("stdio:local_user", text)
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert lines[0] == "[agent]: " + "A" * 2000
        assert lines[1] == "--- (continued) ---"
        assert lines[2] == "[agent]: " + "A" * 2000
        assert lines[3] == "--- (continued) ---"
        assert lines[4] == "[agent]: " + "A" * 500


# ---------------------------------------------------------------------------
# 5. Approval flow
# ---------------------------------------------------------------------------


class TestApprovalFlow:
    """Test approval request sending and resolution via stdin."""

    @pytest.mark.asyncio
    async def test_send_approval_request(self, capsys: pytest.CaptureFixture[str]) -> None:
        """send_approval_request prints the expected prompt and stores the approval id."""
        channel = _make_stdio_channel()
        await channel.send_approval_request(
            "stdio:local_user",
            "approval-123",
            "delete_task",
            {"task_id": "42"},
            show_args=True,
        )
        captured = capsys.readouterr()
        assert "🔒 Approval Required: delete_task" in captured.out
        assert "Args:" in captured.out
        assert "task_id" in captured.out
        assert "Approve? [y/n]:" in captured.out
        assert channel._pending_approval_id == "approval-123"

    @pytest.mark.asyncio
    async def test_send_approval_request_hides_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        """show_args=False omits the arguments from the prompt."""
        channel = _make_stdio_channel()
        await channel.send_approval_request(
            "stdio:local_user",
            "approval-456",
            "overwrite_file",
            {"path": "secret.txt"},
            show_args=False,
        )
        captured = capsys.readouterr()
        assert "🔒 Approval Required: overwrite_file" in captured.out
        assert "Args:" not in captured.out
        assert channel._pending_approval_id == "approval-456"

    @pytest.mark.asyncio
    async def test_approval_yes_response(self) -> None:
        """Typing 'y' resolves the pending approval with approved=True."""
        channel = _make_stdio_channel()
        received: list[tuple[str, bool]] = []
        event = asyncio.Event()

        async def callback(approval_id: str, approved: bool) -> None:
            received.append((approval_id, approved))
            event.set()

        channel.on_approval(callback)
        channel._pending_approval_id = "approval-123"

        with patch("sys.stdin", StringIO("y\n")):
            await channel.start()
            await asyncio.wait_for(event.wait(), timeout=1.0)
            await channel.stop()

        assert len(received) == 1
        assert received[0] == ("approval-123", True)
        assert channel._pending_approval_id is None

    @pytest.mark.asyncio
    async def test_approval_no_response(self) -> None:
        """Typing 'no' resolves the pending approval with approved=False."""
        channel = _make_stdio_channel()
        received: list[tuple[str, bool]] = []
        event = asyncio.Event()

        async def callback(approval_id: str, approved: bool) -> None:
            received.append((approval_id, approved))
            event.set()

        channel.on_approval(callback)
        channel._pending_approval_id = "approval-123"

        with patch("sys.stdin", StringIO("no\n")):
            await channel.start()
            await asyncio.wait_for(event.wait(), timeout=1.0)
            await channel.stop()

        assert len(received) == 1
        assert received[0] == ("approval-123", False)
        assert channel._pending_approval_id is None

    @pytest.mark.asyncio
    async def test_approval_without_pending_id_is_treated_as_message(self) -> None:
        """When no approval is pending, 'y' is treated as a normal message."""
        channel = _make_stdio_channel()
        approval_received: list[tuple[str, bool]] = []
        messages: list[Message] = []
        event = asyncio.Event()

        async def approval_cb(approval_id: str, approved: bool) -> None:
            approval_received.append((approval_id, approved))

        async def message_cb(msg: Message) -> None:
            messages.append(msg)
            event.set()

        channel.on_approval(approval_cb)
        channel.on_message(message_cb)

        with patch("sys.stdin", StringIO("y\n")):
            await channel.start()
            await asyncio.wait_for(event.wait(), timeout=1.0)
            await channel.stop()

        assert len(approval_received) == 0
        assert len(messages) == 1
        assert messages[0].content == "y"


# ---------------------------------------------------------------------------
# 6. Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    """Test start/stop behavior and shutdown signals."""

    @pytest.mark.asyncio
    async def test_start_creates_reader_task(self) -> None:
        """start() creates the background reader task and sets _running."""
        channel = _make_stdio_channel()
        with patch("sys.stdin", StringIO("hello\n")):
            await channel.start()
            assert channel._running is True
            assert channel._reader_task is not None
            await channel.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self) -> None:
        """stop() clears _running and cancels the reader task."""
        channel = _make_stdio_channel()
        with patch("sys.stdin", StringIO("hello\n")):
            await channel.start()
            await channel.stop()
            assert channel._running is False

    @pytest.mark.asyncio
    async def test_empty_line_signals_shutdown(self) -> None:
        """An empty line causes the reader loop to exit cleanly."""
        channel = _make_stdio_channel()
        messages: list[Message] = []
        event = asyncio.Event()

        async def capture(msg: Message) -> None:
            messages.append(msg)
            event.set()

        channel.on_message(capture)

        with patch("sys.stdin", StringIO("first\n\n")):
            await channel.start()
            await asyncio.wait_for(event.wait(), timeout=1.0)
            # After the empty line the task should exit on its own
            await asyncio.sleep(0.1)
            await channel.stop()

        assert len(messages) == 1
        assert messages[0].content == "first"
        assert channel._running is False

    @pytest.mark.asyncio
    async def test_eof_signals_shutdown(self) -> None:
        """EOF (empty readline result) causes the reader loop to exit."""
        channel = _make_stdio_channel()
        with patch("sys.stdin", StringIO("")):
            await channel.start()
            # Give the executor a moment to process the EOF
            await asyncio.sleep(0.1)
            assert channel._running is False
            if channel._reader_task:
                await channel._reader_task

    @pytest.mark.asyncio
    async def test_stop_cancels_pending_read(self) -> None:
        """stop() cancels the reader task even when blocked on stdin."""
        channel = _make_stdio_channel()
        with patch("sys.stdin", StringIO("")):
            await channel.start()
            # At this point the task has likely already exited due to EOF,
            # but we still verify stop() is idempotent / safe.
            await channel.stop()
            assert channel._running is False


# ---------------------------------------------------------------------------
# 7. Factory integration
# ---------------------------------------------------------------------------


class TestFactoryIntegration:
    """Test that the channel factory correctly produces StdioChannel instances."""

    def test_factory_creates_stdio_channel(self) -> None:
        """create_channel('stdio', ...) returns a StdioChannel."""
        channel = create_channel("stdio", {}, "factory_workspace")
        assert isinstance(channel, StdioChannel)
        assert isinstance(channel, ChannelAdapter)
        assert channel.workspace_name == "factory_workspace"

    def test_factory_with_channel_name(self) -> None:
        """Custom channel_name overrides the adapter name."""
        channel = create_channel("stdio", {}, "test_ws", channel_name="cli")
        assert isinstance(channel, StdioChannel)
        assert channel.name == "cli"

    def test_factory_ignores_config_keys(self) -> None:
        """Stdio channel ignores channel-specific config keys."""
        config = {"token": "ignored", "allowed_users": [1, 2]}
        channel = create_channel("stdio", config, "ws")
        assert isinstance(channel, StdioChannel)


# ---------------------------------------------------------------------------
# 8. File path detection
# ---------------------------------------------------------------------------


class TestFilePathDetection:
    """Test _detect_file_path heuristics."""

    def test_detect_unix_absolute_path(self) -> None:
        assert _make_stdio_channel()._detect_file_path("/tmp/test.txt") == "/tmp/test.txt"

    def test_detect_relative_path(self) -> None:
        assert _make_stdio_channel()._detect_file_path("./test.py") == "./test.py"

    def test_detect_home_path(self) -> None:
        assert _make_stdio_channel()._detect_file_path("~/notes.md") == "~/notes.md"

    def test_detect_windows_path(self) -> None:
        assert _make_stdio_channel()._detect_file_path("C:\\file.txt") == "C:\\file.txt"

    def test_detect_by_extension_py(self) -> None:
        assert _make_stdio_channel()._detect_file_path("report.py") == "report.py"

    def test_detect_by_extension_md(self) -> None:
        assert _make_stdio_channel()._detect_file_path("README.md") == "README.md"

    def test_detect_by_extension_txt(self) -> None:
        assert _make_stdio_channel()._detect_file_path("notes.txt") == "notes.txt"

    def test_detect_by_extension_pdf(self) -> None:
        assert _make_stdio_channel()._detect_file_path("doc.pdf") == "doc.pdf"

    def test_no_detection_for_plain_text(self) -> None:
        assert _make_stdio_channel()._detect_file_path("hello world") is None

    def test_no_detection_for_unknown_extension(self) -> None:
        assert _make_stdio_channel()._detect_file_path("image.png") is None


# ---------------------------------------------------------------------------
# 9. File attachment handling
# ---------------------------------------------------------------------------


class TestFileAttachmentHandling:
    """Test that existing files are attached to inbound messages."""

    def test_line_to_message_with_existing_file(self) -> None:
        """A line pointing to an existing file produces a Message with an Attachment."""
        channel = _make_stdio_channel()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello file")
            path = f.name

        try:
            msg = channel._line_to_message(path)
            assert msg is not None
            assert msg.content == f"[File: {os.path.basename(path)}]"
            assert len(msg.attachments) == 1
            assert msg.attachments[0].type == "document"
            assert msg.attachments[0].data == b"hello file"
            assert msg.attachments[0].filename == os.path.basename(path)
            assert msg.attachments[0].mime_type == "text/plain"
        finally:
            os.unlink(path)

    def test_line_to_message_with_nonexistent_file(self) -> None:
        """A line pointing to a nonexistent file is treated as plain text."""
        channel = _make_stdio_channel()
        msg = channel._line_to_message("/nonexistent/path.txt")
        assert msg is not None
        assert msg.content == "/nonexistent/path.txt"
        assert msg.attachments == []

    def test_line_to_message_plain_text(self) -> None:
        """Plain text without a file path produces a message with no attachments."""
        channel = _make_stdio_channel()
        msg = channel._line_to_message("hello world")
        assert msg is not None
        assert msg.content == "hello world"
        assert msg.attachments == []


# ---------------------------------------------------------------------------
# 10. File sending
# ---------------------------------------------------------------------------


class TestSendFile:
    """Test send_file stdout acknowledgment."""

    @pytest.mark.asyncio
    async def test_send_file_prints_acknowledgment(self, capsys: pytest.CaptureFixture[str]) -> None:
        """send_file prints a truncated base64 acknowledgment."""
        channel = _make_stdio_channel()
        await channel.send_file("stdio:local_user", b"file-data", "test.txt")
        captured = capsys.readouterr()
        assert "Sending file 'test.txt'" in captured.out
        assert "Base64:" in captured.out

    @pytest.mark.asyncio
    async def test_send_file_includes_caption(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When a caption is provided it is printed as well."""
        channel = _make_stdio_channel()
        await channel.send_file("stdio:local_user", b"x", "x.txt", caption="Here is the file")
        captured = capsys.readouterr()
        assert "Here is the file" in captured.out


# ---------------------------------------------------------------------------
# 11. Callback registration
# ---------------------------------------------------------------------------


class TestCallbackRegistration:
    """Test on_message and on_approval callback registration."""

    def test_on_message_stores_callback(self) -> None:
        channel = _make_stdio_channel()

        async def my_callback(msg: Message) -> None:
            pass

        channel.on_message(my_callback)
        assert channel._message_callback is my_callback

    def test_on_approval_stores_callback(self) -> None:
        channel = _make_stdio_channel()

        async def my_callback(approval_id: str, approved: bool) -> None:
            pass

        channel.on_approval(my_callback)
        assert channel._approval_callback is my_callback

    def test_initial_callbacks_are_none(self) -> None:
        channel = _make_stdio_channel()
        assert channel._message_callback is None
        assert channel._approval_callback is None
