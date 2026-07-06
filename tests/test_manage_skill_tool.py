"""Tests for the manage_skill builtin tool."""

from pathlib import Path

import pytest

from openpaw.builtins.registry import BuiltinRegistry
from openpaw.builtins.tools.manage_skill import ManageSkillTool
from openpaw.model.status_event import StatusEvent
from openpaw.stores.skill import SkillLimits, SkillStore


class NullEmitter:
    async def emit(self, event: StatusEvent) -> None:
        return None


async def noop_reload() -> None:
    return None


@pytest.fixture
def workspace_path(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "agent" / "skills").mkdir(parents=True)
    return ws


@pytest.fixture
def store(workspace_path: Path) -> SkillStore:
    return SkillStore(
        workspace_path=workspace_path,
        workspace="test-ws",
        limits=SkillLimits(),
        emitter=NullEmitter(),
        reload_trigger=noop_reload,
    )


def make_tool(store: SkillStore | None, approval: str = "immediate"):
    builtin = ManageSkillTool()
    if store is not None:
        builtin.set_skill_store(store, approval=approval)
    return builtin.get_langchain_tool()


CREATE_ARGS = {
    "operation": "create",
    "name": "digest-format",
    "description": "How digests are formatted",
    "content": "# Digest\n\nLead with calendar conflicts.",
    "source": "telegram:1:conv_x",
}


class TestManageSkillTool:
    async def test_no_context_returns_clean_error(self):
        tool = make_tool(store=None)
        result = await tool.ainvoke(CREATE_ARGS)
        assert "not available in this context" in result

    async def test_create_writes_skill_and_reports_active(self, store, workspace_path):
        tool = make_tool(store)
        result = await tool.ainvoke(CREATE_ARGS)

        assert "created" in result
        assert "v1" in result
        assert (
            workspace_path / "agent" / "skills" / "digest-format" / "SKILL.md"
        ).exists()

    async def test_staged_policy_reports_staged(self, store):
        tool = make_tool(store, approval="staged")
        result = await tool.ainvoke(CREATE_ARGS)

        assert "STAGED" in result
        assert "/skills approve digest-format" in result

    async def test_gate_errors_surfaced_verbatim(self, store):
        tool = make_tool(store)
        args = dict(CREATE_ARGS, content="password: hunter2-oops")
        result = await tool.ainvoke(args)

        assert "rejected by validation gates" in result
        assert "[content]" in result
        assert "password" in result

    async def test_create_missing_description_errors(self, store):
        tool = make_tool(store)
        args = {k: v for k, v in CREATE_ARGS.items() if k != "description"}
        result = await tool.ainvoke(args)
        assert "requires both 'description' and 'content'" in result

    async def test_update_bumps_version(self, store):
        tool = make_tool(store)
        await tool.ainvoke(CREATE_ARGS)
        result = await tool.ainvoke(
            {
                "operation": "update",
                "name": "digest-format",
                "content": "# Digest v2\n\nNew steps.",
            }
        )
        assert "updated" in result
        assert "v2" in result

    async def test_update_missing_content_errors(self, store):
        tool = make_tool(store)
        result = await tool.ainvoke({"operation": "update", "name": "digest-format"})
        assert "'update' requires 'content'" in result

    async def test_deprecate(self, store):
        tool = make_tool(store)
        await tool.ainvoke(CREATE_ARGS)
        result = await tool.ainvoke(
            {"operation": "deprecate", "name": "digest-format"}
        )
        assert "deprecated" in result

    async def test_deprecate_missing_skill_surfaces_gate_error(self, store):
        tool = make_tool(store)
        result = await tool.ainvoke({"operation": "deprecate", "name": "ghost"})
        assert "[schema]" in result
        assert "does not exist" in result

    def test_registered_in_builtin_registry(self):
        BuiltinRegistry.reset()
        try:
            registry = BuiltinRegistry.get_instance()
            assert registry.get_tool_class("manage_skill") is ManageSkillTool
            # No prerequisites — available everywhere, gated by wiring/config.
            assert "manage_skill" in registry.get_available_tools()
        finally:
            BuiltinRegistry.reset()
