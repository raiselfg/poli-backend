from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import utc_now
from app.models.category import Category
from app.repository.category import CategoryRepository
from app.repository.media import MediaRepository
from app.schemas.category import CategoryAdmin, CategoryCreate, CategoryImage, CategoryUpdate


class CategoryNotFoundError(Exception):
    pass


class CategoryConflictError(Exception):
    pass


class InvalidCategoryMediaError(Exception):
    pass


class InvalidCategoryOrderError(Exception):
    pass


class CategoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.categories = CategoryRepository(db)
        self.media = MediaRepository(db)

    async def list(self, *, published_only: bool = False) -> list[CategoryAdmin]:
        categories = await self.categories.list(published_only=published_only)
        images = await self.categories.images([category.id for category in categories])
        return [self._response(category, images.get(category.id, [])) for category in categories]

    async def get(self, category_id: UUID) -> CategoryAdmin:
        category = await self.categories.by_id(category_id)
        if category is None:
            raise CategoryNotFoundError
        images = await self.categories.images([category.id])
        return self._response(category, images.get(category.id, []))

    async def create(self, body: CategoryCreate) -> CategoryAdmin:
        await self._validate_media(body.media_ids)
        category = Category(id=uuid4(), **body.model_dump(exclude={"media_ids"}))
        try:
            self.categories.add(category)
            await self.categories.replace_images(category.id, body.media_ids)
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise CategoryConflictError from None
        await self.db.refresh(category)
        return await self.get(category.id)

    async def update(self, category_id: UUID, body: CategoryUpdate) -> CategoryAdmin:
        category = await self.categories.by_id(category_id)
        if category is None:
            raise CategoryNotFoundError
        values = body.model_dump(exclude_unset=True)
        media_ids = values.pop("media_ids", None)
        if media_ids is not None:
            await self._validate_media(media_ids)
        try:
            for key, value in values.items():
                setattr(category, key, value)
            if media_ids is not None:
                await self.categories.replace_images(category_id, media_ids)
                category.updated_at = utc_now()
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise CategoryConflictError from None
        await self.db.refresh(category)
        return await self.get(category_id)

    async def reorder(self, ids: list[UUID]) -> None:
        categories = await self.categories.list(lock=True)
        by_id = {category.id: category for category in categories}
        if len(ids) != len(set(ids)) or set(ids) != set(by_id):
            raise InvalidCategoryOrderError
        for order, category_id in enumerate(ids):
            by_id[category_id].sort_order = order
        await self.db.commit()

    async def delete(self, category_id: UUID) -> None:
        category = await self.categories.by_id(category_id)
        if category is None:
            raise CategoryNotFoundError
        await self.categories.delete(category)
        await self.db.commit()

    async def _validate_media(self, ids: list[UUID]) -> None:
        if not ids:
            return
        media = await self.media.by_ids(ids)
        if len(media) != len(ids) or await self.media.used_by_requests(ids):
            raise InvalidCategoryMediaError

    @staticmethod
    def _response(category, images) -> CategoryAdmin:
        return CategoryAdmin(
            id=category.id,
            slug=category.slug,
            title=category.title,
            description=category.description,
            images=[CategoryImage.model_validate(image) for image in images],
            is_published=category.is_published,
            sort_order=category.sort_order,
            created_at=category.created_at,
            updated_at=category.updated_at,
        )
