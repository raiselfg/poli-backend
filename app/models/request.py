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
            "status IN ('new', 'in_progress', 'completed')", name="chk_requests_status"
        ),
        Index("idx_requests_created_at", text("created_at DESC"), text("id DESC")),
        Index("idx_requests_status_created_at", "status", text("created_at DESC")),
        Index("idx_requests_category_id", "category_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str] = mapped_column(String(40))
    comment: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL", name="fk_requests_category")
    )
    media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media.id", ondelete="RESTRICT", name="fk_requests_media"), unique=True
    )
    status: Mapped[str] = mapped_column(String(20), server_default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
