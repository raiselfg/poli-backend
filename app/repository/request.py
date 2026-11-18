from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media
from app.models.request import Request, RequestAttachment


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

    async def ids_with_files(self, status: str | None) -> set[UUID]:
        stmt = select(RequestAttachment.request_id).distinct()
        if status is not None:
            stmt = stmt.join(Request, Request.id == RequestAttachment.request_id).where(
                Request.status == status
            )
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def files(self, request_id: UUID) -> list[Media]:
        stmt = (
            select(Media)
            .join(RequestAttachment, Media.id == RequestAttachment.media_id)
            .where(RequestAttachment.request_id == request_id)
            .order_by(RequestAttachment.position)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def add(self, request: Request) -> None:
        self.db.add(request)

    def attach_files(self, request_id: UUID, media_ids: list[UUID]) -> None:
        self.db.add_all(
            [
                RequestAttachment(request_id=request_id, position=position, media_id=media_id)
                for position, media_id in enumerate(media_ids)
            ]
        )
