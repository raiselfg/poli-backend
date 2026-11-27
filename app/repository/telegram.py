from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram import TelegramBinding


class TelegramRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, *, for_update: bool = False) -> TelegramBinding:
        return await self.db.get_one(TelegramBinding, 1, with_for_update=for_update)

    async def connect(
        self,
        *,
        link_hash: str,
        now: datetime,
        chat_id: int,
        admin_origin: str | None,
        bot_token_hash: str,
    ) -> bool:
        stmt = (
            update(TelegramBinding)
            .where(
                TelegramBinding.id == 1,
                TelegramBinding.link_hash == link_hash,
                TelegramBinding.link_expires_at > now,
            )
            .values(
                chat_id=chat_id,
                admin_origin=admin_origin,
                bot_token_hash=bot_token_hash,
                link_hash=None,
                link_expires_at=None,
            )
            .returning(TelegramBinding.id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None
