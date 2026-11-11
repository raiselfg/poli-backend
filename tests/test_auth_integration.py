"""Run against a dedicated PostgreSQL database via AUTH_TEST_DATABASE_URL."""

import asyncio
import json
import os
import subprocess
import sys
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.engine import make_url

import app.core.config as config_module
import app.services.auth as auth_module
from app.core.security import token_hash
from app.db.session import create_database
from app.models.session import Session
from app.models.user import User
from app.services.auth import (
    AuthenticationRequiredError,
    AuthService,
    InvalidCredentialsError,
    LoginAlreadyExistsError,
)
from tests.fakes import make_settings

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTH_TEST_DATABASE_URL"),
    reason="Set AUTH_TEST_DATABASE_URL to a dedicated test database",
)


@pytest.fixture(scope="module")
def settings():
    url = make_url(os.environ["AUTH_TEST_DATABASE_URL"])
    if url.drivername not in {"postgresql", "postgresql+asyncpg"} or url.query:
        raise ValueError("AUTH_TEST_DATABASE_URL must be a PostgreSQL URL without query parameters")
    return make_settings(
        pg_user=url.username,
        pg_password=url.password,
        pg_db=url.database,
        pg_port=url.port or 5432,
        pg_host=url.host,
    )


@pytest.fixture(scope="module", autouse=True)
def migrate_database(settings):
    env = {
        **os.environ,
        "APP_ENV": settings.app_env,
        "PG_USER": settings.pg_user,
        "PG_PASSWORD": settings.pg_password.get_secret_value(),
        "PG_DB": settings.pg_db,
        "PG_PORT": str(settings.pg_port),
        "PG_HOST": settings.pg_host,
        "ALLOWED_ORIGINS": json.dumps(settings.allowed_origins),
        "ALLOW_INSECURE_COOKIES": "false",
        "SESSION_TTL_SECONDS": str(settings.session_ttl_seconds),
    }
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)


@pytest.fixture
async def database(settings):
    database = create_database(settings)
    try:
        yield database
    finally:
        await database.engine.dispose()


@pytest.fixture
async def register(database, settings):
    ids = []

    async def create(login):
        async with database.session_factory() as db:
            user = await AuthService(db, settings).register(login, "secret")
            ids.append(user.id)
            return user

    try:
        yield create
    finally:
        async with database.session_factory() as db:
            stmt = delete(User).where(User.id.in_(ids))
            await db.execute(stmt)
            await db.commit()


@pytest.fixture
async def account(register):
    return await register("test_" + uuid4().hex[:20])


async def test_full_http_flow_with_postgresql(settings, database, monkeypatch):
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    from app.main import app

    monkeypatch.setattr(app.state, "settings", settings)
    body = {"login": "test_" + uuid4().hex[:20], "password": "secret"}
    user_id = None
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://api.example.com"
            ) as client:
                assert (await client.get("/ready")).status_code == 200
                response = await client.post("/api/v1/auth/register", json=body)
                assert response.status_code == 201
                user_id = response.json()["id"]
                assert not client.cookies
                assert (await client.get("/api/v1/auth/me")).status_code == 401
                assert (await client.post("/api/v1/auth/register", json=body)).status_code == 409
                assert (await client.post("/api/v1/auth/login", json=body)).status_code == 200
                token = client.cookies.get("__Host-session")
                response = await client.get("/api/v1/auth/me")
                assert response.json()["id"] == user_id
                response = await client.post("/api/v1/auth/logout")
                assert response.status_code == 204
                assert response.content == b""
                assert len(response.headers.get_list("set-cookie")) == 1
                assert client.cookies.get("__Host-session") is None
                response = await client.get(
                    "/api/v1/auth/me", headers={"Cookie": f"__Host-session={token}"}
                )
                assert response.status_code == 401
    finally:
        if user_id is not None:
            async with database.session_factory() as db:
                stmt = delete(User).where(User.id == UUID(user_id))
                await db.execute(stmt)
                await db.commit()


async def test_case_sensitive_registration_and_login(database, settings, account, register):
    upper = await register(account.login.upper())
    assert upper.id != account.id
    async with database.session_factory() as db:
        service = AuthService(db, settings)
        for user in (account, upper):
            _, token = await service.login(user.login, "secret")
            assert (await service.verify_session(token)).user.id == user.id
        with pytest.raises(LoginAlreadyExistsError):
            await service.register(account.login, "secret")
        for login, password in [(account.login, "incorrect"), ("Missing", "secret")]:
            with pytest.raises(InvalidCredentialsError):
                await service.login(login, password)


async def test_concurrent_registration_has_one_winner(account, register, monkeypatch):
    barrier = asyncio.Barrier(2)
    original_hash = auth_module.hash_password

    async def synchronized_hash(password):
        await asyncio.wait_for(barrier.wait(), timeout=5)
        return await original_hash(password)

    monkeypatch.setattr(auth_module, "hash_password", synchronized_hash)
    results = await asyncio.gather(
        register(account.login.upper()), register(account.login.upper()), return_exceptions=True
    )
    assert sum(isinstance(result, User) for result in results) == 1
    assert sum(isinstance(result, LoginAlreadyExistsError) for result in results) == 1


@pytest.mark.parametrize("phase", ["selected", "updated", "committed"])
async def test_logout_cannot_be_undone_by_inflight_session_refresh(
    database, settings, account, phase
):
    async with database.session_factory() as db:
        _, token = await AuthService(db, settings).login(account.login, "secret")
    async with database.session_factory() as fill_db, database.session_factory() as logout_db:
        fill = AuthService(fill_db, settings)
        logout = AuthService(logout_db, settings)
        fill_started, resume_fill, logout_started = (
            asyncio.Event(), asyncio.Event(), asyncio.Event()
        )
        if phase == "selected":
            target, method = fill.sessions, "get_active"
        elif phase == "updated":
            target, method = fill.sessions, "refresh"
        else:
            target, method = fill_db, "commit"
        original_fill = getattr(target, method)
        original_delete = logout.sessions.delete_active

        async def delayed_fill(*args, **kwargs):
            result = await original_fill(*args, **kwargs)
            fill_started.set()
            await resume_fill.wait()
            return result

        async def observed_delete(*args, **kwargs):
            logout_started.set()
            return await original_delete(*args, **kwargs)

        setattr(target, method, delayed_fill)
        logout.sessions.delete_active = observed_delete
        pending_fill = asyncio.create_task(fill.verify_session(token))
        pending_logout = None
        try:
            await asyncio.wait_for(fill_started.wait(), timeout=5)
            pending_logout = asyncio.create_task(logout.logout(token))
            await asyncio.wait_for(logout_started.wait(), timeout=5)
            if phase == "updated":
                # Logout waits for the row lock held by the session refresh.
                done, _ = await asyncio.wait({pending_logout}, timeout=0.2)
                assert not done
            else:
                await asyncio.wait_for(pending_logout, timeout=5)
            resume_fill.set()
            if phase == "selected":
                with pytest.raises(AuthenticationRequiredError):
                    await asyncio.wait_for(pending_fill, timeout=5)
            else:
                await asyncio.wait_for(pending_fill, timeout=5)
            await asyncio.wait_for(pending_logout, timeout=5)
        finally:
            resume_fill.set()
            tasks = [task for task in (pending_fill, pending_logout) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    async with database.session_factory() as db:
        stmt = select(Session).where(Session.token_hash == token_hash(token))
        session = await db.scalar(stmt)
        assert session is None
        with pytest.raises(AuthenticationRequiredError):
            await AuthService(db, settings).verify_session(token)
