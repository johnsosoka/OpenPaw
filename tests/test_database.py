"""Tests for database manager."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import select, text

from openpaw.db.database import DatabaseManager, get_db_manager, init_db_manager
from openpaw.db.models import Base, Workspace


class TestDatabaseManager:
    """Test DatabaseManager functionality."""

    async def test_init_creates_database_file(self):
        """Test database file is created on init."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            manager = DatabaseManager(db_path)
            await manager.init_db()

            assert db_path.exists()

            await manager.close()

    async def test_init_db_creates_tables(self):
        """Test init_db creates all required tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            manager = DatabaseManager(db_path)
            await manager.init_db()

            # Verify tables exist by querying sqlite_master
            async with manager.session() as session:
                result = await session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )
                tables = {row[0] for row in result.fetchall()}

            # Check for key tables
            expected_tables = {
                "workspaces",
                "workspace_configs",
                "channel_bindings",
                "cron_jobs",
                "settings",
                "builtin_configs",
                "agent_metrics",
            }
            assert expected_tables.issubset(tables)

            await manager.close()

    async def test_session_context_manager_commits_on_success(self):
        """Test session context manager commits changes on success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            manager = DatabaseManager(db_path)
            await manager.init_db()

            # Create a workspace within session context
            async with manager.session() as session:
                workspace = Workspace(
                    name="test-workspace",
                    path="/path/to/workspace",
                    enabled=True,
                )
                session.add(workspace)
                # Context manager should auto-commit

            # Verify the workspace was persisted
            async with manager.session() as session:
                result = await session.execute(
                    select(Workspace).where(Workspace.name == "test-workspace")
                )
                saved_workspace = result.scalar_one_or_none()
                assert saved_workspace is not None
                assert saved_workspace.name == "test-workspace"

            await manager.close()

    async def test_session_context_manager_rolls_back_on_exception(self):
        """Test session context manager rolls back changes on exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            manager = DatabaseManager(db_path)
            await manager.init_db()

            # Try to create a workspace but raise an exception
            with pytest.raises(ValueError):
                async with manager.session() as session:
                    workspace = Workspace(
                        name="test-workspace",
                        path="/path/to/workspace",
                        enabled=True,
                    )
                    session.add(workspace)
                    raise ValueError("Simulated error")

            # Verify the workspace was NOT persisted
            async with manager.session() as session:
                result = await session.execute(
                    select(Workspace).where(Workspace.name == "test-workspace")
                )
                saved_workspace = result.scalar_one_or_none()
                assert saved_workspace is None

            await manager.close()

    async def test_foreign_keys_enabled(self):
        """Test that foreign key constraints are enabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            manager = DatabaseManager(db_path)
            await manager.init_db()

            # Check PRAGMA foreign_keys is ON
            async with manager.session() as session:
                result = await session.execute(text("PRAGMA foreign_keys"))
                fk_status = result.scalar()
                assert fk_status == 1  # 1 means ON

            await manager.close()

    async def test_close_disposes_engine(self):
        """Test close method disposes the engine."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            manager = DatabaseManager(db_path)
            await manager.init_db()

            # Close the manager
            await manager.close()

            # Engine should be disposed (we can't directly check, but verify no error)
            assert manager.engine is not None


class TestSingletonAccess:
    """Test singleton database manager access."""

    def setup_method(self):
        """Reset singleton before each test."""
        # Access the module-level _db_manager and reset it
        import openpaw.db.database

        openpaw.db.database._db_manager = None

    async def test_init_db_manager_creates_singleton(self):
        """Test init_db_manager creates and returns manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            manager = init_db_manager(db_path)

            assert manager is not None
            assert isinstance(manager, DatabaseManager)
            assert manager.db_path == db_path

            await manager.close()

    async def test_get_db_manager_returns_singleton(self):
        """Test get_db_manager returns initialized singleton."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            manager1 = init_db_manager(db_path)
            manager2 = get_db_manager()

            # Should return the same instance
            assert manager1 is manager2

            await manager1.close()

    def test_get_db_manager_raises_if_not_initialized(self):
        """Test get_db_manager raises error if not initialized."""
        with pytest.raises(RuntimeError, match="Database not initialized"):
            get_db_manager()

    async def test_init_db_manager_replaces_existing_singleton(self):
        """Test init_db_manager replaces existing singleton."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path1 = Path(tmpdir) / "test1.db"
            db_path2 = Path(tmpdir) / "test2.db"

            manager1 = init_db_manager(db_path1)
            manager2 = init_db_manager(db_path2)

            # Should be different instances
            assert manager1 is not manager2
            assert manager1.db_path == db_path1
            assert manager2.db_path == db_path2

            # get_db_manager should return the latest
            manager3 = get_db_manager()
            assert manager3 is manager2

            await manager1.close()
            await manager2.close()
