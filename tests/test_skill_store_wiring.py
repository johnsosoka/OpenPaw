"""Tests for WorkspaceRunner learning-loop wiring (_init_skill_store)."""

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openpaw.core.config.models import WorkspaceConfig
from openpaw.core.workspace import AgentWorkspace
from openpaw.stores.skill import SkillStore
from openpaw.workspace.runner import WorkspaceRunner


def make_workspace(tmp_path: Path, learning_enabled: bool) -> AgentWorkspace:
    skills_path = tmp_path / "agent" / "skills"
    skills_path.mkdir(parents=True, exist_ok=True)
    return AgentWorkspace(
        name="wiring-test",
        path=tmp_path,
        agent_md="",
        user_md="",
        soul_md="",
        heartbeat_md="",
        skills_path=skills_path,
        tools_path=tmp_path / "tools",
        config=WorkspaceConfig.model_validate(
            {"learning": {"enabled": learning_enabled, "approval": "staged"}}
        ),
    )


@pytest.fixture
def stub_runner(tmp_path: Path) -> MagicMock:
    stub = MagicMock()
    stub.workspace_name = "wiring-test"
    stub.logger = logging.getLogger("test-wiring")
    stub._agent_factory = MagicMock()
    stub._agent_factory.status_emitter = None
    return stub


def test_store_built_and_tool_wired_when_enabled(stub_runner: MagicMock, tmp_path: Path) -> None:
    stub_runner._workspace = make_workspace(tmp_path, True)
    tool = MagicMock()
    stub_runner._builtin_loader.get_tool_instance.return_value = tool

    store = WorkspaceRunner._init_skill_store(stub_runner)

    assert isinstance(store, SkillStore)
    tool.set_skill_store.assert_called_once()
    _, kwargs = tool.set_skill_store.call_args
    assert kwargs["approval"] == "staged"


def test_no_store_when_learning_disabled(stub_runner: MagicMock, tmp_path: Path) -> None:
    stub_runner._workspace = make_workspace(tmp_path, False)
    assert WorkspaceRunner._init_skill_store(stub_runner) is None
    stub_runner._builtin_loader.get_tool_instance.assert_not_called()


def test_store_built_even_without_tool_instance(stub_runner: MagicMock, tmp_path: Path) -> None:
    stub_runner._workspace = make_workspace(tmp_path, True)
    stub_runner._builtin_loader.get_tool_instance.return_value = None
    assert isinstance(WorkspaceRunner._init_skill_store(stub_runner), SkillStore)
