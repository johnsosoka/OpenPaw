"""Tests for startup deprecation warnings (PRD-003 S-A2)."""

import logging

import pytest

from openpaw.core.config import deprecations
from openpaw.core.config.loader import load_config
from openpaw.core.config.models import Config, ProviderDefinition
from openpaw.core.config.models.workspace import WorkspaceModelConfig


@pytest.fixture(autouse=True)
def _reset_warned():
    """Isolate the once-per-process guard between tests."""
    deprecations.reset_warnings()
    yield
    deprecations.reset_warnings()


def _catalog_config(**agent_kwargs) -> Config:
    return Config(
        providers={"fast": ProviderDefinition(api_key="k")},
        agent=agent_kwargs,  # type: ignore[arg-type]
    )


class TestGlobalAgentApiKeyWarning:
    def test_warns_when_agent_api_key_set(self, caplog):
        config = Config(agent={"api_key": "sk-test"})  # type: ignore[arg-type]
        with caplog.at_level(logging.WARNING):
            deprecations.warn_deprecated_global_keys(config)
        messages = [r.message for r in caplog.records]
        assert any("agent.api_key" in m and "0.6" in m for m in messages)

    def test_no_warning_without_api_key(self, caplog):
        with caplog.at_level(logging.WARNING):
            deprecations.warn_deprecated_global_keys(Config())
        assert not caplog.records

    def test_warns_only_once(self, caplog):
        config = Config(agent={"api_key": "sk-test"})  # type: ignore[arg-type]
        with caplog.at_level(logging.WARNING):
            deprecations.warn_deprecated_global_keys(config)
            deprecations.warn_deprecated_global_keys(config)
        assert len(caplog.records) == 1

    def test_load_config_emits_warning(self, tmp_path, caplog):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("agent:\n  api_key: sk-test\n")
        with caplog.at_level(logging.WARNING):
            load_config(config_file)
        assert any("agent.api_key" in r.message for r in caplog.records)


class TestWorkspaceInlineCredentialWarnings:
    def test_warns_per_inline_key_when_catalog_exists(self, caplog):
        model = WorkspaceModelConfig(
            provider="openai",
            model="gpt-4o",
            api_key="sk-test",
            base_url="https://example.com/v1",
            region="us-east-1",
        )
        with caplog.at_level(logging.WARNING):
            deprecations.warn_deprecated_workspace_model_keys(
                _catalog_config(), model, "gilfoyle"
            )
        messages = [r.message for r in caplog.records]
        assert len(messages) == 3
        for key in ("model.api_key", "model.base_url", "model.region"):
            assert any(key in m and "gilfoyle" in m and "0.6" in m for m in messages)

    def test_no_warning_without_catalog(self, caplog):
        model = WorkspaceModelConfig(model="gpt-4o", api_key="sk-test")
        with caplog.at_level(logging.WARNING):
            deprecations.warn_deprecated_workspace_model_keys(
                Config(), model, "gilfoyle"
            )
        assert not caplog.records

    def test_no_warning_without_inline_credentials(self, caplog):
        model = WorkspaceModelConfig(provider="anthropic", model="claude-test")
        with caplog.at_level(logging.WARNING):
            deprecations.warn_deprecated_workspace_model_keys(
                _catalog_config(), model, "gilfoyle"
            )
        assert not caplog.records

    def test_no_warning_for_none_model_config(self, caplog):
        with caplog.at_level(logging.WARNING):
            deprecations.warn_deprecated_workspace_model_keys(
                _catalog_config(), None, "gilfoyle"
            )
        assert not caplog.records

    def test_warns_only_once_per_key_per_workspace(self, caplog):
        model = WorkspaceModelConfig(model="gpt-4o", api_key="sk-test")
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                deprecations.warn_deprecated_workspace_model_keys(
                    _catalog_config(), model, "gilfoyle"
                )
        assert len(caplog.records) == 1

    def test_distinct_workspaces_each_warn(self, caplog):
        model = WorkspaceModelConfig(model="gpt-4o", api_key="sk-test")
        with caplog.at_level(logging.WARNING):
            deprecations.warn_deprecated_workspace_model_keys(
                _catalog_config(), model, "gilfoyle"
            )
            deprecations.warn_deprecated_workspace_model_keys(
                _catalog_config(), model, "dinesh"
            )
        assert len(caplog.records) == 2


class TestMisplacedWorkspaceKeys:
    """harness:/learning: in global config.yaml are silently swallowed —
    warn so the extra=forbid fail-fast intent isn't defeated (T5 finding)."""

    def test_warns_on_global_harness_key(self, caplog):
        from openpaw.core.config.deprecations import (
            reset_warnings,
            warn_misplaced_workspace_keys,
        )

        reset_warnings()
        with caplog.at_level(logging.WARNING):
            warn_misplaced_workspace_keys({"harness": {"type": "planner"}})
        assert "harness" in caplog.text
        assert "no effect" in caplog.text

    def test_warns_on_global_learning_key_once(self, caplog):
        from openpaw.core.config.deprecations import (
            reset_warnings,
            warn_misplaced_workspace_keys,
        )

        reset_warnings()
        with caplog.at_level(logging.WARNING):
            warn_misplaced_workspace_keys({"learning": {"enabled": True}})
            warn_misplaced_workspace_keys({"learning": {"enabled": True}})
        assert caplog.text.count("'learning:'") == 1

    def test_silent_without_misplaced_keys(self, caplog):
        from openpaw.core.config.deprecations import (
            reset_warnings,
            warn_misplaced_workspace_keys,
        )

        reset_warnings()
        with caplog.at_level(logging.WARNING):
            warn_misplaced_workspace_keys({"agent": {}, "providers": {}})
        assert "no effect" not in caplog.text
