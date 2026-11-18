from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import CATALOG_PREFIX, Media
from app.repository.media import MediaRepository
from app.schemas.media import MediaRead
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

    async def list(self) -> list[MediaRead]:
        return [self._response(media) for media in await self.media.list_catalog()]

    async def get(self, media_id: UUID) -> Media:
        media = await self.media.by_id(media_id)
        if media is None or not media.object_key.startswith(CATALOG_PREFIX):
            raise MediaNotFoundError
        return media

    async def upload(
        self,
        stream: BinaryIO,
        name: str,
        mime_type: str,
        size: int,
        width: int,
        height: int,
        alt: str,
    ) -> MediaRead:
        media_id = uuid4()
        bucket = self.storage.settings.s3_public_bucket
        key = f"{CATALOG_PREFIX}{media_id}"
        await self.storage.upload(bucket, key, stream, mime_type)
        media = Media(
            id=media_id,
            object_key=key,
            original_name=name,
            mime_type=mime_type,
            size_bytes=size,
            width=width,
            height=height,
            alt=alt,
        )
        try:
            self.media.add(media)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            await self.storage.delete(bucket, key)
            raise
        await self.db.refresh(media)
        return self._response(media)

    async def update(self, media_id: UUID, alt: str) -> MediaRead:
        media = await self.get(media_id)
        media.alt = alt
        await self.db.commit()
        await self.db.refresh(media)
        return self._response(media)

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
        await self.storage.delete(self.storage.settings.s3_public_bucket, media.object_key)

    def _response(self, media: Media) -> MediaRead:
        return MediaRead(
            id=media.id,
            url=self.storage.settings.public_url(media.object_key),
            original_name=media.original_name,
            mime_type=media.mime_type,
            size_bytes=media.size_bytes,
            width=media.width,
            height=media.height,
            alt=media.alt,
            created_at=media.created_at,
        )
