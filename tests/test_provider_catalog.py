"""Tests for the provider catalog feature.

Covers:
- resolve_provider() resolution logic
- Config model changes (ProviderDefinition, Config.providers, WorkspaceConfig shorthand)
- AgentFactory integration with provider_catalog parameter
"""

from unittest.mock import MagicMock, patch

from openpaw.agent.runner import AgentRunner
from openpaw.core.config.models import Config, ProviderDefinition, WorkspaceConfig
from openpaw.core.config.providers import resolve_provider
from openpaw.workspace.agent_factory import AgentFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_catalog(**entries: dict) -> dict[str, ProviderDefinition]:
    """Build a catalog dict from keyword args."""
    return {name: ProviderDefinition(**kwargs) for name, kwargs in entries.items()}


def _make_factory(
    model: str = "anthropic:claude-test",
    api_key: str | None = "test-key",
    catalog: dict[str, ProviderDefinition] | None = None,
) -> AgentFactory:
    """Create a minimal AgentFactory with optional catalog."""
    with patch.object(AgentRunner, "__init__", return_value=None):
        return AgentFactory(
            workspace=MagicMock(),
            model=model,
            api_key=api_key,
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


# ---------------------------------------------------------------------------
# resolve_provider() — core resolution logic
# ---------------------------------------------------------------------------


class TestResolveProvider:
    """Tests for the resolve_provider() function."""

    def test_unknown_provider_passes_through_unchanged(self):
        """Unknown provider returns pass-through with None key/region and empty extras."""
        result = resolve_provider("anthropic:claude-sonnet", {})
        assert result.model_str == "anthropic:claude-sonnet"
        assert result.display_str == "anthropic:claude-sonnet"
        assert result.api_key is None
        assert result.region is None
        assert result.extra_kwargs == {}

    def test_native_provider_type_defaults_to_key_name(self):
        """When type is None in catalog, langchain_type defaults to the catalog key."""
        catalog = _make_catalog(anthropic={"api_key": "ant-key"})
        result = resolve_provider("anthropic:claude-sonnet", catalog)

        # type not set → defaults to "anthropic"
        assert result.model_str == "anthropic:claude-sonnet"
        assert result.display_str == "anthropic:claude-sonnet"
        assert result.api_key == "ant-key"
        assert result.region is None
        assert result.extra_kwargs == {}

    def test_custom_type_mapping(self):
        """Catalog entry with type='openai' remaps the model_str provider."""
        catalog = _make_catalog(moonshot={"type": "openai", "api_key": "ms-key", "base_url": "https://api.moonshot.ai/v1"})
        result = resolve_provider("moonshot:kimi-k2.5", catalog)

        # LangChain should see openai type
        assert result.model_str == "openai:kimi-k2.5"
        # User-facing display preserves the catalog name
        assert result.display_str == "moonshot:kimi-k2.5"
        assert result.api_key == "ms-key"
        assert result.extra_kwargs == {"base_url": "https://api.moonshot.ai/v1"}

    def test_base_url_flows_into_extra_kwargs(self):
        """base_url set on provider appears in extra_kwargs."""
        catalog = _make_catalog(
            custom={"type": "openai", "api_key": "k", "base_url": "https://custom.example.com/v1"}
        )
        result = resolve_provider("custom:my-model", catalog)

        assert result.extra_kwargs == {"base_url": "https://custom.example.com/v1"}

    def test_extra_fields_via_model_config_extra_allow(self):
        """Arbitrary extra fields on ProviderDefinition appear in extra_kwargs."""
        definition = ProviderDefinition(
            type="openai",
            api_key="k",
            base_url="https://example.com",
            timeout=60,
            extra_body={"thinking": {"type": "disabled"}},
        )
        catalog = {"myprovider": definition}
        result = resolve_provider("myprovider:some-model", catalog)

        assert result.extra_kwargs["base_url"] == "https://example.com"
        assert result.extra_kwargs["timeout"] == 60
        assert result.extra_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        # Excluded fields should NOT appear
        assert "type" not in result.extra_kwargs
        assert "api_key" not in result.extra_kwargs
        assert "region" not in result.extra_kwargs

    def test_region_passes_through(self):
        """Region set on a provider definition is surfaced on the resolved object."""
        catalog = _make_catalog(bedrock={"region": "us-east-1"})
        result = resolve_provider("bedrock:claude-haiku", catalog)

        assert result.region == "us-east-1"
        assert result.model_str == "bedrock:claude-haiku"

    def test_bedrock_provider_no_api_key(self):
        """Bedrock provider in catalog carries no api_key (AWS creds via env)."""
        catalog = _make_catalog(bedrock={"type": "bedrock_converse", "region": "us-east-1"})
        result = resolve_provider("bedrock:moonshot.kimi", catalog)

        assert result.api_key is None
        assert result.model_str == "bedrock_converse:moonshot.kimi"
        assert result.region == "us-east-1"

    def test_empty_catalog_equals_backward_compat(self):
        """An empty catalog produces pass-through for every model string."""
        for model in ["anthropic:claude", "openai:gpt-4", "bedrock_converse:model"]:
            result = resolve_provider(model, {})
            assert result.model_str == model
            assert result.display_str == model
            assert result.api_key is None
            assert result.extra_kwargs == {}

    def test_model_without_colon_passes_through(self):
        """A bare model string with no colon is returned unchanged."""
        result = resolve_provider("just-a-model", {})
        assert result.model_str == "just-a-model"
        assert result.display_str == "just-a-model"
        assert result.api_key is None

    def test_provider_with_all_none_fields(self):
        """A provider with all None fields still resolves; type defaults to key."""
        catalog = _make_catalog(myprovider={})
        result = resolve_provider("myprovider:some-model", catalog)

        assert result.model_str == "myprovider:some-model"
        assert result.display_str == "myprovider:some-model"
        assert result.api_key is None
        assert result.region is None
        assert result.extra_kwargs == {}

    def test_none_fields_excluded_from_extra_kwargs(self):
        """None-valued fields on ProviderDefinition are excluded from extra_kwargs."""
        catalog = _make_catalog(myprovider={"type": "openai", "base_url": None})
        result = resolve_provider("myprovider:model", catalog)

        assert "base_url" not in result.extra_kwargs


# ---------------------------------------------------------------------------
# Config model changes
# ---------------------------------------------------------------------------


class TestConfigModels:
    """Tests for config model additions in Phase 1."""

    def test_workspace_config_string_coercion_with_colon(self):
        """'model: provider:model_id' shorthand in agent.yaml is coerced correctly."""
        config = WorkspaceConfig.model_validate({"model": "anthropic:claude-sonnet-4-20250514"})

        assert config.model.provider == "anthropic"
        assert config.model.model == "claude-sonnet-4-20250514"

    def test_workspace_config_string_coercion_without_colon(self):
        """A bare model name without colon is coerced to model-only dict."""
        config = WorkspaceConfig.model_validate({"model": "claude-sonnet"})

        assert config.model.provider is None
        assert config.model.model == "claude-sonnet"

    def test_config_providers_field_accepts_dict(self):
        """Config.providers accepts a dict of ProviderDefinition entries."""
        config = Config.model_validate({
            "providers": {
                "moonshot": {"type": "openai", "api_key": "key", "base_url": "https://api.moonshot.ai/v1"},
                "bedrock": {"type": "bedrock_converse", "region": "us-east-1"},
            }
        })

        assert "moonshot" in config.providers
        assert config.providers["moonshot"].type == "openai"
        assert config.providers["moonshot"].api_key == "key"
        assert "bedrock" in config.providers
        assert config.providers["bedrock"].region == "us-east-1"

    def test_config_providers_defaults_to_empty_dict(self):
        """Config.providers defaults to an empty dict when not specified."""
        config = Config.model_validate({})
        assert config.providers == {}

    def test_provider_definition_accepts_extra_fields(self):
        """ProviderDefinition allows arbitrary extra fields via extra='allow'."""
        definition = ProviderDefinition.model_validate({
            "type": "openai",
            "api_key": "k",
            "base_url": "https://api.example.com",
            "timeout": 30,
            "custom_param": "value",
        })

        assert definition.type == "openai"
        assert definition.timeout == 30
        assert definition.custom_param == "value"


# ---------------------------------------------------------------------------
# AgentFactory integration
# ---------------------------------------------------------------------------


class TestAgentFactoryProviderCatalog:
    """Tests for AgentFactory with provider_catalog."""

    def test_no_catalog_defaults_to_empty(self):
        """When no catalog is passed, _provider_catalog defaults to {}."""
        factory = _make_factory()
        assert factory._provider_catalog == {}

    def test_resolve_for_model_uses_catalog(self):
        """_resolve_for_model() resolves through the catalog correctly."""
        catalog = _make_catalog(
            moonshot={"type": "openai", "api_key": "ms-key", "base_url": "https://api.moonshot.ai/v1"}
        )
        factory = _make_factory(model="moonshot:kimi-k2.5", api_key=None, catalog=catalog)

        resolved = factory._resolve_for_model("moonshot:kimi-k2.5")
        assert resolved.model_str == "openai:kimi-k2.5"
        assert resolved.display_str == "moonshot:kimi-k2.5"
        assert resolved.api_key == "ms-key"

    def test_resolve_api_key_prefers_catalog(self):
        """_resolve_api_key() returns catalog api_key over env lookup."""
        catalog = _make_catalog(
            moonshot={"type": "openai", "api_key": "catalog-key", "base_url": "https://api.moonshot.ai/v1"}
        )
        factory = _make_factory(model="moonshot:kimi-k2.5", api_key=None, catalog=catalog)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "env-key"}):
            key = factory._resolve_api_key("moonshot:kimi-k2.5")

        assert key == "catalog-key"

    def test_resolve_api_key_falls_back_to_env(self):
        """_resolve_api_key() falls back to env var when catalog has no api_key."""
        catalog = _make_catalog(moonshot={"type": "openai", "base_url": "https://api.moonshot.ai/v1"})
        factory = _make_factory(model="moonshot:kimi-k2.5", api_key=None, catalog=catalog)

        with patch.dict("os.environ", {"OPENAI_API_KEY": "env-key"}):
            key = factory._resolve_api_key("moonshot:kimi-k2.5")

        assert key == "env-key"

    def test_resolve_api_key_same_provider_reuses_configured(self):
        """_resolve_api_key() returns the configured api_key when provider matches."""
        # No catalog entry for anthropic → falls back to same-provider check.
        factory = _make_factory(model="anthropic:claude-test", api_key="test-key")
        key = factory._resolve_api_key("anthropic:claude-other")
        assert key == "test-key"

    def test_active_model_returns_display_str(self):
        """active_model property returns the user-facing catalog name."""
        catalog = _make_catalog(
            moonshot={"type": "openai", "api_key": "k", "base_url": "https://api.moonshot.ai/v1"}
        )
        factory = _make_factory(model="moonshot:kimi-k2.5", api_key=None, catalog=catalog)

        # display_str should be the catalog name, not the LangChain type
        assert factory.active_model == "moonshot:kimi-k2.5"

    def test_configured_model_returns_display_str(self):
        """configured_model property returns the user-facing catalog name."""
        catalog = _make_catalog(
            moonshot={"type": "openai", "api_key": "k", "base_url": "https://api.moonshot.ai/v1"}
        )
        factory = _make_factory(model="moonshot:kimi-k2.5", api_key=None, catalog=catalog)
        assert factory.configured_model == "moonshot:kimi-k2.5"

    def test_active_model_passthrough_when_not_in_catalog(self):
        """active_model is unchanged when provider is not in catalog."""
        factory = _make_factory(model="anthropic:claude-test", api_key="key")
        assert factory.active_model == "anthropic:claude-test"

    def test_catalog_extras_merged_into_agent_runner(self):
        """create_agent() merges catalog extra_kwargs; workspace extras win."""
        catalog = _make_catalog(
            moonshot={"type": "openai", "api_key": "k", "base_url": "https://api.moonshot.ai/v1"}
        )
        with patch.object(AgentRunner, "__init__", return_value=None):
            factory = AgentFactory(
                workspace=MagicMock(),
                model="moonshot:kimi-k2.5",
                api_key=None,
                max_turns=50,
                temperature=0.7,
                region=None,
                timeout_seconds=300.0,
                builtin_tools=[],
                workspace_tools=[],
                enabled_builtin_names=[],
                extra_model_kwargs={"timeout": 30},  # workspace-level extras
                middleware=[],
                logger=MagicMock(),
                provider_catalog=catalog,
            )

        with patch.object(AgentRunner, "__init__", return_value=None) as mock_init:
            factory.create_agent()

        _, kwargs = mock_init.call_args
        merged = kwargs["extra_model_kwargs"]
        # Catalog provides base_url; workspace provides timeout.
        assert merged["base_url"] == "https://api.moonshot.ai/v1"
        assert merged["timeout"] == 30

    def test_workspace_extras_override_catalog_extras(self):
        """Workspace-level extra_model_kwargs overrides conflicting catalog values."""
        catalog = _make_catalog(
            moonshot={
                "type": "openai",
                "api_key": "k",
                "base_url": "https://api.moonshot.ai/v1",
                "timeout": 60,  # catalog default
            }
        )
        with patch.object(AgentRunner, "__init__", return_value=None):
            factory = AgentFactory(
                workspace=MagicMock(),
                model="moonshot:kimi-k2.5",
                api_key=None,
                max_turns=50,
                temperature=0.7,
                region=None,
                timeout_seconds=300.0,
                builtin_tools=[],
                workspace_tools=[],
                enabled_builtin_names=[],
                extra_model_kwargs={"timeout": 999},  # workspace overrides catalog
                middleware=[],
                logger=MagicMock(),
                provider_catalog=catalog,
            )

        with patch.object(AgentRunner, "__init__", return_value=None) as mock_init:
            factory.create_agent()

        _, kwargs = mock_init.call_args
        assert kwargs["extra_model_kwargs"]["timeout"] == 999

    def test_create_agent_uses_resolved_model_str(self):
        """create_agent() passes the LangChain model_str (not catalog name) to AgentRunner."""
        catalog = _make_catalog(
            moonshot={"type": "openai", "api_key": "k", "base_url": "https://api.moonshot.ai/v1"}
        )
        with patch.object(AgentRunner, "__init__", return_value=None):
            factory = AgentFactory(
                workspace=MagicMock(),
                model="moonshot:kimi-k2.5",
                api_key=None,
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

        with patch.object(AgentRunner, "__init__", return_value=None) as mock_init:
            factory.create_agent()

        _, kwargs = mock_init.call_args
        # LangChain receives "openai:kimi-k2.5", not "moonshot:kimi-k2.5"
        assert kwargs["model"] == "openai:kimi-k2.5"

    def test_create_stateless_agent_uses_configured_model(self):
        """create_stateless_agent() uses configured model, ignoring runtime override."""
        catalog = _make_catalog(
            moonshot={"type": "openai", "api_key": "k", "base_url": "https://api.moonshot.ai/v1"}
        )
        with patch.object(AgentRunner, "__init__", return_value=None):
            factory = AgentFactory(
                workspace=MagicMock(),
                model="moonshot:kimi-k2.5",
                api_key=None,
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

        from openpaw.workspace.agent_factory import RuntimeModelOverride
        factory.set_runtime_override(RuntimeModelOverride(model="anthropic:claude-sonnet"))

        with patch.object(AgentRunner, "__init__", return_value=None) as mock_init:
            factory.create_stateless_agent()

        _, kwargs = mock_init.call_args
        # Stateless agent ignores override → should use resolved configured model
        assert kwargs["model"] == "openai:kimi-k2.5"

    def test_validate_model_resolves_through_catalog(self):
        """validate_model() resolves catalog provider before checking support.

        validate_model() does a local ``from openpaw.agent.runner import
        create_chat_model`` inside the function body, so we intercept by
        replacing the attribute on the source module before the call.
        """
        import openpaw.agent.runner as runner_mod

        catalog = _make_catalog(
            moonshot={"type": "openai", "api_key": "catalog-key", "base_url": "https://api.moonshot.ai/v1"}
        )
        factory = _make_factory(model="moonshot:kimi-k2.5", api_key=None, catalog=catalog)

        captured_args: list = []

        def fake_create_chat_model(*args, **kwargs):
            captured_args.append(args)
            return MagicMock()

        original = runner_mod.create_chat_model
        runner_mod.create_chat_model = fake_create_chat_model
        try:
            valid, msg = factory.validate_model("moonshot:kimi-k2.5")
        finally:
            runner_mod.create_chat_model = original

        assert valid is True
        assert len(captured_args) == 1
        # First positional arg is the model string — must be the resolved LangChain type.
        assert captured_args[0][0] == "openai:kimi-k2.5"

    def test_region_from_catalog_passed_to_agent_runner(self):
        """Catalog-defined region is passed through to AgentRunner."""
        catalog = _make_catalog(
            bedrock={"type": "bedrock_converse", "region": "us-east-1"}
        )
        with patch.object(AgentRunner, "__init__", return_value=None):
            factory = AgentFactory(
                workspace=MagicMock(),
                model="bedrock:claude-haiku",
                api_key=None,
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

        with patch.object(AgentRunner, "__init__", return_value=None) as mock_init:
            factory.create_agent()

        _, kwargs = mock_init.call_args
        assert kwargs["region"] == "us-east-1"
        assert kwargs["model"] == "bedrock_converse:claude-haiku"
