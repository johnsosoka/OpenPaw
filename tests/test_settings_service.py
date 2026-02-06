"""Tests for SettingsService."""

import tempfile
from pathlib import Path

import pytest
import yaml

from openpaw.api.services.settings_service import SettingsService
from openpaw.db.database import DatabaseManager
from openpaw.db.models import Setting


@pytest.fixture
async def db_manager():
    """Provide a temporary database manager."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        manager = DatabaseManager(db_path)
        await manager.init_db()
        yield manager
        await manager.close()


@pytest.fixture
async def settings_service(db_manager):
    """Provide a SettingsService instance with a clean database."""
    async with db_manager.session() as session:
        yield SettingsService(session)


class TestSettingsService:
    """Test SettingsService methods."""

    async def test_get_all_empty(self, settings_service):
        """Test get_all returns empty dict when no settings exist."""
        result = await settings_service.get_all()
        assert result == {}

    async def test_get_all_grouped_by_category(self, db_manager):
        """Test get_all groups settings by category."""
        async with db_manager.session() as session:
            settings = [
                Setting(
                    key="agent.model",
                    value={"value": "claude-sonnet-4"},
                    category="agent",
                ),
                Setting(
                    key="agent.temperature",
                    value={"value": 0.7},
                    category="agent",
                ),
                Setting(
                    key="queue.mode",
                    value={"value": "collect"},
                    category="queue",
                ),
                Setting(
                    key="lanes.main_concurrency",
                    value={"value": 4},
                    category="lanes",
                ),
            ]
            session.add_all(settings)
            await session.commit()

        async with db_manager.session() as session:
            service = SettingsService(session)
            result = await service.get_all()

            assert "agent" in result
            assert "queue" in result
            assert "lanes" in result

            assert result["agent"]["model"] == "claude-sonnet-4"
            assert result["agent"]["temperature"] == 0.7
            assert result["queue"]["mode"] == "collect"
            assert result["lanes"]["main_concurrency"] == 4

    async def test_get_category_valid(self, db_manager):
        """Test get_category returns settings for valid category."""
        async with db_manager.session() as session:
            settings = [
                Setting(
                    key="agent.model",
                    value={"value": "claude"},
                    category="agent",
                ),
                Setting(
                    key="agent.temperature",
                    value={"value": 0.5},
                    category="agent",
                ),
                Setting(
                    key="queue.mode",
                    value={"value": "steer"},
                    category="queue",
                ),
            ]
            session.add_all(settings)
            await session.commit()

        async with db_manager.session() as session:
            service = SettingsService(session)
            result = await service.get_category("agent")

            assert result is not None
            assert len(result) == 2
            assert result["model"] == "claude"
            assert result["temperature"] == 0.5

    async def test_get_category_invalid(self, settings_service):
        """Test get_category returns None for invalid category."""
        result = await settings_service.get_category("invalid")
        assert result is None

    async def test_get_category_empty(self, settings_service):
        """Test get_category returns empty dict for valid but empty category."""
        result = await settings_service.get_category("agent")
        assert result == {}

    async def test_update_category_creates_new_settings(self, db_manager):
        """Test update_category creates new settings."""
        async with db_manager.session() as session:
            service = SettingsService(session)
            data = {
                "model": "claude-sonnet-4",
                "temperature": 0.7,
                "max_turns": 50,
            }
            result = await service.update_category("agent", data)
            await session.commit()

            assert result["model"] == "claude-sonnet-4"
            assert result["temperature"] == 0.7
            assert result["max_turns"] == 50

        # Verify settings were persisted
        async with db_manager.session() as session:
            service = SettingsService(session)
            retrieved = await service.get_category("agent")

            assert retrieved is not None
            assert retrieved["model"] == "claude-sonnet-4"
            assert retrieved["temperature"] == 0.7
            assert retrieved["max_turns"] == 50

    async def test_update_category_updates_existing_settings(self, db_manager):
        """Test update_category updates existing settings."""
        async with db_manager.session() as session:
            setting = Setting(
                key="agent.model",
                value={"value": "old-model"},
                category="agent",
            )
            session.add(setting)
            await session.commit()

        async with db_manager.session() as session:
            service = SettingsService(session)
            result = await service.update_category("agent", {"model": "new-model"})
            await session.commit()

            assert result["model"] == "new-model"

        # Verify update was persisted
        async with db_manager.session() as session:
            service = SettingsService(session)
            retrieved = await service.get_category("agent")
            assert retrieved["model"] == "new-model"

    async def test_update_category_invalid_raises_error(self, settings_service):
        """Test update_category raises ValueError for invalid category."""
        with pytest.raises(ValueError, match="Invalid category: invalid"):
            await settings_service.update_category("invalid", {"key": "value"})

    async def test_import_from_yaml_success(self, db_manager):
        """Test importing settings from YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_data = {
                "agent": {
                    "model": "anthropic:claude-sonnet-4",
                    "temperature": 0.7,
                    "max_turns": 50,
                },
                "queue": {
                    "mode": "collect",
                    "debounce_ms": 1000,
                    "cap": 20,
                },
                "lanes": {
                    "main_concurrency": 4,
                    "subagent_concurrency": 8,
                },
            }
            with config_path.open("w") as f:
                yaml.dump(config_data, f)

            async with db_manager.session() as session:
                service = SettingsService(session)
                result = await service.import_from_yaml(config_path)
                await session.commit()

                assert result["imported"]["settings"] == 8
                assert result["skipped"] == 0
                assert result["errors"] == []

            # Verify settings were imported
            async with db_manager.session() as session:
                service = SettingsService(session)
                agent = await service.get_category("agent")
                queue = await service.get_category("queue")
                lanes = await service.get_category("lanes")

                assert agent is not None
                assert agent["model"] == "anthropic:claude-sonnet-4"
                assert agent["temperature"] == 0.7

                assert queue is not None
                assert queue["mode"] == "collect"

                assert lanes is not None
                assert lanes["main_concurrency"] == 4

    async def test_import_from_yaml_with_builtins(self, db_manager):
        """Test importing builtins from YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_data = {
                "agent": {
                    "model": "claude",
                },
                "builtins": {
                    "brave_search": {
                        "enabled": True,
                        "config": {"count": 5},
                    },
                    "whisper": {
                        "enabled": True,
                    },
                },
            }
            with config_path.open("w") as f:
                yaml.dump(config_data, f)

            async with db_manager.session() as session:
                service = SettingsService(session)
                result = await service.import_from_yaml(config_path)
                await session.commit()

                # Should import agent settings and builtins
                assert result["imported"]["settings"] == 1
                assert result["imported"]["builtins"] > 0
                assert result["errors"] == []

    async def test_import_from_yaml_file_not_found(self, settings_service):
        """Test import_from_yaml handles missing file gracefully."""
        result = await settings_service.import_from_yaml(Path("/nonexistent/path.yaml"))

        assert result["imported"]["settings"] == 0
        assert result["imported"]["builtins"] == 0
        assert len(result["errors"]) == 1
        assert "not found" in result["errors"][0]

    async def test_import_from_yaml_invalid_yaml(self, settings_service):
        """Test import_from_yaml handles invalid YAML gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "invalid.yaml"
            config_path.write_text("invalid: yaml: content: [")

            result = await settings_service.import_from_yaml(config_path)

            assert result["imported"]["settings"] == 0
            assert len(result["errors"]) == 1
            assert "YAML parsing error" in result["errors"][0]

    async def test_import_from_yaml_empty_file(self, settings_service):
        """Test import_from_yaml handles empty YAML file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "empty.yaml"
            config_path.write_text("")

            result = await settings_service.import_from_yaml(config_path)

            assert result["imported"]["settings"] == 0
            assert len(result["errors"]) == 1
            assert "Empty or invalid" in result["errors"][0]

    async def test_flatten_dict_simple(self, settings_service):
        """Test _flatten_dict with simple nested structure."""
        data = {
            "level1": {
                "level2": "value",
            }
        }
        result = settings_service._flatten_dict(data)
        assert result == {"level1.level2": "value"}

    async def test_flatten_dict_multiple_levels(self, settings_service):
        """Test _flatten_dict with multiple nesting levels."""
        data = {
            "a": {
                "b": {
                    "c": "deep-value",
                },
                "d": "shallow-value",
            },
            "e": "top-value",
        }
        result = settings_service._flatten_dict(data)
        assert result["a.b.c"] == "deep-value"
        assert result["a.d"] == "shallow-value"
        assert result["e"] == "top-value"

    async def test_flatten_dict_with_prefix(self, settings_service):
        """Test _flatten_dict with custom prefix."""
        data = {"key": "value"}
        result = settings_service._flatten_dict(data, prefix="prefix")
        assert result == {"prefix.key": "value"}

    async def test_valid_categories(self):
        """Test VALID_CATEGORIES constant is correct."""
        assert SettingsService.VALID_CATEGORIES == {"agent", "queue", "lanes"}
