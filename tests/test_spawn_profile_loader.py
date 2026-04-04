"""Tests for the spawn profile loader."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openpaw.workspace.profile_loader import load_spawn_profiles

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_profile(directory: Path, filename: str, content: str) -> Path:
    """Write a YAML profile file and return its path."""
    path = directory / filename
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Happy-path loading
# ---------------------------------------------------------------------------


def test_load_valid_profile_with_all_fields(tmp_path: Path) -> None:
    """A fully-specified YAML profile is loaded without errors."""
    write_profile(
        tmp_path,
        "news-scout.yaml",
        """
name: news-scout
description: Searches for recent AI news
system_prompt: You are a focused news researcher.
model: anthropic:claude-haiku-4-5-20251001
temperature: 0.3
allowed_tools:
  - brave_search
  - group:filesystem
denied_tools:
  - browser_navigate
timeout_minutes: 15
max_turns: 20
""",
    )

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    p = profiles[0]
    assert p.name == "news-scout"
    assert p.description == "Searches for recent AI news"
    assert p.system_prompt == "You are a focused news researcher."
    assert p.model == "anthropic:claude-haiku-4-5-20251001"
    assert p.temperature == pytest.approx(0.3)
    assert p.allowed_tools == ["brave_search", "group:filesystem"]
    assert p.denied_tools == ["browser_navigate"]
    assert p.timeout_minutes == 15
    assert p.max_turns == 20
    assert p.source == "workspace"
    assert p.path == tmp_path / "news-scout.yaml"


def test_name_defaults_to_filename_stem(tmp_path: Path) -> None:
    """When the YAML omits 'name', the loader uses the filename stem."""
    write_profile(
        tmp_path,
        "code-reviewer.yaml",
        "description: Reviews pull requests\n",
    )

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "code-reviewer"


def test_description_defaults_to_empty_string(tmp_path: Path) -> None:
    """When 'description' is absent the field is an empty string."""
    write_profile(tmp_path, "minimal.yaml", "name: minimal\n")

    profiles = load_spawn_profiles(tmp_path)

    assert profiles[0].description == ""


def test_optional_fields_are_none_when_absent(tmp_path: Path) -> None:
    """Absent optional fields resolve to None, not a default value."""
    write_profile(tmp_path, "bare.yaml", "name: bare\ndescription: Bare profile\n")

    profiles = load_spawn_profiles(tmp_path)

    p = profiles[0]
    assert p.system_prompt is None
    assert p.model is None
    assert p.temperature is None
    assert p.allowed_tools is None
    assert p.denied_tools is None
    assert p.timeout_minutes is None
    assert p.max_turns is None


def test_source_parameter_is_attached_to_profiles(tmp_path: Path) -> None:
    """The caller-supplied source label is stored on every loaded profile."""
    write_profile(tmp_path, "system-agent.yaml", "name: system-agent\n")

    profiles = load_spawn_profiles(tmp_path, source="system")

    assert profiles[0].source == "system"


def test_path_is_set_to_absolute_yaml_file(tmp_path: Path) -> None:
    """The loaded profile carries the absolute path to its source file."""
    write_profile(tmp_path, "path-check.yaml", "name: path-check\n")

    profiles = load_spawn_profiles(tmp_path)

    assert profiles[0].path == tmp_path / "path-check.yaml"


# ---------------------------------------------------------------------------
# File-skipping rules
# ---------------------------------------------------------------------------


def test_underscore_prefixed_files_are_skipped(tmp_path: Path) -> None:
    """Files whose stems start with '_' are silently ignored."""
    write_profile(tmp_path, "_disabled.yaml", "name: disabled\n")
    write_profile(tmp_path, "enabled.yaml", "name: enabled\n")

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "enabled"


def test_non_yaml_files_are_ignored(tmp_path: Path) -> None:
    """Files with extensions other than .yaml/.yml are not loaded."""
    (tmp_path / "profile.json").write_text('{"name": "ignored"}', encoding="utf-8")
    (tmp_path / "profile.toml").write_text('name = "ignored"', encoding="utf-8")
    write_profile(tmp_path, "real-profile.yaml", "name: real-profile\n")

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "real-profile"


# ---------------------------------------------------------------------------
# .yaml vs .yml precedence
# ---------------------------------------------------------------------------


def test_yaml_extension_takes_precedence_over_yml(tmp_path: Path) -> None:
    """When both .yaml and .yml exist for the same stem, .yaml wins."""
    write_profile(tmp_path, "agent.yaml", "name: yaml-version\ndescription: from yaml\n")
    write_profile(tmp_path, "agent.yml", "name: yml-version\ndescription: from yml\n")

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].description == "from yaml"


def test_yml_loaded_when_no_yaml_counterpart(tmp_path: Path) -> None:
    """A .yml file is loaded normally when no matching .yaml exists."""
    write_profile(tmp_path, "scout.yml", "name: scout\ndescription: yml only\n")

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "scout"
    assert profiles[0].path == tmp_path / "scout.yml"


def test_both_yaml_and_yml_load_when_different_stems(tmp_path: Path) -> None:
    """Distinct stems each load their own profile regardless of extension."""
    write_profile(tmp_path, "alpha.yaml", "name: alpha\n")
    write_profile(tmp_path, "beta.yml", "name: beta\n")

    profiles = load_spawn_profiles(tmp_path)

    names = {p.name for p in profiles}
    assert names == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# Error handling — malformed files
# ---------------------------------------------------------------------------


def test_invalid_yaml_is_logged_and_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A file with malformed YAML is logged at ERROR level and skipped."""
    write_profile(tmp_path, "broken.yaml", "name: [unclosed bracket\n")
    write_profile(tmp_path, "good.yaml", "name: good\n")

    with caplog.at_level(logging.ERROR, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "good"
    assert any("broken.yaml" in record.message for record in caplog.records)


def test_one_bad_file_does_not_prevent_others_from_loading(tmp_path: Path) -> None:
    """A bad profile file does not abort loading of subsequent valid files."""
    write_profile(tmp_path, "aaa-broken.yaml", "name: [broken\n")
    write_profile(tmp_path, "bbb-valid.yaml", "name: bbb-valid\n")
    write_profile(tmp_path, "ccc-valid.yaml", "name: ccc-valid\n")

    profiles = load_spawn_profiles(tmp_path)

    names = [p.name for p in profiles]
    assert "bbb-valid" in names
    assert "ccc-valid" in names


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------


def test_invalid_name_uppercase_is_logged_and_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A profile whose resolved name contains uppercase letters is skipped."""
    write_profile(tmp_path, "bad-name.yaml", "name: UpperCase\n")
    write_profile(tmp_path, "good-name.yaml", "name: good-name\n")

    with caplog.at_level(logging.WARNING, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "good-name"
    assert any("UpperCase" in record.message for record in caplog.records)


def test_invalid_name_spaces_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A profile name containing spaces does not pass name validation."""
    write_profile(tmp_path, "spaced.yaml", "name: spaces here\n")

    with caplog.at_level(logging.WARNING, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert profiles == []


def test_invalid_name_leading_hyphen_is_skipped(tmp_path: Path) -> None:
    """A profile name that starts with a hyphen fails the regex and is skipped."""
    write_profile(tmp_path, "bad.yaml", "name: -starts-with-hyphen\n")

    profiles = load_spawn_profiles(tmp_path)

    assert profiles == []


def test_valid_name_with_numbers_and_hyphens_loads(tmp_path: Path) -> None:
    """Names matching the pattern ^[a-z0-9][a-z0-9-]*$ load without issue."""
    write_profile(tmp_path, "profile.yaml", "name: agent-v2\n")

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "agent-v2"


# ---------------------------------------------------------------------------
# Unknown YAML keys
# ---------------------------------------------------------------------------


def test_unknown_yaml_keys_emit_warning_but_load_succeeds(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An unrecognised YAML key triggers a warning but does not abort loading."""
    write_profile(
        tmp_path,
        "forward-compat.yaml",
        "name: forward-compat\ndescription: ok\nfuture_field: some-value\n",
    )

    with caplog.at_level(logging.WARNING, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "forward-compat"
    assert any("future_field" in record.message for record in caplog.records)


# ---------------------------------------------------------------------------
# Missing / empty directory
# ---------------------------------------------------------------------------


def test_missing_directory_returns_empty_list(tmp_path: Path) -> None:
    """Passing a non-existent path returns an empty list without raising."""
    absent = tmp_path / "does-not-exist"

    profiles = load_spawn_profiles(absent)

    assert profiles == []


def test_empty_directory_returns_empty_list(tmp_path: Path) -> None:
    """An existing but empty directory yields an empty list."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    profiles = load_spawn_profiles(empty_dir)

    assert profiles == []


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


def test_multiple_profiles_are_sorted_by_name(tmp_path: Path) -> None:
    """Profiles are returned sorted alphabetically by name, not by filename."""
    write_profile(tmp_path, "zebra.yaml", "name: zebra\n")
    write_profile(tmp_path, "apple.yaml", "name: apple\n")
    write_profile(tmp_path, "mango.yaml", "name: mango\n")

    profiles = load_spawn_profiles(tmp_path)

    assert [p.name for p in profiles] == ["apple", "mango", "zebra"]


def test_sort_uses_resolved_name_not_filename(tmp_path: Path) -> None:
    """Sort order is based on the profile name field, not the file stem."""
    write_profile(tmp_path, "zzz-file.yaml", "name: aaa-agent\n")
    write_profile(tmp_path, "aaa-file.yaml", "name: zzz-agent\n")

    profiles = load_spawn_profiles(tmp_path)

    assert profiles[0].name == "aaa-agent"
    assert profiles[1].name == "zzz-agent"


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------


def test_non_numeric_temperature_is_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A temperature value that cannot be cast to float is discarded (None)."""
    write_profile(
        tmp_path,
        "bad-temp.yaml",
        "name: bad-temp\ntemperature: not-a-number\n",
    )

    with caplog.at_level(logging.WARNING, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].temperature is None
    assert any("temperature" in record.message for record in caplog.records)


def test_numeric_string_temperature_is_coerced(tmp_path: Path) -> None:
    """A temperature expressed as a YAML string that looks numeric is accepted."""
    write_profile(tmp_path, "str-temp.yaml", 'name: str-temp\ntemperature: "0.7"\n')

    profiles = load_spawn_profiles(tmp_path)

    assert profiles[0].temperature == pytest.approx(0.7)


def test_non_list_allowed_tools_is_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A scalar value for allowed_tools triggers a warning and resolves to None."""
    write_profile(
        tmp_path,
        "bad-tools.yaml",
        "name: bad-tools\nallowed_tools: brave_search\n",
    )

    with caplog.at_level(logging.WARNING, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].allowed_tools is None
    assert any("tool list field" in record.message for record in caplog.records)


def test_non_list_denied_tools_is_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A scalar value for denied_tools triggers a warning and resolves to None."""
    write_profile(
        tmp_path,
        "bad-denied.yaml",
        "name: bad-denied\ndenied_tools: send_message\n",
    )

    with caplog.at_level(logging.WARNING, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].denied_tools is None


def test_tool_list_items_are_coerced_to_strings(tmp_path: Path) -> None:
    """Non-string items in a tool list are cast to str."""
    write_profile(
        tmp_path,
        "mixed-tools.yaml",
        "name: mixed-tools\nallowed_tools:\n  - brave_search\n  - 42\n",
    )

    profiles = load_spawn_profiles(tmp_path)

    assert profiles[0].allowed_tools == ["brave_search", "42"]


def test_empty_yaml_file_uses_filename_stem_as_name(tmp_path: Path) -> None:
    """A completely empty YAML file resolves its name from the filename stem."""
    write_profile(tmp_path, "empty-yaml.yaml", "")

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "empty-yaml"


# ---------------------------------------------------------------------------
# allowed_skills / denied_skills fields
# ---------------------------------------------------------------------------


def test_allowed_skills_list_loads_correctly(tmp_path: Path) -> None:
    """A profile with allowed_skills is loaded with the correct list value."""
    write_profile(
        tmp_path,
        "selective.yaml",
        "name: selective\nallowed_skills:\n  - skill-a\n  - skill-b\n",
    )

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].allowed_skills == ["skill-a", "skill-b"]


def test_denied_skills_list_loads_correctly(tmp_path: Path) -> None:
    """A profile with denied_skills is loaded with the correct list value."""
    write_profile(
        tmp_path,
        "filtered.yaml",
        "name: filtered\ndenied_skills:\n  - skill-c\n",
    )

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].denied_skills == ["skill-c"]


def test_allowed_skills_empty_list_loads_as_empty_list(tmp_path: Path) -> None:
    """allowed_skills: [] (explicit empty list) is preserved as [] not None."""
    write_profile(
        tmp_path,
        "no-skills.yaml",
        "name: no-skills\nallowed_skills: []\n",
    )

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].allowed_skills == []
    assert profiles[0].allowed_skills is not None


def test_allowed_skills_and_denied_skills_not_in_unknown_key_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """allowed_skills and denied_skills are recognised keys — no warning is emitted."""
    write_profile(
        tmp_path,
        "known-keys.yaml",
        "name: known-keys\nallowed_skills:\n  - skill-a\ndenied_skills:\n  - skill-b\n",
    )

    with caplog.at_level(logging.WARNING, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    # Neither field should appear in any warning message.
    warning_text = " ".join(r.message for r in caplog.records if r.levelno >= logging.WARNING)
    assert "allowed_skills" not in warning_text
    assert "denied_skills" not in warning_text


# ---------------------------------------------------------------------------
# inherit_tools field and directory profile format
# ---------------------------------------------------------------------------


def test_flat_yaml_has_default_inherit_tools_and_empty_tools(tmp_path: Path) -> None:
    """A flat YAML profile defaults inherit_tools to True and tools to []."""
    (tmp_path / "flat.yaml").write_text("name: flat\ndescription: flat profile\n")

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].inherit_tools is True
    assert profiles[0].tools == []


def test_directory_profile_loads_from_profile_yaml(tmp_path: Path) -> None:
    """A directory containing profile.yaml is loaded with the correct fields."""
    profile_dir = tmp_path / "my-profile"
    profile_dir.mkdir()
    (profile_dir / "profile.yaml").write_text(
        "name: my-profile\ndescription: directory profile\n"
    )

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "my-profile"
    assert profiles[0].description == "directory profile"


def test_directory_profile_with_tools_loads_tool_functions(tmp_path: Path) -> None:
    """Tools in a directory profile's tools/ subdir are loaded onto the profile."""
    profile_dir = tmp_path / "my-tool-profile"
    profile_dir.mkdir()
    (profile_dir / "profile.yaml").write_text(
        "name: my-tool-profile\ndescription: has tools\n"
    )
    tools_dir = profile_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "sample_tool.py").write_text(
        'from langchain_core.tools import tool\n\n'
        '@tool\n'
        'def sample_tool(query: str) -> str:\n'
        '    """A sample tool for testing."""\n'
        '    return f"result: {query}"\n'
    )

    mock_tool = MagicMock()
    mock_tool.name = "sample_tool"

    with patch(
        "openpaw.workspace.tool_loader.load_workspace_tools",
        return_value=[mock_tool],
    ):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert len(profiles[0].tools) == 1
    assert profiles[0].tools[0].name == "sample_tool"


def test_directory_profile_without_tools_dir(tmp_path: Path) -> None:
    """A directory profile with no tools/ subdirectory loads with an empty tools list."""
    profile_dir = tmp_path / "no-tools"
    profile_dir.mkdir()
    (profile_dir / "profile.yaml").write_text("name: no-tools\ndescription: bare dir\n")

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].tools == []


def test_directory_without_profile_yaml_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A directory lacking profile.yaml is skipped with a debug log message."""
    bad_dir = tmp_path / "bad-dir"
    bad_dir.mkdir()
    (tmp_path / "good.yaml").write_text("name: good\ndescription: valid flat profile\n")

    with caplog.at_level(logging.DEBUG, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "good"
    assert any("no profile.yaml" in record.message for record in caplog.records)


def test_same_stem_file_and_directory_directory_wins(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """When a .yaml file and directory share the same stem, the directory wins."""
    (tmp_path / "clash.yaml").write_text(
        "name: clash\ndescription: from file\n"
    )
    clash_dir = tmp_path / "clash"
    clash_dir.mkdir()
    (clash_dir / "profile.yaml").write_text(
        "name: clash\ndescription: from directory\n"
    )

    with caplog.at_level(logging.WARNING, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].description == "from directory"
    assert any("both file and directory" in record.message for record in caplog.records)


def test_underscore_prefix_directory_is_skipped(tmp_path: Path) -> None:
    """Directories whose names start with '_' are silently ignored."""
    disabled_dir = tmp_path / "_disabled"
    disabled_dir.mkdir()
    (disabled_dir / "profile.yaml").write_text("name: disabled\ndescription: should skip\n")
    (tmp_path / "enabled.yaml").write_text("name: enabled\ndescription: visible\n")

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].name == "enabled"


def test_inherit_tools_false_parsed(tmp_path: Path) -> None:
    """A flat YAML profile with inherit_tools: false is parsed correctly."""
    (tmp_path / "no-inherit.yaml").write_text(
        "name: no-inherit\ndescription: test\ninherit_tools: false\n"
    )

    profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].inherit_tools is False


def test_inherit_tools_invalid_value_defaults_to_true(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-boolean inherit_tools value falls back to True with a warning logged."""
    (tmp_path / "bad-inherit.yaml").write_text(
        "name: bad-inherit\ndescription: test\ninherit_tools: not_a_bool\n"
    )

    with caplog.at_level(logging.WARNING, logger="openpaw.workspace.profile_loader"):
        profiles = load_spawn_profiles(tmp_path)

    assert len(profiles) == 1
    assert profiles[0].inherit_tools is True
    assert any("inherit_tools" in record.message for record in caplog.records)
