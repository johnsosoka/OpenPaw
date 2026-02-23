"""Tests for AgentRunner.get_context_info()."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openpaw.agent.runner import AgentRunner


@pytest.fixture
def mock_runner():
    """Create a mock AgentRunner with patched dependencies."""
    workspace = MagicMock()
    workspace.name = "test"
    workspace.path = MagicMock()
    workspace.config = None

    with patch.object(AgentRunner, "_build_agent", return_value=MagicMock()):
        runner = AgentRunner(workspace=workspace, model="openai:test-model", api_key="fake")

    # Mock the agent's aget_state
    runner._agent = AsyncMock()
    runner._model_instance = MagicMock()
    return runner


@pytest.mark.asyncio
async def test_get_context_info_returns_dict(mock_runner):
    """Test get_context_info returns a dict with all expected keys."""
    # Mock messages
    mock_msg1 = MagicMock()
    mock_msg1.content = "Hello"
    mock_msg2 = MagicMock()
    mock_msg2.content = "World"

    # Mock state
    mock_state = MagicMock()
    mock_state.values = {"messages": [mock_msg1, mock_msg2]}
    mock_runner._agent.aget_state = AsyncMock(return_value=mock_state)

    # Mock model profile
    mock_runner._model_instance.profile = {"max_input_tokens": 128000}

    with patch("langchain_core.messages.utils.count_tokens_approximately", return_value=50000):
        result = await mock_runner.get_context_info("test:thread:123")

    assert isinstance(result, dict)
    assert "max_input_tokens" in result
    assert "approximate_tokens" in result
    assert "utilization" in result
    assert "message_count" in result
    assert result["max_input_tokens"] == 128000
    assert result["approximate_tokens"] == 50000
    assert result["message_count"] == 2


@pytest.mark.asyncio
async def test_get_context_info_empty_state(mock_runner):
    """Test get_context_info returns zeros when state is empty."""
    # Mock empty state
    mock_state = MagicMock()
    mock_state.values = None
    mock_runner._agent.aget_state = AsyncMock(return_value=mock_state)

    result = await mock_runner.get_context_info("test:thread:123")

    assert result["max_input_tokens"] == 0
    assert result["approximate_tokens"] == 0
    assert result["utilization"] == 0.0
    assert result["message_count"] == 0


@pytest.mark.asyncio
async def test_get_context_info_calculates_utilization(mock_runner):
    """Test get_context_info correctly calculates utilization."""
    mock_msg = MagicMock()
    mock_msg.content = "Test"

    mock_state = MagicMock()
    mock_state.values = {"messages": [mock_msg]}
    mock_runner._agent.aget_state = AsyncMock(return_value=mock_state)

    mock_runner._model_instance.profile = {"max_input_tokens": 100000}

    with patch("langchain_core.messages.utils.count_tokens_approximately", return_value=25000):
        result = await mock_runner.get_context_info("test:thread:123")

    # 25000 / 100000 = 0.25
    assert result["utilization"] == 0.25
    assert result["max_input_tokens"] == 100000
    assert result["approximate_tokens"] == 25000


@pytest.mark.asyncio
async def test_get_context_info_uses_model_profile(mock_runner):
    """Test get_context_info uses model profile for max_input_tokens."""
    mock_msg = MagicMock()
    mock_msg.content = "Test"

    mock_state = MagicMock()
    mock_state.values = {"messages": [mock_msg]}
    mock_runner._agent.aget_state = AsyncMock(return_value=mock_state)

    # Set a custom max_input_tokens via profile
    mock_runner._model_instance.profile = {"max_input_tokens": 256000}

    with patch("langchain_core.messages.utils.count_tokens_approximately", return_value=50000):
        result = await mock_runner.get_context_info("test:thread:123")

    assert result["max_input_tokens"] == 256000


@pytest.mark.asyncio
async def test_get_context_info_fallback_no_profile(mock_runner):
    """Test get_context_info uses 200000 fallback when no profile available."""
    mock_msg = MagicMock()
    mock_msg.content = "Test"

    mock_state = MagicMock()
    mock_state.values = {"messages": [mock_msg]}
    mock_runner._agent.aget_state = AsyncMock(return_value=mock_state)

    # No profile attribute
    mock_runner._model_instance.profile = None

    with patch("langchain_core.messages.utils.count_tokens_approximately", return_value=50000):
        result = await mock_runner.get_context_info("test:thread:123")

    assert result["max_input_tokens"] == 200000


@pytest.mark.asyncio
async def test_get_context_info_message_count(mock_runner):
    """Test get_context_info returns correct message count."""
    # Create 5 mock messages
    messages = [MagicMock(content=f"Message {i}") for i in range(5)]

    mock_state = MagicMock()
    mock_state.values = {"messages": messages}
    mock_runner._agent.aget_state = AsyncMock(return_value=mock_state)

    mock_runner._model_instance.profile = {"max_input_tokens": 128000}

    with patch("langchain_core.messages.utils.count_tokens_approximately", return_value=10000):
        result = await mock_runner.get_context_info("test:thread:123")

    assert result["message_count"] == 5
