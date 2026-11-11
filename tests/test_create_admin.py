from unittest.mock import AsyncMock, Mock

import pytest

import app.create_admin as create_admin_module
from app.schemas.auth import Credentials
from app.services.auth import LoginAlreadyExistsError
from tests.fakes import make_settings


async def test_create_admin_uses_auth_service_and_disposes_engine(monkeypatch):
    settings = make_settings()
    session = object()
    session_context = AsyncMock()
    session_context.__aenter__.return_value = session
    database = Mock()
    database.session_factory.return_value = session_context
    database.engine.dispose = AsyncMock()
    service = Mock()
    service.register = AsyncMock()
    monkeypatch.setattr(create_admin_module, "get_settings", lambda: settings)
    monkeypatch.setattr(create_admin_module, "create_database", lambda _: database)
    service_factory = Mock(return_value=service)
    monkeypatch.setattr(create_admin_module, "AuthService", service_factory)

    await create_admin_module.create_admin(Credentials(login="User", password="secret"))

    service_factory.assert_called_once_with(session, settings)
    service.register.assert_awaited_once_with("User", "secret")
    database.engine.dispose.assert_awaited_once()


def test_cli_rejects_duplicate_without_printing_password(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["create_admin", "User"])
    monkeypatch.setattr(create_admin_module, "getpass", lambda _: "secret")
    monkeypatch.setattr(
        create_admin_module, "create_admin", AsyncMock(side_effect=LoginAlreadyExistsError)
    )
    with pytest.raises(SystemExit) as error:
        create_admin_module.main()
    assert error.value.code == 1
    assert "secret" not in capsys.readouterr().err
