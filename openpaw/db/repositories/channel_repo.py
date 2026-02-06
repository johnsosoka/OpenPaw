"""Repository for channel binding operations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from openpaw.db.models import ChannelBinding, Workspace
from openpaw.db.repositories.base import BaseRepository


class ChannelRepository(BaseRepository[ChannelBinding]):
    """Repository for channel binding operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, ChannelBinding)

    async def get_by_workspace(self, workspace_name: str) -> ChannelBinding | None:
        """Get channel binding by workspace name.

        Args:
            workspace_name: Name of the workspace

        Returns:
            ChannelBinding or None if not found
        """
        stmt = (
            select(ChannelBinding)
            .join(Workspace)
            .where(Workspace.name == workspace_name)
            .options(selectinload(ChannelBinding.workspace))
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_or_update(
        self,
        workspace_id: int,
        channel_type: str,
        config_encrypted: str,
        allowed_users: list[int] | None = None,
        allowed_groups: list[int] | None = None,
        allow_all: bool = False,
        enabled: bool = True,
    ) -> ChannelBinding:
        """Create or update channel binding for a workspace.

        Args:
            workspace_id: Workspace ID
            channel_type: Type of channel (telegram, discord, slack)
            config_encrypted: Encrypted configuration JSON
            allowed_users: List of allowed user IDs
            allowed_groups: List of allowed group IDs
            allow_all: Whether to allow all users/groups
            enabled: Whether the channel is enabled

        Returns:
            Created or updated ChannelBinding
        """
        # Check if binding exists for this workspace
        stmt = select(ChannelBinding).where(
            ChannelBinding.workspace_id == workspace_id
        )
        result = await self.session.execute(stmt)
        binding = result.scalar_one_or_none()

        if binding:
            # Update existing binding
            binding.channel_type = channel_type
            binding.config_encrypted = config_encrypted
            if allowed_users is not None:
                binding.allowed_users = allowed_users
            if allowed_groups is not None:
                binding.allowed_groups = allowed_groups
            binding.allow_all = allow_all
            binding.enabled = enabled
        else:
            # Create new binding
            binding = ChannelBinding(
                workspace_id=workspace_id,
                channel_type=channel_type,
                config_encrypted=config_encrypted,
                allowed_users=allowed_users or [],
                allowed_groups=allowed_groups or [],
                allow_all=allow_all,
                enabled=enabled,
            )
            self.session.add(binding)

        await self.session.flush()
        await self.session.refresh(binding)
        return binding
