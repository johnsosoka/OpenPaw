"""Tests for the learning-loop prompt section gating (PRD-001 F1.1/F1.2)."""

from pathlib import Path

from openpaw.core.config.models import WorkspaceConfig
from openpaw.core.workspace import AgentWorkspace
from openpaw.model.skill import SkillInfo


def make_workspace(tmp_path: Path, learning_enabled: bool) -> AgentWorkspace:
    config = WorkspaceConfig.model_validate({"learning": {"enabled": learning_enabled}})
    return AgentWorkspace(
        name="learn-test",
        path=tmp_path,
        agent_md="# Agent",
        user_md="# User",
        soul_md="# Soul",
        heartbeat_md="",
        skills_path=tmp_path / "agent" / "skills",
        tools_path=tmp_path / "tools",
        config=config,
    )


def authoring_skill() -> SkillInfo:
    return SkillInfo(
        name="skill-authoring",
        description="How to write a good skill",
        content="guide body",
        path=Path("/x/SKILL.md"),
        source="framework",
    )


def test_learning_section_present_when_enabled(tmp_path: Path) -> None:
    prompt = make_workspace(tmp_path, True).build_system_prompt()
    assert "## Learning" in prompt
    assert "manage_skill" in prompt


def test_learning_section_absent_when_disabled(tmp_path: Path) -> None:
    prompt = make_workspace(tmp_path, False).build_system_prompt()
    assert "## Learning" not in prompt


def test_learning_section_absent_without_config(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, True)
    ws.config = None
    assert "## Learning" not in ws.build_system_prompt()


def test_authoring_skill_injected_only_when_learning_enabled(tmp_path: Path) -> None:
    on = make_workspace(tmp_path, True)
    on.skills = [authoring_skill()]
    assert "skill-authoring" in on.build_system_prompt()

    off = make_workspace(tmp_path, False)
    off.skills = [authoring_skill()]
    assert "skill-authoring" not in off.build_system_prompt()


def test_other_skills_unaffected_by_learning_gate(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path, False)
    ws.skills = [
        SkillInfo(
            name="digest-format",
            description="digest style",
            content="body",
            path=Path("/x/SKILL.md"),
            source="workspace",
        )
    ]
    assert "digest-format" in ws.build_system_prompt()
