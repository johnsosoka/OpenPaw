"""FastAPI dependency injection providers."""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from openpaw.api.services.encryption import EncryptionService
from openpaw.db.database import get_async_session
from openpaw.orchestrator import OpenPawOrchestrator

if TYPE_CHECKING:
    from openpaw.api.services.settings_service import SettingsService


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Provide database session.

    Yields:
        AsyncSession: Database session with automatic commit/rollback
    """
    async for session in get_async_session():
        yield session


def get_orchestrator(request: Request) -> OpenPawOrchestrator | None:
    """
    Get orchestrator from app state.

    The orchestrator may be None if the API is running standalone
    without any active workspaces.

    Args:
        request: FastAPI request object

    Returns:
        OpenPawOrchestrator instance or None
    """
    return getattr(request.app.state, "orchestrator", None)


def get_workspaces_path(request: Request) -> Path:
    """
    Get workspaces path from app config.

    Args:
        request: FastAPI request object

    Returns:
        Path to agent_workspaces directory
    """
    path: Path = request.app.state.workspaces_path
    return path


def get_encryption() -> EncryptionService:
    """
    Get encryption service instance.

    Returns:
        EncryptionService: Singleton encryption service
    """
    return EncryptionService()


# Service provider implementations
async def get_workspace_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    workspaces_path: Annotated[Path, Depends(get_workspaces_path)],
    orchestrator: Annotated[OpenPawOrchestrator | None, Depends(get_orchestrator)],
) -> Any:
    """
    Get workspace service instance.

    Args:
        session: Database session
        workspaces_path: Path to workspaces directory
        orchestrator: Optional orchestrator instance

    Returns:
        WorkspaceService instance
    """
    from openpaw.api.services.workspace_service import WorkspaceService

    return WorkspaceService(session, workspaces_path, orchestrator)


async def get_settings_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> "SettingsService":
    """
    Get settings service instance.

    Args:
        session: Database session

    Returns:
        SettingsService instance
    """
    from openpaw.api.services.settings_service import SettingsService

    return SettingsService(session)


async def get_builtin_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    encryption: Annotated[EncryptionService, Depends(get_encryption)],
) -> Any:
    """
    Get builtin service instance.

    Args:
        session: Database session
        encryption: Encryption service

    Returns:
        BuiltinService instance (stub for future implementation)
    """
    # TODO: Import and instantiate BuiltinService once implemented
    raise NotImplementedError("BuiltinService not yet implemented")


async def get_cron_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    orchestrator: Annotated[OpenPawOrchestrator | None, Depends(get_orchestrator)],
) -> Any:
    """
    Get cron service instance.

    Args:
        session: Database session
        orchestrator: Optional orchestrator instance

    Returns:
        CronService instance (stub for future implementation)
    """
    # TODO: Import and instantiate CronService once implemented
    raise NotImplementedError("CronService not yet implemented")


async def get_channel_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    encryption: Annotated[EncryptionService, Depends(get_encryption)],
    orchestrator: Annotated[OpenPawOrchestrator | None, Depends(get_orchestrator)],
) -> Any:
    """
    Get channel service instance.

    Args:
        session: Database session
        encryption: Encryption service
        orchestrator: Optional orchestrator instance

    Returns:
        ChannelService instance (stub for future implementation)
    """
    # TODO: Import and instantiate ChannelService once implemented
    raise NotImplementedError("ChannelService not yet implemented")


async def get_monitoring_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    orchestrator: Annotated[OpenPawOrchestrator | None, Depends(get_orchestrator)],
) -> Any:
    """
    Get monitoring service instance.

    Args:
        session: Database session
        orchestrator: Optional orchestrator instance

    Returns:
        MonitoringService instance (stub for future implementation)
    """
    # TODO: Import and instantiate MonitoringService once implemented
    raise NotImplementedError("MonitoringService not yet implemented")


async def get_migration_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    encryption: Annotated[EncryptionService, Depends(get_encryption)],
) -> Any:
    """
    Get migration service instance.

    Args:
        session: Database session
        encryption: Encryption service

    Returns:
        MigrationService instance
    """
    from openpaw.api.services.migration_service import MigrationService

    return MigrationService(session, encryption)


# Type aliases for annotating dependencies
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
Orchestrator = Annotated[OpenPawOrchestrator | None, Depends(get_orchestrator)]
WorkspacesPath = Annotated[Path, Depends(get_workspaces_path)]
Encryption = Annotated[EncryptionService, Depends(get_encryption)]
