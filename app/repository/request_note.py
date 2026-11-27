from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import Media
from app.models.request import RequestNote, RequestNoteAttachment


class RequestNoteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, request_id: UUID) -> list[RequestNote]:
        stmt = (
            select(RequestNote)
            .where(RequestNote.request_id == request_id)
            .order_by(RequestNote.created_at.desc(), RequestNote.id.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def add(self, note: RequestNote) -> None:
        self.db.add(note)

    def attach_files(self, note_id: UUID, media_ids: list[UUID]) -> None:
        self.db.add_all(
            [
                RequestNoteAttachment(note_id=note_id, media_id=media_id, position=position)
                for position, media_id in enumerate(media_ids)
            ]
        )

    async def files_by_note(self, request_id: UUID) -> dict[UUID, list[Media]]:
        stmt = (
            select(RequestNoteAttachment.note_id, Media)
            .join(Media, Media.id == RequestNoteAttachment.media_id)
            .join(RequestNote, RequestNote.id == RequestNoteAttachment.note_id)
            .where(RequestNote.request_id == request_id)
            .order_by(RequestNoteAttachment.position)
        )
        result = await self.db.execute(stmt)
        files: dict[UUID, list[Media]] = {}
        for note_id, media in result.all():
            files.setdefault(note_id, []).append(media)
        return files

    async def file(self, request_id: UUID, note_id: UUID, file_id: UUID) -> Media | None:
        stmt = (
            select(Media)
            .join(RequestNoteAttachment, RequestNoteAttachment.media_id == Media.id)
            .join(RequestNote, RequestNote.id == RequestNoteAttachment.note_id)
            .where(
                RequestNote.request_id == request_id, RequestNote.id == note_id, Media.id == file_id
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()
