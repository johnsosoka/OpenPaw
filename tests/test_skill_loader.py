"""Tests for workspace skill loading and system prompt integration."""

import logging
from pathlib import Path

import pytest

from openpaw.core.workspace import AgentWorkspace
from openpaw.model.skill import SkillInfo, SkillInjectMode
from openpaw.workspace.skill_loader import load_workspace_skills

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skills_dir(base: Path) -> Path:
    """Create and return a skills directory under base."""
    skills_dir = base / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    return skills_dir


def _make_skill(skills_dir: Path, name: str, content: str) -> Path:
    """Create a skill subdirectory with a SKILL.md file and return the directory."""
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def _make_workspace(tmp_path: Path, skills: list[SkillInfo] | None = None) -> AgentWorkspace:
    """Build a minimal AgentWorkspace suitable for system-prompt tests."""
    workspace_path = tmp_path / "ws"
    workspace_path.mkdir(parents=True, exist_ok=True)

    return AgentWorkspace(
        name="test-workspace",
        path=workspace_path,
        agent_md="# Agent",
        user_md="# User",
        soul_md="# Soul",
        heartbeat_md="",
        skills_path=workspace_path / "agent" / "skills",
        tools_path=workspace_path / "agent" / "tools",
        skills=skills or [],
    )


# ---------------------------------------------------------------------------
# TestLoadValidSkill
# ---------------------------------------------------------------------------

class TestLoadValidSkill:
    """SKILL.md with frontmatter produces correct SkillInfo fields."""

    def test_name_from_frontmatter(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(
            skills_dir,
            "my-skill",
            "---\nname: My Custom Skill\ndescription: Does useful things\n---\n\n# Body content\n",
        )

        skills = load_workspace_skills(skills_dir)

        assert len(skills) == 1
        assert skills[0].name == "My Custom Skill"

    def test_description_from_frontmatter(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(
            skills_dir,
            "my-skill",
            "---\nname: My Skill\ndescription: Does useful things\n---\n\n# Body\n",
        )

        skills = load_workspace_skills(skills_dir)

        assert skills[0].description == "Does useful things"

    def test_content_excludes_frontmatter(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(
            skills_dir,
            "my-skill",
            "---\nname: My Skill\ndescription: Short desc\n---\n\n# Skill Body\n\nSome details.\n",
        )

        skills = load_workspace_skills(skills_dir)

        assert "# Skill Body" in skills[0].content
        assert "Some details." in skills[0].content
        # Frontmatter keys must not appear in body
        assert "name: My Skill" not in skills[0].content
        assert "description:" not in skills[0].content

    def test_path_points_to_skill_directory(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        skill_dir = _make_skill(
            skills_dir,
            "my-skill",
            "---\nname: My Skill\ndescription: Desc\n---\n\nBody.\n",
        )

        skills = load_workspace_skills(skills_dir)

        assert skills[0].path == skill_dir


# ---------------------------------------------------------------------------
# TestLoadSkillWithoutFrontmatter
# ---------------------------------------------------------------------------

class TestLoadSkillWithoutFrontmatter:
    """SKILL.md without frontmatter falls back to directory name and empty description."""

    def test_name_falls_back_to_directory_name(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(skills_dir, "plain-skill", "# Just markdown content\n\nNo frontmatter here.\n")

        skills = load_workspace_skills(skills_dir)

        assert skills[0].name == "plain-skill"

    def test_description_is_empty_string(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(skills_dir, "plain-skill", "# Just markdown content\n")

        skills = load_workspace_skills(skills_dir)

        assert skills[0].description == ""

    def test_full_file_content_is_body(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        body = "# Just markdown content\n\nSome text here.\n"
        _make_skill(skills_dir, "plain-skill", body)

        skills = load_workspace_skills(skills_dir)

        assert skills[0].content == body


# ---------------------------------------------------------------------------
# TestSkipUnderscoreDirectories
# ---------------------------------------------------------------------------

class TestSkipUnderscoreDirectories:
    """Directories prefixed with `_` are ignored."""

    def test_underscore_directory_is_skipped(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(skills_dir, "_disabled", "---\nname: Hidden\n---\n\nContent.\n")

        skills = load_workspace_skills(skills_dir)

        assert skills == []

    def test_underscore_directory_skipped_alongside_valid_skill(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(skills_dir, "_draft", "---\nname: Draft\n---\n\nDraft content.\n")
        _make_skill(skills_dir, "active-skill", "---\nname: Active\n---\n\nActive content.\n")

        skills = load_workspace_skills(skills_dir)

        assert len(skills) == 1
        assert skills[0].name == "Active"


# ---------------------------------------------------------------------------
# TestEmptySkillsDirectory
# ---------------------------------------------------------------------------

class TestEmptySkillsDirectory:
    """An empty skills directory returns an empty list."""

    def test_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)

        skills = load_workspace_skills(skills_dir)

        assert skills == []

    def test_directory_with_no_skill_md_files_returns_empty_list(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        # Subdirectory exists but has no SKILL.md
        (skills_dir / "incomplete-skill").mkdir()

        skills = load_workspace_skills(skills_dir)

        assert skills == []


# ---------------------------------------------------------------------------
# TestMissingSkillsDirectory
# ---------------------------------------------------------------------------

class TestMissingSkillsDirectory:
    """A non-existent skills path returns an empty list without raising."""

    def test_nonexistent_path_returns_empty_list(self, tmp_path: Path) -> None:
        missing_path = tmp_path / "does" / "not" / "exist"

        skills = load_workspace_skills(missing_path)

        assert skills == []

    def test_nonexistent_path_does_not_raise(self, tmp_path: Path) -> None:
        missing_path = tmp_path / "nonexistent"

        # Must not raise any exception
        result = load_workspace_skills(missing_path)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# TestFrontmatterEdgeCases
# ---------------------------------------------------------------------------

class TestFrontmatterEdgeCases:
    """Edge cases in frontmatter parsing."""

    def test_unclosed_frontmatter_treated_as_plain_content(self, tmp_path: Path) -> None:
        """A file with an opening `---` but no closing delimiter is treated as plain content."""
        skills_dir = _make_skills_dir(tmp_path)
        raw = "---\nname: Broken\ndescription: No closing delimiter\n\n# Body\n"
        _make_skill(skills_dir, "broken-skill", raw)

        skills = load_workspace_skills(skills_dir)

        # Falls back to directory name (no frontmatter parsed)
        assert skills[0].name == "broken-skill"
        assert skills[0].description == ""
        # Entire raw file is the content
        assert skills[0].content == raw

    def test_invalid_yaml_in_frontmatter_falls_back_gracefully(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Invalid YAML inside frontmatter logs a warning and falls back to directory name."""
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(
            skills_dir,
            "bad-yaml-skill",
            "---\nname: [unclosed bracket\n---\n\n# Real body content\n",
        )

        with caplog.at_level(logging.WARNING, logger="openpaw.workspace.skill_loader"):
            skills = load_workspace_skills(skills_dir)

        assert len(skills) == 1
        assert skills[0].name == "bad-yaml-skill"
        assert skills[0].description == ""
        # Warning should have been logged
        assert any("frontmatter" in record.message.lower() for record in caplog.records)

    def test_frontmatter_missing_name_falls_back_to_dir_name(self, tmp_path: Path) -> None:
        """Frontmatter without a `name` key uses the directory name."""
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(
            skills_dir,
            "unnamed-skill",
            "---\ndescription: Only a description here\n---\n\nBody content.\n",
        )

        skills = load_workspace_skills(skills_dir)

        assert skills[0].name == "unnamed-skill"
        assert skills[0].description == "Only a description here"

    def test_frontmatter_missing_description_yields_empty_string(self, tmp_path: Path) -> None:
        """Frontmatter with a name but no description yields empty description."""
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(
            skills_dir,
            "named-only",
            "---\nname: Named Only\n---\n\nBody.\n",
        )

        skills = load_workspace_skills(skills_dir)

        assert skills[0].description == ""


# ---------------------------------------------------------------------------
# TestDescriptionTruncation
# ---------------------------------------------------------------------------

class TestDescriptionTruncation:
    """Descriptions exceeding 1024 characters are truncated."""

    def test_long_description_is_truncated_to_1024_chars(self, tmp_path: Path) -> None:
        long_desc = "x" * 2000
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(
            skills_dir,
            "long-desc-skill",
            f"---\nname: Long Desc\ndescription: {long_desc}\n---\n\nBody.\n",
        )

        skills = load_workspace_skills(skills_dir)

        assert len(skills[0].description) == 1024
        assert skills[0].description == "x" * 1024

    def test_short_description_is_not_truncated(self, tmp_path: Path) -> None:
        desc = "Short and sweet"
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(
            skills_dir,
            "short-desc-skill",
            f"---\nname: Short Desc\ndescription: {desc}\n---\n\nBody.\n",
        )

        skills = load_workspace_skills(skills_dir)

        assert skills[0].description == desc


# ---------------------------------------------------------------------------
# TestSkillSorting
# ---------------------------------------------------------------------------

class TestSkillSorting:
    """Skills are returned sorted alphabetically by name."""

    def test_skills_sorted_by_name(self, tmp_path: Path) -> None:
        skills_dir = _make_skills_dir(tmp_path)
        _make_skill(skills_dir, "zebra-skill", "---\nname: Zebra\n---\n\nZ content.\n")
        _make_skill(skills_dir, "alpha-skill", "---\nname: Alpha\n---\n\nA content.\n")
        _make_skill(skills_dir, "mango-skill", "---\nname: Mango\n---\n\nM content.\n")

        skills = load_workspace_skills(skills_dir)

        # load_workspace_skills sorts by iterdir() order (alphabetical by directory name)
        names = [s.name for s in skills]
        assert names == ["Alpha", "Mango", "Zebra"]


# ---------------------------------------------------------------------------
# TestSystemPromptSkillsSection
# ---------------------------------------------------------------------------

class TestSystemPromptSkillsSection:
    """Skills are correctly embedded in the system prompt."""

    def test_skills_block_present_when_skills_loaded(self, tmp_path: Path) -> None:
        """System prompt includes a <skills> block when skills are populated."""
        skill = SkillInfo(
            name="Python Patterns",
            description="Common Python design patterns.",
            content="## Singleton\nUse module-level singletons...",
            path=tmp_path / "python-patterns",
        )
        workspace = _make_workspace(tmp_path, skills=[skill])

        prompt = workspace.build_system_prompt(enabled_builtins=[])

        assert "<skills>" in prompt
        assert "</skills>" in prompt

    def test_skills_block_absent_when_no_skills(self, tmp_path: Path) -> None:
        """System prompt omits the <skills> block when no skills are loaded."""
        workspace = _make_workspace(tmp_path, skills=[])

        prompt = workspace.build_system_prompt(enabled_builtins=[])

        assert "<skills>" not in prompt

    def test_skill_name_in_prompt(self, tmp_path: Path) -> None:
        """Skill name appears as a markdown heading inside <skills>."""
        skill = SkillInfo(
            name="Error Handling",
            description="Best practices for error handling.",
            content="Always catch specific exceptions...",
            path=tmp_path / "error-handling",
        )
        workspace = _make_workspace(tmp_path, skills=[skill])

        prompt = workspace.build_system_prompt(enabled_builtins=[])

        assert "### Error Handling" in prompt

    def test_skill_description_in_prompt(self, tmp_path: Path) -> None:
        """Skill description appears in the prompt when present."""
        skill = SkillInfo(
            name="Logging",
            description="Structured logging conventions.",
            content="Use structlog for structured output...",
            path=tmp_path / "logging",
        )
        workspace = _make_workspace(tmp_path, skills=[skill])

        prompt = workspace.build_system_prompt(enabled_builtins=[])

        assert "Structured logging conventions." in prompt

    def test_skill_content_in_prompt(self, tmp_path: Path) -> None:
        """Skill body content appears in the prompt."""
        skill = SkillInfo(
            name="Testing",
            description="",
            content="Use pytest fixtures for reusable setup.",
            path=tmp_path / "testing",
            inject=SkillInjectMode.FULL,
        )
        workspace = _make_workspace(tmp_path, skills=[skill])

        prompt = workspace.build_system_prompt(enabled_builtins=[])

        assert "Use pytest fixtures for reusable setup." in prompt

    def test_skill_without_description_omits_description_line(self, tmp_path: Path) -> None:
        """Skills with an empty description do not add a blank description line."""
        skill = SkillInfo(
            name="No Desc",
            description="",
            content="Some content here.",
            path=tmp_path / "no-desc",
            inject=SkillInjectMode.FULL,
        )
        workspace = _make_workspace(tmp_path, skills=[skill])
        prompt = workspace.build_system_prompt(enabled_builtins=[])

        # The heading and separator should be present
        assert "### No Desc" in prompt
        # Blank description should not produce stray empty lines between heading and separator
        # Verify heading is directly followed by the separator (no description between them)
        skills_block_start = prompt.index("<skills>")
        skills_block_end = prompt.index("</skills>")
        skills_block = prompt[skills_block_start:skills_block_end]
        heading_pos = skills_block.index("### No Desc")
        sep_pos = skills_block.index("---")
        assert sep_pos > heading_pos

    def test_skills_section_formatting(self, tmp_path: Path) -> None:
        """Skills section uses `### name / description / --- / content` structure."""
        skill = SkillInfo(
            name="My Skill",
            description="A helpful skill.",
            content="Detailed instructions here.",
            path=tmp_path / "my-skill",
            inject=SkillInjectMode.FULL,
        )
        workspace = _make_workspace(tmp_path, skills=[skill])

        prompt = workspace.build_system_prompt(enabled_builtins=[])

        skills_start = prompt.index("<skills>") + len("<skills>")
        skills_end = prompt.index("</skills>")
        skills_block = prompt[skills_start:skills_end]

        heading_pos = skills_block.index("### My Skill")
        desc_pos = skills_block.index("A helpful skill.")
        sep_pos = skills_block.index("---")
        content_pos = skills_block.index("Detailed instructions here.")

        assert heading_pos < desc_pos < sep_pos < content_pos

    def test_multiple_skills_all_present_in_prompt(self, tmp_path: Path) -> None:
        """Multiple skills all appear in the system prompt."""
        skills = [
            SkillInfo(
                name="Skill Alpha",
                description="Alpha description.",
                content="Alpha body.",
                path=tmp_path / "alpha",
                inject=SkillInjectMode.FULL,
            ),
            SkillInfo(
                name="Skill Beta",
                description="Beta description.",
                content="Beta body.",
                path=tmp_path / "beta",
                inject=SkillInjectMode.FULL,
            ),
        ]
        workspace = _make_workspace(tmp_path, skills=skills)

        prompt = workspace.build_system_prompt(enabled_builtins=[])

        assert "### Skill Alpha" in prompt
        assert "### Skill Beta" in prompt
        assert "Alpha body." in prompt
        assert "Beta body." in prompt

    def test_skills_section_appears_before_workspace_context(self, tmp_path: Path) -> None:
        """<skills> block is positioned before <workspace_context>."""
        skill = SkillInfo(
            name="Positioning Test",
            description="",
            content="Content.",
            path=tmp_path / "positioning",
        )
        workspace = _make_workspace(tmp_path, skills=[skill])

        prompt = workspace.build_system_prompt(enabled_builtins=[])

        skills_pos = prompt.index("<skills>")
        context_pos = prompt.index("<workspace_context>")
        assert skills_pos < context_pos


# ---------------------------------------------------------------------------
# TestSkillInjectMode
# ---------------------------------------------------------------------------


class TestSkillInjectMode:
    """Tests for the inject frontmatter field parsing."""

    def test_inject_defaults_to_summary(self, tmp_path: Path) -> None:
        """Skill with no inject field in frontmatter defaults to SUMMARY."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A skill\n---\nContent here.")

        skills = load_workspace_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].inject == SkillInjectMode.SUMMARY

    def test_inject_full_parsed(self, tmp_path: Path) -> None:
        """inject: full in frontmatter produces FULL mode."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ninject: full\n---\nContent.")

        skills = load_workspace_skills(tmp_path)
        assert skills[0].inject == SkillInjectMode.FULL

    def test_inject_summary_parsed(self, tmp_path: Path) -> None:
        """inject: summary in frontmatter produces SUMMARY mode."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ninject: summary\n---\nContent.")

        skills = load_workspace_skills(tmp_path)
        assert skills[0].inject == SkillInjectMode.SUMMARY

    def test_inject_invalid_falls_back_to_summary(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Invalid inject value logs warning and defaults to SUMMARY."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ninject: bogus\n---\nContent.")

        with caplog.at_level(logging.WARNING):
            skills = load_workspace_skills(tmp_path)

        assert skills[0].inject == SkillInjectMode.SUMMARY
        assert "invalid inject mode" in caplog.text.lower()

    def test_inject_case_insensitive(self, tmp_path: Path) -> None:
        """inject: FULL (uppercase) is accepted."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ninject: FULL\n---\nContent.")

        skills = load_workspace_skills(tmp_path)
        assert skills[0].inject == SkillInjectMode.FULL


# ---------------------------------------------------------------------------
# TestSkillReadPath
# ---------------------------------------------------------------------------


class TestSkillReadPath:
    """Tests for read_path computation."""

    def test_read_path_computed_from_directory_name(self, tmp_path: Path) -> None:
        """read_path uses the directory name, not the frontmatter name."""
        skill_dir = tmp_path / "my-cool-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: Different Name\n---\nContent.")

        skills = load_workspace_skills(tmp_path)
        assert skills[0].read_path == "agent/skills/my-cool-skill/SKILL.md"

    def test_read_path_independent_of_frontmatter_name(self, tmp_path: Path) -> None:
        """Even with a custom frontmatter name, read_path uses dir name."""
        skill_dir = tmp_path / "dir-name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: custom-name\n---\nContent.")

        skills = load_workspace_skills(tmp_path)
        assert skills[0].name == "custom-name"  # Name from frontmatter
        assert skills[0].read_path == "agent/skills/dir-name/SKILL.md"  # Path from dir


# ---------------------------------------------------------------------------
# TestSkillInjectModeInPrompt
# ---------------------------------------------------------------------------


class TestSkillInjectModeInPrompt:
    """Tests for inject-mode-aware system prompt rendering."""

    def test_full_inject_includes_content_in_prompt(self, tmp_path: Path) -> None:
        """FULL mode includes complete skill content in prompt."""
        skill = SkillInfo(
            name="Full Skill", description="Desc", content="Detailed content here.",
            path=tmp_path / "full", inject=SkillInjectMode.FULL,
        )
        workspace = _make_workspace(tmp_path, skills=[skill])
        prompt = workspace.build_system_prompt(enabled_builtins=[])
        assert "Detailed content here." in prompt
        assert "---" in prompt  # Separator present

    def test_summary_inject_excludes_content_from_prompt(self, tmp_path: Path) -> None:
        """SUMMARY mode does NOT include skill content in prompt."""
        skill = SkillInfo(
            name="Summary Skill", description="Desc", content="Secret content.",
            path=tmp_path / "summary", inject=SkillInjectMode.SUMMARY,
            read_path="agent/skills/summary/SKILL.md",
        )
        workspace = _make_workspace(tmp_path, skills=[skill])
        prompt = workspace.build_system_prompt(enabled_builtins=[])
        assert "Secret content." not in prompt

    def test_summary_inject_includes_read_pointer(self, tmp_path: Path) -> None:
        """SUMMARY mode includes read_file() pointer in prompt."""
        skill = SkillInfo(
            name="Summary Skill", description="Desc", content="Content.",
            path=tmp_path / "summary", inject=SkillInjectMode.SUMMARY,
            read_path="agent/skills/summary/SKILL.md",
        )
        workspace = _make_workspace(tmp_path, skills=[skill])
        prompt = workspace.build_system_prompt(enabled_builtins=[])
        assert "read_file('agent/skills/summary/SKILL.md')" in prompt

    def test_summary_inject_includes_description(self, tmp_path: Path) -> None:
        """SUMMARY mode includes the description in prompt."""
        skill = SkillInfo(
            name="My Skill", description="A helpful description.", content="Content.",
            path=tmp_path / "my", inject=SkillInjectMode.SUMMARY,
            read_path="agent/skills/my/SKILL.md",
        )
        workspace = _make_workspace(tmp_path, skills=[skill])
        prompt = workspace.build_system_prompt(enabled_builtins=[])
        assert "A helpful description." in prompt

    def test_mixed_inject_modes(self, tmp_path: Path) -> None:
        """One FULL and one SUMMARY skill render correctly together."""
        full_skill = SkillInfo(
            name="Always", description="Always present.", content="Full body.",
            path=tmp_path / "always", inject=SkillInjectMode.FULL,
        )
        summary_skill = SkillInfo(
            name="On Demand", description="Load when needed.", content="Hidden body.",
            path=tmp_path / "ondemand", inject=SkillInjectMode.SUMMARY,
            read_path="agent/skills/ondemand/SKILL.md",
        )
        workspace = _make_workspace(tmp_path, skills=[full_skill, summary_skill])
        prompt = workspace.build_system_prompt(enabled_builtins=[])

        assert "Full body." in prompt           # FULL content present
        assert "Hidden body." not in prompt     # SUMMARY content absent
        assert "read_file('agent/skills/ondemand/SKILL.md')" in prompt  # Pointer present

    def test_preamble_present_with_summary_skills(self, tmp_path: Path) -> None:
        """Preamble about read_file() appears when summary skills exist."""
        skill = SkillInfo(
            name="My Skill", description="Desc", content="Content.",
            path=tmp_path / "my", inject=SkillInjectMode.SUMMARY,
            read_path="agent/skills/my/SKILL.md",
        )
        workspace = _make_workspace(tmp_path, skills=[skill])
        prompt = workspace.build_system_prompt(enabled_builtins=[])
        assert "Use read_file()" in prompt

    def test_no_preamble_with_only_full_skills(self, tmp_path: Path) -> None:
        """No preamble when all skills are FULL inject."""
        skill = SkillInfo(
            name="Full Only", description="Desc", content="Content.",
            path=tmp_path / "full", inject=SkillInjectMode.FULL,
        )
        workspace = _make_workspace(tmp_path, skills=[skill])
        prompt = workspace.build_system_prompt(enabled_builtins=[])
        assert "Use read_file()" not in prompt


# ---------------------------------------------------------------------------
# TestSkillSource
# ---------------------------------------------------------------------------


class TestSkillSource:
    """Tests for the source field."""

    def test_workspace_skill_default_source(self, tmp_path: Path) -> None:
        """Loaded workspace skills have source='workspace' by default."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: my-skill\n---\nContent.")

        skills = load_workspace_skills(tmp_path)
        assert skills[0].source == "workspace"
