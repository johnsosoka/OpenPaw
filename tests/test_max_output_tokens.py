"""Tests for max_output_tokens cap on stateless agents."""

from unittest.mock import MagicMock

import pytest

from openpaw.core.config.models import CronDefinition, HeartbeatConfig, WorkspaceModelConfig
from openpaw.workspace.agent_factory import AgentFactory


# ---------------------------------------------------------------------------
# Config model field presence
# ---------------------------------------------------------------------------


class TestWorkspaceModelConfigField:
    """WorkspaceModelConfig accepts the max_output_tokens field."""

    def test_default_is_none(self):
        """max_output_tokens defaults to None (uncapped)."""
        cfg = WorkspaceModelConfig()
        assert cfg.max_output_tokens is None

    def test_explicit_value(self):
        """max_output_tokens stores the provided integer."""
        cfg = WorkspaceModelConfig(max_output_tokens=2000)
        assert cfg.max_output_tokens == 2000

    def test_zero_not_treated_as_none(self):
        """A value of 0 is distinct from None."""
        cfg = WorkspaceModelConfig(max_output_tokens=0)
        assert cfg.max_output_tokens == 0


class TestHeartbeatConfigField:
    """HeartbeatConfig accepts the max_output_tokens field."""

    def test_default_is_none(self):
        cfg = HeartbeatConfig()
        assert cfg.max_output_tokens is None

    def test_explicit_value(self):
        cfg = HeartbeatConfig(max_output_tokens=1500)
        assert cfg.max_output_tokens == 1500


class TestCronDefinitionField:
    """CronDefinition accepts the max_output_tokens field."""

    def test_default_is_none(self):
        cron = CronDefinition(
            name="test-job",
            schedule="0 9 * * *",
            prompt="Do something",
            output={"channel": "telegram"},
        )
        assert cron.max_output_tokens is None

    def test_explicit_value(self):
        cron = CronDefinition(
            name="test-job",
            schedule="0 9 * * *",
            prompt="Do something",
            output={"channel": "telegram"},
            max_output_tokens=3000,
        )
        assert cron.max_output_tokens == 3000


# ---------------------------------------------------------------------------
# AgentFactory.create_stateless_agent with extra_overrides
# ---------------------------------------------------------------------------


def _make_factory() -> AgentFactory:
    """Build a minimal AgentFactory with mocked dependencies."""
    workspace = MagicMock()
    workspace.name = "test-workspace"
    workspace.path = MagicMock()
    workspace.config = MagicMock()
    workspace.config.timezone = "UTC"

    factory = AgentFactory(
        workspace=workspace,
        model="anthropic:claude-haiku",
        api_key="fake-key",
        max_turns=10,
        temperature=0.5,
        region=None,
        timeout_seconds=60.0,
        builtin_tools=[],
        workspace_tools=[],
        enabled_builtin_names=[],
        extra_model_kwargs={"some_existing_kwarg": True},
        middleware=[],
        logger=MagicMock(),
        provider_catalog=None,
    )
    return factory


class TestCreateStatelessAgentOverrides:
    """create_stateless_agent merges extra_overrides correctly."""

    def test_no_overrides_preserves_existing_kwargs(self):
        """Without extra_overrides the workspace kwargs pass through unchanged."""
        factory = _make_factory()

        # Patch AgentRunner to capture the kwargs it receives
        captured: dict = {}

        def fake_runner(**kwargs):
            captured.update(kwargs)
            return MagicMock()

        import openpaw.workspace.agent_factory as mod
        original = mod.AgentRunner
        mod.AgentRunner = lambda **kw: (captured.update(kw) or MagicMock())

        try:
            factory.create_stateless_agent()
        except Exception:
            pass
        finally:
            mod.AgentRunner = original

        # extra_model_kwargs forwarded to runner should not contain max_tokens
        assert "max_tokens" not in captured.get("extra_model_kwargs", {})
        assert captured.get("extra_model_kwargs", {}).get("some_existing_kwarg") is True

    def test_extra_overrides_injects_max_tokens(self):
        """extra_overrides with max_tokens propagates to AgentRunner."""
        factory = _make_factory()

        captured: dict = {}

        import openpaw.workspace.agent_factory as mod
        original = mod.AgentRunner
        mod.AgentRunner = lambda **kw: (captured.update(kw) or MagicMock())

        try:
            factory.create_stateless_agent(extra_overrides={"max_tokens": 1500})
        except Exception:
            pass
        finally:
            mod.AgentRunner = original

        assert captured.get("extra_model_kwargs", {}).get("max_tokens") == 1500

    def test_extra_overrides_wins_over_workspace_kwargs(self):
        """extra_overrides values override identically-named workspace kwargs."""
        factory = _make_factory()
        # Inject a base max_tokens via the factory's own kwargs
        factory._extra_model_kwargs["max_tokens"] = 5000

        captured: dict = {}

        import openpaw.workspace.agent_factory as mod
        original = mod.AgentRunner
        mod.AgentRunner = lambda **kw: (captured.update(kw) or MagicMock())

        try:
            factory.create_stateless_agent(extra_overrides={"max_tokens": 1000})
        except Exception:
            pass
        finally:
            mod.AgentRunner = original

        # Per-call override (1000) wins over workspace-level default (5000)
        assert captured.get("extra_model_kwargs", {}).get("max_tokens") == 1000


# ---------------------------------------------------------------------------
# Factory closure forwards kwargs
# ---------------------------------------------------------------------------


class TestFactoryClosureKwargs:
    """get_agent_factory_closure returns a callable that forwards kwargs."""

    def test_closure_accepts_keyword_args(self):
        """The closure should accept **kwargs without raising TypeError."""
        factory = _make_factory()
        closure = factory.get_agent_factory_closure()

        received: dict = {}

        import openpaw.workspace.agent_factory as mod
        original = mod.AgentRunner
        mod.AgentRunner = lambda **kw: (received.update(kw) or MagicMock())

        try:
            closure(extra_overrides={"max_tokens": 800})
        except Exception:
            pass
        finally:
            mod.AgentRunner = original

        assert received.get("extra_model_kwargs", {}).get("max_tokens") == 800

    def test_closure_no_args_behaves_as_before(self):
        """Calling closure without args remains backward-compatible."""
        factory = _make_factory()
        closure = factory.get_agent_factory_closure()

        received: dict = {}

        import openpaw.workspace.agent_factory as mod
        original = mod.AgentRunner
        mod.AgentRunner = lambda **kw: (received.update(kw) or MagicMock())

        try:
            closure()
        except Exception:
            pass
        finally:
            mod.AgentRunner = original

        # No max_tokens injected when not requested
        assert "max_tokens" not in received.get("extra_model_kwargs", {})


# ---------------------------------------------------------------------------
# AgentRunner.max_output_tokens property
# ---------------------------------------------------------------------------


class TestAgentRunnerMaxOutputTokensProperty:
    """AgentRunner exposes a max_output_tokens property from extra_model_kwargs."""

    def _make_runner(self, extra_model_kwargs=None):
        """Create an AgentRunner with patched _build_agent to avoid real LangGraph."""
        from openpaw.agent.runner import AgentRunner

        workspace = MagicMock()
        workspace.name = "test"
        workspace.path = MagicMock()
        workspace.config = MagicMock()
        workspace.config.timezone = "UTC"
        workspace.build_system_prompt = MagicMock(return_value="sys")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(AgentRunner, "_build_agent", lambda self: MagicMock())
            runner = AgentRunner(
                workspace=workspace,
                model="anthropic:claude-haiku",
                api_key="fake",
                extra_model_kwargs=extra_model_kwargs,
            )
        return runner

    def test_property_returns_none_when_not_set(self):
        """max_output_tokens is None when extra_model_kwargs has no max_tokens."""
        runner = self._make_runner()
        assert runner.max_output_tokens is None

    def test_property_returns_value_when_set(self):
        """max_output_tokens reflects the max_tokens value from extra_model_kwargs."""
        runner = self._make_runner(extra_model_kwargs={"max_tokens": 2000})
        assert runner.max_output_tokens == 2000
