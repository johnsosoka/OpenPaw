"""Repository for builtin configuration operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openpaw.db.models import BuiltinAllowlist, BuiltinConfig
from openpaw.db.repositories.base import BaseRepository


class BuiltinRepository(BaseRepository[BuiltinConfig]):
    """Repository for builtin configuration operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, BuiltinConfig)

    async def get_config(
        self,
        name: str,
        workspace_id: int | None = None,
    ) -> BuiltinConfig | None:
        """Get builtin configuration.

        Args:
            name: Builtin name
            workspace_id: Workspace ID (None for global config)

        Returns:
            BuiltinConfig or None if not found
        """
        stmt = select(BuiltinConfig).where(
            BuiltinConfig.builtin_name == name,
            BuiltinConfig.workspace_id == workspace_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create_config(
        self,
        name: str,
        workspace_id: int | None = None,
    ) -> BuiltinConfig:
        """Get or create builtin configuration.

        Args:
            name: Builtin name
            workspace_id: Workspace ID (None for global config)

        Returns:
            Existing or newly created BuiltinConfig
        """
        config = await self.get_config(name, workspace_id)
        if not config:
            config = BuiltinConfig(
                workspace_id=workspace_id,
                builtin_name=name,
                enabled=True,
                config={},
            )
            self.session.add(config)
            await self.session.flush()
            await self.session.refresh(config)
        return config

    async def get_allowlist(
        self,
        workspace_id: int | None = None,
    ) -> dict[str, list[str]]:
        """Get allow/deny lists for builtins.

        Args:
            workspace_id: Workspace ID (None for global lists)

        Returns:
            Dict with 'allow' and 'deny' list entries
        """
        stmt = select(BuiltinAllowlist).where(
            BuiltinAllowlist.workspace_id == workspace_id
        )
        result = await self.session.execute(stmt)

        allow = []
        deny = []
        for entry in result.scalars().all():
            if entry.list_type == "allow":
                allow.append(entry.entry)
            else:
                deny.append(entry.entry)

        return {"allow": allow, "deny": deny}
