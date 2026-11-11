from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session


class SessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def add(self, session: Session) -> None:
        self.db.add(session)

    async def get_active(self, digest: str, now: datetime) -> Session | None:
        stmt = select(Session).where(Session.token_hash == digest, Session.expires_at > now)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def refresh(
        self, session_id: UUID, now: datetime, expires_at: datetime
    ) -> Session | None:
        # Never revive a revoked/expired row or shorten it during concurrent requests.
        stmt = (
            update(Session)
            .where(Session.id == session_id, Session.expires_at > now)
            .values(expires_at=func.greatest(Session.expires_at, expires_at))
            .returning(Session)
            .execution_options(populate_existing=True)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_active(self, digest: str, now: datetime) -> UUID | None:
        stmt = (
            delete(Session)
            .where(Session.token_hash == digest, Session.expires_at > now)
            .returning(Session.id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
