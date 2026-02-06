"""Tests for repository classes."""

import tempfile
from pathlib import Path

import pytest

from openpaw.db.database import DatabaseManager
from openpaw.db.models import (
    BuiltinAllowlist,
    BuiltinConfig,
    ListType,
    Setting,
    Workspace,
    WorkspaceConfig,
)
from openpaw.db.repositories.builtin_repo import BuiltinRepository
from openpaw.db.repositories.settings_repo import SettingsRepository
from openpaw.db.repositories.workspace_repo import WorkspaceRepository


@pytest.fixture
async def db_manager():
    """Provide a temporary database manager."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        manager = DatabaseManager(db_path)
        await manager.init_db()
        yield manager
        await manager.close()


class TestWorkspaceRepository:
    """Test WorkspaceRepository methods."""

    async def test_create_workspace(self, db_manager):
        """Test creating a workspace via repository."""
        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            workspace = Workspace(name="test", path="/path", enabled=True)
            created = await repo.create(workspace)

            assert created.id is not None
            assert created.name == "test"

    async def test_get_by_id(self, db_manager):
        """Test retrieving workspace by ID."""
        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            workspace = Workspace(name="test", path="/path")
            created = await repo.create(workspace)
            workspace_id = created.id

        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            retrieved = await repo.get_by_id(workspace_id)

            assert retrieved is not None
            assert retrieved.id == workspace_id
            assert retrieved.name == "test"

    async def test_get_by_name(self, db_manager):
        """Test retrieving workspace by name."""
        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            workspace = Workspace(name="unique-name", path="/path")
            await repo.create(workspace)

        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            retrieved = await repo.get_by_name("unique-name")

            assert retrieved is not None
            assert retrieved.name == "unique-name"

    async def test_get_by_name_not_found(self, db_manager):
        """Test get_by_name returns None for non-existent workspace."""
        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            retrieved = await repo.get_by_name("non-existent")

            assert retrieved is None

    async def test_get_by_name_loads_relations(self, db_manager):
        """Test get_by_name eagerly loads relationships."""
        async with db_manager.session() as session:
            workspace = Workspace(name="test", path="/path")
            config = WorkspaceConfig(
                workspace=workspace,
                model_provider="anthropic",
                temperature=0.7,
            )
            session.add(workspace)
            session.add(config)
            await session.commit()

        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            retrieved = await repo.get_by_name("test")

            assert retrieved is not None
            # Relationships should be loaded
            assert retrieved.config is not None
            assert retrieved.config.model_provider == "anthropic"
            assert retrieved.config.temperature == 0.7

    async def test_list_all(self, db_manager):
        """Test listing all workspaces."""
        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            ws1 = Workspace(name="workspace1", path="/path1")
            ws2 = Workspace(name="workspace2", path="/path2")
            await repo.create(ws1)
            await repo.create(ws2)

        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            workspaces = await repo.list_all()

            assert len(workspaces) == 2
            names = {ws.name for ws in workspaces}
            assert names == {"workspace1", "workspace2"}

    async def test_list_all_with_relations(self, db_manager):
        """Test listing all workspaces with relations."""
        async with db_manager.session() as session:
            ws1 = Workspace(name="ws1", path="/path1")
            ws2 = Workspace(name="ws2", path="/path2")
            config1 = WorkspaceConfig(workspace=ws1, model_provider="anthropic")
            config2 = WorkspaceConfig(workspace=ws2, model_provider="openai")
            session.add_all([ws1, ws2, config1, config2])
            await session.commit()

        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            workspaces = await repo.list_all_with_relations()

            assert len(workspaces) == 2
            # All configs should be loaded
            for ws in workspaces:
                assert ws.config is not None
                assert ws.config.model_provider in ("anthropic", "openai")

    async def test_delete_by_name(self, db_manager):
        """Test deleting workspace by name."""
        async with db_manager.session() as session:
            workspace = Workspace(name="to-delete", path="/path")
            session.add(workspace)
            await session.commit()

        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            result = await repo.delete_by_name("to-delete")
            assert result is True

        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            retrieved = await repo.get_by_name("to-delete")
            assert retrieved is None

    async def test_delete_by_name_not_found(self, db_manager):
        """Test delete_by_name returns False for non-existent workspace."""
        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            result = await repo.delete_by_name("non-existent")
            assert result is False

    async def test_delete(self, db_manager):
        """Test deleting workspace via delete method."""
        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            workspace = Workspace(name="test", path="/path")
            created = await repo.create(workspace)
            workspace_id = created.id

        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            workspace = await repo.get_by_id(workspace_id)
            await repo.delete(workspace)

        async with db_manager.session() as session:
            repo = WorkspaceRepository(session)
            retrieved = await repo.get_by_id(workspace_id)
            assert retrieved is None


class TestSettingsRepository:
    """Test SettingsRepository methods."""

    async def test_get_by_key(self, db_manager):
        """Test retrieving setting by key."""
        async with db_manager.session() as session:
            setting = Setting(
                key="test.key",
                value={"value": "test-value"},
                category="test",
            )
            session.add(setting)
            await session.commit()

        async with db_manager.session() as session:
            repo = SettingsRepository(session)
            retrieved = await repo.get_by_key("test.key")

            assert retrieved is not None
            assert retrieved.key == "test.key"
            assert retrieved.value == {"value": "test-value"}

    async def test_get_by_key_not_found(self, db_manager):
        """Test get_by_key returns None for non-existent key."""
        async with db_manager.session() as session:
            repo = SettingsRepository(session)
            retrieved = await repo.get_by_key("non-existent")

            assert retrieved is None

    async def test_get_by_category(self, db_manager):
        """Test retrieving settings by category."""
        async with db_manager.session() as session:
            setting1 = Setting(
                key="agent.model",
                value={"value": "claude"},
                category="agent",
            )
            setting2 = Setting(
                key="agent.temperature",
                value={"value": 0.7},
                category="agent",
            )
            setting3 = Setting(
                key="queue.mode",
                value={"value": "collect"},
                category="queue",
            )
            session.add_all([setting1, setting2, setting3])
            await session.commit()

        async with db_manager.session() as session:
            repo = SettingsRepository(session)
            agent_settings = await repo.get_by_category("agent")

            assert len(agent_settings) == 2
            keys = {s.key for s in agent_settings}
            assert keys == {"agent.model", "agent.temperature"}

    async def test_upsert_creates_new_setting(self, db_manager):
        """Test upsert creates new setting when key doesn't exist."""
        async with db_manager.session() as session:
            repo = SettingsRepository(session)
            setting = await repo.upsert(
                key="new.key",
                value="new-value",
                category="test",
                encrypted=False,
            )

            assert setting.id is not None
            assert setting.key == "new.key"
            assert setting.value == {"value": "new-value"}
            assert setting.category == "test"
            assert setting.encrypted is False

    async def test_upsert_updates_existing_setting(self, db_manager):
        """Test upsert updates existing setting when key exists."""
        async with db_manager.session() as session:
            setting = Setting(
                key="update.key",
                value={"value": "old-value"},
                category="old-category",
                encrypted=False,
            )
            session.add(setting)
            await session.commit()

        async with db_manager.session() as session:
            repo = SettingsRepository(session)
            updated = await repo.upsert(
                key="update.key",
                value="new-value",
                category="new-category",
                encrypted=True,
            )

            assert updated.key == "update.key"
            assert updated.value == {"value": "new-value"}
            assert updated.category == "new-category"
            assert updated.encrypted is True

        # Verify no duplicate was created
        async with db_manager.session() as session:
            repo = SettingsRepository(session)
            all_settings = await repo.list_all()
            matching = [s for s in all_settings if s.key == "update.key"]
            assert len(matching) == 1


class TestBuiltinRepository:
    """Test BuiltinRepository methods."""

    async def test_get_config_global(self, db_manager):
        """Test retrieving global builtin config."""
        async with db_manager.session() as session:
            builtin = BuiltinConfig(
                workspace_id=None,
                builtin_name="brave_search",
                enabled=True,
                config={"count": 5},
            )
            session.add(builtin)
            await session.commit()

        async with db_manager.session() as session:
            repo = BuiltinRepository(session)
            retrieved = await repo.get_config("brave_search", workspace_id=None)

            assert retrieved is not None
            assert retrieved.builtin_name == "brave_search"
            assert retrieved.workspace_id is None
            assert retrieved.config == {"count": 5}

    async def test_get_config_workspace_specific(self, db_manager):
        """Test retrieving workspace-specific builtin config."""
        async with db_manager.session() as session:
            workspace = Workspace(name="test", path="/path")
            builtin = BuiltinConfig(
                workspace=workspace,
                builtin_name="whisper",
                enabled=True,
                config={"model": "whisper-1"},
            )
            session.add(workspace)
            session.add(builtin)
            await session.commit()
            workspace_id = workspace.id

        async with db_manager.session() as session:
            repo = BuiltinRepository(session)
            retrieved = await repo.get_config("whisper", workspace_id=workspace_id)

            assert retrieved is not None
            assert retrieved.builtin_name == "whisper"
            assert retrieved.workspace_id == workspace_id
            assert retrieved.config == {"model": "whisper-1"}

    async def test_get_config_not_found(self, db_manager):
        """Test get_config returns None when not found."""
        async with db_manager.session() as session:
            repo = BuiltinRepository(session)
            retrieved = await repo.get_config("non-existent", workspace_id=None)

            assert retrieved is None

    async def test_get_or_create_config_creates_new(self, db_manager):
        """Test get_or_create_config creates new config when not found."""
        async with db_manager.session() as session:
            repo = BuiltinRepository(session)
            config = await repo.get_or_create_config("new_builtin", workspace_id=None)

            assert config.id is not None
            assert config.builtin_name == "new_builtin"
            assert config.workspace_id is None
            assert config.enabled is True
            assert config.config == {}

    async def test_get_or_create_config_returns_existing(self, db_manager):
        """Test get_or_create_config returns existing config."""
        async with db_manager.session() as session:
            existing = BuiltinConfig(
                workspace_id=None,
                builtin_name="existing",
                enabled=False,
                config={"key": "value"},
            )
            session.add(existing)
            await session.commit()
            existing_id = existing.id

        async with db_manager.session() as session:
            repo = BuiltinRepository(session)
            config = await repo.get_or_create_config("existing", workspace_id=None)

            assert config.id == existing_id
            assert config.enabled is False
            assert config.config == {"key": "value"}

    async def test_get_allowlist_empty(self, db_manager):
        """Test get_allowlist returns empty lists when no entries."""
        async with db_manager.session() as session:
            repo = BuiltinRepository(session)
            lists = await repo.get_allowlist(workspace_id=None)

            assert lists == {"allow": [], "deny": []}

    async def test_get_allowlist_global(self, db_manager):
        """Test get_allowlist retrieves global allow/deny lists."""
        async with db_manager.session() as session:
            allow1 = BuiltinAllowlist(
                workspace_id=None,
                entry="brave_search",
                list_type=ListType.ALLOW,
            )
            allow2 = BuiltinAllowlist(
                workspace_id=None,
                entry="whisper",
                list_type=ListType.ALLOW,
            )
            deny1 = BuiltinAllowlist(
                workspace_id=None,
                entry="group:voice",
                list_type=ListType.DENY,
            )
            session.add_all([allow1, allow2, deny1])
            await session.commit()

        async with db_manager.session() as session:
            repo = BuiltinRepository(session)
            lists = await repo.get_allowlist(workspace_id=None)

            assert set(lists["allow"]) == {"brave_search", "whisper"}
            assert lists["deny"] == ["group:voice"]

    async def test_get_allowlist_workspace_specific(self, db_manager):
        """Test get_allowlist retrieves workspace-specific lists."""
        async with db_manager.session() as session:
            workspace = Workspace(name="test", path="/path")
            allow = BuiltinAllowlist(
                workspace=workspace,
                entry="elevenlabs",
                list_type=ListType.ALLOW,
            )
            deny = BuiltinAllowlist(
                workspace=workspace,
                entry="brave_search",
                list_type=ListType.DENY,
            )
            session.add_all([workspace, allow, deny])
            await session.commit()
            workspace_id = workspace.id

        async with db_manager.session() as session:
            repo = BuiltinRepository(session)
            lists = await repo.get_allowlist(workspace_id=workspace_id)

            assert lists["allow"] == ["elevenlabs"]
            assert lists["deny"] == ["brave_search"]

    async def test_get_allowlist_isolates_workspaces(self, db_manager):
        """Test get_allowlist only returns entries for specified workspace."""
        async with db_manager.session() as session:
            workspace = Workspace(name="test", path="/path")
            global_entry = BuiltinAllowlist(
                workspace_id=None,
                entry="global",
                list_type=ListType.ALLOW,
            )
            workspace_entry = BuiltinAllowlist(
                workspace=workspace,
                entry="workspace",
                list_type=ListType.ALLOW,
            )
            session.add_all([workspace, global_entry, workspace_entry])
            await session.commit()
            workspace_id = workspace.id

        # Get global list
        async with db_manager.session() as session:
            repo = BuiltinRepository(session)
            global_lists = await repo.get_allowlist(workspace_id=None)
            assert global_lists["allow"] == ["global"]

        # Get workspace list
        async with db_manager.session() as session:
            repo = BuiltinRepository(session)
            workspace_lists = await repo.get_allowlist(workspace_id=workspace_id)
            assert workspace_lists["allow"] == ["workspace"]
