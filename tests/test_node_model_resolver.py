"""Tests for NodeModelResolver (ADR-103 per-node model resolution)."""

from openpaw.core.config.models import NodeModelConfig, ProviderDefinition
from openpaw.workspace.model_resolver import ModelResolver
from openpaw.workspace.node_model_resolver import NodeModelResolver


def make_resolver(catalog: dict[str, ProviderDefinition] | None = None) -> NodeModelResolver:
    resolver = ModelResolver(
        provider_catalog=catalog or {},
        configured_model="anthropic:claude-sonnet-4-20250514",
        api_key="ws-key",
        region=None,
        extra_model_kwargs={"thinking": True},
    )
    return NodeModelResolver(
        resolver=resolver,
        workspace_model="anthropic:claude-sonnet-4-20250514",
        workspace_api_key="ws-key",
        workspace_temperature=0.7,
        workspace_region=None,
        workspace_extra_kwargs={"thinking": True},
    )


class TestInheritedNode:
    def test_unset_model_inherits_workspace(self) -> None:
        r = make_resolver().resolve_node(NodeModelConfig())
        assert r.inherited
        assert r.model_str == "anthropic:claude-sonnet-4-20250514"
        assert r.api_key == "ws-key"
        assert r.temperature == 0.7
        assert r.extra_kwargs.get("thinking") is True  # workspace extras kept

    def test_node_temperature_overrides_for_node_only(self) -> None:
        nmr = make_resolver()
        hot = nmr.resolve_node(NodeModelConfig(temperature=1.0))
        cold = nmr.resolve_node(NodeModelConfig())
        assert hot.temperature == 1.0
        assert cold.temperature == 0.7

    def test_node_max_tokens_lands_in_extras(self) -> None:
        r = make_resolver().resolve_node(NodeModelConfig(max_tokens=512))
        assert r.extra_kwargs["max_tokens"] == 512


class TestCatalogNode:
    CATALOG = {
        "fast": ProviderDefinition(
            type="openai",
            api_key="fast-key",
            base_url="https://api.inceptionlabs.ai/v1",
            model="mercury-2",
        ),
    }

    def test_catalog_name_resolves_fully(self) -> None:
        r = make_resolver(self.CATALOG).resolve_node(NodeModelConfig(model="fast"))
        assert not r.inherited
        assert r.model_str == "openai:mercury-2"
        assert r.api_key == "fast-key"

    def test_workspace_extras_do_not_leak_to_catalog_node(self) -> None:
        r = make_resolver(self.CATALOG).resolve_node(NodeModelConfig(model="fast"))
        assert "thinking" not in r.extra_kwargs  # ws-specific kwargs stay home
        assert r.extra_kwargs.get("base_url") == "https://api.inceptionlabs.ai/v1"

    def test_provider_model_string_form(self) -> None:
        r = make_resolver().resolve_node(NodeModelConfig(model="openai:gpt-4o-mini"))
        assert not r.inherited
        assert r.model_str == "openai:gpt-4o-mini"
