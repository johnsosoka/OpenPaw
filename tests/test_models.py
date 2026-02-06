"""Tests for ORM models."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from openpaw.db.database import DatabaseManager
from openpaw.db.models import (
    AgentState,
    BuiltinAllowlist,
    BuiltinConfig,
    ChannelBinding,
    CronJob,
    ListType,
    Setting,
    Workspace,
    WorkspaceConfig,
)


@pytest.fixture
async def db_manager():
    """Provide a temporary database manager."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        manager = DatabaseManager(db_path)
        await manager.init_db()
        yield manager
        await manager.close()


class TestWorkspaceModel:
    """Test Workspace model functionality."""

    async def test_create_basic_workspace(self, db_manager):
        """Test creating a workspace with minimal fields."""
        async with db_manager.session() as session:
            workspace = Workspace(
                name="test-workspace",
                path="/path/to/workspace",
                enabled=True,
            )
            session.add(workspace)
            await session.flush()

            assert workspace.id is not None
            assert workspace.name == "test-workspace"
            assert workspace.enabled is True
            assert isinstance(workspace.created_at, datetime)

    async def test_workspace_name_must_be_unique(self, db_manager):
        """Test workspace name uniqueness constraint."""
        session = db_manager.session_factory()
        try:
            workspace1 = Workspace(name="duplicate", path="/path1")
            workspace2 = Workspace(name="duplicate", path="/path2")
            session.add(workspace1)
            session.add(workspace2)

            with pytest.raises(IntegrityError):
                await session.flush()
        finally:
            await session.close()

    async def test_workspace_with_config_relationship(self, db_manager):
        """Test workspace with related config."""
        async with db_manager.session() as session:
            workspace = Workspace(name="test", path="/path")
            config = WorkspaceConfig(
                workspace=workspace,
                model_provider="anthropic",
                model_name="claude-sonnet-4",
                temperature=0.7,
                max_turns=50,
            )
            session.add(workspace)
            session.add(config)
            await session.flush()

            # Verify relationship
            assert workspace.config is not None
            assert workspace.config.model_provider == "anthropic"
            assert workspace.config.temperature == 0.7

    async def test_workspace_with_channel_binding(self, db_manager):
        """Test workspace with channel binding."""
        async with db_manager.session() as session:
            workspace = Workspace(name="test", path="/path")
            channel = ChannelBinding(
                workspace=workspace,
                channel_type="telegram",
                config_encrypted="encrypted_token_here",
                allowed_users=[123, 456],
                enabled=True,
            )
            session.add(workspace)
            session.add(channel)
            await session.flush()

            # Verify relationship
            assert workspace.channel_binding is not None
            assert workspace.channel_binding.channel_type == "telegram"
            assert workspace.channel_binding.allowed_users == [123, 456]

    async def test_workspace_with_cron_jobs(self, db_manager):
        """Test workspace with multiple cron jobs."""
        async with db_manager.session() as session:
            workspace = Workspace(name="test", path="/path")
            cron1 = CronJob(
                workspace=workspace,
                name="daily-summary",
                schedule="0 9 * * *",
                prompt="Generate summary",
                output_config={"channel": "telegram"},
                enabled=True,
            )
            cron2 = CronJob(
                workspace=workspace,
                name="hourly-check",
                schedule="0 * * * *",
                prompt="Check status",
                output_config={"channel": "telegram"},
                enabled=True,
            )
            session.add(workspace)
            session.add(cron1)
            session.add(cron2)
            await session.flush()

            # Verify relationship
            assert len(workspace.cron_jobs) == 2
            assert {c.name for c in workspace.cron_jobs} == {"daily-summary", "hourly-check"}

    async def test_workspace_cascade_delete(self, db_manager):
        """Test cascade deletion of workspace relationships."""
        async with db_manager.session() as session:
            # Create workspace with all relationships
            workspace = Workspace(name="test", path="/path")
            config = WorkspaceConfig(workspace=workspace, model_provider="anthropic")
            channel = ChannelBinding(
                workspace=workspace,
                channel_type="telegram",
                config_encrypted="token",
            )
            cron = CronJob(
                workspace=workspace,
                name="test-cron",
                schedule="* * * * *",
                prompt="test",
                output_config={},
            )
            builtin_cfg = BuiltinConfig(
                workspace=workspace,
                builtin_name="brave_search",
                enabled=True,
            )
            session.add_all([workspace, config, channel, cron, builtin_cfg])
            await session.flush()

            workspace_id = workspace.id

        # Delete workspace in new session
        async with db_manager.session() as session:
            workspace = await session.get(Workspace, workspace_id)
            await session.delete(workspace)
            await session.flush()

        # Verify all related entities were deleted
        async with db_manager.session() as session:
            # Check workspace is gone
            workspace = await session.get(Workspace, workspace_id)
            assert workspace is None

            # Check config is gone
            config_result = await session.execute(
                select(WorkspaceConfig).where(WorkspaceConfig.workspace_id == workspace_id)
            )
            assert config_result.scalar_one_or_none() is None

            # Check channel is gone
            channel_result = await session.execute(
                select(ChannelBinding).where(ChannelBinding.workspace_id == workspace_id)
            )
            assert channel_result.scalar_one_or_none() is None

            # Check cron is gone
            cron_result = await session.execute(
                select(CronJob).where(CronJob.workspace_id == workspace_id)
            )
            assert cron_result.scalar_one_or_none() is None

            # Check builtin config is gone
            builtin_result = await session.execute(
                select(BuiltinConfig).where(BuiltinConfig.workspace_id == workspace_id)
            )
            assert builtin_result.scalar_one_or_none() is None


class TestCronJobModel:
    """Test CronJob model constraints."""

    async def test_cron_unique_per_workspace(self, db_manager):
        """Test cron name must be unique per workspace."""
        session = db_manager.session_factory()
        try:
            workspace = Workspace(name="test", path="/path")
            cron1 = CronJob(
                workspace=workspace,
                name="duplicate",
                schedule="* * * * *",
                prompt="test",
                output_config={},
            )
            cron2 = CronJob(
                workspace=workspace,
                name="duplicate",
                schedule="0 * * * *",
                prompt="test2",
                output_config={},
            )
            session.add_all([workspace, cron1, cron2])

            with pytest.raises(IntegrityError):
                await session.flush()
        finally:
            await session.close()

    async def test_cron_same_name_different_workspaces(self, db_manager):
        """Test cron name can be reused across different workspaces."""
        async with db_manager.session() as session:
            workspace1 = Workspace(name="ws1", path="/path1")
            workspace2 = Workspace(name="ws2", path="/path2")
            cron1 = CronJob(
                workspace=workspace1,
                name="daily",
                schedule="* * * * *",
                prompt="test",
                output_config={},
            )
            cron2 = CronJob(
                workspace=workspace2,
                name="daily",
                schedule="* * * * *",
                prompt="test",
                output_config={},
            )
            session.add_all([workspace1, workspace2, cron1, cron2])
            await session.flush()

            # Should succeed - different workspaces
            assert cron1.id is not None
            assert cron2.id is not None


class TestSettingModel:
    """Test Setting model functionality."""

    async def test_create_setting_with_json_value(self, db_manager):
        """Test creating setting with JSON value field."""
        async with db_manager.session() as session:
            setting = Setting(
                key="agent.model",
                value={"value": "claude-sonnet-4"},
                category="agent",
                encrypted=False,
            )
            session.add(setting)
            await session.flush()

            assert setting.id is not None
            assert setting.value == {"value": "claude-sonnet-4"}
            assert setting.category == "agent"

    async def test_setting_key_must_be_unique(self, db_manager):
        """Test setting key uniqueness constraint."""
        session = db_manager.session_factory()
        try:
            setting1 = Setting(
                key="duplicate",
                value={"value": "val1"},
                category="test",
            )
            setting2 = Setting(
                key="duplicate",
                value={"value": "val2"},
                category="test",
            )
            session.add(setting1)
            session.add(setting2)

            with pytest.raises(IntegrityError):
                await session.flush()
        finally:
            await session.close()

    async def test_setting_encrypted_flag(self, db_manager):
        """Test setting encrypted flag."""
        async with db_manager.session() as session:
            setting = Setting(
                key="api_key",
                value={"value": "encrypted_key_data"},
                category="credentials",
                encrypted=True,
            )
            session.add(setting)
            await session.flush()

            assert setting.encrypted is True


class TestBuiltinConfigModel:
    """Test BuiltinConfig model functionality."""

    async def test_global_builtin_config(self, db_manager):
        """Test creating global builtin config (workspace_id=None)."""
        async with db_manager.session() as session:
            builtin = BuiltinConfig(
                workspace_id=None,
                builtin_name="brave_search",
                enabled=True,
                config={"count": 5},
            )
            session.add(builtin)
            await session.flush()

            assert builtin.id is not None
            assert builtin.workspace_id is None
            assert builtin.config == {"count": 5}

    async def test_workspace_specific_builtin_config(self, db_manager):
        """Test creating workspace-specific builtin config."""
        async with db_manager.session() as session:
            workspace = Workspace(name="test", path="/path")
            builtin = BuiltinConfig(
                workspace=workspace,
                builtin_name="whisper",
                enabled=True,
                config={"model": "whisper-1"},
            )
            session.add_all([workspace, builtin])
            await session.flush()

            assert builtin.workspace_id is not None
            assert builtin.workspace_id == workspace.id

    async def test_builtin_unique_per_workspace(self, db_manager):
        """Test builtin name must be unique per workspace."""
        session = db_manager.session_factory()
        try:
            workspace = Workspace(name="test", path="/path")
            builtin1 = BuiltinConfig(
                workspace=workspace,
                builtin_name="duplicate",
                enabled=True,
            )
            builtin2 = BuiltinConfig(
                workspace=workspace,
                builtin_name="duplicate",
                enabled=False,
            )
            session.add_all([workspace, builtin1, builtin2])

            with pytest.raises(IntegrityError):
                await session.flush()
        finally:
            await session.close()

    async def test_builtin_same_name_global_and_workspace(self, db_manager):
        """Test builtin can have both global and workspace-specific configs."""
        async with db_manager.session() as session:
            workspace = Workspace(name="test", path="/path")
            global_builtin = BuiltinConfig(
                workspace_id=None,
                builtin_name="brave_search",
                config={"count": 5},
            )
            workspace_builtin = BuiltinConfig(
                workspace=workspace,
                builtin_name="brave_search",
                config={"count": 10},
            )
            session.add_all([workspace, global_builtin, workspace_builtin])
            await session.flush()

            # Should succeed - different scopes
            assert global_builtin.id is not None
            assert workspace_builtin.id is not None


class TestBuiltinAllowlistModel:
    """Test BuiltinAllowlist model functionality."""

    async def test_create_allowlist_entries(self, db_manager):
        """Test creating allow/deny list entries."""
        async with db_manager.session() as session:
            workspace = Workspace(name="test", path="/path")
            allow_entry = BuiltinAllowlist(
                workspace=workspace,
                entry="brave_search",
                list_type=ListType.ALLOW,
            )
            deny_entry = BuiltinAllowlist(
                workspace=workspace,
                entry="group:voice",
                list_type=ListType.DENY,
            )
            session.add_all([workspace, allow_entry, deny_entry])
            await session.flush()

            assert allow_entry.id is not None
            assert allow_entry.list_type == "allow"
            assert deny_entry.list_type == "deny"

    async def test_global_allowlist(self, db_manager):
        """Test creating global allowlist (workspace_id=None)."""
        async with db_manager.session() as session:
            entry = BuiltinAllowlist(
                workspace_id=None,
                entry="brave_search",
                list_type=ListType.ALLOW,
            )
            session.add(entry)
            await session.flush()

            assert entry.workspace_id is None


class TestEnumerations:
    """Test enum types work correctly."""

    def test_agent_state_enum(self):
        """Test AgentState enum values."""
        assert AgentState.IDLE == "idle"
        assert AgentState.ACTIVE == "active"
        assert AgentState.STUCK == "stuck"
        assert AgentState.ERROR == "error"
        assert AgentState.STOPPED == "stopped"

    def test_list_type_enum(self):
        """Test ListType enum values."""
        assert ListType.ALLOW == "allow"
        assert ListType.DENY == "deny"

    async def test_enum_stored_as_string(self, db_manager):
        """Test enum values are stored as strings in database."""
        async with db_manager.session() as session:
            entry = BuiltinAllowlist(
                workspace_id=None,
                entry="test",
                list_type=ListType.ALLOW,
            )
            session.add(entry)
            await session.flush()

            # Query raw value to verify storage
            result = await session.execute(
                select(BuiltinAllowlist).where(BuiltinAllowlist.entry == "test")
            )
            retrieved = result.scalar_one()
            assert retrieved.list_type == "allow"
            assert isinstance(retrieved.list_type, str)
