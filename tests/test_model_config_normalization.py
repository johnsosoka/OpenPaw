"""Tests for WorkspaceModelConfig provider:model auto-split."""

import pytest

from openpaw.core.config.models import WorkspaceModelConfig


class TestWorkspaceModelConfigNormalization:
    """Tests for the model_validator that splits combined model strings."""

    def test_combined_string_splits(self):
        """'provider:model' string is split into separate fields."""
        config = WorkspaceModelConfig(model="anthropic:claude-sonnet-4-20250514")
        assert config.provider == "anthropic"
        assert config.model == "claude-sonnet-4-20250514"

    def test_separate_fields_preserved(self):
        """Explicit provider + model fields are not modified."""
        config = WorkspaceModelConfig(provider="openai", model="gpt-4o")
        assert config.provider == "openai"
        assert config.model == "gpt-4o"

    def test_no_split_when_provider_set(self):
        """Combined string is NOT split when provider is already set."""
        config = WorkspaceModelConfig(provider="custom", model="custom:special-model")
        assert config.provider == "custom"
        assert config.model == "custom:special-model"

    def test_bedrock_colon_in_model_handled(self):
        """Bedrock IDs like 'us.anthropic.claude-haiku:v1:0' split correctly on first colon."""
        config = WorkspaceModelConfig(model="bedrock_converse:us.anthropic.claude-haiku:v1:0")
        assert config.provider == "bedrock_converse"
        assert config.model == "us.anthropic.claude-haiku:v1:0"

    def test_no_colon_no_split(self):
        """Model without colon remains as-is (no provider inferred)."""
        config = WorkspaceModelConfig(model="gpt-4o")
        assert config.provider is None
        assert config.model == "gpt-4o"

    def test_empty_model_no_error(self):
        """Empty/None model does not error."""
        config = WorkspaceModelConfig()
        assert config.provider is None
        assert config.model is None

    def test_xai_combined_string(self):
        """xAI provider splits correctly."""
        config = WorkspaceModelConfig(model="xai:grok-3-mini")
        assert config.provider == "xai"
        assert config.model == "grok-3-mini"

    def test_base_url_preserved_for_non_legacy_providers(self):
        """base_url survives normalization on providers that legitimately use it (e.g. Ollama)."""
        config = WorkspaceModelConfig(
            model="ollama:gemma4:31b-it-q4_K_M",
            base_url="http://localhost:11434",
        )
        assert config.provider == "ollama"
        assert config.model == "gemma4:31b-it-q4_K_M"
        assert config.base_url == "http://localhost:11434"

    def test_empty_string_provider_not_split(self):
        """Empty string provider should not trigger auto-split."""
        config = WorkspaceModelConfig(provider="", model="provider:model-id")
        assert config.provider == ""
        assert config.model == "provider:model-id"

    def test_legacy_moonshot_via_openai_rejected(self):
        """Pre-0.4.3 'openai + base_url=api.moonshot.ai' shape is hard-rejected."""
        with pytest.raises(ValueError, match="moonshot"):
            WorkspaceModelConfig(
                model="openai:kimi-k2.5",
                base_url="https://api.moonshot.ai/v1",
            )

    def test_legacy_extra_body_thinking_rejected(self):
        """Pre-0.4.3 'extra_body.thinking' shape is hard-rejected."""
        with pytest.raises(ValueError, match="extra_body.thinking"):
            WorkspaceModelConfig(
                provider="openai",
                model="kimi-k2.5",
                extra_body={"thinking": {"type": "disabled"}},
            )

    def test_native_moonshot_thinking_flag(self):
        """Native moonshot provider accepts the top-level thinking flag."""
        config = WorkspaceModelConfig(
            model="moonshot:kimi-k2.5",
            thinking=True,
        )
        assert config.provider == "moonshot"
        assert config.model == "kimi-k2.5"
        assert config.thinking is True
