from io import BytesIO
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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

    with BytesIO(b"file") as stream, pytest.raises(IntegrityError) as exc:
        await MediaService(db, storage).upload(stream, "image.png", "image/png", 4, 1, 1, "Alt")

    assert exc.value is error
    expected_order = ["upload", "commit", "rollback", "delete"]
    assert [call[0] for call in calls.mock_calls] == expected_order
    bucket, key = storage.upload.await_args.args[:2]
    storage.delete.assert_awaited_once_with(bucket, key)
