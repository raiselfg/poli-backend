"""Catalog tests use the dedicated AUTH_TEST_DATABASE_URL database."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.models.category import Category
from app.models.media import Media
from app.schemas.category import CategoryCreate, CategoryUpdate
from app.services.category import CategoryService, InvalidCategoryOrderError
from tests.test_auth_integration import database, migrate_database, settings  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTH_TEST_DATABASE_URL"),
    reason="Set AUTH_TEST_DATABASE_URL to a dedicated test database",
)


async def test_category_visibility_gallery_and_order(database):  # noqa: F811
    category_ids = []
    media_ids = [uuid4(), uuid4()]
    async with database.session_factory() as db:
        db.add_all(
            [
                Media(
                    id=media_id,
                    url=f"https://cdn.example.com/test/{media_id}",
                    original_name="image.png",
                    mime_type="image/png",
                    size_bytes=10,
                )
                for media_id in media_ids
            ]
        )
        await db.commit()
        service = CategoryService(db)
        try:
            category = await service.create(
                CategoryCreate(slug=f"test-{uuid4().hex}", title="Test", mediaIds=media_ids)
            )
            category_ids.append(category.id)
            assert [image.id for image in category.images] == media_ids
            assert category.id not in {item.id for item in await service.list(published_only=True)}
            category = await service.update(category.id, CategoryUpdate(is_published=True))
            assert [image.id for image in category.images] == media_ids
            assert category.id in {item.id for item in await service.list(published_only=True)}
            category = await service.update(category.id, CategoryUpdate(mediaIds=[]))
            assert category.images == []
            with pytest.raises(InvalidCategoryOrderError):
                await service.reorder([category.id, category.id])
        finally:
            await db.rollback()
            stmt = delete(Category).where(Category.id.in_(category_ids))
            await db.execute(stmt)
            stmt = delete(Media).where(Media.id.in_(media_ids))
            await db.execute(stmt)
            await db.commit()
