import logging
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.media import CATALOG_PREFIX, CatalogVariant, Media
from app.repository.media import MediaRepository
from app.schemas.media import MediaRead
from app.storage.catalog_images import (
    CATALOG_IMAGE_CACHE_CONTROL,
    CATALOG_IMAGE_MIME,
    CATALOG_IMAGE_SIZES,
    CatalogImageVariant,
    encode_catalog_variants,
)
from app.storage.s3 import S3Storage

logger = logging.getLogger(__name__)


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

    async def get(self, media_id: UUID, *, lock: bool = False) -> Media:
        media = await self.media.by_id(media_id, lock=lock)
        if media is None or not media.object_key.startswith(CATALOG_PREFIX):
            raise MediaNotFoundError
        return media

    async def upload(self, stream: BinaryIO, name: str, alt: str) -> MediaRead:
        media_id = uuid4()
        key = f"{CATALOG_PREFIX}{media_id}"
        files = await run_in_threadpool(encode_catalog_variants, stream)
        largest = files[-1]
        media = Media(
            id=media_id,
            object_key=key,
            original_name=name,
            mime_type=CATALOG_IMAGE_MIME,
            size_bytes=largest.size,
            width=largest.width,
            height=largest.height,
            alt=alt,
        )
        attempted: list[str] = []
        try:
            media.catalog_variants = await self._upload_variants(
                key, files, attempted, use_canonical_key=True
            )
            self.media.add(media)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            await self._cleanup(attempted)
            raise
        finally:
            for file in files:
                file.stream.close()
        await self.db.refresh(media)
        return self._response(media)

    async def backfill_variants(self, media_id: UUID) -> bool:
        media = await self.media.by_id(media_id, lock=True)
        if media is None or not media.object_key.startswith(CATALOG_PREFIX):
            return False
        if media.catalog_variants is not None:
            return False

        attempted: list[str] = []
        files: list[CatalogImageVariant] = []
        try:
            with SpooledTemporaryFile(max_size=1024 * 1024) as source:
                await self.storage.download(
                    self.storage.settings.s3_public_bucket, media.object_key, source
                )
                files = await run_in_threadpool(encode_catalog_variants, source)
            media.catalog_variants = await self._upload_variants(
                media.object_key, files, attempted, use_canonical_key=False
            )
            await self.db.commit()
        except Exception:
            await self._cleanup(attempted)
            await self.db.rollback()
            raise
        finally:
            for file in files:
                file.stream.close()
        return True

    async def _upload_variants(
        self,
        canonical_key: str,
        files: list[CatalogImageVariant],
        attempted: list[str],
        *,
        use_canonical_key: bool,
    ) -> list[CatalogVariant]:
        bucket = self.storage.settings.s3_public_bucket
        variants: list[CatalogVariant] = []
        for file in files:
            key = (
                canonical_key
                if use_canonical_key and file.limit == CATALOG_IMAGE_SIZES[-1]
                else f"{canonical_key}/{file.limit}.webp"
            )
            attempted.append(key)
            await self.storage.upload(
                bucket,
                key,
                file.stream,
                CATALOG_IMAGE_MIME,
                cache_control=CATALOG_IMAGE_CACHE_CONTROL,
            )
            variants.append({"key": key, "width": file.width, "height": file.height})
        return variants

    async def _cleanup(self, keys: list[str]) -> None:
        for key in keys:
            try:
                await self.storage.delete(self.storage.settings.s3_public_bucket, key)
            except Exception:
                logger.exception("Unable to delete catalog object %s", key)

    async def update(self, media_id: UUID, alt: str) -> MediaRead:
        media = await self.get(media_id)
        media.alt = alt
        await self.db.commit()
        await self.db.refresh(media)
        return self._response(media)

    async def delete(self, media_id: UUID, *, category_id: UUID | None = None) -> None:
        media = await self.get(media_id, lock=True)
        variant_keys = [
            variant["key"]
            for variant in media.catalog_variants or ()
            if variant["key"] != media.object_key
        ]
        try:
            if category_id is not None:
                await self.media.detach_from_category(media_id, category_id)
            if await self.media.used_by_category(media_id) or await self.media.used_by_requests(
                [media_id]
            ):
                raise MediaInUseError
            await self.media.delete(media)
            # Check foreign keys before deleting the object. Roll back if storage rejects deletion.
            await self.db.flush()
            await self.storage.delete(self.storage.settings.s3_public_bucket, media.object_key)
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise MediaInUseError from None
        except Exception:
            await self.db.rollback()
            raise
        await self._cleanup(variant_keys)

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
