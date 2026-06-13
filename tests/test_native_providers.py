"""Tests for native moonshot and ollama providers in create_chat_model.

These tests must run in environments WITHOUT the optional ``[moonshot]`` or
``[ollama]`` extras installed. Each test injects a mock module into
``sys.modules`` so that ``from langchain_moonshot import ChatMoonshot`` (or
the ollama equivalent) inside ``create_chat_model`` succeeds with the mock
regardless of whether the real package is present.
"""

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
