from io import BytesIO
from unittest.mock import AsyncMock, Mock, call
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media
from app.services.media import MediaService


async def test_database_failure_after_upload():
    db = AsyncMock(spec=AsyncSession)
    storage = Mock(upload=AsyncMock(), delete=AsyncMock())
    storage.settings.s3_public_bucket = "public"
    calls = Mock()
    calls.attach_mock(storage.upload, "upload")
    calls.attach_mock(db.commit, "commit")
    calls.attach_mock(db.rollback, "rollback")
    calls.attach_mock(storage.delete, "delete")

    error = IntegrityError(None, None, Exception())
    db.commit.side_effect = error

    with BytesIO() as stream, pytest.raises(IntegrityError) as exc:
        Image.new("RGB", (900, 600)).save(stream, format="PNG")
        await MediaService(db, storage).upload(stream, "image.png", "Alt")

    assert exc.value is error
    assert [item[0] for item in calls.mock_calls] == [
        "upload",
        "upload",
        "upload",
        "commit",
        "rollback",
        "delete",
        "delete",
        "delete",
    ]
    assert storage.delete.await_args_list == [
        call(*upload.args[:2]) for upload in storage.upload.await_args_list
    ]


async def test_backfill_keeps_existing_object_and_skips_already_updated_media():
    db = AsyncMock(spec=AsyncSession)
    media = Media(id=uuid4(), object_key="catalog/old")
    db.get.return_value = media
    storage = Mock(upload=AsyncMock(), delete=AsyncMock(), download=AsyncMock())
    storage.settings.s3_public_bucket = "public"

    def write_source(_bucket, _key, file):
        Image.new("RGB", (1800, 900)).save(file, format="JPEG")

    storage.download.side_effect = write_source
    service = MediaService(db, storage)
    assert await service.backfill_variants(media.id)
    assert not await service.backfill_variants(media.id)
    assert media.catalog_variants == [
        {"key": "catalog/old/240.webp", "width": 240, "height": 120},
        {"key": "catalog/old/800.webp", "width": 800, "height": 400},
        {"key": "catalog/old/1600.webp", "width": 1600, "height": 800},
    ]
    assert [item.args[1] for item in storage.upload.await_args_list] == [
        variant["key"] for variant in media.catalog_variants
    ]
    storage.download.assert_awaited_once()
    storage.delete.assert_not_awaited()
    db.commit.assert_awaited_once()
