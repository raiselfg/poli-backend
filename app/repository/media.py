from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import CATALOG_PREFIX, CategoryMedia, Media
from app.models.request import RequestAttachment


class MediaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def by_ids(self, ids: list[UUID]) -> list[Media]:
        stmt = select(Media).where(Media.id.in_(ids))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def used_by_requests(self, ids: list[UUID]) -> set[UUID]:
        stmt = select(RequestAttachment.media_id).where(RequestAttachment.media_id.in_(ids))
        result = await self.db.execute(stmt)
        return set(result.scalars().all())

    async def by_id(self, media_id: UUID, *, lock: bool = False) -> Media | None:
        return await self.db.get(Media, media_id, with_for_update=lock)

    async def catalog_ids_without_variants(self) -> list[UUID]:
        stmt = select(Media.id).where(
            Media.object_key.startswith(CATALOG_PREFIX, autoescape=True),
            Media.catalog_variants.is_(None),
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_catalog(self) -> list[Media]:
        stmt = (
            select(Media)
            .where(Media.object_key.startswith(CATALOG_PREFIX, autoescape=True))
            .order_by(Media.created_at.desc(), Media.id.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def used_by_category(self, media_id: UUID) -> bool:
        stmt = select(CategoryMedia.media_id).where(CategoryMedia.media_id == media_id).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    def add(self, media: Media) -> None:
        self.db.add(media)

    async def detach_from_category(self, media_id: UUID, category_id: UUID) -> None:
        stmt = delete(CategoryMedia).where(
            CategoryMedia.media_id == media_id,
            CategoryMedia.category_id == category_id,
        )
        await self.db.execute(stmt)

    async def delete(self, media: Media) -> None:
        await self.db.delete(media)
