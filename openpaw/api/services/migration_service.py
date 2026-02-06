"""Service for migrating YAML configurations to database."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openpaw.api.services.encryption import EncryptionService
from openpaw.core.config import (
    Config,
    WorkspaceConfig,
    load_config,
)
from openpaw.cron.loader import CronDefinition
from openpaw.db.models import (
    BuiltinAllowlist,
    BuiltinConfig,
    ChannelBinding,
    CronJob,
    ListType,
    Setting,
    Workspace,
)
from openpaw.db.models import (
    WorkspaceConfig as WorkspaceConfigModel,
)
from openpaw.workspace.loader import WorkspaceLoader

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    """Result of a migration operation."""

    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def add_error(self, error: str) -> None:
        """Add an error message to the result."""
        self.errors.append(error)
        logger.error(error)

    def add_imported(self, count: int = 1) -> None:
        """Increment imported count."""
        self.imported += count

    def add_skipped(self, count: int = 1) -> None:
        """Increment skipped count."""
        self.skipped += count


@dataclass
class VerificationResult:
    """Result of verifying migration against YAML."""

    matches: bool
    differences: list[str] = field(default_factory=list)


class MigrationService:
    """Handles migration from YAML files to database configuration."""

    def __init__(
        self,
        session: AsyncSession,
        encryption: EncryptionService,
    ):
        """Initialize the migration service.

        Args:
            session: Database session for queries and commits.
            encryption: Encryption service for sensitive data.
        """
        self.session = session
        self.encryption = encryption

    async def import_global_config(
        self,
        config_path: Path,
        overwrite: bool = False,
    ) -> MigrationResult:
        """Import global config.yaml settings to database.

        Imports:
        - agent.* settings (model, temperature, max_turns)
        - queue.* settings (mode, debounce_ms, cap, drop_policy)
        - lanes.* settings (concurrency values)
        - builtins allow/deny lists

        Args:
            config_path: Path to config.yaml file.
            overwrite: If True, update existing settings. If False, skip existing.

        Returns:
            MigrationResult with counts and error details.
        """
        result = MigrationResult()

        try:
            config = load_config(config_path)
        except Exception as e:
            result.add_error(f"Failed to load config file: {e}")
            return result

        # Import agent settings
        await self._import_agent_settings(config, result, overwrite)

        # Import queue settings
        await self._import_queue_settings(config, result, overwrite)

        # Import lane settings
        await self._import_lane_settings(config, result, overwrite)

        # Import builtin allow/deny lists
        await self._import_builtin_lists(config, result, overwrite)

        # Import builtin configurations
        await self._import_builtin_configs(config, result, overwrite)

        try:
            await self.session.commit()
        except Exception as e:
            await self.session.rollback()
            result.add_error(f"Failed to commit global config: {e}")

        return result

    async def import_workspace(
        self,
        workspace_path: Path,
        overwrite: bool = False,
    ) -> MigrationResult:
        """Import a single workspace's agent.yaml config.

        Creates workspace record if not exists.
        Imports model config, queue config, channel config.
        Encrypts sensitive data (tokens, API keys).

        Args:
            workspace_path: Path to workspace directory.
            overwrite: If True, update existing records. If False, skip existing.

        Returns:
            MigrationResult with import details.
        """
        result = MigrationResult()

        workspace_name = workspace_path.name

        # Load workspace using existing loader
        loader = WorkspaceLoader(workspace_path.parent)
        try:
            workspace_data = loader.load(workspace_name)
        except Exception as e:
            result.add_error(f"Failed to load workspace {workspace_name}: {e}")
            return result

        # Create or get workspace record
        workspace_model = await self._get_or_create_workspace(
            workspace_name, workspace_path, workspace_data.config
        )

        if workspace_model is None:
            result.add_error(f"Failed to create/get workspace {workspace_name}")
            return result

        # Import workspace config (model, queue)
        if workspace_data.config:
            await self._import_workspace_config(
                workspace_model, workspace_data.config, result, overwrite
            )

            # Import channel binding
            await self._import_channel_binding(
                workspace_model, workspace_data.config, result, overwrite
            )

            # Import workspace-specific builtin configuration
            await self._import_workspace_builtins(
                workspace_model, workspace_data.config, result, overwrite
            )

        try:
            await self.session.commit()
            result.add_imported()
            result.details["workspace_name"] = workspace_name
        except Exception as e:
            await self.session.rollback()
            result.add_error(f"Failed to commit workspace {workspace_name}: {e}")

        return result

    async def import_all_workspaces(
        self,
        workspaces_path: Path,
        overwrite: bool = False,
    ) -> dict[str, MigrationResult]:
        """Import all workspaces from a directory.

        Args:
            workspaces_path: Path to agent_workspaces directory.
            overwrite: If True, update existing records.

        Returns:
            Dict mapping workspace name to MigrationResult.
        """
        results: dict[str, MigrationResult] = {}

        loader = WorkspaceLoader(workspaces_path)
        workspace_names = loader.list_workspaces()

        for workspace_name in workspace_names:
            workspace_path = workspaces_path / workspace_name
            result = await self.import_workspace(workspace_path, overwrite)
            results[workspace_name] = result

            # Import crons for this workspace
            cron_result = await self.import_crons(workspace_name, workspace_path, overwrite)
            results[f"{workspace_name}_crons"] = cron_result

        return results

    async def import_crons(
        self,
        workspace_name: str,
        workspace_path: Path,
        overwrite: bool = False,
    ) -> MigrationResult:
        """Import cron jobs from workspace's crons/ directory.

        Args:
            workspace_name: Name of the workspace.
            workspace_path: Path to workspace directory.
            overwrite: If True, update existing crons.

        Returns:
            MigrationResult with import details.
        """
        result = MigrationResult()

        # Get workspace from database
        stmt = select(Workspace).where(Workspace.name == workspace_name)
        db_result = await self.session.execute(stmt)
        workspace = db_result.scalar_one_or_none()

        if not workspace:
            result.add_error(f"Workspace {workspace_name} not found in database")
            return result

        # Load cron definitions
        crons_path = workspace_path / "crons"
        if not crons_path.exists():
            result.add_skipped()
            result.details["reason"] = "No crons directory found"
            return result

        loader = WorkspaceLoader(workspace_path.parent)
        try:
            workspace_data = loader.load(workspace_name)
            cron_definitions = workspace_data.crons
        except Exception as e:
            result.add_error(f"Failed to load crons for {workspace_name}: {e}")
            return result

        # Import each cron
        for cron_def in cron_definitions:
            try:
                await self._import_cron_job(
                    workspace, cron_def, result, overwrite
                )
            except Exception as e:
                result.add_error(f"Failed to import cron {cron_def.name}: {e}")

        try:
            await self.session.commit()
        except Exception as e:
            await self.session.rollback()
            result.add_error(f"Failed to commit crons for {workspace_name}: {e}")

        return result

    async def verify_migration(
        self,
        config_path: Path,
        workspaces_path: Path,
    ) -> VerificationResult:
        """Compare YAML config against database, report differences.

        Args:
            config_path: Path to global config.yaml.
            workspaces_path: Path to agent_workspaces directory.

        Returns:
            VerificationResult with match status and differences.
        """
        result = VerificationResult(matches=True)

        # Load YAML config
        try:
            config = load_config(config_path)
        except Exception as e:
            result.matches = False
            result.differences.append(f"Failed to load config: {e}")
            return result

        # Verify global settings
        await self._verify_global_settings(config, result)

        # Verify workspaces
        await self._verify_workspaces(workspaces_path, result)

        return result

    # =========================================================================
    # Private helper methods
    # =========================================================================

    async def _get_or_create_workspace(
        self,
        name: str,
        path: Path,
        config: WorkspaceConfig | None,
    ) -> Workspace | None:
        """Get existing workspace or create new one."""
        stmt = select(Workspace).where(Workspace.name == name)
        db_result = await self.session.execute(stmt)
        workspace = db_result.scalar_one_or_none()

        if workspace:
            return workspace

        # Create new workspace
        description = config.description if config else None
        workspace = Workspace(
            name=name,
            description=description,
            path=str(path.absolute()),
            enabled=True,
        )
        self.session.add(workspace)
        await self.session.flush()
        return workspace

    async def _import_agent_settings(
        self,
        config: Config,
        result: MigrationResult,
        overwrite: bool,
    ) -> None:
        """Import agent.* settings to database."""
        settings_to_import = {
            "agent.model": config.agent.model,
            "agent.temperature": config.agent.temperature,
            "agent.max_turns": config.agent.max_turns,
        }

        # Handle encrypted API key
        if config.agent.api_key:
            encrypted_key = self.encryption.encrypt(config.agent.api_key)
            await self._upsert_setting(
                "agent.api_key",
                {"encrypted_value": encrypted_key},
                encrypted=True,
                category="agent",
                result=result,
                overwrite=overwrite,
            )

        for key, value in settings_to_import.items():
            if value is not None:
                await self._upsert_setting(
                    key,
                    {"value": value},
                    encrypted=False,
                    category="agent",
                    result=result,
                    overwrite=overwrite,
                )

    async def _import_queue_settings(
        self,
        config: Config,
        result: MigrationResult,
        overwrite: bool,
    ) -> None:
        """Import queue.* settings to database."""
        settings_to_import = {
            "queue.mode": config.queue.mode,
            "queue.debounce_ms": config.queue.debounce_ms,
            "queue.cap": config.queue.cap,
            "queue.drop_policy": config.queue.drop_policy,
        }

        for key, value in settings_to_import.items():
            await self._upsert_setting(
                key,
                {"value": value},
                encrypted=False,
                category="queue",
                result=result,
                overwrite=overwrite,
            )

    async def _import_lane_settings(
        self,
        config: Config,
        result: MigrationResult,
        overwrite: bool,
    ) -> None:
        """Import lanes.* settings to database."""
        settings_to_import = {
            "lanes.main_concurrency": config.lanes.main_concurrency,
            "lanes.subagent_concurrency": config.lanes.subagent_concurrency,
            "lanes.cron_concurrency": config.lanes.cron_concurrency,
        }

        for key, value in settings_to_import.items():
            await self._upsert_setting(
                key,
                {"value": value},
                encrypted=False,
                category="lanes",
                result=result,
                overwrite=overwrite,
            )

    async def _import_builtin_lists(
        self,
        config: Config,
        result: MigrationResult,
        overwrite: bool,
    ) -> None:
        """Import builtins allow/deny lists to database."""
        # Delete existing lists if overwriting
        if overwrite:
            stmt = select(BuiltinAllowlist).where(BuiltinAllowlist.workspace_id.is_(None))
            db_result = await self.session.execute(stmt)
            existing = db_result.scalars().all()
            for item in existing:
                await self.session.delete(item)

        # Import allow list
        for entry in config.builtins.allow:
            allowlist_item = BuiltinAllowlist(
                workspace_id=None,
                entry=entry,
                list_type=ListType.ALLOW.value,
            )
            self.session.add(allowlist_item)
            result.add_imported()

        # Import deny list
        for entry in config.builtins.deny:
            denylist_item = BuiltinAllowlist(
                workspace_id=None,
                entry=entry,
                list_type=ListType.DENY.value,
            )
            self.session.add(denylist_item)
            result.add_imported()

    async def _import_builtin_configs(
        self,
        config: Config,
        result: MigrationResult,
        overwrite: bool,
    ) -> None:
        """Import builtin configurations (brave_search, whisper, elevenlabs)."""
        builtin_configs = {
            "brave_search": config.builtins.brave_search,
            "whisper": config.builtins.whisper,
            "elevenlabs": config.builtins.elevenlabs,
        }

        for builtin_name, builtin_config in builtin_configs.items():
            # Check if exists
            stmt = select(BuiltinConfig).where(
                BuiltinConfig.workspace_id.is_(None),
                BuiltinConfig.builtin_name == builtin_name,
            )
            db_result = await self.session.execute(stmt)
            existing = db_result.scalar_one_or_none()

            if existing and not overwrite:
                result.add_skipped()
                continue

            if existing:
                # Update existing
                existing.enabled = builtin_config.enabled
                existing.config = builtin_config.config
                result.add_imported()
            else:
                # Create new
                new_config = BuiltinConfig(
                    workspace_id=None,
                    builtin_name=builtin_name,
                    enabled=builtin_config.enabled,
                    config=builtin_config.config,
                )
                self.session.add(new_config)
                result.add_imported()

    async def _import_workspace_config(
        self,
        workspace: Workspace,
        config: WorkspaceConfig,
        result: MigrationResult,
        overwrite: bool,
    ) -> None:
        """Import workspace model and queue configuration."""
        # Check if config exists
        stmt = select(WorkspaceConfigModel).where(
            WorkspaceConfigModel.workspace_id == workspace.id
        )
        db_result = await self.session.execute(stmt)
        existing = db_result.scalar_one_or_none()

        if existing and not overwrite:
            result.add_skipped()
            return

        # Encrypt API key if present
        api_key_encrypted = None
        if config.model.api_key:
            api_key_encrypted = self.encryption.encrypt(config.model.api_key)

        if existing:
            # Update existing
            existing.model_provider = config.model.provider
            existing.model_name = config.model.model
            existing.temperature = config.model.temperature
            existing.max_turns = config.model.max_turns
            existing.api_key_encrypted = api_key_encrypted
            existing.region = config.model.region
            existing.queue_mode = config.queue.mode
            existing.debounce_ms = config.queue.debounce_ms
            result.add_imported()
        else:
            # Create new
            new_config = WorkspaceConfigModel(
                workspace_id=workspace.id,
                model_provider=config.model.provider,
                model_name=config.model.model,
                temperature=config.model.temperature,
                max_turns=config.model.max_turns,
                api_key_encrypted=api_key_encrypted,
                region=config.model.region,
                queue_mode=config.queue.mode,
                debounce_ms=config.queue.debounce_ms,
            )
            self.session.add(new_config)
            result.add_imported()

    async def _import_channel_binding(
        self,
        workspace: Workspace,
        config: WorkspaceConfig,
        result: MigrationResult,
        overwrite: bool,
    ) -> None:
        """Import workspace channel configuration."""
        if not config.channel.type:
            return

        # Check if binding exists
        stmt = select(ChannelBinding).where(
            ChannelBinding.workspace_id == workspace.id
        )
        db_result = await self.session.execute(stmt)
        existing = db_result.scalar_one_or_none()

        if existing and not overwrite:
            result.add_skipped()
            return

        # Prepare encrypted config
        channel_config = {}
        if config.channel.token:
            channel_config["token"] = config.channel.token

        config_encrypted = self.encryption.encrypt_json(channel_config)

        if existing:
            # Update existing
            existing.channel_type = config.channel.type
            existing.config_encrypted = config_encrypted
            existing.allowed_users = config.channel.allowed_users
            existing.allowed_groups = config.channel.allowed_groups
            existing.allow_all = config.channel.allow_all
            result.add_imported()
        else:
            # Create new
            new_binding = ChannelBinding(
                workspace_id=workspace.id,
                channel_type=config.channel.type,
                config_encrypted=config_encrypted,
                allowed_users=config.channel.allowed_users,
                allowed_groups=config.channel.allowed_groups,
                allow_all=config.channel.allow_all,
                enabled=True,
            )
            self.session.add(new_binding)
            result.add_imported()

    async def _import_workspace_builtins(
        self,
        workspace: Workspace,
        config: WorkspaceConfig,
        result: MigrationResult,
        overwrite: bool,
    ) -> None:
        """Import workspace-specific builtin configuration."""
        # Import allow/deny lists
        if overwrite:
            stmt = select(BuiltinAllowlist).where(
                BuiltinAllowlist.workspace_id == workspace.id
            )
            db_result = await self.session.execute(stmt)
            existing = db_result.scalars().all()
            for item in existing:
                await self.session.delete(item)

        # Import allow list
        for entry in config.builtins.allow:
            allowlist_item = BuiltinAllowlist(
                workspace_id=workspace.id,
                entry=entry,
                list_type=ListType.ALLOW.value,
            )
            self.session.add(allowlist_item)
            result.add_imported()

        # Import deny list
        for entry in config.builtins.deny:
            denylist_item = BuiltinAllowlist(
                workspace_id=workspace.id,
                entry=entry,
                list_type=ListType.DENY.value,
            )
            self.session.add(denylist_item)
            result.add_imported()

        # Import builtin configs
        builtin_configs = {
            "brave_search": config.builtins.brave_search,
            "whisper": config.builtins.whisper,
            "elevenlabs": config.builtins.elevenlabs,
        }

        for builtin_name, builtin_config in builtin_configs.items():
            if builtin_config is None:
                continue

            # Check if exists
            config_stmt = select(BuiltinConfig).where(
                BuiltinConfig.workspace_id == workspace.id,
                BuiltinConfig.builtin_name == builtin_name,
            )
            config_result = await self.session.execute(config_stmt)
            existing_config = config_result.scalar_one_or_none()

            if existing_config and not overwrite:
                result.add_skipped()
                continue

            if existing_config:
                # Update existing
                existing_config.enabled = builtin_config.enabled
                existing_config.config = builtin_config.config
                result.add_imported()
            else:
                # Create new
                new_config = BuiltinConfig(
                    workspace_id=workspace.id,
                    builtin_name=builtin_name,
                    enabled=builtin_config.enabled,
                    config=builtin_config.config,
                )
                self.session.add(new_config)
                result.add_imported()

    async def _import_cron_job(
        self,
        workspace: Workspace,
        cron_def: CronDefinition,
        result: MigrationResult,
        overwrite: bool,
    ) -> None:
        """Import a single cron job definition."""
        # Check if exists
        stmt = select(CronJob).where(
            CronJob.workspace_id == workspace.id,
            CronJob.name == cron_def.name,
        )
        db_result = await self.session.execute(stmt)
        existing = db_result.scalar_one_or_none()

        if existing and not overwrite:
            result.add_skipped()
            return

        # Convert output config to dict
        output_config = cron_def.output.model_dump()

        if existing:
            # Update existing
            existing.schedule = cron_def.schedule
            existing.enabled = cron_def.enabled
            existing.prompt = cron_def.prompt
            existing.output_config = output_config
            result.add_imported()
        else:
            # Create new
            new_cron = CronJob(
                workspace_id=workspace.id,
                name=cron_def.name,
                schedule=cron_def.schedule,
                enabled=cron_def.enabled,
                prompt=cron_def.prompt,
                output_config=output_config,
            )
            self.session.add(new_cron)
            result.add_imported()

    async def _upsert_setting(
        self,
        key: str,
        value: dict[str, Any],
        encrypted: bool,
        category: str,
        result: MigrationResult,
        overwrite: bool,
    ) -> None:
        """Insert or update a setting."""
        stmt = select(Setting).where(Setting.key == key)
        db_result = await self.session.execute(stmt)
        existing = db_result.scalar_one_or_none()

        if existing and not overwrite:
            result.add_skipped()
            return

        if existing:
            # Update existing
            existing.value = value
            existing.encrypted = encrypted
            result.add_imported()
        else:
            # Create new
            new_setting = Setting(
                key=key,
                value=value,
                encrypted=encrypted,
                category=category,
            )
            self.session.add(new_setting)
            result.add_imported()

    async def _verify_global_settings(
        self,
        config: Config,
        result: VerificationResult,
    ) -> None:
        """Verify global settings match between YAML and database."""
        settings_to_check = {
            "agent.model": config.agent.model,
            "agent.temperature": config.agent.temperature,
            "agent.max_turns": config.agent.max_turns,
            "queue.mode": config.queue.mode,
            "queue.debounce_ms": config.queue.debounce_ms,
            "queue.cap": config.queue.cap,
            "queue.drop_policy": config.queue.drop_policy,
            "lanes.main_concurrency": config.lanes.main_concurrency,
            "lanes.subagent_concurrency": config.lanes.subagent_concurrency,
            "lanes.cron_concurrency": config.lanes.cron_concurrency,
        }

        for key, expected_value in settings_to_check.items():
            stmt = select(Setting).where(Setting.key == key)
            db_result = await self.session.execute(stmt)
            setting = db_result.scalar_one_or_none()

            if not setting:
                result.matches = False
                result.differences.append(f"Setting {key} missing in database")
            elif setting.value.get("value") != expected_value:
                result.matches = False
                result.differences.append(
                    f"Setting {key} mismatch: YAML={expected_value}, DB={setting.value.get('value')}"
                )

    async def _verify_workspaces(
        self,
        workspaces_path: Path,
        result: VerificationResult,
    ) -> None:
        """Verify workspaces match between filesystem and database."""
        loader = WorkspaceLoader(workspaces_path)
        yaml_workspaces = set(loader.list_workspaces())

        # Get database workspaces
        stmt = select(Workspace.name)
        db_result = await self.session.execute(stmt)
        db_workspaces = set(db_result.scalars().all())

        # Check for missing workspaces
        missing_in_db = yaml_workspaces - db_workspaces
        if missing_in_db:
            result.matches = False
            result.differences.append(
                f"Workspaces missing in database: {', '.join(missing_in_db)}"
            )

        extra_in_db = db_workspaces - yaml_workspaces
        if extra_in_db:
            result.matches = False
            result.differences.append(
                f"Extra workspaces in database: {', '.join(extra_in_db)}"
            )
