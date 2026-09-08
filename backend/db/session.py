"""Async SQLAlchemy engine, session factory, and FastAPI dependency."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.config import get_settings


def create_engine(database_url: str | None = None, *, echo: bool | None = None) -> AsyncEngine:
    """Construct an async engine without opening a connection eagerly."""

    settings = get_settings()
    return create_async_engine(
        database_url or settings.database_url,
        echo=settings.database_echo if echo is None else echo,
        pool_pre_ping=True,
    )


engine = create_engine()
AsyncSessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Conventional aliases used by application services and test overrides.
async_session_factory = AsyncSessionFactory
SessionLocal = AsyncSessionFactory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield one transaction-neutral session for a FastAPI request."""

    async with AsyncSessionFactory() as session:
        yield session


get_session = get_db_session


async def close_database() -> None:
    """Release all pooled database connections during application shutdown."""

    await engine.dispose()


__all__ = [
    "AsyncSessionFactory",
    "SessionLocal",
    "async_session_factory",
    "close_database",
    "create_engine",
    "engine",
    "get_db_session",
    "get_session",
]
