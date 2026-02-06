"""Repository for settings operations."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openpaw.db.models import Setting
from openpaw.db.repositories.base import BaseRepository


class SettingsRepository(BaseRepository[Setting]):
    """Repository for settings operations."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, Setting)

    async def get_by_key(self, key: str) -> Setting | None:
        """Get setting by key."""
        stmt = select(Setting).where(Setting.key == key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_category(self, category: str) -> list[Setting]:
        """Get all settings in a category."""
        stmt = select(Setting).where(Setting.category == category)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def upsert(
        self,
        key: str,
        value: Any,
        category: str,
        encrypted: bool = False,
    ) -> Setting:
        """Insert or update a setting."""
        setting = await self.get_by_key(key)

        if setting:
            setting.value = {"value": value}
            setting.category = category
            setting.encrypted = encrypted
        else:
            setting = Setting(
                key=key,
                value={"value": value},
                category=category,
                encrypted=encrypted,
            )
            self.session.add(setting)

        await self.session.flush()
        await self.session.refresh(setting)
        return setting
