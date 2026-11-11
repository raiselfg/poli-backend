from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import CategoryMedia, Media
from app.models.request import Request


class MediaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def by_ids(self, ids: list[UUID]) -> list[Media]:
        stmt = select(Media).where(Media.id.in_(ids))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def used_by_requests(self, ids: list[UUID]) -> set[UUID]:
        stmt = select(Request.media_id).where(Request.media_id.in_(ids))
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def by_id(self, media_id: UUID) -> Media | None:
        return await self.db.get(Media, media_id)

    async def list_catalog(self, url_prefix: str) -> list[Media]:
        stmt = select(Media).where(Media.url.startswith(url_prefix, autoescape=True)).order_by(
            Media.created_at.desc(), Media.id.desc()
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def used_by_category(self, media_id: UUID) -> bool:
        stmt = select(CategoryMedia.media_id).where(CategoryMedia.media_id == media_id).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    def add(self, media: Media) -> None:
        self.db.add(media)

    async def delete(self, media: Media) -> None:
        await self.db.delete(media)
