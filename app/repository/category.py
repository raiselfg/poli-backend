from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.media import CategoryMedia, Media


class CategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def by_id(self, category_id: UUID) -> Category | None:
        return await self.db.get(Category, category_id)

    async def list(self, *, published_only: bool = False, lock: bool = False) -> list[Category]:
        stmt = select(Category).order_by(Category.sort_order, Category.id)
        if published_only:
            stmt = stmt.where(Category.is_published.is_(True))
        if lock:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def images(self, category_ids: list[UUID]) -> dict[UUID, list[Media]]:
        stmt = (
            select(CategoryMedia.category_id, Media)
            .join(Media, Media.id == CategoryMedia.media_id)
            .where(CategoryMedia.category_id.in_(category_ids))
            .order_by(CategoryMedia.category_id, CategoryMedia.sort_order, Media.id)
        )
        result = await self.db.execute(stmt)
        images: dict[UUID, list[Media]] = {}
        for category_id, media in result.all():
            images.setdefault(category_id, []).append(media)
        return images

    def add(self, category: Category) -> None:
        self.db.add(category)

    async def replace_images(self, category_id: UUID, media_ids: list[UUID]) -> None:
        stmt = delete(CategoryMedia).where(CategoryMedia.category_id == category_id)
        await self.db.execute(stmt)
        self.db.add_all(
            [
                CategoryMedia(category_id=category_id, media_id=media_id, sort_order=index)
                for index, media_id in enumerate(media_ids)
            ]
        )

    async def delete(self, category: Category) -> None:
        await self.db.delete(category)
