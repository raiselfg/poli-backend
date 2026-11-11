from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from argon2 import PasswordHasher
from sqlalchemy.engine import Result
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.auth as auth_module
from app.core.security import new_token, token_hash
from app.models.session import Session
from app.models.user import User
from app.services.auth import (
    AuthenticationRequiredError,
    AuthService,
    InvalidCredentialsError,
    LoginAlreadyExistsError,
)
from tests.fakes import make_settings

PASSWORD = "long secure password"


@pytest.fixture
def auth():
    return AuthService(AsyncMock(spec=AsyncSession), make_settings())


@pytest.fixture
def db_result(auth):
    result = Mock(spec=Result)
    auth.db.execute.return_value = result
    return result


async def test_registration_does_not_create_session(auth, db_result):
    db_result.scalar_one_or_none.return_value = None
    user = await auth.register("User", PASSWORD)
    auth.db.add.assert_called_once_with(user)
    auth.db.commit.assert_awaited_once()
    assert user.login == "User"
    assert await auth_module.verify_password(user.password_hash, PASSWORD)


async def test_duplicate_registration(auth, db_result):
    db_result.scalar_one_or_none.return_value = Mock(spec=User)
    with pytest.raises(LoginAlreadyExistsError):
        await auth.register("User", PASSWORD)
    auth.db.add.assert_not_called()
    auth.db.commit.assert_not_awaited()


@pytest.mark.parametrize("constraint", ["uq_users_login", "other_constraint"])
async def test_registration_conflict_rolls_back(auth, db_result, constraint):
    db_result.scalar_one_or_none.return_value = None
    original = Exception()
    original.__cause__ = Exception()
    original.__cause__.constraint_name = constraint
    error = IntegrityError("insert", {}, original)
    auth.db.commit.side_effect = error
    expected = LoginAlreadyExistsError if constraint == "uq_users_login" else IntegrityError
    with pytest.raises(expected):
        await auth.register("User", PASSWORD)
    auth.db.rollback.assert_awaited_once()


async def test_invalid_credentials_same_response_and_dummy_check(auth, db_result, monkeypatch):
    user = User(password_hash=await auth_module.hash_password(PASSWORD))
    db_result.scalar_one_or_none.side_effect = [user, None]
    verify = AsyncMock(wraps=auth_module.verify_password)
    monkeypatch.setattr(auth_module, "verify_password", verify)
    errors = []
    for login, password in [("User", "incorrect password"), ("Missing", PASSWORD)]:
        with pytest.raises(InvalidCredentialsError) as exc:
            await auth.login(login, password)
        errors.append((type(exc.value), str(exc.value)))
    assert errors[0] == errors[1]
    assert verify.await_args_list[-1].args == (None, PASSWORD)
    auth.db.add.assert_not_called()


async def test_only_token_hash_stored(auth, db_result):
    user = User(id=uuid4(), password_hash=await auth_module.hash_password(PASSWORD))
    db_result.scalar_one_or_none.return_value = user
    result, token = await auth.login("User", PASSWORD)
    session = auth.db.add.call_args.args[0]
    assert result is user
    assert isinstance(session, Session)
    assert session.token_hash == token_hash(token)
    assert token not in vars(session).values()
    auth.db.commit.assert_awaited_once()


@pytest.mark.parametrize("method", ["verify_session", "logout"])
@pytest.mark.parametrize("token", [None, "", "invalid", "я" * 43])
async def test_malformed_token_never_reaches_database(auth, method, token):
    with pytest.raises(AuthenticationRequiredError):
        await getattr(auth, method)(token)
    auth.db.execute.assert_not_awaited()
    auth.db.get.assert_not_awaited()


async def test_password_rehash_is_saved_on_login(auth, db_result):
    old_hash = PasswordHasher(time_cost=1, memory_cost=19456, parallelism=1).hash(PASSWORD)
    user = User(id=uuid4(), password_hash=old_hash)
    db_result.scalar_one_or_none.return_value = user
    await auth.login("User", PASSWORD)
    assert user.password_hash != old_hash
    assert await auth_module.verify_password(user.password_hash, PASSWORD)
    assert not auth_module.needs_rehash(user.password_hash)
    auth.db.commit.assert_awaited_once()


async def test_revoked_session_is_not_restored_during_refresh(auth, db_result):
    db_result.scalar_one_or_none.side_effect = [Session(id=uuid4(), user_id=uuid4()), None]
    auth.db.get.return_value = User()
    with pytest.raises(AuthenticationRequiredError):
        await auth.verify_session(new_token())
    auth.db.commit.assert_not_awaited()


async def test_failed_commit_does_not_return_current_session(auth, db_result):
    db_result.scalar_one_or_none.side_effect = [
        Session(id=uuid4(), user_id=uuid4()),
        Session(expires_at=datetime(2026, 12, 2, tzinfo=UTC)),
    ]
    auth.db.get.return_value = User()
    auth.db.commit.side_effect = ConnectionError("commit failed")
    with pytest.raises(ConnectionError):
        await auth.verify_session(new_token())


async def test_verification_returns_session_with_its_user(auth, db_result):
    now = datetime(2026, 11, 2, tzinfo=UTC)
    user = User(id=uuid4(), login="User", created_at=now)
    session = Session(
        id=uuid4(), user_id=user.id, expires_at=now + timedelta(days=30)
    )
    db_result.scalar_one_or_none.side_effect = [session, session]
    auth.db.get.return_value = user

    current_session = await auth.verify_session(new_token())

    assert current_session.user.id == user.id
    assert current_session.user.login == "User"
    assert current_session.session_expires_at == session.expires_at
    auth.db.get.assert_awaited_once_with(User, user.id)
    auth.db.commit.assert_awaited_once()


@pytest.mark.parametrize("missing", ["session", "user"])
async def test_verification_rejects_missing_session_or_user(auth, db_result, missing):
    session = Session(id=uuid4(), user_id=uuid4())
    db_result.scalar_one_or_none.return_value = None if missing == "session" else session
    auth.db.get.return_value = None

    with pytest.raises(AuthenticationRequiredError):
        await auth.verify_session(new_token())

    auth.db.commit.assert_not_awaited()


async def test_logout_does_not_refresh_session(auth, db_result):
    db_result.scalar_one_or_none.return_value = uuid4()
    await auth.logout(new_token())
    auth.db.execute.assert_awaited_once()
    auth.db.get.assert_not_awaited()
    auth.db.commit.assert_awaited_once()


async def test_missing_session_cannot_logout(auth, db_result):
    db_result.scalar_one_or_none.return_value = None
    with pytest.raises(AuthenticationRequiredError):
        await auth.logout(new_token())
    auth.db.commit.assert_not_awaited()
