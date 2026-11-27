from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TelegramBinding(Base):
    __tablename__ = "telegram_binding"
    __table_args__ = (CheckConstraint("id = 1", name="chk_telegram_binding_singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger)
    admin_origin: Mapped[str | None] = mapped_column(String)
    bot_token_hash: Mapped[str | None] = mapped_column(String(64))
    link_hash: Mapped[str | None] = mapped_column(String(64))
    link_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
