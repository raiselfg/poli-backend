from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.repository.contact import ContactRepository
from app.schemas.contact import ContactUpdate


class ContactNotFoundError(Exception):
    pass


class InvalidContactError(Exception):
    pass


class ContactService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.contacts = ContactRepository(db)

    async def get(self) -> Contact:
        contact = await self.contacts.get()
        if contact is None:
            raise ContactNotFoundError
        return contact

    async def update(self, body: ContactUpdate) -> Contact:
        contact = await self.get()
        values = body.model_dump(exclude_unset=True)
        if any(value is None for value in values.values()):
            raise InvalidContactError
        for key, value in values.items():
            setattr(contact, key, value)
        await self.db.commit()
        await self.db.refresh(contact)
        return contact
