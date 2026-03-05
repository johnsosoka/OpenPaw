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
            provider_catalog=None,
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


# /model list tests


@pytest.mark.asyncio
async def test_model_list_no_catalog(factory):
    """/model list returns 'No providers configured.' when catalog is absent."""
    context = make_context(factory)
    command = ModelCommand()
    message = Mock()

    result = await command.handle(message, "list", context)

    assert result.response == "No providers configured."


@pytest.mark.asyncio
async def test_model_list_empty_catalog(factory):
    """/model list returns 'No providers configured.' for an empty catalog."""
    factory._provider_catalog = {}
    context = make_context(factory)
    command = ModelCommand()
    message = Mock()

    result = await command.handle(message, "list", context)

    assert result.response == "No providers configured."


@pytest.mark.asyncio
async def test_model_list_shows_providers(factory):
    """/model list shows each provider name and type."""
    anthropic_def = MagicMock()
    anthropic_def.type = None
    anthropic_def.base_url = None
    anthropic_def.region = None

    moonshot_def = MagicMock()
    moonshot_def.type = "openai"
    moonshot_def.base_url = "https://api.moonshot.ai/v1"
    moonshot_def.region = None

    factory._provider_catalog = {"anthropic": anthropic_def, "moonshot": moonshot_def}
    context = make_context(factory)
    command = ModelCommand()
    message = Mock()

    result = await command.handle(message, "list", context)

    assert "Configured providers:" in result.response
    assert "anthropic (type: anthropic)" in result.response
    assert "moonshot (type: openai" in result.response
    assert "base_url: https://api.moonshot.ai/v1" in result.response
    assert "Active model:" in result.response


@pytest.mark.asyncio
async def test_model_list_shows_region(factory):
    """/model list includes region when set on a provider."""
    bedrock_def = MagicMock()
    bedrock_def.type = "bedrock_converse"
    bedrock_def.base_url = None
    bedrock_def.region = "us-east-1"

    factory._provider_catalog = {"bedrock": bedrock_def}
    context = make_context(factory)
    command = ModelCommand()
    message = Mock()

    result = await command.handle(message, "list", context)

    assert "bedrock (type: bedrock_converse" in result.response
    assert "region: us-east-1" in result.response


@pytest.mark.asyncio
async def test_model_list_no_factory(factory):
    """/model list returns 'No providers configured.' when factory is absent."""
    context = make_context(factory)
    context.agent_factory = None
    command = ModelCommand()
    message = Mock()

    result = await command.handle(message, "list", context)

    assert result.response == "No providers configured."


# _show_current catalog type hint tests


@pytest.mark.asyncio
async def test_show_current_appends_via_hint_when_type_differs(factory):
    """/model shows '(via openai)' when catalog maps provider to a different type."""
    moonshot_def = MagicMock()
    moonshot_def.type = "openai"

    factory._provider_catalog = {"moonshot": moonshot_def}
    override = RuntimeModelOverride(model="moonshot:kimi-k2.5")
    factory.set_runtime_override(override)

    context = make_context(factory)
    command = ModelCommand()
    message = Mock()

    result = await command.handle(message, "", context)

    assert "(via openai)" in result.response


@pytest.mark.asyncio
async def test_show_current_no_via_hint_when_type_matches(factory):
    """/model does not show '(via ...)' when catalog type equals provider name."""
    anthropic_def = MagicMock()
    anthropic_def.type = "anthropic"

    factory._provider_catalog = {"anthropic": anthropic_def}
    context = make_context(factory)
    command = ModelCommand()
    message = Mock()

    result = await command.handle(message, "", context)

    assert "(via " not in result.response


# Catalog-aware update_model tests (resolved model_str must reach AgentRunner)


@pytest.mark.asyncio
async def test_switch_model_passes_resolved_model_str_to_runner():
    """/model switch passes the LangChain model_str (not display_str) to update_model."""
    from openpaw.core.config.models import ProviderDefinition

    catalog = {"moonshot": ProviderDefinition(type="openai", api_key="moon-key")}
    with patch.object(AgentRunner, "__init__", return_value=None):
        fact = AgentFactory(
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
            provider_catalog=catalog,
        )

    context = make_context(fact)
    command = ModelCommand()
    message = Mock()

    with patch.object(fact, "validate_model", return_value=(True, "Valid")):
        await command.handle(message, "moonshot:kimi-k2.5", context)

    # update_model must receive "openai:kimi-k2.5", not "moonshot:kimi-k2.5"
    context.agent_runner.update_model.assert_called_once()
    call_kwargs = context.agent_runner.update_model.call_args
    assert call_kwargs[1]["model"] == "openai:kimi-k2.5"


@pytest.mark.asyncio
async def test_reset_model_passes_resolved_model_str_to_runner():
    """/model reset passes the LangChain model_str (not display_str) to update_model."""
    from openpaw.core.config.models import ProviderDefinition

    catalog = {"moonshot": ProviderDefinition(type="openai", api_key="moon-key")}
    with patch.object(AgentRunner, "__init__", return_value=None):
        fact = AgentFactory(
            workspace=MagicMock(),
            model="moonshot:kimi-k2.5",
            api_key="moon-key",
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
            provider_catalog=catalog,
        )

    # Set an override so reset has something to revert
    override = RuntimeModelOverride(model="anthropic:claude-test")
    fact.set_runtime_override(override)

    context = make_context(fact)
    command = ModelCommand()
    message = Mock()

    await command.handle(message, "reset", context)

    # update_model must receive "openai:kimi-k2.5" (resolved), not "moonshot:kimi-k2.5" (display)
    context.agent_runner.update_model.assert_called_once()
    call_kwargs = context.agent_runner.update_model.call_args
    assert call_kwargs[1]["model"] == "openai:kimi-k2.5"
