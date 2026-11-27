from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.request import RequestNote


class RequestNoteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, request_id: UUID) -> list[RequestNote]:
        stmt = (
            select(RequestNote)
            .where(RequestNote.request_id == request_id)
            .order_by(RequestNote.created_at.desc(), RequestNote.id.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def add(self, note: RequestNote) -> None:
        self.db.add(note)
