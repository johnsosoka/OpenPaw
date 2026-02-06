"""Tests for MigrationService."""

import tempfile
from pathlib import Path

import pytest
import yaml

from openpaw.api.services.encryption import EncryptionService
from openpaw.api.services.migration_service import MigrationService
from openpaw.db.database import DatabaseManager
from openpaw.db.models import (
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


@pytest.fixture
def encryption_service():
    """Provide an encryption service instance."""
    return EncryptionService()


@pytest.fixture
async def migration_service(db_manager, encryption_service):
    """Provide a MigrationService with clean database."""
    async with db_manager.session() as session:
        yield MigrationService(session, encryption_service)


class TestGlobalConfigImport:
    """Test importing global config.yaml settings."""

    async def test_import_global_config_success(self, db_manager, encryption_service):
        """Test import_global_config imports all settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_data = {
                "agent": {
                    "model": "anthropic:claude-sonnet-4",
                    "temperature": 0.7,
                    "max_turns": 50,
                    "api_key": "test-key-123",
                },
                "queue": {
                    "mode": "collect",
                    "debounce_ms": 1000,
                    "cap": 20,
                    "drop_policy": "oldest",
                },
                "lanes": {
                    "main_concurrency": 4,
                    "subagent_concurrency": 8,
                    "cron_concurrency": 2,
                },
                "builtins": {
                    "allow": ["brave_search"],
                    "deny": ["group:voice"],
                },
            }
            with config_path.open("w") as f:
                yaml.dump(config_data, f)

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                result = await service.import_global_config(config_path, overwrite=False)

                assert result.imported > 0
                assert result.errors == []

            # Verify settings were imported
            async with db_manager.session() as session:
                from sqlalchemy import select
                result = await session.execute(select(Setting))
                settings = {s.key: s.value for s in result.scalars().all()}

                assert settings["agent.model"]["value"] == "anthropic:claude-sonnet-4"
                assert settings["agent.temperature"]["value"] == 0.7
                assert settings["queue.mode"]["value"] == "collect"
                assert settings["lanes.main_concurrency"]["value"] == 4

    async def test_import_global_config_handles_missing_file(self, migration_service):
        """Test import_global_config handles missing file gracefully."""
        result = await migration_service.import_global_config(
            Path("/nonexistent/config.yaml"),
            overwrite=False
        )

        assert result.imported == 0
        assert len(result.errors) > 0
        assert "Failed to load" in result.errors[0]

    async def test_import_global_config_encrypts_api_key(self, db_manager, encryption_service):
        """Test import_global_config encrypts sensitive data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_data = {
                "agent": {
                    "model": "claude",
                    "api_key": "secret-key-123",
                }
            }
            with config_path.open("w") as f:
                yaml.dump(config_data, f)

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                await service.import_global_config(config_path, overwrite=False)

            # Verify API key is encrypted
            async with db_manager.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Setting).where(Setting.key == "agent.api_key")
                )
                setting = result.scalar_one_or_none()

                assert setting is not None
                assert setting.encrypted is True
                assert "encrypted_value" in setting.value
                # Should be able to decrypt
                decrypted = encryption_service.decrypt(setting.value["encrypted_value"])
                assert decrypted == "secret-key-123"

    async def test_import_global_config_with_overwrite(self, db_manager, encryption_service):
        """Test import_global_config with overwrite=True updates existing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"

            # First import
            config_data = {"agent": {"model": "old-model"}}
            with config_path.open("w") as f:
                yaml.dump(config_data, f)

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                await service.import_global_config(config_path, overwrite=False)

            # Second import with different value
            config_data = {"agent": {"model": "new-model"}}
            with config_path.open("w") as f:
                yaml.dump(config_data, f)

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                result = await service.import_global_config(config_path, overwrite=True)

                assert result.imported > 0

            # Verify value was updated
            async with db_manager.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Setting).where(Setting.key == "agent.model")
                )
                setting = result.scalar_one()
                assert setting.value["value"] == "new-model"

    async def test_import_builtin_lists(self, db_manager, encryption_service):
        """Test import_global_config imports builtin allow/deny lists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_data = {
                "agent": {"model": "test"},
                "builtins": {
                    "allow": ["brave_search", "elevenlabs"],
                    "deny": ["group:voice", "whisper"],
                },
            }
            with config_path.open("w") as f:
                yaml.dump(config_data, f)

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                await service.import_global_config(config_path, overwrite=False)

            # Verify allowlists were created
            async with db_manager.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(BuiltinAllowlist).where(
                        BuiltinAllowlist.workspace_id.is_(None)
                    )
                )
                allowlists = result.scalars().all()

                allow_entries = [a.entry for a in allowlists if a.list_type == ListType.ALLOW.value]
                deny_entries = [a.entry for a in allowlists if a.list_type == ListType.DENY.value]

                assert "brave_search" in allow_entries
                assert "elevenlabs" in allow_entries
                assert "group:voice" in deny_entries
                assert "whisper" in deny_entries


class TestWorkspaceImport:
    """Test importing workspace configurations."""

    async def test_import_workspace_creates_record(self, db_manager, encryption_service):
        """Test import_workspace creates workspace in database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir) / "test-workspace"
            workspace_path.mkdir()

            # Create required files
            (workspace_path / "AGENT.md").write_text("# Agent")
            (workspace_path / "USER.md").write_text("# User")
            (workspace_path / "SOUL.md").write_text("# Soul")
            (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat")

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                result = await service.import_workspace(workspace_path, overwrite=False)

                assert result.imported == 1
                assert result.errors == []

            # Verify workspace was created
            async with db_manager.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Workspace).where(Workspace.name == "test-workspace")
                )
                workspace = result.scalar_one_or_none()

                assert workspace is not None
                assert workspace.name == "test-workspace"
                assert workspace.enabled is True

    async def test_import_workspace_with_config(self, db_manager, encryption_service):
        """Test import_workspace imports agent.yaml configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir) / "test-workspace"
            workspace_path.mkdir()

            # Create required files
            (workspace_path / "AGENT.md").write_text("# Agent")
            (workspace_path / "USER.md").write_text("# User")
            (workspace_path / "SOUL.md").write_text("# Soul")
            (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat")

            # Create agent.yaml
            agent_config = {
                "name": "test-workspace",
                "description": "Test workspace",
                "model": {
                    "provider": "anthropic",
                    "model": "claude-sonnet-4",
                    "temperature": 0.7,
                    "max_turns": 50,
                    "api_key": "test-api-key",
                },
                "queue": {
                    "mode": "collect",
                    "debounce_ms": 2000,
                },
                "channel": {
                    "type": "telegram",
                    "token": "telegram-token",
                    "allowed_users": [123, 456],
                },
            }
            with (workspace_path / "agent.yaml").open("w") as f:
                yaml.dump(agent_config, f)

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                result = await service.import_workspace(workspace_path, overwrite=False)

                assert result.imported > 0
                assert result.errors == []

            # Verify workspace config was created
            async with db_manager.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Workspace).where(Workspace.name == "test-workspace")
                )
                workspace = result.scalar_one()

                assert workspace.config is not None
                assert workspace.config.model_provider == "anthropic"
                assert workspace.config.model_name == "claude-sonnet-4"
                assert workspace.config.temperature == 0.7
                assert workspace.config.queue_mode == "collect"

                # Verify API key is encrypted
                assert workspace.config.api_key_encrypted is not None

    async def test_import_workspace_with_channel_binding(self, db_manager, encryption_service):
        """Test import_workspace creates channel binding with encrypted config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir) / "test-workspace"
            workspace_path.mkdir()

            # Create required files
            (workspace_path / "AGENT.md").write_text("# Agent")
            (workspace_path / "USER.md").write_text("# User")
            (workspace_path / "SOUL.md").write_text("# Soul")
            (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat")

            # Create agent.yaml with channel config
            agent_config = {
                "name": "test-workspace",
                "channel": {
                    "type": "telegram",
                    "token": "secret-token-123",
                    "allowed_users": [123],
                    "allowed_groups": [],
                },
            }
            with (workspace_path / "agent.yaml").open("w") as f:
                yaml.dump(agent_config, f)

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                await service.import_workspace(workspace_path, overwrite=False)

            # Verify channel binding was created
            async with db_manager.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(Workspace).where(Workspace.name == "test-workspace")
                )
                workspace = result.scalar_one()

                assert workspace.channel_binding is not None
                assert workspace.channel_binding.channel_type == "telegram"
                assert workspace.channel_binding.allowed_users == [123]
                assert workspace.channel_binding.config_encrypted is not None

                # Verify token is encrypted
                decrypted = encryption_service.decrypt_json(
                    workspace.channel_binding.config_encrypted
                )
                assert decrypted["token"] == "secret-token-123"

    async def test_import_workspace_handles_missing_files(self, db_manager, encryption_service):
        """Test import_workspace handles missing workspace gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir) / "nonexistent"

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                result = await service.import_workspace(workspace_path, overwrite=False)

                assert result.imported == 0
                assert len(result.errors) > 0


class TestCronImport:
    """Test importing cron job definitions."""

    async def test_import_crons_success(self, db_manager, encryption_service):
        """Test import_crons creates cron job records."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir) / "test-workspace"
            workspace_path.mkdir()

            # Create required files
            (workspace_path / "AGENT.md").write_text("# Agent")
            (workspace_path / "USER.md").write_text("# User")
            (workspace_path / "SOUL.md").write_text("# Soul")
            (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat")

            # Create cron directory and job
            crons_path = workspace_path / "crons"
            crons_path.mkdir()

            cron_config = {
                "name": "daily-summary",
                "schedule": "0 9 * * *",
                "enabled": True,
                "prompt": "Generate daily summary",
                "output": {
                    "channel": "telegram",
                    "chat_id": 123456,
                },
            }
            with (crons_path / "daily-summary.yaml").open("w") as f:
                yaml.dump(cron_config, f)

            # First create workspace
            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                await service.import_workspace(workspace_path, overwrite=False)

            # Then import crons
            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                result = await service.import_crons(
                    "test-workspace",
                    workspace_path,
                    overwrite=False
                )

                assert result.imported > 0
                assert result.errors == []

            # Verify cron job was created
            async with db_manager.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(CronJob).where(CronJob.name == "daily-summary")
                )
                cron = result.scalar_one_or_none()

                assert cron is not None
                assert cron.schedule == "0 9 * * *"
                assert cron.enabled is True
                assert cron.prompt == "Generate daily summary"
                assert cron.output_config["channel"] == "telegram"

    async def test_import_crons_workspace_not_found(self, db_manager, encryption_service):
        """Test import_crons handles missing workspace gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir) / "test-workspace"
            workspace_path.mkdir()

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                result = await service.import_crons(
                    "nonexistent",
                    workspace_path,
                    overwrite=False
                )

                assert result.imported == 0
                assert len(result.errors) > 0
                assert "not found" in result.errors[0]

    async def test_import_crons_no_crons_directory(self, db_manager, encryption_service):
        """Test import_crons handles missing crons directory gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir) / "test-workspace"
            workspace_path.mkdir()

            # Create workspace first
            async with db_manager.session() as session:
                workspace = Workspace(
                    name="test-workspace",
                    path=str(workspace_path),
                    enabled=True,
                )
                session.add(workspace)
                await session.commit()

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                result = await service.import_crons(
                    "test-workspace",
                    workspace_path,
                    overwrite=False
                )

                assert result.skipped > 0
                assert "No crons directory" in result.details.get("reason", "")


class TestBatchImport:
    """Test batch import operations."""

    async def test_import_all_workspaces(self, db_manager, encryption_service):
        """Test import_all_workspaces processes multiple workspaces."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspaces_path = Path(tmpdir)

            # Create two workspaces
            for name in ["workspace1", "workspace2"]:
                ws_path = workspaces_path / name
                ws_path.mkdir()
                (ws_path / "AGENT.md").write_text("# Agent")
                (ws_path / "USER.md").write_text("# User")
                (ws_path / "SOUL.md").write_text("# Soul")
                (ws_path / "HEARTBEAT.md").write_text("# Heartbeat")

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                results = await service.import_all_workspaces(
                    workspaces_path,
                    overwrite=False
                )

                assert "workspace1" in results
                assert "workspace2" in results
                assert results["workspace1"].imported > 0
                assert results["workspace2"].imported > 0


class TestMigrationTracking:
    """Test migration result tracking."""

    def test_migration_result_add_error(self):
        """Test MigrationResult.add_error increments error count."""
        from openpaw.api.services.migration_service import MigrationResult

        result = MigrationResult()
        result.add_error("Test error")

        assert len(result.errors) == 1
        assert result.errors[0] == "Test error"

    def test_migration_result_add_imported(self):
        """Test MigrationResult.add_imported increments count."""
        from openpaw.api.services.migration_service import MigrationResult

        result = MigrationResult()
        result.add_imported()
        result.add_imported(3)

        assert result.imported == 4

    def test_migration_result_add_skipped(self):
        """Test MigrationResult.add_skipped increments count."""
        from openpaw.api.services.migration_service import MigrationResult

        result = MigrationResult()
        result.add_skipped()
        result.add_skipped(2)

        assert result.skipped == 3


class TestEncryptionInMigration:
    """Test encryption is properly applied during migration."""

    async def test_workspace_api_key_encryption(self, db_manager, encryption_service):
        """Test workspace API keys are encrypted during import."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir) / "test"
            workspace_path.mkdir()

            # Create required files
            (workspace_path / "AGENT.md").write_text("# Agent")
            (workspace_path / "USER.md").write_text("# User")
            (workspace_path / "SOUL.md").write_text("# Soul")
            (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat")

            agent_config = {
                "model": {
                    "provider": "anthropic",
                    "model": "claude",
                    "api_key": "sensitive-key-123",
                }
            }
            with (workspace_path / "agent.yaml").open("w") as f:
                yaml.dump(agent_config, f)

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                await service.import_workspace(workspace_path, overwrite=False)

            # Verify API key is encrypted in database
            async with db_manager.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(WorkspaceConfig)
                )
                config = result.scalar_one()

                assert config.api_key_encrypted is not None
                decrypted = encryption_service.decrypt(config.api_key_encrypted)
                assert decrypted == "sensitive-key-123"

    async def test_channel_token_encryption(self, db_manager, encryption_service):
        """Test channel tokens are encrypted during import."""
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_path = Path(tmpdir) / "test"
            workspace_path.mkdir()

            # Create required files
            (workspace_path / "AGENT.md").write_text("# Agent")
            (workspace_path / "USER.md").write_text("# User")
            (workspace_path / "SOUL.md").write_text("# Soul")
            (workspace_path / "HEARTBEAT.md").write_text("# Heartbeat")

            agent_config = {
                "channel": {
                    "type": "telegram",
                    "token": "sensitive-telegram-token",
                }
            }
            with (workspace_path / "agent.yaml").open("w") as f:
                yaml.dump(agent_config, f)

            async with db_manager.session() as session:
                service = MigrationService(session, encryption_service)
                await service.import_workspace(workspace_path, overwrite=False)

            # Verify token is encrypted
            async with db_manager.session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(ChannelBinding)
                )
                binding = result.scalar_one()

                assert binding.config_encrypted is not None
                decrypted = encryption_service.decrypt_json(binding.config_encrypted)
                assert decrypted["token"] == "sensitive-telegram-token"
