"""Catalog tests use the dedicated AUTH_TEST_DATABASE_URL database."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.models.category import Category
from app.models.media import Media
from app.schemas.category import CategoryCreate, CategoryUpdate
from app.services.category import CategoryService, InvalidCategoryOrderError
from app.services.media import MediaService
from app.storage.s3 import S3Storage, StorageSettings
from tests.test_auth_integration import database, migrate_database, settings  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTH_TEST_DATABASE_URL"),
    reason="Set AUTH_TEST_DATABASE_URL to a dedicated test database",
)


async def test_category_visibility_gallery_and_order(database):  # noqa: F811
    category_ids = []
    media_ids = [uuid4(), uuid4()]
    storage_settings = StorageSettings(
        _env_file=None,
        s3_endpoint_url="https://cdn.example.com",
        s3_access_key_id="test-key",
        s3_secret_access_key="test-secret",
        s3_public_bucket="public",
        s3_private_bucket="private",
    )
    async with database.session_factory() as db:
        db.add_all(
            [
                Media(
                    id=media_id,
                    object_key=f"catalog/{media_id}",
                    original_name="image.png",
                    mime_type="image/png",
                    size_bytes=10,
                )
                for media_id in media_ids
            ]
        )
        await db.commit()
        service = CategoryService(db, storage_settings)
        try:
            category = await service.create(
                CategoryCreate(slug=f"test-{uuid4().hex}", title="Test", mediaIds=media_ids)
            )
            category_ids.append(category.id)
            assert [image.id for image in category.images] == media_ids
            assert [image.url for image in category.images] == [
                f"https://cdn.example.com/public/catalog/{media_id}" for media_id in media_ids
            ]
            new_settings = storage_settings.model_copy(
                update={"s3_endpoint_url": "https://files.example.com"}
            )
            new_category = await CategoryService(db, new_settings).get(category.id)
            assert [image.url for image in new_category.images] == [
                f"https://files.example.com/public/catalog/{media_id}" for media_id in media_ids
            ]
            media = await MediaService(db, S3Storage(new_settings)).list()
            assert {item.url for item in media if item.id in media_ids} == {
                image.url for image in new_category.images
            }
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
