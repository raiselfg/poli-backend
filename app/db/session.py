from collections.abc import AsyncIterator
from typing import NamedTuple

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


class Database(NamedTuple):
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


def create_database(settings: Settings) -> Database:
    engine = create_async_engine(
        settings.database_url, pool_pre_ping=True, hide_parameters=True
    )
    return Database(engine, async_sessionmaker(engine, expire_on_commit=False))


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session
