from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Numeric, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Contact(Base):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint("id = 1", name="chk_contacts_singleton"),
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) OR "
            "(latitude IS NOT NULL AND longitude IS NOT NULL)",
            name="chk_contacts_coordinates",
        ),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="chk_contacts_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="chk_contacts_longitude"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default="1")
    phone: Mapped[str] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(254))
    address: Mapped[str] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    working_hours: Mapped[str | None] = mapped_column(String(255))
    telegram_url: Mapped[str | None] = mapped_column(Text)
    whatsapp_url: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
