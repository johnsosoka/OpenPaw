"""Tests for CLI init template helpers and model string parsing."""


import pytest
import yaml

from openpaw.cli_init.templates import (
    _build_agent_yaml,
    _parse_model_string,
)


class TestBuildAgentYaml:
    """Unit tests for _build_agent_yaml()."""

    def test_no_flags_model_section_commented_out(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, None)
        assert "# model:" in yaml_text
        # The top-level model key must NOT be present as an active YAML key
        # (i.e., no line starting with "model:" without a leading #).
        active_keys = {
            line.split(":")[0]
            for line in yaml_text.splitlines()
            if line and not line.startswith("#") and ":" in line
        }
        assert "model" not in active_keys

    def test_no_flags_channel_section_commented_out(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, None)
        assert "# channel:" in yaml_text
        active_keys = {
            line.split(":")[0]
            for line in yaml_text.splitlines()
            if line and not line.startswith("#") and ":" in line
        }
        assert "channel" not in active_keys

    def test_model_flag_populates_model_section(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, "anthropic:claude-sonnet-4-20250514")
        parsed = yaml.safe_load(yaml_text)
        assert parsed["model"]["provider"] == "anthropic"
        assert parsed["model"]["model"] == "claude-sonnet-4-20250514"

    def test_channel_flag_populates_channel_section(self) -> None:
        yaml_text = _build_agent_yaml("mybot", "telegram", None)
        parsed = yaml.safe_load(yaml_text)
        assert parsed["channel"]["type"] == "telegram"

    def test_both_flags_set_both_sections(self) -> None:
        yaml_text = _build_agent_yaml("mybot", "telegram", "openai:gpt-4o")
        parsed = yaml.safe_load(yaml_text)
        assert parsed["model"]["provider"] == "openai"
        assert parsed["channel"]["type"] == "telegram"

    def test_queue_section_always_present(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, None)
        parsed = yaml.safe_load(yaml_text)
        assert parsed["queue"]["mode"] == "collect"
        assert parsed["queue"]["debounce_ms"] == 1000

    def test_workspace_name_in_name_field(self) -> None:
        yaml_text = _build_agent_yaml("clippy", None, None)
        parsed = yaml.safe_load(yaml_text)
        assert parsed["name"] == "clippy"

    def test_model_without_colon_defaults_to_anthropic(self) -> None:
        """A bare model string without a colon should still produce valid YAML."""
        yaml_text = _build_agent_yaml("mybot", None, "gpt-4o")
        parsed = yaml.safe_load(yaml_text)
        assert parsed["model"]["provider"] == "anthropic"
        assert parsed["model"]["model"] == "gpt-4o"

    def test_native_provider_includes_shorthand_comment(self) -> None:
        """Well-known providers should include a shorthand alternative comment."""
        yaml_text = _build_agent_yaml("mybot", None, "anthropic:claude-sonnet-4-20250514")
        assert "# model: anthropic:claude-sonnet-4-20250514" in yaml_text
        assert "# Or use shorthand with a configured provider:" in yaml_text

    def test_shorthand_comment_included_for_openai(self) -> None:
        """openai is a native provider and should include the shorthand comment."""
        yaml_text = _build_agent_yaml("mybot", None, "openai:gpt-4o")
        assert "# model: openai:gpt-4o" in yaml_text

    def test_unknown_provider_no_shorthand_comment(self) -> None:
        """Custom/unknown providers should NOT include the shorthand comment."""
        yaml_text = _build_agent_yaml("mybot", None, "mycustom:my-model")
        assert "# Or use shorthand with a configured provider:" not in yaml_text


class TestParseModelString:
    """Tests for _parse_model_string()."""

    def test_splits_provider_and_model(self) -> None:
        assert _parse_model_string("anthropic:claude-sonnet-4-20250514") == (
            "anthropic",
            "claude-sonnet-4-20250514",
        )

    def test_bare_model_defaults_to_anthropic(self) -> None:
        assert _parse_model_string("gpt-4o") == ("anthropic", "gpt-4o")

    def test_rejects_empty_model_id(self) -> None:
        with pytest.raises(ValueError, match="model ID is empty"):
            _parse_model_string("anthropic:")

    def test_rejects_empty_provider(self) -> None:
        with pytest.raises(ValueError, match="provider is empty"):
            _parse_model_string(":claude-sonnet-4-20250514")

    def test_bedrock_model_string(self) -> None:
        provider, model_id = _parse_model_string("bedrock_converse:us.anthropic.claude-haiku:v1:0")
        assert provider == "bedrock_converse"
        assert model_id == "us.anthropic.claude-haiku:v1:0"


class TestBedrockScaffold:
    """Tests ensuring Bedrock providers omit api_key."""

    def test_bedrock_omits_api_key_in_yaml(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, "bedrock_converse:us.anthropic.claude-haiku:v1:0")
        assert "api_key" not in yaml_text

    def test_bedrock_model_section_valid(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, "bedrock_converse:us.anthropic.claude-haiku:v1:0")
        parsed = yaml.safe_load(yaml_text)
        assert parsed["model"]["provider"] == "bedrock_converse"
        assert parsed["model"]["model"] == "us.anthropic.claude-haiku:v1:0"

    def test_anthropic_includes_api_key_in_yaml(self) -> None:
        yaml_text = _build_agent_yaml("mybot", None, "anthropic:claude-sonnet-4-20250514")
        assert "api_key" in yaml_text
