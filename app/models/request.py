from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Request(Base):
    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="chk_requests_name"),
        CheckConstraint("length(btrim(phone)) > 0", name="chk_requests_phone"),
        CheckConstraint(
            "status IN ('new', 'in_progress', 'clarifying', 'quote_sent', 'waiting_reply', "
            "'completed', 'cancelled')",
            name="chk_requests_status",
        ),
        Index("idx_requests_created_at", text("created_at DESC"), text("id DESC")),
        Index("idx_requests_status_created_at", "status", text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(40))
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RequestNote(Base):
    __tablename__ = "request_notes"
    __table_args__ = (
        Index("idx_request_notes_request_created_at", "request_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE", name="fk_request_notes_request")
    )
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RequestNoteAttachment(Base):
    __tablename__ = "request_note_attachments"
    __table_args__ = (
        CheckConstraint("position BETWEEN 0 AND 4", name="chk_request_note_attachments_position"),
    )

    note_id: Mapped[UUID] = mapped_column(
        ForeignKey("request_notes.id", ondelete="CASCADE", name="fk_request_note_attachments_note"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    media_id: Mapped[UUID] = mapped_column(
        ForeignKey("media.id", ondelete="RESTRICT", name="fk_request_note_attachments_media"),
        unique=True,
    )


class RequestAttachment(Base):
    __tablename__ = "request_attachments"
    __table_args__ = (
        CheckConstraint("position BETWEEN 0 AND 2", name="chk_request_attachments_position"),
    )

    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE", name="fk_request_attachments_request"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    media_id: Mapped[UUID] = mapped_column(
        ForeignKey("media.id", ondelete="RESTRICT", name="fk_request_attachments_media"),
        unique=True,
    )
