from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media
from app.models.request import Request
from app.repository.category import CategoryRepository
from app.repository.media import MediaRepository
from app.repository.request import RequestRepository
from app.schemas.request import RequestCreated, RequestDetail, RequestFile, RequestListItem
from app.storage.s3 import S3Storage


class RequestNotFoundError(Exception):
    pass


class RequestCategoryNotFoundError(Exception):
    pass


class RequestService:
    def __init__(self, db: AsyncSession, storage: S3Storage):
        self.db = db
        self.requests = RequestRepository(db)
        self.categories = CategoryRepository(db)
        self.media = MediaRepository(db)
        self.storage = storage

    async def create(
        self,
        name: str,
        phone: str,
        comment: str | None,
        category_id: UUID | None,
        file: tuple[BinaryIO, str, str, int, int | None, int | None] | None,
    ) -> RequestCreated:
        if category_id is not None and await self.categories.by_id(category_id) is None:
            raise RequestCategoryNotFoundError
        request_id = uuid4()
        media_id = None
        if file is not None:
            stream, original_name, mime_type, size, width, height = file
            media_id = uuid4()
            bucket = self.storage.settings.s3_private_bucket
            await self.storage.upload(bucket, f"requests/{media_id}", stream, mime_type)
            media = Media(
                id=media_id,
                url=self.storage.url(bucket, "requests", media_id),
                original_name=original_name,
                mime_type=mime_type,
                size_bytes=size,
                width=width,
                height=height,
            )
            self.media.add(media)
        request = Request(
            id=request_id,
            name=name,
            phone=phone,
            comment=comment,
            category_id=category_id,
            media_id=media_id,
        )
        self.requests.add(request)
        await self.db.commit()
        await self.db.refresh(request)
        return RequestCreated(
            id=request.id,
            status=request.status,
            has_file=media_id is not None,
            created_at=request.created_at,
        )

    async def list(self, status: str | None) -> list[RequestListItem]:
        requests = await self.requests.list(status)
        return [
            RequestListItem(
                id=item.id,
                name=item.name,
                phone=item.phone,
                comment=item.comment,
                category_id=item.category_id,
                status=item.status,
                has_file=item.media_id is not None,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in requests
        ]

    async def get(self, request_id: UUID) -> Request:
        request = await self.requests.by_id(request_id)
        if request is None:
            raise RequestNotFoundError
        return request

    async def detail(self, request_id: UUID) -> RequestDetail:
        request = await self.get(request_id)
        file = None
        if request.media_id is not None:
            media = await self.media.by_id(request.media_id)
            if media is None:
                raise RequestNotFoundError
            file = RequestFile(
                id=media.id,
                original_name=media.original_name,
                mime_type=media.mime_type,
                size_bytes=media.size_bytes,
                download_url=f"/api/v1/admin/requests/{request.id}/file",
            )
        return RequestDetail(
            id=request.id,
            name=request.name,
            phone=request.phone,
            comment=request.comment,
            category_id=request.category_id,
            status=request.status,
            created_at=request.created_at,
            updated_at=request.updated_at,
            file=file,
        )

    async def file(self, request_id: UUID):
        request = await self.get(request_id)
        if request.media_id is None:
            raise RequestNotFoundError
        media = await self.media.by_id(request.media_id)
        if media is None:
            raise RequestNotFoundError
        obj = await self.storage.get(
            self.storage.settings.s3_private_bucket, f"requests/{media.id}"
        )
        return media, obj["Body"]

    async def update(self, request_id: UUID, status: str) -> RequestDetail:
        request = await self.get(request_id)
        request.status = status
        await self.db.commit()
        await self.db.refresh(request)
        return await self.detail(request_id)
