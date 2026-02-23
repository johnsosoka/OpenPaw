"""Tests for /model command and runtime model switching."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from openpaw.agent.runner import AgentRunner
from openpaw.channels.commands.base import CommandContext
from openpaw.channels.commands.handlers.model import ModelCommand
from openpaw.workspace.agent_factory import AgentFactory, RuntimeModelOverride


@pytest.fixture
def factory():
    """Create a minimal AgentFactory for testing."""
    with patch.object(AgentRunner, "__init__", return_value=None):
        return AgentFactory(
            workspace=MagicMock(),
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
            logger=MagicMock(),
        )


def make_context(factory):
    """Create a CommandContext with mocked dependencies."""
    mock_runner = MagicMock()
    mock_runner.model_id = factory.active_model
    return CommandContext(
        channel=MagicMock(),
        session_manager=MagicMock(),
        checkpointer=MagicMock(),
        agent_runner=mock_runner,
        workspace_name="test",
        workspace_path=MagicMock(),
        queue_manager=MagicMock(),
        agent_factory=factory,
    )


# Factory tests


def test_active_model_returns_configured_by_default(factory):
    """Test active_model returns configured model when no override is set."""
    assert factory.active_model == "anthropic:claude-test"
    assert factory.active_model == factory.configured_model


def test_active_model_returns_override(factory):
    """Test active_model returns override when set."""
    override = RuntimeModelOverride(model="openai:gpt-4")
    factory.set_runtime_override(override)

    assert factory.active_model == "openai:gpt-4"
    assert factory.configured_model == "anthropic:claude-test"


def test_clear_override_reverts(factory):
    """Test clear_override reverts to configured model."""
    override = RuntimeModelOverride(model="openai:gpt-4")
    factory.set_runtime_override(override)
    assert factory.active_model == "openai:gpt-4"

    factory.clear_runtime_override()
    assert factory.active_model == "anthropic:claude-test"


def test_stateless_agent_ignores_override(factory):
    """Test create_stateless_agent uses configured model, ignoring override."""
    override = RuntimeModelOverride(model="openai:gpt-4")
    factory.set_runtime_override(override)

    with patch.object(AgentRunner, "__init__", return_value=None) as mock_init:
        factory.create_stateless_agent()

        # Verify AgentRunner was called with configured model, not override
        args, kwargs = mock_init.call_args
        assert kwargs["model"] == "anthropic:claude-test"


def test_resolve_api_key_same_provider(factory):
    """Test _resolve_api_key returns configured key when provider matches."""
    api_key = factory._resolve_api_key("anthropic:claude-other")
    assert api_key == "test-key"


def test_resolve_api_key_bedrock(factory):
    """Test _resolve_api_key returns None for bedrock providers."""
    api_key = factory._resolve_api_key("bedrock_converse:model")
    assert api_key is None

    api_key = factory._resolve_api_key("bedrock:model")
    assert api_key is None


def test_resolve_api_key_from_env(factory):
    """Test _resolve_api_key looks up environment variable for different provider."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "env-openai-key"}):
        api_key = factory._resolve_api_key("openai:gpt-4")
        assert api_key == "env-openai-key"


def test_validate_model_unsupported_provider(factory):
    """Test validate_model returns False for unsupported providers."""
    valid, message = factory.validate_model("unsupported:model-name")
    assert not valid
    assert "Unsupported provider" in message


# Command handler tests


@pytest.mark.asyncio
async def test_model_show_current(factory):
    """Test /model with no args shows active model."""
    context = make_context(factory)
    command = ModelCommand()
    message = Mock()

    result = await command.handle(message, "", context)

    assert "Active model: anthropic:claude-test" in result.response


@pytest.mark.asyncio
async def test_model_switch(factory):
    """Test /model with valid model string switches model."""
    context = make_context(factory)
    command = ModelCommand()
    message = Mock()

    with patch.object(factory, "validate_model", return_value=(True, "Valid")):
        result = await command.handle(message, "openai:gpt-4", context)

    assert "Switched to: openai:gpt-4" in result.response
    assert factory.active_model == "openai:gpt-4"


@pytest.mark.asyncio
async def test_model_reset(factory):
    """Test /model reset reverts to configured model."""
    # Set an override first
    override = RuntimeModelOverride(model="openai:gpt-4")
    factory.set_runtime_override(override)

    context = make_context(factory)
    context.agent_runner.model_id = "openai:gpt-4"
    command = ModelCommand()
    message = Mock()

    result = await command.handle(message, "reset", context)

    assert "Reverted to configured model: anthropic:claude-test" in result.response
    assert factory.active_model == "anthropic:claude-test"
