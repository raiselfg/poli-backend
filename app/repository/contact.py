from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact


class ContactRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self) -> Contact | None:
        return await self.db.get(Contact, 1)
