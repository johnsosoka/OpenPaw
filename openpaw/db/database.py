"""Database connection manager for OpenPaw."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from openpaw.db.models import Base


def _enable_foreign_keys(dbapi_conn: Any, connection_record: Any) -> None:
    """Enable foreign key constraints for SQLite connections."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class DatabaseManager:
    """Manages async SQLite database connections."""

    def __init__(self, db_path: Path | str = "openpaw.db"):
        self.db_path = Path(db_path)
        self.db_url = f"sqlite+aiosqlite:///{self.db_path}"

        self.engine = create_async_engine(
            self.db_url,
            echo=False,
            future=True,
        )

        # Enable foreign key constraints for SQLite
        event.listen(self.engine.sync_engine, "connect", _enable_foreign_keys)

        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_db(self) -> None:
        """Create all tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        """Close database connections."""
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide a transactional session."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# Singleton access
_db_manager: DatabaseManager | None = None


def init_db_manager(db_path: Path | str = "openpaw.db") -> DatabaseManager:
    """Initialize the global database manager."""
    global _db_manager
    _db_manager = DatabaseManager(db_path)
    return _db_manager


def get_db_manager() -> DatabaseManager:
    """Get the database manager (must be initialized first)."""
    if _db_manager is None:
        raise RuntimeError("Database not initialized. Call init_db_manager() first.")
    return _db_manager


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions."""
    db = get_db_manager()
    async with db.session() as session:
        yield session
