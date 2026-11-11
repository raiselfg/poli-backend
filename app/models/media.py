from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (
        CheckConstraint("url ~ '^https?://'", name="chk_media_url"),
        CheckConstraint("size_bytes > 0", name="chk_media_size"),
        CheckConstraint("width IS NULL OR width > 0", name="chk_media_width"),
        CheckConstraint("height IS NULL OR height > 0", name="chk_media_height"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    url: Mapped[str] = mapped_column(Text, unique=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None]
    height: Mapped[int | None]
    alt: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CategoryMedia(Base):
    __tablename__ = "category_media"
    __table_args__ = (
        CheckConstraint("sort_order >= 0", name="chk_category_media_sort_order"),
        Index("idx_category_media_order", "category_id", "sort_order"),
        Index("idx_category_media_media_id", "media_id"),
    )

    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE", name="fk_category_media_category"),
        primary_key=True,
    )
    media_id: Mapped[UUID] = mapped_column(
        ForeignKey("media.id", ondelete="RESTRICT", name="fk_category_media_media"),
        primary_key=True,
    )
    sort_order: Mapped[int] = mapped_column(server_default="0")
