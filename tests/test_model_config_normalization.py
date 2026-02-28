"""Tests for WorkspaceModelConfig provider:model auto-split."""

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

    def test_extra_kwargs_preserved(self):
        """Extra kwargs (like base_url) are preserved through normalization."""
        config = WorkspaceModelConfig(
            model="openai:kimi-k2.5",
            base_url="https://api.moonshot.ai/v1",
        )
        assert config.provider == "openai"
        assert config.model == "kimi-k2.5"
        assert config.base_url == "https://api.moonshot.ai/v1"

    def test_empty_string_provider_not_split(self):
        """Empty string provider should not trigger auto-split."""
        config = WorkspaceModelConfig(provider="", model="provider:model-id")
        assert config.provider == ""
        assert config.model == "provider:model-id"
