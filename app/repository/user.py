from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def by_login(self, login: str) -> User | None:
        stmt = select(User).where(User.login == login)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def by_id(self, user_id: UUID) -> User | None:
        return await self.db.get(User, user_id)

    def add(self, user: User) -> None:
        self.db.add(user)
