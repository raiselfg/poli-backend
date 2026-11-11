from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi.middleware.cors import CORSMiddleware

import app.core.config as config_module
from app.api.dependencies import get_auth_service, get_request_service
from app.core.security import new_token, utc_now
from app.schemas.user import UserRead
from app.services.auth import (
    AuthenticationRequiredError,
    AuthService,
    InvalidCredentialsError,
)
from tests.fakes import make_settings

ORIGIN = "https://app.example.com"
HEADERS = {"Origin": ORIGIN}
BODY = {"login": "User", "password": "secret"}


@pytest.fixture
def settings():
    return make_settings(allowed_origins=[ORIGIN])


@pytest.fixture
def auth_service():
    service = AsyncMock(spec=AuthService)
    user = UserRead(id=uuid4(), login="User", created_at=utc_now())
    service.login.return_value = (user, new_token())
    return service


@pytest.fixture
def application(settings, auth_service, monkeypatch):
    monkeypatch.setattr(config_module, "get_settings", lambda: settings)
    from app.main import app

    cors = next(item for item in app.user_middleware if item.cls is CORSMiddleware)
    monkeypatch.setitem(cors.kwargs, "allow_origins", settings.allowed_origins)
    monkeypatch.setattr(app, "middleware_stack", None)
    monkeypatch.setattr(app.state, "settings", settings)
    monkeypatch.setattr(app, "dependency_overrides", {get_auth_service: lambda: auth_service})
    return app


@pytest.fixture
async def client(application):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="https://api.example.com"
    ) as client:
        yield client


async def test_registration_is_not_public(client, auth_service):
    response = await client.post("/api/v1/auth/register", json=BODY, headers=HEADERS)
    assert response.status_code == 404
    auth_service.register.assert_not_awaited()


async def test_login_sets_cookie(client, auth_service):
    response = await client.post("/api/v1/auth/login", json=BODY, headers=HEADERS)
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert client.cookies.get("__Host-session") == auth_service.login.return_value[1]
    auth_service.login.assert_awaited_once_with("User", "secret")


async def test_invalid_body_uses_fastapi_validation(client, auth_service):
    response = await client.post("/api/v1/auth/login", data=BODY, headers=HEADERS)
    assert response.status_code == 422
    auth_service.login.assert_not_awaited()


async def test_validation_does_not_echo_password(client):
    response = await client.post(
        "/api/v1/auth/login",
        json={"login": "User", "password": "s3cr!"},
        headers=HEADERS,
    )
    assert response.status_code == 422
    assert "s3cr!" not in response.text


async def test_cors_preflight(client):
    response = await client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    response = await client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


async def test_logout_clears_cookie_without_renewal(client, auth_service):
    token = new_token()
    response = await client.post(
        "/api/v1/auth/logout", headers={**HEADERS, "Cookie": f"__Host-session={token}"}
    )
    assert response.status_code == 204
    assert response.content == b""
    assert len(response.headers.get_list("set-cookie")) == 1
    assert "Max-Age=0" in response.headers["set-cookie"]
    auth_service.logout.assert_awaited_once_with(token)
    auth_service.verify_session.assert_not_awaited()


async def test_health_without_database(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_expired_session_does_not_refresh_cookie(client, auth_service):
    auth_service.verify_session.side_effect = AuthenticationRequiredError()
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


async def test_service_errors_keep_http_contract(client, auth_service):
    auth_service.login.side_effect = InvalidCredentialsError()
    result = await client.post("/api/v1/auth/login", json=BODY, headers=HEADERS)
    assert result.status_code == 401
    assert result.json() == {"detail": "Invalid login or password"}

    assert result.headers["access-control-allow-origin"] == ORIGIN


async def test_json_with_charset_accepted(client):
    result = await client.post(
        "/api/v1/auth/login",
        json=BODY,
        headers={**HEADERS, "Content-Type": "application/json; charset=utf-8"},
    )
    assert result.status_code == 200


async def test_logout_requires_authentication(client, auth_service):
    auth_service.logout.side_effect = AuthenticationRequiredError()
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 401
    assert "set-cookie" not in response.headers


def test_api_has_only_basic_auth_routes(application):
    paths = {path for path in application.openapi()["paths"] if path.startswith("/api/v1/auth")}
    assert paths == {
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
    }


@pytest.mark.parametrize(
    "settings",
    [
        make_settings(
            allowed_origins=["http://localhost:3000"],
            allow_insecure_cookies=True,
            session_ttl_seconds=60,
        )
    ],
)
async def test_app_settings_control_cookies_and_cors(application):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://localhost:8000"
    ) as client:
        response = await client.post(
            "/api/v1/auth/login", json=BODY, headers={"Origin": "http://localhost:3000"}
        )
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("session=")
    assert "Max-Age=60" in cookie
    assert "Secure" not in cookie
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_request_file_download_does_not_require_session(client, application, auth_service):
    request_id = uuid4()
    service = AsyncMock()
    media = SimpleNamespace(original_name="drawing.pdf", mime_type="application/pdf")
    service.file.return_value = media, BytesIO(b"drawing")
    application.dependency_overrides[get_request_service] = lambda: service

    response = await client.get(f"/api/v1/admin/requests/{request_id}/file")

    assert response.status_code == 200
    assert response.content == b"drawing"
    service.file.assert_awaited_once_with(request_id)
    auth_service.verify_session.assert_not_awaited()
