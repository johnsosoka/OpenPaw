"""Tests for model creation and extra_model_kwargs in AgentRunner."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from openpaw.agent.runner import AgentRunner
from openpaw.core.workspace import AgentWorkspace

# Common patches for isolating AgentRunner from real dependencies
_PATCH_FS = "openpaw.agent.runner.FilesystemTools"
_PATCH_AGENT = "openpaw.agent.runner.create_agent"

# Provider patches (local imports in _create_model, patch at source)
_PATCH_OPENAI = "langchain_openai.ChatOpenAI"
_PATCH_ANTHROPIC = "langchain_anthropic.ChatAnthropic"
_PATCH_BEDROCK = "langchain_aws.ChatBedrockConverse"


@pytest.fixture
def mock_workspace(tmp_path: Path) -> AgentWorkspace:
    """Create a mock workspace for testing."""
    workspace_path = tmp_path / "test_workspace"
    workspace_path.mkdir()

    agent_dir = workspace_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "AGENT.md").write_text("Test agent")
    (agent_dir / "USER.md").write_text("Test user")
    (agent_dir / "SOUL.md").write_text("Test soul")
    (agent_dir / "HEARTBEAT.md").write_text("Test heartbeat")

    workspace = Mock(spec=AgentWorkspace)
    workspace.path = workspace_path
    workspace.name = "test_workspace"
    workspace.build_system_prompt = Mock(return_value="Test prompt")

    return workspace


def test_extra_model_kwargs_stored_on_init(mock_workspace: AgentWorkspace) -> None:
    """Test that extra_model_kwargs are stored during initialization."""
    extra_kwargs = {"base_url": "https://api.example.com/v1", "custom_param": "value"}

    with patch("openpaw.agent.runner.AgentRunner._create_model") as mock_create, \
         patch(_PATCH_FS), patch(_PATCH_AGENT):
        mock_create.return_value = Mock()

        agent_runner = AgentRunner(
            workspace=mock_workspace,
            model="openai:test-model",
            api_key="test-key",
            extra_model_kwargs=extra_kwargs,
        )

        assert agent_runner.extra_model_kwargs == extra_kwargs


def test_extra_model_kwargs_defaults_to_empty_dict(mock_workspace: AgentWorkspace) -> None:
    """Test that extra_model_kwargs defaults to empty dict when None."""
    with patch("openpaw.agent.runner.AgentRunner._create_model") as mock_create, \
         patch(_PATCH_FS), patch(_PATCH_AGENT):
        mock_create.return_value = Mock()

        agent_runner = AgentRunner(
            workspace=mock_workspace,
            model="openai:test-model",
            api_key="test-key",
            extra_model_kwargs=None,
        )

        assert agent_runner.extra_model_kwargs == {}


def test_openai_provider_creates_chat_openai(mock_workspace: AgentWorkspace) -> None:
    """Test that openai provider instantiates ChatOpenAI with all kwargs."""
    extra_kwargs = {"base_url": "https://api.moonshot.ai/v1", "timeout": 60}

    with patch(_PATCH_OPENAI) as mock_cls, \
         patch(_PATCH_FS), patch(_PATCH_AGENT):
        mock_cls.return_value = Mock()

        AgentRunner(
            workspace=mock_workspace,
            model="openai:kimi-k2.5",
            api_key="test-moonshot-key",
            temperature=0.6,
            extra_model_kwargs=extra_kwargs,
        )

        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]

        assert call_kwargs["model"] == "kimi-k2.5"
        assert call_kwargs["temperature"] == 0.6
        assert call_kwargs["api_key"] == "test-moonshot-key"
        assert call_kwargs["base_url"] == "https://api.moonshot.ai/v1"
        assert call_kwargs["timeout"] == 60


def test_model_kwargs_flattened_into_direct_args(mock_workspace: AgentWorkspace) -> None:
    """Test that nested model_kwargs are flattened so extra_body reaches the provider."""
    extra_kwargs = {
        "base_url": "https://api.moonshot.ai/v1",
        "model_kwargs": {"extra_body": {"thinking": {"type": "disabled"}}},
    }

    with patch(_PATCH_OPENAI) as mock_cls, \
         patch(_PATCH_FS), patch(_PATCH_AGENT):
        mock_cls.return_value = Mock()

        AgentRunner(
            workspace=mock_workspace,
            model="openai:kimi-k2.5",
            api_key="test-key",
            temperature=0.6,
            extra_model_kwargs=extra_kwargs,
        )

        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]

        # extra_body should be a direct kwarg, NOT nested under model_kwargs
        assert "model_kwargs" not in call_kwargs
        assert call_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        assert call_kwargs["base_url"] == "https://api.moonshot.ai/v1"


def test_bedrock_excludes_api_key_but_includes_extra_kwargs(mock_workspace: AgentWorkspace) -> None:
    """Test that Bedrock models exclude api_key but still accept extra kwargs."""
    extra_kwargs = {"custom_bedrock_param": "value"}

    with patch(_PATCH_BEDROCK) as mock_cls, \
         patch(_PATCH_FS), patch(_PATCH_AGENT):
        mock_cls.return_value = Mock()

        AgentRunner(
            workspace=mock_workspace,
            model="bedrock_converse:moonshot.kimi-k2-thinking",
            api_key="should-not-be-passed",
            region="us-east-1",
            extra_model_kwargs=extra_kwargs,
        )

        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]

        assert "api_key" not in call_kwargs
        assert call_kwargs["region_name"] == "us-east-1"
        assert call_kwargs["custom_bedrock_param"] == "value"


def test_anthropic_provider_creates_chat_anthropic(mock_workspace: AgentWorkspace) -> None:
    """Test that anthropic provider instantiates ChatAnthropic."""
    with patch(_PATCH_ANTHROPIC) as mock_cls, \
         patch(_PATCH_FS), patch(_PATCH_AGENT):
        mock_cls.return_value = Mock()

        AgentRunner(
            workspace=mock_workspace,
            model="anthropic:claude-sonnet-4-20250514",
            api_key="test-key",
            extra_model_kwargs={},
        )

        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]

        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["api_key"] == "test-key"


def test_unsupported_provider_raises_error(mock_workspace: AgentWorkspace) -> None:
    """Test that unsupported provider raises ValueError."""
    with patch(_PATCH_FS), patch(_PATCH_AGENT), \
         pytest.raises(ValueError, match="Unsupported model provider"):
        AgentRunner(
            workspace=mock_workspace,
            model="unsupported:some-model",
            extra_model_kwargs={},
        )


def test_empty_extra_model_kwargs_works(mock_workspace: AgentWorkspace) -> None:
    """Test that empty extra_model_kwargs dict works correctly."""
    with patch(_PATCH_ANTHROPIC) as mock_cls, \
         patch(_PATCH_FS), patch(_PATCH_AGENT):
        mock_cls.return_value = Mock()

        AgentRunner(
            workspace=mock_workspace,
            model="anthropic:claude-sonnet-4-20250514",
            api_key="test-key",
            extra_model_kwargs={},
        )

        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]

        assert call_kwargs["temperature"] == 0.7
        assert call_kwargs["api_key"] == "test-key"
        assert set(call_kwargs.keys()) == {"model", "temperature", "api_key"}
