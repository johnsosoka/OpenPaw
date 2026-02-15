"""Tests for /status command token usage display."""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

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
    log_path = workspace_path / ".openpaw" / "token_usage.jsonl"
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
