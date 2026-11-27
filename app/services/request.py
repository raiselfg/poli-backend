import logging
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media
from app.models.request import Request, RequestNote
from app.repository.media import MediaRepository
from app.repository.request import RequestRepository
from app.repository.request_note import RequestNoteRepository
from app.schemas.request import RequestCreated, RequestDetail, RequestFile, RequestListItem
from app.storage.s3 import S3Storage

logger = logging.getLogger(__name__)


class RequestNotFoundError(Exception):
    pass


class RequestService:
    def __init__(self, db: AsyncSession, storage: S3Storage):
        self.db = db
        self.requests = RequestRepository(db)
        self.notes = RequestNoteRepository(db)
        self.media = MediaRepository(db)
        self.storage = storage

    async def create(
        self,
        name: str,
        phone: str,
        comment: str | None,
        files: list[tuple[BinaryIO, str, str, int, int | None, int | None]],
    ) -> RequestCreated:
        request = Request(
            id=uuid4(),
            name=name,
            phone=phone,
            comment=comment,
        )
        bucket = self.storage.settings.s3_private_bucket
        attachment_ids: list[UUID] = []
        try:
            for stream, original_name, mime_type, size, width, height in files:
                media_id = uuid4()
                media = Media(
                    id=media_id,
                    object_key=f"requests/{media_id}",
                    original_name=original_name,
                    mime_type=mime_type,
                    size_bytes=size,
                    width=width,
                    height=height,
                )
                attachment_ids.append(media_id)
                await self.storage.upload(bucket, media.object_key, stream, mime_type)
                self.media.add(media)
            self.requests.add(request)
            if attachment_ids:
                await self.db.flush()
                self.requests.attach_files(request.id, attachment_ids)
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            for media_id in attachment_ids:
                try:
                    await self.storage.delete(bucket, f"requests/{media_id}")
                except Exception:
                    logger.exception("Failed to clean up request attachment %s", media_id)
            raise
        await self.db.refresh(request)
        return RequestCreated(
            id=request.id,
            status=request.status,
            has_file=bool(attachment_ids),
            created_at=request.created_at,
        )

    async def list(self, status: str | None) -> list[RequestListItem]:
        requests = await self.requests.list(status)
        with_files = await self.requests.ids_with_files(status)
        return [
            RequestListItem(
                id=item.id,
                name=item.name,
                phone=item.phone,
                comment=item.comment,
                status=item.status,
                has_file=item.id in with_files,
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
        download_url = f"/api/v1/admin/requests/{request.id}/file"
        files = [
            RequestFile(
                id=media.id,
                original_name=media.original_name,
                mime_type=media.mime_type,
                size_bytes=media.size_bytes,
                download_url=f"{download_url}?file_id={media.id}",
            )
            for media in await self.requests.files(request.id)
        ]
        return RequestDetail(
            id=request.id,
            name=request.name,
            phone=request.phone,
            comment=request.comment,
            status=request.status,
            created_at=request.created_at,
            updated_at=request.updated_at,
            file=files[0].model_copy(update={"download_url": download_url}) if files else None,
            files=files,
        )

    async def file(self, request_id: UUID, file_id: UUID | None = None):
        uploads = await self.requests.files(request_id)
        for media in uploads:
            if file_id is None or media.id == file_id:
                obj = await self.storage.get(
                    self.storage.settings.s3_private_bucket, media.object_key
                )
                return media, obj["Body"]
        raise RequestNotFoundError

    async def update(self, request_id: UUID, status: str) -> RequestDetail:
        request = await self.get(request_id)
        request.status = status
        await self.db.commit()
        await self.db.refresh(request)
        return await self.detail(request_id)

    async def list_notes(self, request_id: UUID) -> list[RequestNote]:
        await self.get(request_id)
        return await self.notes.list(request_id)

    async def add_note(self, request_id: UUID, text: str) -> RequestNote:
        await self.get(request_id)
        note = RequestNote(id=uuid4(), request_id=request_id, text=text)
        self.notes.add(note)
        await self.db.commit()
        await self.db.refresh(note)
        return note
