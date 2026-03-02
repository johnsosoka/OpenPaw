"""Tests for /status command token usage display."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from openpaw.agent.metrics import TokenUsageLogger
from openpaw.channels.commands.base import CommandContext
from openpaw.channels.commands.handlers.status import StatusCommand
from openpaw.runtime.session.manager import SessionManager


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    """Create a temporary workspace directory."""
    workspace = tmp_path / "test_workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def token_logger(workspace_path: Path) -> TokenUsageLogger:
    """Create a TokenUsageLogger for testing."""
    return TokenUsageLogger(workspace_path)


@pytest.fixture
def command_context(workspace_path: Path) -> CommandContext:
    """Create a mock CommandContext for testing."""
    mock_agent_runner = Mock()
    mock_agent_runner.model_id = "test-model-1"

    session_manager = SessionManager(workspace_path)

    return CommandContext(
        channel=Mock(),
        session_manager=session_manager,
        checkpointer=Mock(),
        agent_runner=mock_agent_runner,
        workspace_name="test_workspace",
        workspace_path=workspace_path,
        queue_manager=Mock(),
        workspace_timezone="UTC",  # Default to UTC
    )


@pytest.mark.asyncio
async def test_status_no_tokens(command_context: CommandContext):
    """Test /status when no token usage log exists."""
    command = StatusCommand()
    message = Mock()
    message.session_key = "telegram:12345"

    result = await command.handle(message, "", command_context)

    # Should not crash, token lines should be absent
    assert result.response is not None
    assert "Tokens" not in result.response


@pytest.mark.asyncio
async def test_status_with_tokens_today(
    token_logger: TokenUsageLogger,
    command_context: CommandContext,
):
    """Test /status displays tokens used today."""
    # Log some token usage for today
    from openpaw.agent.metrics import InvocationMetrics

    metrics = InvocationMetrics(
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        llm_calls=1,
        duration_ms=1234.5,
        model="test-model",
    )

    token_logger.log(
        metrics=metrics,
        workspace="test_workspace",
        invocation_type="user",
        session_key="telegram:12345",
    )

    # Create a second entry
    token_logger.log(
        metrics=InvocationMetrics(
            input_tokens=2000,
            output_tokens=1000,
            total_tokens=3000,
        ),
        workspace="test_workspace",
        invocation_type="user",
        session_key="telegram:67890",
    )

    command = StatusCommand()
    message = Mock()
    message.session_key = "telegram:12345"

    result = await command.handle(message, "", command_context)

    # Should show today's total (1500 + 3000 = 4500)
    assert "Tokens today: 4,500" in result.response
    assert "in: 3,000" in result.response
    assert "out: 1,500" in result.response

    # Should show session total (1500)
    assert "Tokens this session: 1,500" in result.response


@pytest.mark.asyncio
async def test_status_session_tokens_only(
    token_logger: TokenUsageLogger,
    command_context: CommandContext,
):
    """Test /status shows correct session-specific token count."""
    from openpaw.agent.metrics import InvocationMetrics

    # Log tokens for session A
    token_logger.log(
        metrics=InvocationMetrics(
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
        ),
        workspace="test_workspace",
        invocation_type="user",
        session_key="telegram:12345",
    )

    # Log tokens for session B (different session)
    token_logger.log(
        metrics=InvocationMetrics(
            input_tokens=2000,
            output_tokens=1000,
            total_tokens=3000,
        ),
        workspace="test_workspace",
        invocation_type="user",
        session_key="telegram:67890",
    )

    command = StatusCommand()
    message = Mock()
    message.session_key = "telegram:12345"

    result = await command.handle(message, "", command_context)

    # Should show session A's tokens only (1500), not session B's
    assert "Tokens this session: 1,500" in result.response
    assert "Tokens today: 4,500" in result.response


@pytest.mark.asyncio
async def test_status_handles_corrupted_log(
    workspace_path: Path,
    command_context: CommandContext,
):
    """Test /status handles corrupted JSONL gracefully."""
    # Create a corrupted token log
    log_path = workspace_path / "data" / "token_usage.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    with open(log_path, "w") as f:
        # Valid entry
        f.write(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "workspace": "test",
                    "invocation_type": "user",
                    "session_key": "telegram:12345",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                }
            )
            + "\n"
        )
        # Corrupted entry
        f.write("not valid json\n")
        # Another valid entry
        f.write(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "workspace": "test",
                    "invocation_type": "user",
                    "session_key": "telegram:12345",
                    "input_tokens": 200,
                    "output_tokens": 100,
                    "total_tokens": 300,
                }
            )
            + "\n"
        )

    command = StatusCommand()
    message = Mock()
    message.session_key = "telegram:12345"

    result = await command.handle(message, "", command_context)

    # Should still show tokens from valid entries (150 + 300 = 450)
    assert "Tokens this session: 450" in result.response


@pytest.mark.asyncio
async def test_status_number_formatting(
    token_logger: TokenUsageLogger,
    command_context: CommandContext,
):
    """Test /status formats large numbers with commas."""
    from openpaw.agent.metrics import InvocationMetrics

    # Log a large token count
    token_logger.log(
        metrics=InvocationMetrics(
            input_tokens=123456,
            output_tokens=78910,
            total_tokens=202366,
        ),
        workspace="test_workspace",
        invocation_type="user",
        session_key="telegram:12345",
    )

    command = StatusCommand()
    message = Mock()
    message.session_key = "telegram:12345"

    result = await command.handle(message, "", command_context)

    # Check comma formatting
    assert "Tokens today: 202,366" in result.response
    assert "in: 123,456" in result.response
    assert "out: 78,910" in result.response


@pytest.mark.asyncio
async def test_status_uses_workspace_timezone(
    token_logger: TokenUsageLogger,
    workspace_path: Path,
):
    """Test /status command uses workspace timezone for token aggregation."""
    from openpaw.agent.metrics import InvocationMetrics

    # Create a context with Mountain Time timezone
    mock_agent_runner = Mock()
    mock_agent_runner.model_id = "test-model-1"
    session_manager = SessionManager(workspace_path)

    context_mountain = CommandContext(
        channel=Mock(),
        session_manager=session_manager,
        checkpointer=Mock(),
        agent_runner=mock_agent_runner,
        workspace_name="test_workspace",
        workspace_path=workspace_path,
        queue_manager=Mock(),
        workspace_timezone="America/Denver",  # Mountain Time
    )

    # Log some tokens
    token_logger.log(
        metrics=InvocationMetrics(
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
        ),
        workspace="test_workspace",
        invocation_type="user",
        session_key="telegram:12345",
    )

    command = StatusCommand()
    message = Mock()
    message.session_key = "telegram:12345"

    # Execute command with Mountain Time context
    result = await command.handle(message, "", context_mountain)

    # Should show tokens (timezone-aware day boundary)
    assert "Tokens" in result.response
    assert "1,500" in result.response


@pytest.mark.asyncio
async def test_status_shows_model_override(workspace_path: Path):
    """Test /status shows configured model when overridden."""
    from openpaw.workspace.agent_factory import AgentFactory, RuntimeModelOverride

    # Create a mock factory with an override
    mock_workspace = Mock()
    mock_workspace.name = "test"
    mock_workspace.path = workspace_path

    with patch("openpaw.agent.runner.AgentRunner.__init__", return_value=None):
        factory = AgentFactory(
            workspace=mock_workspace,
            model="anthropic:claude-test",
            api_key="test-key",
            max_turns=50,
            temperature=0.7,
            region=None,
            timeout_seconds=300.0,
            builtin_tools=[],
            workspace_tools=[],
            enabled_builtin_names=[],
            extra_model_kwargs={},
            middleware=[],
            logger=Mock(),
        )

    # Set an override
    override = RuntimeModelOverride(model="openai:gpt-4")
    factory.set_runtime_override(override)

    # Create context with factory
    mock_agent_runner = Mock()
    mock_agent_runner.model_id = "openai:gpt-4"
    session_manager = SessionManager(workspace_path)

    context = CommandContext(
        channel=Mock(),
        session_manager=session_manager,
        checkpointer=Mock(),
        agent_runner=mock_agent_runner,
        workspace_name="test_workspace",
        workspace_path=workspace_path,
        queue_manager=Mock(),
        workspace_timezone="UTC",
        agent_factory=factory,
    )

    command = StatusCommand()
    message = Mock()
    message.session_key = "telegram:12345"

    result = await command.handle(message, "", context)

    # Should show configured model with override indicator
    assert "Configured: anthropic:claude-test (overridden)" in result.response


@pytest.mark.asyncio
async def test_status_shows_context_utilization(workspace_path: Path):
    """Test /status shows context utilization when available."""
    mock_agent_runner = Mock()
    mock_agent_runner.model_id = "test-model"

    # Mock get_context_info
    async def mock_get_context_info(thread_id):
        return {
            "max_input_tokens": 128000,
            "approximate_tokens": 64000,
            "utilization": 0.5,
            "message_count": 10,
        }

    mock_agent_runner.get_context_info = mock_get_context_info

    session_manager = SessionManager(workspace_path)
    # Create a session state by getting thread_id (auto-creates)
    session_manager.get_thread_id("telegram:12345")

    context = CommandContext(
        channel=Mock(),
        session_manager=session_manager,
        checkpointer=Mock(),
        agent_runner=mock_agent_runner,
        workspace_name="test_workspace",
        workspace_path=workspace_path,
        queue_manager=Mock(),
        workspace_timezone="UTC",
    )

    command = StatusCommand()
    message = Mock()
    message.session_key = "telegram:12345"

    result = await command.handle(message, "", context)

    # Should show context utilization
    assert "Context: 50%" in result.response
    assert "64,000" in result.response
    assert "128,000" in result.response


@pytest.mark.asyncio
async def test_status_shows_active_subagents(workspace_path: Path):
    """Test /status shows active subagents when available."""
    from openpaw.model.subagent import SubAgentRequest, SubAgentStatus

    mock_agent_runner = Mock()
    mock_agent_runner.model_id = "test-model"
    session_manager = SessionManager(workspace_path)

    # Create mock subagent store with active requests
    request1 = SubAgentRequest(
        id="req1",
        task="Task 1",
        label="research-task",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
    )
    request2 = SubAgentRequest(
        id="req2",
        task="Task 2",
        label="analysis-task",
        status=SubAgentStatus.RUNNING,
        session_key="telegram:12345",
        timeout_minutes=30,
    )
    subagent_store = Mock()
    subagent_store.list_active = Mock(return_value=[request1, request2])

    context = CommandContext(
        channel=Mock(),
        session_manager=session_manager,
        checkpointer=Mock(),
        agent_runner=mock_agent_runner,
        workspace_name="test_workspace",
        workspace_path=workspace_path,
        queue_manager=Mock(),
        workspace_timezone="UTC",
        subagent_store=subagent_store,
    )

    command = StatusCommand()
    message = Mock()
    message.session_key = "telegram:12345"

    result = await command.handle(message, "", context)

    # Should show active subagents
    assert "Subagents: 2 active" in result.response
    assert "research-task" in result.response
    assert "analysis-task" in result.response


@pytest.mark.asyncio
async def test_status_shows_in_progress_tasks(workspace_path: Path):
    """Test /status shows in-progress task titles."""
    from openpaw.model.task import Task, TaskStatus
    from openpaw.stores.task import TaskStore

    mock_agent_runner = Mock()
    mock_agent_runner.model_id = "test-model"
    session_manager = SessionManager(workspace_path)

    # Create task store with in-progress tasks
    task_store = TaskStore(workspace_path)
    task1 = Task(
        id="task1",
        type="deployment",
        description="Deploy production server",
        status=TaskStatus.IN_PROGRESS,
    )
    task2 = Task(
        id="task2",
        type="research",
        description="Update documentation",
        status=TaskStatus.IN_PROGRESS,
    )
    task3 = Task(
        id="task3",
        type="custom",
        description="Fix bug #123",
        status=TaskStatus.PENDING,
    )
    task_store.create(task1)
    task_store.create(task2)
    task_store.create(task3)

    context = CommandContext(
        channel=Mock(),
        session_manager=session_manager,
        checkpointer=Mock(),
        agent_runner=mock_agent_runner,
        workspace_name="test_workspace",
        workspace_path=workspace_path,
        queue_manager=Mock(),
        workspace_timezone="UTC",
        task_store=task_store,
    )

    command = StatusCommand()
    message = Mock()
    message.session_key = "telegram:12345"

    result = await command.handle(message, "", context)

    # Should show task summary and in-progress descriptions
    assert "Tasks: 1 pending, 2 in progress, 0 completed" in result.response
    assert "Deploy production server" in result.response
    assert "Update documentation" in result.response
