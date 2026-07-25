from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.config import settings
from src.db.base import Base

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    echo=settings.environment == "dev" and settings.log_level.upper() == "DEBUG",
)

session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def init_db() -> None:
    """Create tables (used for quick bootstrap/dev). Prefer Alembic in prod."""
    from src.logging_setup import get_logger

    log = get_logger(__name__)
    async with engine.begin() as conn:
        log.info("db.init", action="create_all")
        await conn.run_sync(Base.metadata.create_all)
