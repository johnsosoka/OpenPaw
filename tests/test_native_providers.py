"""Tests for native moonshot and ollama providers in create_chat_model.

These tests must run in environments WITHOUT the optional ``[moonshot]`` or
``[ollama]`` extras installed. Each test injects a mock module into
``sys.modules`` so that ``from langchain_moonshot import ChatMoonshot`` (or
the ollama equivalent) inside ``create_chat_model`` succeeds with the mock
regardless of whether the real package is present.
"""

import logging
import sys
from unittest.mock import MagicMock, Mock, patch

import pytest

from openpaw.agent.model_factory import create_chat_model


def _mock_module(class_name: str) -> tuple[MagicMock, Mock]:
    """Build a fake module exposing a single mock class.

    Returns ``(module, class_mock)`` — install the module into ``sys.modules``
    with ``patch.dict`` and inspect calls on the class mock.
    """
    cls_mock = Mock()
    cls_mock.return_value = Mock()
    module = MagicMock()
    setattr(module, class_name, cls_mock)
    return module, cls_mock


class TestMoonshotProvider:
    """ChatMoonshot wiring (thinking flag, temperature auto-correct, ImportError)."""

    def test_moonshot_provider_creates_chat_moonshot(self) -> None:
        """`moonshot:` provider instantiates ChatMoonshot with model + api_key."""
        module, mock_cls = _mock_module("ChatMoonshot")
        with patch.dict(sys.modules, {"langchain_moonshot": module}):
            create_chat_model(
                model_str="moonshot:kimi-k2.5",
                api_key="test-key",
                temperature=0.6,
                extra_kwargs={"thinking": False},
            )

        mock_cls.assert_called_once()
        kwargs = mock_cls.call_args[1]
        assert kwargs["model"] == "kimi-k2.5"
        assert kwargs["api_key"] == "test-key"
        assert kwargs["thinking"] is False
        assert kwargs["temperature"] == 0.6

    def test_moonshot_auto_corrects_temperature_for_thinking_false(self) -> None:
        """Framework-default temperature (0.7) auto-corrects to 0.6 when thinking=False."""
        module, mock_cls = _mock_module("ChatMoonshot")
        with patch.dict(sys.modules, {"langchain_moonshot": module}):
            create_chat_model(
                model_str="moonshot:kimi-k2.5",
                api_key="k",
                temperature=0.7,  # framework default — should be replaced
                extra_kwargs={"thinking": False},
            )

        assert mock_cls.call_args[1]["temperature"] == 0.6

    def test_moonshot_auto_corrects_temperature_for_thinking_true(self) -> None:
        """Framework-default temperature (0.7) auto-corrects to 1.0 when thinking=True."""
        module, mock_cls = _mock_module("ChatMoonshot")
        with patch.dict(sys.modules, {"langchain_moonshot": module}):
            create_chat_model(
                model_str="moonshot:kimi-k2.5",
                api_key="k",
                temperature=0.7,
                extra_kwargs={"thinking": True},
            )

        assert mock_cls.call_args[1]["temperature"] == 1.0

    def test_moonshot_respects_explicit_temperature(self) -> None:
        """Explicit non-default temperature is left alone (ChatMoonshot will validate)."""
        module, mock_cls = _mock_module("ChatMoonshot")
        with patch.dict(sys.modules, {"langchain_moonshot": module}):
            create_chat_model(
                model_str="moonshot:kimi-k2.5",
                api_key="k",
                temperature=0.5,  # explicit, non-default
                extra_kwargs={"thinking": False},
            )

        assert mock_cls.call_args[1]["temperature"] == 0.5

    def test_moonshot_forwards_max_retries(self) -> None:
        """max_retries from extra_kwargs is forwarded to ChatMoonshot."""
        module, mock_cls = _mock_module("ChatMoonshot")
        with patch.dict(sys.modules, {"langchain_moonshot": module}):
            create_chat_model(
                model_str="moonshot:kimi-k2.5",
                api_key="k",
                temperature=0.7,
                extra_kwargs={"thinking": False, "max_retries": 5},
            )

        assert mock_cls.call_args[1]["max_retries"] == 5

    def test_moonshot_coerces_none_thinking_to_false(self) -> None:
        """``thinking: None`` (WorkspaceModelConfig default) becomes False, not None."""
        module, mock_cls = _mock_module("ChatMoonshot")
        with patch.dict(sys.modules, {"langchain_moonshot": module}):
            create_chat_model(
                model_str="moonshot:kimi-k2.5",
                api_key="k",
                temperature=0.6,
                extra_kwargs={"thinking": None},
            )

        kwargs = mock_cls.call_args[1]
        assert kwargs["thinking"] is False

    def test_moonshot_missing_package_raises_clear_import_error(self) -> None:
        """Missing langchain-moonshot raises a friendly ImportError with install hint."""
        with patch.dict(sys.modules, {"langchain_moonshot": None}):
            with pytest.raises(ImportError, match=r"openpaw-ai\[moonshot\]"):
                create_chat_model(
                    model_str="moonshot:kimi-k2.5",
                    api_key="k",
                    temperature=0.7,
                    extra_kwargs={"thinking": False},
                )


class TestOllamaProvider:
    """ChatOllama wiring (base_url, no api_key, retry defaults)."""

    def test_ollama_provider_creates_chat_ollama(self) -> None:
        """`ollama:` provider instantiates ChatOllama with model + base_url."""
        module, mock_cls = _mock_module("ChatOllama")
        with patch.dict(sys.modules, {"langchain_ollama": module}):
            create_chat_model(
                model_str="ollama:gemma4:31b-it-q4_K_M",
                api_key=None,
                temperature=0.7,
                extra_kwargs={"base_url": "http://localhost:11434"},
            )

        mock_cls.assert_called_once()
        kwargs = mock_cls.call_args[1]
        # First colon splits, so model name preserves the rest.
        assert kwargs["model"] == "gemma4:31b-it-q4_K_M"
        assert kwargs["base_url"] == "http://localhost:11434"
        assert kwargs["temperature"] == 0.7

    def test_ollama_drops_api_key(self) -> None:
        """Ollama is keyless — api_key must never reach the constructor."""
        module, mock_cls = _mock_module("ChatOllama")
        with patch.dict(sys.modules, {"langchain_ollama": module}):
            create_chat_model(
                model_str="ollama:llama3.1",
                api_key="ignored-key",
                temperature=0.7,
                extra_kwargs={},
            )

        assert "api_key" not in mock_cls.call_args[1]

    def test_ollama_forwards_ollama_specific_kwargs(self) -> None:
        """Ollama-specific knobs (num_ctx, num_predict, keep_alive) reach the constructor."""
        module, mock_cls = _mock_module("ChatOllama")
        with patch.dict(sys.modules, {"langchain_ollama": module}):
            create_chat_model(
                model_str="ollama:llama3.1",
                api_key=None,
                temperature=0.7,
                extra_kwargs={
                    "base_url": "http://localhost:11434",
                    "num_ctx": 8192,
                    "num_predict": 2048,
                    "keep_alive": "5m",
                    "reasoning": True,
                },
            )

        kwargs = mock_cls.call_args[1]
        assert kwargs["num_ctx"] == 8192
        assert kwargs["num_predict"] == 2048
        assert kwargs["keep_alive"] == "5m"
        assert kwargs["reasoning"] is True

    def test_ollama_does_not_pass_max_retries(self) -> None:
        """max_retries should be dropped for ollama (local server, fast-fail preferred)."""
        module, mock_cls = _mock_module("ChatOllama")
        with patch.dict(sys.modules, {"langchain_ollama": module}):
            create_chat_model(
                model_str="ollama:llama3.1",
                api_key=None,
                temperature=0.7,
                extra_kwargs={"max_retries": 5},
            )

        assert "max_retries" not in mock_cls.call_args[1]

    def test_ollama_missing_package_raises_clear_import_error(self) -> None:
        """Missing langchain-ollama raises a friendly ImportError with install hint."""
        with patch.dict(sys.modules, {"langchain_ollama": None}):
            with pytest.raises(ImportError, match=r"openpaw-ai\[ollama\]"):
                create_chat_model(
                    model_str="ollama:llama3.1",
                    api_key=None,
                    temperature=0.7,
                    extra_kwargs={},
                )


class TestProviderCatalogIntegration:
    """End-to-end: provider catalog → resolve_provider → create_chat_model."""

    def test_moonshot_catalog_entry_resolves_to_chat_moonshot(self) -> None:
        """Catalog entry of type=moonshot routes through ChatMoonshot."""
        from openpaw.core.config.models.base import ProviderDefinition
        from openpaw.core.config.providers import resolve_provider

        catalog = {
            "moonshot": ProviderDefinition(type="moonshot", api_key="catalog-key"),
        }
        resolved = resolve_provider("moonshot:kimi-k2.5", catalog)

        assert resolved.model_str == "moonshot:kimi-k2.5"
        assert resolved.display_str == "moonshot:kimi-k2.5"
        assert resolved.api_key == "catalog-key"

        module, mock_cls = _mock_module("ChatMoonshot")
        with patch.dict(sys.modules, {"langchain_moonshot": module}):
            create_chat_model(
                model_str=resolved.model_str,
                api_key=resolved.api_key,
                temperature=0.7,
                extra_kwargs={**resolved.extra_kwargs, "thinking": False},
            )
        mock_cls.assert_called_once()

    def test_ollama_catalog_entry_resolves_to_chat_ollama(self) -> None:
        """Catalog entry of type=ollama routes through ChatOllama with base_url."""
        from openpaw.core.config.models.base import ProviderDefinition
        from openpaw.core.config.providers import resolve_provider

        catalog = {
            "ollama": ProviderDefinition(type="ollama", base_url="http://localhost:11434"),
        }
        resolved = resolve_provider("ollama:gemma4:31b-it-q4_K_M", catalog)

        assert resolved.model_str == "ollama:gemma4:31b-it-q4_K_M"
        assert resolved.extra_kwargs.get("base_url") == "http://localhost:11434"

        module, mock_cls = _mock_module("ChatOllama")
        with patch.dict(sys.modules, {"langchain_ollama": module}):
            create_chat_model(
                model_str=resolved.model_str,
                api_key=None,
                temperature=0.7,
                extra_kwargs=resolved.extra_kwargs,
            )
        assert mock_cls.call_args[1]["base_url"] == "http://localhost:11434"


class TestFireworksThinkingCoercion:
    """Fireworks `thinking` bool is coerced into the object form the API expects.

    The Fireworks API rejects a raw boolean ``thinking: true``; it requires a
    discriminated union like ``{"type": "enabled", "budget_tokens": N}`` or
    ``{"type": "disabled"}``.  These tests verify that ``create_chat_model``
    performs the coercion before the value reaches ``ChatFireworks``.

    ``max_retries=0`` is passed so the retry-patching block (which monkey-patches
    ``model._agenerate``) is skipped — the mock instance doesn't need it and
    skipping it avoids touching live SDK internals.
    """

    def test_thinking_true_produces_enabled_object(self) -> None:
        """`thinking=True` → {"type": "enabled", "budget_tokens": 4096}."""
        module, mock_cls = _mock_module("ChatFireworks")
        with patch.dict(sys.modules, {"langchain_fireworks": module}):
            create_chat_model(
                model_str="fireworks:accounts/fireworks/models/kimi-k2p6",
                api_key="test-key",
                temperature=0.6,
                extra_kwargs={"thinking": True, "max_retries": 0},
            )

        mock_cls.assert_called_once()
        assert mock_cls.call_args[1]["model_kwargs"]["thinking"] == {
            "type": "enabled",
            "budget_tokens": 4096,
        }

    def test_thinking_false_produces_disabled_object(self) -> None:
        """`thinking=False` → {"type": "disabled"}."""
        module, mock_cls = _mock_module("ChatFireworks")
        with patch.dict(sys.modules, {"langchain_fireworks": module}):
            create_chat_model(
                model_str="fireworks:accounts/fireworks/models/kimi-k2p6",
                api_key="test-key",
                temperature=0.6,
                extra_kwargs={"thinking": False, "max_retries": 0},
            )

        assert mock_cls.call_args[1]["model_kwargs"]["thinking"] == {"type": "disabled"}

    def test_thinking_budget_capped_when_max_tokens_equals_budget(self) -> None:
        """`max_tokens=4096` with `thinking=True` → budget capped to 2048.

        The budget must not exceed max_tokens — that would leave no tokens for
        the visible answer.  When ``budget >= max_tokens`` the cap formula is
        ``max(1024, max_tokens // 2)``.
        """
        module, mock_cls = _mock_module("ChatFireworks")
        with patch.dict(sys.modules, {"langchain_fireworks": module}):
            create_chat_model(
                model_str="fireworks:accounts/fireworks/models/kimi-k2p6",
                api_key="test-key",
                temperature=0.6,
                extra_kwargs={"thinking": True, "max_tokens": 4096, "max_retries": 0},
            )

        thinking_obj = mock_cls.call_args[1]["model_kwargs"]["thinking"]
        assert thinking_obj["type"] == "enabled"
        assert thinking_obj["budget_tokens"] == 2048

    def test_thinking_absent_leaves_no_thinking_in_model_kwargs(self) -> None:
        """When `thinking` is not provided, no thinking key appears in model_kwargs.

        Regression guard: other providers (openai, anthropic, xai) must not
        accidentally receive a ``model_kwargs["thinking"]`` entry.
        """
        module, mock_cls = _mock_module("ChatFireworks")
        with patch.dict(sys.modules, {"langchain_fireworks": module}):
            create_chat_model(
                model_str="fireworks:accounts/fireworks/models/kimi-k2p6",
                api_key="test-key",
                temperature=0.6,
                extra_kwargs={"max_retries": 0},
            )

        call_kwargs = mock_cls.call_args[1]
        model_kwargs = call_kwargs.get("model_kwargs", {})
        assert "thinking" not in model_kwargs


class TestAnthropicExtendedThinkingNotRejected:
    """Regression guard: the legacy validator must not block Anthropic's extra_body.thinking."""

    def test_anthropic_extra_body_thinking_accepted(self) -> None:
        """Anthropic's extended-thinking budget via extra_body.thinking is allowed."""
        from openpaw.core.config.models.workspace import WorkspaceModelConfig

        # Anthropic uses extra_body: {thinking: {type: enabled, budget_tokens: 5000}}
        # natively. The 0.4.3 legacy guard is scoped to provider='openai' only.
        config = WorkspaceModelConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            extra_body={"thinking": {"type": "enabled", "budget_tokens": 5000}},
        )
        assert config.provider == "anthropic"


class TestThinkingLeakGuard:
    """`thinking` must never leak into an unsupported provider's constructor.

    When ``thinking`` is passed as a top-level extra_kwarg to a provider that
    doesn't consume it (i.e., NOT moonshot or fireworks), the central pop in
    ``create_chat_model`` must:

    1. Remove it from the kwargs before the constructor is called.
    2. Emit a WARNING containing "not supported for provider".

    Existing moonshot + fireworks tests are unaffected: those providers are in
    ``THINKING_SUPPORTED_PROVIDERS`` so no warning is emitted and the value is
    forwarded to the provider branch for proper coercion.
    """

    @pytest.mark.parametrize(
        "model_str, module_name, cls_name, region, extra_kwargs",
        [
            pytest.param(
                "openai:gpt-4o",
                "langchain_openai",
                "ChatOpenAI",
                None,
                {"thinking": True, "max_retries": 0},
                id="openai",
            ),
            pytest.param(
                "anthropic:claude-sonnet-4-20250514",
                "langchain_anthropic",
                "ChatAnthropic",
                None,
                {"thinking": True, "max_retries": 0},
                id="anthropic",
            ),
            pytest.param(
                "xai:grok-3",
                "langchain_xai",
                "ChatXAI",
                None,
                {"thinking": True, "max_retries": 0},
                id="xai",
            ),
            pytest.param(
                "bedrock_converse:anthropic.claude-3-5-sonnet-20241022-v2:0",
                "langchain_aws",
                "ChatBedrockConverse",
                "us-east-1",
                {"thinking": True, "max_retries": 0},
                id="bedrock_converse",
            ),
            pytest.param(
                "ollama:llama3.1",
                "langchain_ollama",
                "ChatOllama",
                None,
                {"thinking": True, "max_retries": 0, "base_url": "http://localhost:11434"},
                id="ollama",
            ),
        ],
    )
    def test_thinking_never_leaks_to_constructor(
        self,
        model_str: str,
        module_name: str,
        cls_name: str,
        region: str | None,
        extra_kwargs: dict,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """``thinking=True`` is stripped before any unsupported provider constructor is called."""
        module, mock_cls = _mock_module(cls_name)
        with caplog.at_level(logging.WARNING, logger="openpaw.agent.model_factory"):
            with patch.dict(sys.modules, {module_name: module}):
                create_chat_model(
                    model_str=model_str,
                    api_key="test-key",
                    temperature=0.6,
                    region=region,
                    extra_kwargs=extra_kwargs,
                )

        mock_cls.assert_called_once()
        constructor_kwargs = mock_cls.call_args[1]
        assert "thinking" not in constructor_kwargs, (
            f"'thinking' leaked into {cls_name} constructor kwargs: {constructor_kwargs}"
        )
        assert "thinking" not in constructor_kwargs.get("model_kwargs", {}), (
            f"'thinking' leaked into {cls_name} model_kwargs: {constructor_kwargs.get('model_kwargs')}"
        )
        assert any("not supported for provider" in msg for msg in caplog.messages), (
            f"Expected warning about unsupported 'thinking' for {model_str!r}. "
            f"Got log messages: {caplog.messages}"
        )
