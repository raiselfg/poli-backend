from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.request import Request


class RequestRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def by_id(self, request_id: UUID) -> Request | None:
        return await self.db.get(Request, request_id)

    async def list(self, status: str | None) -> list[Request]:
        stmt = select(Request).order_by(Request.created_at.desc(), Request.id.desc())
        if status is not None:
            stmt = stmt.where(Request.status == status)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def add(self, request: Request) -> None:
        self.db.add(request)
