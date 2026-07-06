"""Tests for WorkspaceRunner.reload_skills()."""

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openpaw.core.workspace import AgentWorkspace
from openpaw.model.skill import SkillInfo
from openpaw.workspace.runner import WorkspaceRunner


def _write_skill(skills_path: Path, dir_name: str, name: str | None = None) -> None:
    """Create a minimal valid skill directory."""
    skill_dir = skills_path / dir_name
    skill_dir.mkdir(parents=True)
    frontmatter_name = name or dir_name
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {frontmatter_name}\ndescription: Test skill\n---\n\n# {frontmatter_name}\n",
        encoding="utf-8",
    )


@pytest.fixture
def workspace(tmp_path) -> AgentWorkspace:
    """Create a real AgentWorkspace backed by tmp_path."""
    skills_path = tmp_path / "agent" / "skills"
    skills_path.mkdir(parents=True)
    return AgentWorkspace(
        name="test-workspace",
        path=tmp_path,
        agent_md="",
        user_md="",
        soul_md="",
        heartbeat_md="",
        skills_path=skills_path,
        tools_path=tmp_path / "tools",
    )


@pytest.fixture
def runner(workspace) -> MagicMock:
    """Stub WorkspaceRunner with just the attributes reload_skills needs."""
    stub = MagicMock()
    stub._workspace = workspace
    stub._agent_runner = MagicMock()
    stub.logger = logging.getLogger("test-reload")
    return stub


@pytest.fixture
def no_framework_skills(monkeypatch):
    """Isolate tests from real framework skills bundled in the package."""
    monkeypatch.setattr(
        "openpaw.workspace.runner.load_framework_skills", lambda: []
    )


class TestReloadSkills:
    """Tests for the reload_skills method."""

    def test_new_skill_on_disk_is_loaded(self, runner, workspace, no_framework_skills):
        _write_skill(workspace.skills_path, "new-skill")

        ws_count, fw_count, errors = WorkspaceRunner.reload_skills(runner)

        assert ws_count == 1
        assert fw_count == 0
        assert errors == []
        assert [s.name for s in workspace.skills] == ["new-skill"]

    def test_removed_skill_disappears_after_reload(
        self, runner, workspace, no_framework_skills
    ):
        _write_skill(workspace.skills_path, "doomed-skill")
        WorkspaceRunner.reload_skills(runner)
        assert len(workspace.skills) == 1

        import shutil

        shutil.rmtree(workspace.skills_path / "doomed-skill")
        ws_count, _, _ = WorkspaceRunner.reload_skills(runner)

        assert ws_count == 0
        assert workspace.skills == []

    def test_changed_skill_content_is_picked_up(
        self, runner, workspace, no_framework_skills
    ):
        _write_skill(workspace.skills_path, "my-skill")
        WorkspaceRunner.reload_skills(runner)

        skill_file = workspace.skills_path / "my-skill" / "SKILL.md"
        skill_file.write_text(
            "---\nname: my-skill\ndescription: Updated\n---\n\nNew content\n",
            encoding="utf-8",
        )
        WorkspaceRunner.reload_skills(runner)

        assert workspace.skills[0].description == "Updated"
        assert "New content" in workspace.skills[0].content

    def test_atomic_replace_not_in_place_mutation(
        self, runner, workspace, no_framework_skills
    ):
        _write_skill(workspace.skills_path, "skill-a")
        WorkspaceRunner.reload_skills(runner)
        old_list = workspace.skills

        _write_skill(workspace.skills_path, "skill-b")
        WorkspaceRunner.reload_skills(runner)

        # Old reference (e.g., held by a running sub-agent) is untouched
        assert workspace.skills is not old_list
        assert [s.name for s in old_list] == ["skill-a"]
        assert [s.name for s in workspace.skills] == ["skill-a", "skill-b"]

    def test_workspace_skill_overrides_framework_by_name(
        self, runner, workspace, monkeypatch, tmp_path
    ):
        framework_skill = SkillInfo(
            name="shared-name",
            description="Framework version",
            content="framework content",
            path=tmp_path / "fw",
            source="framework",
        )
        monkeypatch.setattr(
            "openpaw.workspace.runner.load_framework_skills",
            lambda: [framework_skill],
        )
        _write_skill(workspace.skills_path, "shared-name")

        ws_count, fw_count, _ = WorkspaceRunner.reload_skills(runner)

        assert ws_count == 1
        assert fw_count == 0
        assert len(workspace.skills) == 1
        assert workspace.skills[0].source == "workspace"

    def test_framework_skills_are_materialized(
        self, runner, workspace, monkeypatch, tmp_path
    ):
        fw_dir = tmp_path / "fw-source" / "fw-skill"
        fw_dir.mkdir(parents=True)
        (fw_dir / "SKILL.md").write_text("framework content", encoding="utf-8")
        framework_skill = SkillInfo(
            name="fw-skill",
            description="",
            content="framework content",
            path=fw_dir,
            source="framework",
        )
        monkeypatch.setattr(
            "openpaw.workspace.runner.load_framework_skills",
            lambda: [framework_skill],
        )

        _, fw_count, _ = WorkspaceRunner.reload_skills(runner)

        assert fw_count == 1
        materialized = (
            workspace.path / "agent" / "skills" / "_framework" / "fw-skill" / "SKILL.md"
        )
        assert materialized.read_text(encoding="utf-8") == "framework content"

    def test_broken_skill_is_skipped_and_error_surfaced(
        self, runner, workspace, no_framework_skills, monkeypatch
    ):
        _write_skill(workspace.skills_path, "good-skill")
        broken_dir = workspace.skills_path / "broken-skill"
        broken_dir.mkdir()
        skill_md = broken_dir / "SKILL.md"
        skill_md.write_text("content", encoding="utf-8")
        # Make the file unreadable to force a per-skill load failure
        skill_md.chmod(0o000)

        try:
            ws_count, _, errors = WorkspaceRunner.reload_skills(runner)
        finally:
            skill_md.chmod(0o644)

        assert ws_count == 1
        assert [s.name for s in workspace.skills] == ["good-skill"]
        assert len(errors) == 1
        assert "broken-skill" in errors[0]

    def test_rebuild_agent_called_after_replace(
        self, runner, workspace, no_framework_skills
    ):
        WorkspaceRunner.reload_skills(runner)

        runner._agent_runner.rebuild_agent.assert_called_once()

    def test_empty_skills_directory_yields_empty_list(
        self, runner, workspace, no_framework_skills
    ):
        ws_count, fw_count, errors = WorkspaceRunner.reload_skills(runner)

        assert (ws_count, fw_count, errors) == (0, 0, [])
        assert workspace.skills == []
