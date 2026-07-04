"""Tests for command handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openpaw.channels.commands.base import CommandContext
from openpaw.channels.commands.handlers import (
    CompactCommand,
    HelpCommand,
    NewCommand,
    QueueModeCommand,
    StartCommand,
    StatusCommand,
)
from openpaw.core.config.models import AutoCompactConfig
from openpaw.model.message import Message
from openpaw.model.session import SessionState
from openpaw.runtime.queue.lane import QueueMode


@pytest.fixture
def mock_message():
    """Create a mock message."""
    msg = MagicMock(spec=Message)
    msg.session_key = "telegram:123456"
    msg.content = "/test"
    msg.channel = "telegram"
    msg.is_command = True
    return msg


@pytest.fixture
def mock_context(tmp_path):
    """Create a mock command context."""
    context = MagicMock(spec=CommandContext)
    context.workspace_name = "test-workspace"
    context.workspace_path = tmp_path
    context.channel = AsyncMock()
    context.session_manager = MagicMock()
    context.queue_manager = AsyncMock()
    context.agent_runner = MagicMock()
    context.agent_runner.model_id = "anthropic:claude-sonnet-4-20250514"
    context.command_router = MagicMock()
    context.checkpointer = AsyncMock()
    context.conversation_archiver = AsyncMock()
    # Flush-before-compact disabled so legacy /compact tests exercise the
    # unchanged two-turn path; flush behavior is tested explicitly below.
    context.auto_compact_config = AutoCompactConfig(flush=False)
    return context


class TestStartCommand:
    """Tests for StartCommand."""

    @pytest.mark.asyncio
    async def test_start_command(self, mock_message, mock_context):
        """Test /start command returns welcome message."""
        handler = StartCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.handled is True
        assert "OpenPaw agent" in result.response
        assert "test-workspace" in result.response
        assert "/help" in result.response
        assert result.new_thread_id is None

    def test_start_definition(self):
        """Test start command definition."""
        handler = StartCommand()
        definition = handler.definition

        assert definition.name == "start"
        assert definition.hidden is True
        assert definition.bypass_queue is False


class TestNewCommand:
    """Tests for NewCommand."""

    @pytest.mark.asyncio
    async def test_new_command(self, mock_message, mock_context):
        """Test /new command creates new conversation and archives the old one."""
        old_conv_id = "conv_2026-02-07T14-30-00-123456"
        old_thread_id = "telegram:123456:conv_2026-02-07T14-30-00-123456"
        new_thread_id = "telegram:123456:conv_2026-02-07T14-35-00-789012"

        # Mock session state for old conversation
        mock_state = MagicMock()
        mock_state.conversation_id = old_conv_id
        mock_context.session_manager.get_state.return_value = mock_state
        mock_context.session_manager.get_thread_id.side_effect = [old_thread_id, new_thread_id]
        mock_context.session_manager.new_conversation.return_value = old_conv_id

        # Mock successful archiving
        mock_archive = MagicMock()
        mock_archive.message_count = 10
        mock_context.conversation_archiver.archive.return_value = mock_archive

        handler = NewCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.handled is True
        assert old_conv_id in result.response
        assert "New conversation started" in result.response
        assert "archived" in result.response.lower()
        assert result.new_thread_id == new_thread_id

        # Verify archiver was called with correct parameters
        mock_context.conversation_archiver.archive.assert_called_once_with(
            checkpointer=mock_context.checkpointer,
            thread_id=old_thread_id,
            session_key="telegram:123456",
            conversation_id=old_conv_id,
            tags=["manual"],
        )

        # Verify new conversation was created
        mock_context.session_manager.new_conversation.assert_called_once_with(
            "telegram:123456"
        )

    def test_new_definition(self):
        """Test new command definition."""
        handler = NewCommand()
        definition = handler.definition

        assert definition.name == "new"
        assert definition.bypass_queue is True
        assert definition.hidden is False


class TestQueueModeCommand:
    """Tests for QueueModeCommand."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "mode_str,expected_mode",
        [
            ("collect", QueueMode.COLLECT),
            ("steer", QueueMode.STEER),
            ("followup", QueueMode.FOLLOWUP),
            ("interrupt", QueueMode.INTERRUPT),
            ("default", QueueMode.COLLECT),
            ("reset", QueueMode.COLLECT),
        ],
    )
    async def test_queue_mode_valid(
        self, mock_message, mock_context, mode_str, expected_mode
    ):
        """Test /queue command with valid modes."""
        handler = QueueModeCommand()
        result = await handler.handle(mock_message, mode_str, mock_context)

        assert result.handled is True
        assert f"Queue mode set to: {expected_mode.value}" in result.response
        assert result.new_thread_id is None

        mock_context.queue_manager.set_session_mode.assert_called_once_with(
            "telegram:123456", expected_mode
        )

    @pytest.mark.asyncio
    async def test_queue_mode_invalid(self, mock_message, mock_context):
        """Test /queue command with invalid mode."""
        handler = QueueModeCommand()
        result = await handler.handle(mock_message, "invalid", mock_context)

        assert result.handled is True
        assert "Unknown mode: invalid" in result.response
        assert "Valid modes:" in result.response
        assert result.new_thread_id is None

        mock_context.queue_manager.set_session_mode.assert_not_called()

    @pytest.mark.asyncio
    async def test_queue_mode_case_insensitive(self, mock_message, mock_context):
        """Test /queue command is case-insensitive."""
        handler = QueueModeCommand()
        result = await handler.handle(mock_message, "COLLECT", mock_context)

        assert result.handled is True
        assert "Queue mode set to: collect" in result.response

        mock_context.queue_manager.set_session_mode.assert_called_once_with(
            "telegram:123456", QueueMode.COLLECT
        )

    def test_queue_definition(self):
        """Test queue command definition."""
        handler = QueueModeCommand()
        definition = handler.definition

        assert definition.name == "queue"
        assert definition.args_description == "<mode>"
        assert definition.bypass_queue is False


class TestHelpCommand:
    """Tests for HelpCommand."""

    @pytest.mark.asyncio
    async def test_help_command(self, mock_message, mock_context):
        """Test /help command lists available commands."""
        # Mock command definitions
        mock_cmd1 = MagicMock()
        mock_cmd1.name = "start"
        mock_cmd1.description = "Initialize the bot"
        mock_cmd1.args_description = None

        mock_cmd2 = MagicMock()
        mock_cmd2.name = "queue"
        mock_cmd2.description = "Set queue mode"
        mock_cmd2.args_description = "<mode>"

        mock_context.command_router.list_commands.return_value = [mock_cmd1, mock_cmd2]

        handler = HelpCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.handled is True
        assert "Available commands:" in result.response
        assert "/start - Initialize the bot" in result.response
        assert "/queue <mode> - Set queue mode" in result.response
        assert result.new_thread_id is None

    @pytest.mark.asyncio
    async def test_help_command_no_router(self, mock_message, mock_context):
        """Test /help command when no router is available."""
        mock_context.command_router = None

        handler = HelpCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.handled is True
        assert "No commands available" in result.response

    @pytest.mark.asyncio
    async def test_help_command_empty_list(self, mock_message, mock_context):
        """Test /help command with empty command list."""
        mock_context.command_router.list_commands.return_value = []

        handler = HelpCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.handled is True
        assert "No commands available" in result.response

    def test_help_definition(self):
        """Test help command definition."""
        handler = HelpCommand()
        definition = handler.definition

        assert definition.name == "help"
        assert definition.bypass_queue is False


class TestStatusCommand:
    """Tests for StatusCommand."""

    @pytest.mark.asyncio
    async def test_status_command_basic(self, mock_message, mock_context):
        """Test /status command shows basic workspace info."""
        state = SessionState(
            conversation_id="conv_2026-02-07T14-30-00-123456",
            started_at=MagicMock(),
            message_count=42,
        )
        mock_context.session_manager.get_state.return_value = state

        handler = StatusCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.handled is True
        assert "Workspace: test-workspace" in result.response
        assert "Model: anthropic:claude-sonnet-4-20250514" in result.response
        assert "Conversation: conv_2026-02-07T14-30-00-123456" in result.response
        assert "Messages: 42" in result.response
        assert result.new_thread_id is None

    @pytest.mark.asyncio
    async def test_status_command_no_session(self, mock_message, mock_context):
        """Test /status command when no session exists."""
        mock_context.session_manager.get_state.return_value = None

        handler = StatusCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.handled is True
        assert "Workspace: test-workspace" in result.response
        assert "Model:" in result.response
        # Should not crash, just omit session info

    @pytest.mark.asyncio
    async def test_status_command_with_tasks(self, mock_message, mock_context, tmp_path):
        """Test /status command includes task counts if TASKS.yaml exists."""
        state = SessionState(
            conversation_id="conv_2026-02-07T14-30-00-123456",
            started_at=MagicMock(),
            message_count=10,
        )
        mock_context.session_manager.get_state.return_value = state

        # Create a TASKS.yaml file
        from openpaw.stores.task import Task, TaskStatus, TaskStore

        task_store = TaskStore(tmp_path)
        task_store.create(
            Task(
                id="task1",
                type="test",
                description="Test task 1",
                status=TaskStatus.PENDING,
            )
        )
        task_store.create(
            Task(
                id="task2",
                type="test",
                description="Test task 2",
                status=TaskStatus.IN_PROGRESS,
            )
        )
        task_store.create(
            Task(
                id="task3",
                type="test",
                description="Test task 3",
                status=TaskStatus.COMPLETED,
            )
        )

        # Add task_store to mock context
        mock_context.task_store = task_store

        handler = StatusCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.handled is True
        assert "Tasks: 1 pending, 1 in progress, 1 completed" in result.response

    def test_status_definition(self):
        """Test status command definition."""
        handler = StatusCommand()
        definition = handler.definition

        assert definition.name == "status"
        assert definition.bypass_queue is False


class TestCompactCommand:
    """Tests for CompactCommand."""

    @pytest.mark.asyncio
    async def test_compact_generates_summary(self, mock_message, mock_context):
        """Test /compact command generates summary using agent."""
        old_conv_id = "conv_2026-02-07T14-30-00-123456"
        old_thread_id = "telegram:123456:conv_2026-02-07T14-30-00-123456"
        new_thread_id = "telegram:123456:conv_2026-02-07T14-35-00-789012"
        summary_text = "Summary of the conversation discussing task management."

        # Mock session state
        mock_state = MagicMock()
        mock_state.conversation_id = old_conv_id
        mock_context.session_manager.get_state.return_value = mock_state
        mock_context.session_manager.get_thread_id.side_effect = [
            old_thread_id,
            new_thread_id,
        ]

        # Mock agent runner to return summary
        mock_context.agent_runner.run = AsyncMock(side_effect=[summary_text, None])

        # Mock archiver
        mock_archive = MagicMock()
        mock_archive.message_count = 15
        mock_context.conversation_archiver.archive = AsyncMock(return_value=mock_archive)

        handler = CompactCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.handled is True
        assert "Conversation compacted" in result.response
        assert "15 messages archived" in result.response
        assert "Summary preserved as context" in result.response
        assert result.new_thread_id == new_thread_id

        # Verify agent was called to generate summary
        assert mock_context.agent_runner.run.call_count == 2
        first_call = mock_context.agent_runner.run.call_args_list[0]
        assert "Summarize the conversation" in first_call.kwargs["message"]
        assert first_call.kwargs["thread_id"] == old_thread_id

    @pytest.mark.asyncio
    async def test_compact_archives_conversation(self, mock_message, mock_context):
        """Test /compact command archives conversation with summary."""
        old_conv_id = "conv_2026-02-07T14-30-00-123456"
        old_thread_id = "telegram:123456:conv_2026-02-07T14-30-00-123456"
        new_thread_id = "telegram:123456:conv_2026-02-07T14-35-00-789012"
        summary_text = "Discussion about project architecture."

        # Mock session state
        mock_state = MagicMock()
        mock_state.conversation_id = old_conv_id
        mock_context.session_manager.get_state.return_value = mock_state
        mock_context.session_manager.get_thread_id.side_effect = [
            old_thread_id,
            new_thread_id,
        ]

        # Mock agent runner
        mock_context.agent_runner.run = AsyncMock(side_effect=[summary_text, None])

        # Mock archiver
        mock_archive = MagicMock()
        mock_archive.message_count = 20
        mock_context.conversation_archiver.archive = AsyncMock(return_value=mock_archive)

        handler = CompactCommand()
        result = await handler.handle(mock_message, "", mock_context)

        # Verify archiver was called with correct parameters including tags=["compact"]
        mock_context.conversation_archiver.archive.assert_called_once_with(
            checkpointer=mock_context.checkpointer,
            thread_id=old_thread_id,
            session_key="telegram:123456",
            conversation_id=old_conv_id,
            summary=summary_text,
            tags=["compact"],
        )

    @pytest.mark.asyncio
    async def test_compact_rotates_conversation(self, mock_message, mock_context):
        """Test /compact command rotates to new conversation."""
        old_conv_id = "conv_2026-02-07T14-30-00-123456"
        old_thread_id = "telegram:123456:conv_2026-02-07T14-30-00-123456"
        new_thread_id = "telegram:123456:conv_2026-02-07T14-35-00-789012"

        # Mock session state
        mock_state = MagicMock()
        mock_state.conversation_id = old_conv_id
        mock_context.session_manager.get_state.return_value = mock_state
        mock_context.session_manager.get_thread_id.side_effect = [
            old_thread_id,
            new_thread_id,
        ]

        # Mock agent runner
        mock_context.agent_runner.run = AsyncMock(return_value="Test summary")

        # Mock archiver
        mock_archive = MagicMock()
        mock_archive.message_count = 10
        mock_context.conversation_archiver.archive = AsyncMock(return_value=mock_archive)

        handler = CompactCommand()
        result = await handler.handle(mock_message, "", mock_context)

        # Verify new conversation was created
        mock_context.session_manager.new_conversation.assert_called_once_with(
            "telegram:123456"
        )

        # Verify result has new thread ID
        assert result.new_thread_id == new_thread_id

    @pytest.mark.asyncio
    async def test_compact_injects_summary(self, mock_message, mock_context):
        """Test /compact command injects summary into new thread."""
        old_conv_id = "conv_2026-02-07T14-30-00-123456"
        old_thread_id = "telegram:123456:conv_2026-02-07T14-30-00-123456"
        new_thread_id = "telegram:123456:conv_2026-02-07T14-35-00-789012"
        summary_text = "We discussed implementing new features."

        # Mock session state
        mock_state = MagicMock()
        mock_state.conversation_id = old_conv_id
        mock_context.session_manager.get_state.return_value = mock_state
        mock_context.session_manager.get_thread_id.side_effect = [
            old_thread_id,
            new_thread_id,
        ]

        # Mock agent runner
        mock_context.agent_runner.run = AsyncMock(side_effect=[summary_text, None])

        # Mock archiver
        mock_archive = MagicMock()
        mock_archive.message_count = 10
        mock_context.conversation_archiver.archive = AsyncMock(return_value=mock_archive)

        handler = CompactCommand()
        result = await handler.handle(mock_message, "", mock_context)

        # Verify agent was called to inject summary into new thread
        assert mock_context.agent_runner.run.call_count == 2
        second_call = mock_context.agent_runner.run.call_args_list[1]
        assert "[CONVERSATION COMPACTED]" in second_call.kwargs["message"]
        assert summary_text in second_call.kwargs["message"]
        assert second_call.kwargs["thread_id"] == new_thread_id

    @pytest.mark.asyncio
    async def test_compact_reinjects_balanced_todos(self, mock_message, mock_context):
        """/compact parity with auto-compact: a runner exposing get_todos
        (balanced harness) has its live checklist appended to the injected
        summary, read from the old thread before rotation."""
        old_thread_id = "telegram:123456:conv_old"
        new_thread_id = "telegram:123456:conv_new"

        mock_state = MagicMock()
        mock_state.conversation_id = "conv_old"
        mock_context.session_manager.get_state.return_value = mock_state
        mock_context.session_manager.get_thread_id.side_effect = [
            old_thread_id,
            new_thread_id,
        ]
        mock_context.agent_runner.run = AsyncMock(side_effect=["Summary text", None])
        mock_context.agent_runner.get_todos = AsyncMock(
            return_value=[{"content": "Build", "status": "in_progress"}]
        )
        mock_archive = MagicMock()
        mock_archive.message_count = 10
        mock_context.conversation_archiver.archive = AsyncMock(return_value=mock_archive)

        handler = CompactCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.new_thread_id == new_thread_id
        mock_context.agent_runner.get_todos.assert_awaited_once_with(old_thread_id)
        inject_call = mock_context.agent_runner.run.call_args_list[-1]
        message = inject_call.kwargs["message"]
        assert "restored after context compaction" in message
        assert "[~] Build" in message

    @pytest.mark.asyncio
    async def test_compact_flush_turn_runs_before_summary(self, mock_message, mock_context):
        """With flush enabled (default), /compact runs a flush turn first and
        references the flush file in the injected summary."""
        mock_context.auto_compact_config = AutoCompactConfig()
        old_thread_id = "telegram:123456:conv_old"
        new_thread_id = "telegram:123456:conv_new"

        mock_state = MagicMock()
        mock_state.conversation_id = "conv_old"
        mock_context.session_manager.get_state.return_value = mock_state
        mock_context.session_manager.get_thread_id.side_effect = [
            old_thread_id,
            new_thread_id,
        ]
        mock_context.agent_runner.run = AsyncMock(
            side_effect=["Saved context.", "Summary text", None]
        )
        mock_archive = MagicMock()
        mock_archive.message_count = 10
        mock_context.conversation_archiver.archive = AsyncMock(return_value=mock_archive)

        handler = CompactCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.new_thread_id == new_thread_id
        assert mock_context.agent_runner.run.call_count == 3
        flush_call, summarize_call, inject_call = (
            mock_context.agent_runner.run.call_args_list
        )
        assert "[PRE-COMPACT FLUSH]" in flush_call.kwargs["message"]
        assert flush_call.kwargs["thread_id"] == old_thread_id
        assert "Summarize the conversation" in summarize_call.kwargs["message"]
        assert "memory/compact-flush-" in inject_call.kwargs["message"]
        assert inject_call.kwargs["thread_id"] == new_thread_id

    @pytest.mark.asyncio
    async def test_compact_flush_failure_does_not_block(self, mock_message, mock_context):
        """A failing flush turn is fail-open: /compact still completes."""
        mock_context.auto_compact_config = AutoCompactConfig()
        old_thread_id = "telegram:123456:conv_old"
        new_thread_id = "telegram:123456:conv_new"

        mock_state = MagicMock()
        mock_state.conversation_id = "conv_old"
        mock_context.session_manager.get_state.return_value = mock_state
        mock_context.session_manager.get_thread_id.side_effect = [
            old_thread_id,
            new_thread_id,
        ]
        mock_context.agent_runner.run = AsyncMock(
            side_effect=[Exception("flush boom"), "Summary text", None]
        )
        mock_archive = MagicMock()
        mock_archive.message_count = 5
        mock_context.conversation_archiver.archive = AsyncMock(return_value=mock_archive)

        handler = CompactCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert "Conversation compacted" in result.response
        assert "Summary preserved as context" in result.response
        inject_call = mock_context.agent_runner.run.call_args_list[2]
        assert "memory/compact-flush-" not in inject_call.kwargs["message"]

    @pytest.mark.asyncio
    async def test_compact_handles_summary_failure(self, mock_message, mock_context):
        """Test /compact command handles summary generation failure gracefully."""
        old_conv_id = "conv_2026-02-07T14-30-00-123456"
        old_thread_id = "telegram:123456:conv_2026-02-07T14-30-00-123456"
        new_thread_id = "telegram:123456:conv_2026-02-07T14-35-00-789012"

        # Mock session state
        mock_state = MagicMock()
        mock_state.conversation_id = old_conv_id
        mock_context.session_manager.get_state.return_value = mock_state
        mock_context.session_manager.get_thread_id.side_effect = [
            old_thread_id,
            new_thread_id,
        ]

        # Mock agent runner to raise exception
        mock_context.agent_runner.run = AsyncMock(
            side_effect=Exception("Agent error")
        )

        # Mock archiver
        mock_archive = MagicMock()
        mock_archive.message_count = 10
        mock_context.conversation_archiver.archive = AsyncMock(return_value=mock_archive)

        handler = CompactCommand()
        result = await handler.handle(mock_message, "", mock_context)

        # Should still complete, but without summary
        assert result.handled is True
        assert "Conversation compacted" in result.response
        assert "10 messages archived" in result.response
        assert "Could not generate summary" in result.response
        assert result.new_thread_id == new_thread_id

        # Verify archiver was still called (with None summary)
        mock_context.conversation_archiver.archive.assert_called_once_with(
            checkpointer=mock_context.checkpointer,
            thread_id=old_thread_id,
            session_key="telegram:123456",
            conversation_id=old_conv_id,
            summary=None,
            tags=["compact"],
        )

        # Verify new conversation was still created
        mock_context.session_manager.new_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_compact_no_checkpointer(self, mock_message, mock_context):
        """Test /compact command returns error when no checkpointer available."""
        mock_context.checkpointer = None

        handler = CompactCommand()
        result = await handler.handle(mock_message, "", mock_context)

        assert result.handled is True
        assert "Cannot compact: no checkpointer available" in result.response
        assert result.new_thread_id is None

        # Should not call any other services
        mock_context.session_manager.new_conversation.assert_not_called()

    @pytest.mark.asyncio
    async def test_compact_handles_archiver_failure(self, mock_message, mock_context):
        """Test /compact command handles archiver failure gracefully."""
        old_conv_id = "conv_2026-02-07T14-30-00-123456"
        old_thread_id = "telegram:123456:conv_2026-02-07T14-30-00-123456"
        new_thread_id = "telegram:123456:conv_2026-02-07T14-35-00-789012"
        summary_text = "Test summary"

        # Mock session state
        mock_state = MagicMock()
        mock_state.conversation_id = old_conv_id
        mock_context.session_manager.get_state.return_value = mock_state
        mock_context.session_manager.get_thread_id.side_effect = [
            old_thread_id,
            new_thread_id,
        ]

        # Mock agent runner
        mock_context.agent_runner.run = AsyncMock(side_effect=[summary_text, None])

        # Mock archiver to raise exception
        mock_context.conversation_archiver.archive = AsyncMock(
            side_effect=Exception("Archive failed")
        )

        handler = CompactCommand()
        result = await handler.handle(mock_message, "", mock_context)

        # Should still complete, but without message count
        assert result.handled is True
        assert "Conversation compacted" in result.response
        assert "Summary preserved as context" in result.response
        assert result.new_thread_id == new_thread_id

        # Verify new conversation was still created
        mock_context.session_manager.new_conversation.assert_called_once()

        # Verify summary was still injected
        assert mock_context.agent_runner.run.call_count == 2

    def test_compact_definition(self):
        """Test compact command definition."""
        handler = CompactCommand()
        definition = handler.definition

        assert definition.name == "compact"
        assert definition.bypass_queue is True
        assert definition.hidden is False
