"""Tests for framework-bundled skills."""

from pathlib import Path

from openpaw.model.skill import SkillInfo, SkillInjectMode
from openpaw.workspace.skill_loader import (
    load_framework_skills,
    load_workspace_skills,
    materialize_framework_skills,
)


class TestLoadFrameworkSkills:
    """Tests for loading framework-bundled skills."""

    def test_loads_skills_from_package(self) -> None:
        """Framework skills are loaded from openpaw/builtins/skills/."""
        skills = load_framework_skills()
        assert len(skills) >= 3  # At minimum our 3 skills

    def test_expected_skill_names(self) -> None:
        """The three expected framework skills are present."""
        skills = load_framework_skills()
        names = {s.name for s in skills}
        assert "team-management" in names
        assert "web-browsing" in names
        assert "channel-awareness" in names

    def test_source_is_framework(self) -> None:
        """All framework skills have source='framework'."""
        skills = load_framework_skills()
        for skill in skills:
            assert skill.source == "framework", f"{skill.name} has wrong source"

    def test_read_path_uses_framework_prefix(self) -> None:
        """Framework skill read_paths point to _framework/ materialized location."""
        skills = load_framework_skills()
        for skill in skills:
            assert skill.read_path.startswith("agent/skills/_framework/"), (
                f"{skill.name} read_path: {skill.read_path}"
            )
            assert skill.read_path.endswith("/SKILL.md")

    def test_skills_have_descriptions(self) -> None:
        """All framework skills have non-empty descriptions."""
        skills = load_framework_skills()
        for skill in skills:
            assert skill.description, f"{skill.name} has empty description"

    def test_skills_have_content(self) -> None:
        """All framework skills have non-empty content."""
        skills = load_framework_skills()
        for skill in skills:
            assert skill.content.strip(), f"{skill.name} has empty content"

    def test_skills_default_to_summary_inject(self) -> None:
        """Framework skills default to summary inject mode."""
        skills = load_framework_skills()
        for skill in skills:
            assert skill.inject == SkillInjectMode.SUMMARY, (
                f"{skill.name} has inject={skill.inject}"
            )


class TestMaterializeFrameworkSkills:
    """Tests for materializing framework skills into workspaces."""

    def test_creates_skill_files_in_workspace(self, tmp_path: Path) -> None:
        """Materialization creates SKILL.md files at expected paths."""
        skills = load_framework_skills()
        materialize_framework_skills(tmp_path, skills)

        for skill in skills:
            if skill.source != "framework":
                continue
            target = tmp_path / "agent" / "skills" / "_framework" / skill.name / "SKILL.md"
            assert target.exists(), f"Missing: {target}"

    def test_file_content_is_non_empty(self, tmp_path: Path) -> None:
        """Materialized files contain actual content."""
        skills = load_framework_skills()
        materialize_framework_skills(tmp_path, skills)

        for skill in skills:
            if skill.source != "framework":
                continue
            target = tmp_path / "agent" / "skills" / "_framework" / skill.name / "SKILL.md"
            content = target.read_text()
            assert len(content) > 100, f"{skill.name} content too short"

    def test_idempotent(self, tmp_path: Path) -> None:
        """Calling materialize twice doesn't error."""
        skills = load_framework_skills()
        materialize_framework_skills(tmp_path, skills)
        materialize_framework_skills(tmp_path, skills)  # Should not raise

    def test_skips_non_framework_skills(self, tmp_path: Path) -> None:
        """Workspace skills are not materialized."""
        workspace_skill = SkillInfo(
            name="my-workspace-skill",
            description="test",
            content="workspace content",
            path=tmp_path / "ws",
            source="workspace",
        )
        materialize_framework_skills(tmp_path, [workspace_skill])

        target = tmp_path / "agent" / "skills" / "_framework" / "my-workspace-skill"
        assert not target.exists()

    def test_underscore_prefix_prevents_double_loading(self, tmp_path: Path) -> None:
        """The _framework directory is skipped by load_workspace_skills."""
        skills = load_framework_skills()
        materialize_framework_skills(tmp_path, skills)

        # Point load_workspace_skills at the skills directory
        skills_dir = tmp_path / "agent" / "skills"
        loaded = load_workspace_skills(skills_dir)

        # Should find nothing — _framework is skipped by underscore convention
        framework_names = {s.name for s in loaded}
        for skill in skills:
            assert skill.name not in framework_names, (
                f"Framework skill '{skill.name}' was double-loaded"
            )


class TestFrameworkSkillOverride:
    """Tests for workspace skills overriding framework skills."""

    def test_workspace_skill_overrides_framework_skill(self) -> None:
        """A workspace skill with the same name wins over framework skill."""
        framework = [
            SkillInfo(name="team-management", description="fw", content="fw content",
                      path=Path("/fw"), source="framework"),
        ]
        workspace = [
            SkillInfo(name="team-management", description="ws", content="ws content",
                      path=Path("/ws"), source="workspace"),
        ]

        # Simulate the merge logic from loader.py
        by_name: dict[str, SkillInfo] = {}
        for s in framework:
            by_name[s.name] = s
        for s in workspace:
            by_name[s.name] = s

        merged = list(by_name.values())
        assert len(merged) == 1
        assert merged[0].source == "workspace"
        assert merged[0].description == "ws"

    def test_non_overlapping_skills_both_present(self) -> None:
        """Framework and workspace skills with different names coexist."""
        framework = [
            SkillInfo(name="web-browsing", description="fw", content="fw",
                      path=Path("/fw"), source="framework"),
        ]
        workspace = [
            SkillInfo(name="my-custom-skill", description="ws", content="ws",
                      path=Path("/ws"), source="workspace"),
        ]

        by_name: dict[str, SkillInfo] = {}
        for s in framework:
            by_name[s.name] = s
        for s in workspace:
            by_name[s.name] = s

        merged = list(by_name.values())
        assert len(merged) == 2
        names = {s.name for s in merged}
        assert "web-browsing" in names
        assert "my-custom-skill" in names


class TestTrimmedFrameworkSections:
    """Tests for trimmed framework prompt sections."""

    def test_sub_agent_section_contains_skill_pointer(self) -> None:
        """Trimmed sub-agent section has read_file reference."""
        from openpaw.core.prompts.framework import SECTION_SUB_AGENT_SPAWNING
        assert "read_file(" in SECTION_SUB_AGENT_SPAWNING
        assert "team-management" in SECTION_SUB_AGENT_SPAWNING

    def test_web_browsing_section_contains_skill_pointer(self) -> None:
        """Trimmed web browsing section has read_file reference."""
        from openpaw.core.prompts.framework import SECTION_WEB_BROWSING
        assert "read_file(" in SECTION_WEB_BROWSING
        assert "web-browsing" in SECTION_WEB_BROWSING

    def test_channel_history_section_contains_skill_pointer(self) -> None:
        """Trimmed channel history section has read_file reference."""
        from openpaw.core.prompts.framework import SECTION_CHANNEL_HISTORY
        assert "read_file(" in SECTION_CHANNEL_HISTORY
        assert "channel-awareness" in SECTION_CHANNEL_HISTORY

    def test_channel_logs_section_contains_skill_pointer(self) -> None:
        """Trimmed channel logs section references channel-awareness skill."""
        from openpaw.core.prompts.framework import SECTION_CHANNEL_LOGS
        assert "channel-awareness" in SECTION_CHANNEL_LOGS

    def test_stubs_preserve_behavioral_keywords(self) -> None:
        """Key behavioral terms still present in trimmed sections."""
        from openpaw.core.prompts.framework import (
            SECTION_CHANNEL_HISTORY,
            SECTION_SUB_AGENT_SPAWNING,
            SECTION_WEB_BROWSING,
        )
        # Sub-agent: delegation and transparency
        assert "proactive" in SECTION_SUB_AGENT_SPAWNING.lower() or "delegation" in SECTION_SUB_AGENT_SPAWNING.lower()
        # Web browsing: snapshot-first, no screenshots
        assert "snapshot" in SECTION_WEB_BROWSING.lower()
        assert "screenshot" in SECTION_WEB_BROWSING.lower()
        # Channel history: browse
        assert "browse" in SECTION_CHANNEL_HISTORY.lower()
