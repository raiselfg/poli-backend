from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media
from app.repository.media import MediaRepository
from app.storage.s3 import S3Storage


class MediaNotFoundError(Exception):
    pass


class MediaInUseError(Exception):
    pass


class MediaService:
    def __init__(self, db: AsyncSession, storage: S3Storage):
        self.db = db
        self.media = MediaRepository(db)
        self.storage = storage

    def _prefix(self) -> str:
        base = self.storage.settings.s3_endpoint_url.rstrip("/")
        return f"{base}/{self.storage.settings.s3_public_bucket}/catalog/"

    async def list(self) -> list[Media]:
        return await self.media.list_catalog(self._prefix())

    async def get(self, media_id: UUID) -> Media:
        media = await self.media.by_id(media_id)
        if media is None or not media.url.startswith(self._prefix()):
            raise MediaNotFoundError
        return media

    async def upload(
        self, stream: BinaryIO, name: str, mime_type: str, size: int, width: int, height: int, alt: str
    ) -> Media:
        media_id = uuid4()
        bucket = self.storage.settings.s3_public_bucket
        key = f"catalog/{media_id}"
        await self.storage.upload(bucket, key, stream, mime_type)
        media = Media(
            id=media_id,
            url=self.storage.url(bucket, "catalog", media_id),
            original_name=name,
            mime_type=mime_type,
            size_bytes=size,
            width=width,
            height=height,
            alt=alt,
        )
        self.media.add(media)
        await self.db.commit()
        await self.db.refresh(media)
        return media

    async def update(self, media_id: UUID, alt: str) -> Media:
        media = await self.get(media_id)
        media.alt = alt
        await self.db.commit()
        await self.db.refresh(media)
        return media

    async def delete(self, media_id: UUID) -> None:
        media = await self.get(media_id)
        if await self.media.used_by_category(media_id) or await self.media.used_by_requests(
            [media_id]
        ):
            raise MediaInUseError
        try:
            await self.media.delete(media)
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise MediaInUseError from None
        await self.storage.delete(self.storage.settings.s3_public_bucket, f"catalog/{media_id}")
