from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    hash_password,
    needs_rehash,
    new_token,
    token_hash,
    utc_now,
    valid_token,
    verify_password,
)
from app.models.session import Session
from app.models.user import User
from app.repository.session import SessionRepository
from app.repository.user import UserRepository
from app.schemas.user import UserRead


class LoginAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class AuthenticationRequiredError(Exception):
    pass


@dataclass(frozen=True)
class CurrentSession:
    user: UserRead
    session_expires_at: datetime


class AuthService:
    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
    ):
        self.db = db
        self.users = UserRepository(db)
        self.sessions = SessionRepository(db)
        self.settings = settings

    async def register(self, login: str, password: str) -> User:
        if await self.users.by_login(login) is not None:
            raise LoginAlreadyExistsError("Login already taken")

        user = User(
            id=uuid4(),
            login=login,
            password_hash=await hash_password(password),
            created_at=utc_now(),
        )

        try:
            self.users.add(user)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            cause = getattr(exc.orig, "__cause__", None)
            if getattr(cause, "constraint_name", None) == "uq_users_login":
                raise LoginAlreadyExistsError("Login already taken") from None
            raise

        return user

    async def login(self, login: str, password: str) -> tuple[User, str]:
        user = await self.users.by_login(login)
        verified = await verify_password(user.password_hash if user else None, password)

        if user is None or not verified:
            raise InvalidCredentialsError("Invalid login or password")

        if needs_rehash(user.password_hash):
            user.password_hash = await hash_password(password)

        now = utc_now()
        token = new_token()
        session = Session(
            id=uuid4(),
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=now + timedelta(seconds=self.settings.session_ttl_seconds),
        )

        self.sessions.add(session)
        await self.db.commit()

        return user, token

    async def verify_session(self, token: str | None) -> CurrentSession:
        if token is None or not valid_token(token):
            raise AuthenticationRequiredError("Authentication required")

        digest = token_hash(token)
        now = utc_now()

        session = await self.sessions.get_active(digest, now)
        if session is None:
            raise AuthenticationRequiredError("Authentication required")

        user = await self.users.by_id(session.user_id)
        if user is None:
            raise AuthenticationRequiredError("Authentication required")

        session = await self.sessions.refresh(
            session.id, now, now + timedelta(seconds=self.settings.session_ttl_seconds)
        )
        if session is None:
            raise AuthenticationRequiredError("Authentication required")

        await self.db.commit()
        return CurrentSession(UserRead.model_validate(user), session.expires_at)

    async def logout(self, token: str | None) -> None:
        if token is None or not valid_token(token):
            raise AuthenticationRequiredError("Authentication required")

        session_id = await self.sessions.delete_active(token_hash(token), utc_now())
        if session_id is None:
            raise AuthenticationRequiredError("Authentication required")
            
        await self.db.commit()
