import logging
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.media import Media
from app.models.request import Request, RequestNote
from app.repository.media import MediaRepository
from app.repository.request import RequestRepository
from app.repository.request_note import RequestNoteRepository
from app.schemas.request import (
    MAX_REQUEST_FILE_SIZE,
    RequestCreated,
    RequestDetail,
    RequestFile,
    RequestListItem,
    RequestNoteRead,
)
from app.storage.catalog_images import CATALOG_IMAGE_SIZES, encode_catalog_variants
from app.storage.s3 import S3Storage

logger = logging.getLogger(__name__)

type AttachmentUpload = tuple[BinaryIO, str, str, int, int | None, int | None]


class RequestNotFoundError(Exception):
    pass


class OptimizedAttachmentTooLargeError(Exception):
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
        files: list[AttachmentUpload],
    ) -> RequestCreated:
        request = Request(
            id=uuid4(),
            name=name,
            phone=phone,
            comment=comment,
        )
        attachment_ids: list[UUID] = []
        try:
            for file in files:
                media_id = uuid4()
                attachment_ids.append(media_id)
                await self._store_attachment(media_id, file)
            self.requests.add(request)
            if attachment_ids:
                await self.db.flush()
                self.requests.attach_files(request.id, attachment_ids)
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            await self._cleanup_attachments(attachment_ids)
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

    async def _store_attachment(self, media_id: UUID, file: AttachmentUpload) -> Media:
        stream, name, mime_type, size, width, height = file
        media = Media(
            id=media_id,
            object_key=f"requests/{media_id}",
            original_name=name,
            mime_type=mime_type,
            size_bytes=size,
            width=width,
            height=height,
        )
        await self.storage.upload(
            self.storage.settings.s3_private_bucket, media.object_key, stream, mime_type
        )
        self.media.add(media)
        return media

    async def _cleanup_attachments(self, media_ids: list[UUID]) -> None:
        for media_id in media_ids:
            try:
                await self.storage.delete(
                    self.storage.settings.s3_private_bucket, f"requests/{media_id}"
                )
            except Exception:
                logger.exception("Failed to clean up request attachment %s", media_id)

    async def _store_note_attachment(self, media_id: UUID, file: AttachmentUpload) -> Media:
        stream, name, mime_type, *_ = file
        if not mime_type.startswith("image/"):
            return await self._store_attachment(media_id, file)

        (optimized,) = await run_in_threadpool(
            encode_catalog_variants,
            stream,
            (CATALOG_IMAGE_SIZES[-1],),
            preserve_format=True,
        )
        with optimized.stream:
            if optimized.size > MAX_REQUEST_FILE_SIZE:
                raise OptimizedAttachmentTooLargeError
            return await self._store_attachment(
                media_id,
                (
                    optimized.stream,
                    name,
                    mime_type,
                    optimized.size,
                    optimized.width,
                    optimized.height,
                ),
            )

    def _note_response(self, note: RequestNote, files: list[Media]) -> RequestNoteRead:
        return RequestNoteRead(
            id=note.id,
            text=note.text,
            created_at=note.created_at,
            files=[
                RequestFile(
                    id=media.id,
                    original_name=media.original_name,
                    mime_type=media.mime_type,
                    size_bytes=media.size_bytes,
                    download_url=(
                        f"/api/v1/admin/requests/{note.request_id}/notes/{note.id}/files/{media.id}"
                    ),
                )
                for media in files
            ],
        )

    async def list_notes(self, request_id: UUID) -> list[RequestNoteRead]:
        await self.get(request_id)
        notes = await self.notes.list(request_id)
        files = await self.notes.files_by_note(request_id) if notes else {}
        return [self._note_response(note, files.get(note.id, [])) for note in notes]

    async def add_note(
        self, request_id: UUID, text: str, files: list[AttachmentUpload] | None = None
    ) -> RequestNoteRead:
        await self.get(request_id)
        note = RequestNote(id=uuid4(), request_id=request_id, text=text)
        attempted_ids: list[UUID] = []
        attachments: list[Media] = []
        try:
            for file in files or []:
                media_id = uuid4()
                attempted_ids.append(media_id)
                attachments.append(await self._store_note_attachment(media_id, file))
            self.notes.add(note)
            if attachments:
                await self.db.flush()
                self.notes.attach_files(note.id, attempted_ids)
            await self.db.commit()
        except BaseException:
            await self.db.rollback()
            await self._cleanup_attachments(attempted_ids)
            raise
        await self.db.refresh(note)
        return self._note_response(note, attachments)

    async def note_file(self, request_id: UUID, note_id: UUID, file_id: UUID):
        media = await self.notes.file(request_id, note_id, file_id)
        if media is None:
            raise RequestNotFoundError
        obj = await self.storage.get(self.storage.settings.s3_private_bucket, media.object_key)
        return media, obj["Body"]
