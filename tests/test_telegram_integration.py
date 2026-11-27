"""Exercise notification settings with PostgreSQL and a simulated Telegram Bot API."""

import asyncio
import json
import os
from contextlib import suppress
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import pytest
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.methods import GetMe, GetUpdates, SendMessage
from aiogram.types import InlineKeyboardMarkup, LinkPreviewOptions
from aiohttp_socks import ProxyError
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import delete

import app.api.dependencies as dependencies
import app.services.telegram as telegram_service
from app.api.router import api_router
from app.core.security import utc_now
from app.models.request import Request
from app.storage.s3 import StorageSettings
from tests.test_auth_integration import (  # noqa: F401
    account,
    database,
    migrate_database,
    register,
    settings,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTH_TEST_DATABASE_URL"),
    reason="Set AUTH_TEST_DATABASE_URL to a dedicated test database",
)


@pytest.mark.parametrize("proxy_url", [None, "socks5://user:pass@proxy.example.com:1080"])
async def test_telegram_link_and_request_notifications(
    proxy_url,
    account,  # noqa: F811
    database,  # noqa: F811
    settings,  # noqa: F811
    monkeypatch,
    caplog,
):
    bot_token = "123:example-token"
    origin = "https://admin.example.com"
    app = FastAPI()
    app.include_router(api_router)
    app.state.settings = settings.model_copy(
        update={
            "telegram_bot_token": SecretStr(bot_token),
            "telegram_proxy_url": SecretStr(proxy_url) if proxy_url else None,
            "allowed_origins": [origin],
        }
    )
    app.state.session_factory = database.session_factory
    storage = StorageSettings(
        _env_file=None,
        s3_endpoint_url="http://127.0.0.1:9000",
        s3_access_key_id="unused",
        s3_secret_access_key="unused",
        s3_public_bucket="catalog",
        s3_private_bucket="requests",
    )
    monkeypatch.setattr(dependencies, "get_storage_settings", lambda: storage)

    updates = []
    outbound = []
    connection_message = asyncio.Event()
    fail_delivery = False

    async def telegram_api(session, bot, method, timeout=None):  # noqa: ASYNC109
        assert bot.token == bot_token
        assert session.proxy == proxy_url
        assert timeout == 4
        if isinstance(method, GetMe):
            result = {
                "id": 123,
                "is_bot": True,
                "first_name": "Requests",
                "username": "TestRequestsBot",
                "can_join_groups": True,
                "can_read_all_group_messages": False,
                "supports_guest_queries": False,
                "supports_inline_queries": False,
                "needs_inline_query_location": False,
                "can_connect_to_business": False,
                "has_main_web_app": False,
                "has_topics_enabled": False,
                "allows_users_to_create_topics": False,
                "has_topic_sidebar": False,
                "can_manage_bots": False,
                "supports_join_request_queries": False,
            }
        elif isinstance(method, GetUpdates):
            assert method.offset == -100
            assert method.allowed_updates == ["message"]
            result = updates
        else:
            assert isinstance(method, SendMessage)
            preview = method.link_preview_options
            assert isinstance(preview, LinkPreviewOptions)
            button_url = None
            if isinstance(method.reply_markup, InlineKeyboardMarkup):
                [[button]] = method.reply_markup.inline_keyboard
                assert button.text == "Вернуться в админку"
                button_url = button.url
                connection_message.set()
            outbound.append((method.chat_id, method.text, preview.is_disabled, button_url))
            if fail_delivery:
                if proxy_url is not None:
                    raise ProxyError(proxy_url)
                content = json.dumps({"ok": False, "error_code": 502, "description": bot_token})
                return session.check_response(bot, method, 502, content).result
            result = {
                "message_id": 1,
                "date": 1_700_000_000,
                "chat": {"id": method.chat_id, "type": "private"},
            }
        content = json.dumps({"ok": True, "result": result})
        return session.check_response(bot, method, 200, content).result

    monkeypatch.setattr(AiohttpSession, "make_request", telegram_api)
    path = "/api/v1/admin/telegram"
    request_ids = []

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=origin, headers={"Origin": origin}
    ) as client:
        assert (await client.get(path)).status_code == 401
        assert (await client.post(f"{path}/link")).status_code == 401
        assert (await client.post(f"{path}/link/confirm", json={"code": ""})).status_code == 401
        assert (await client.delete(path)).status_code == 401
        logged_in = await client.post(
            "/api/v1/auth/login", json={"login": account.login, "password": "secret"}
        )
        assert logged_in.status_code == 200
        try:
            assert (await client.get(path)).json() == {"status": "disconnected"}
            first_link = (await client.post(f"{path}/link")).json()
            link = (await client.post(f"{path}/link")).json()
            assert link["username"] == "TestRequestsBot"

            async def confirm(code):
                return (await client.post(f"{path}/link/confirm", json={"code": code})).json()

            assert await confirm(first_link["code"]) == {"status": "expired"}

            def add_update(chat_id, chat_type, text):
                update_id = len(updates) + 1
                updates.append(
                    {
                        "update_id": update_id,
                        "message": {
                            "message_id": update_id,
                            "date": 1_700_000_000,
                            "chat": {"id": chat_id, "type": chat_type},
                            "text": text,
                        },
                    }
                )

            command = f"/start {link['code']}"
            add_update(-123, "group", command)
            add_update(123, "private", "/start")
            assert await confirm(link["code"]) == {"status": "waiting"}
            add_update(2**40, "private", command)
            polling = asyncio.create_task(
                telegram_service.poll_telegram_links(
                    database.session_factory,
                    bot_token,
                    app.state.settings.telegram_proxy_url,
                    [origin],
                )
            )
            try:
                await asyncio.wait_for(connection_message.wait(), timeout=3)
            finally:
                polling.cancel()
                with suppress(asyncio.CancelledError):
                    await polling
            assert outbound == [
                (
                    2**40,
                    "Telegram успешно подключён. Новые заявки будут приходить в этот чат.\n\n"
                    "Вернитесь в раздел «Заявки», чтобы проверить статус подключения.",
                    True,
                    origin + "/requests",
                )
            ]
            assert await confirm(link["code"]) == {"status": "connected"}
            assert len(outbound) == 1
            outbound.clear()
            assert (await client.get(path)).json() == {"status": "connected"}

            with monkeypatch.context() as patch:
                expiring_link = (await client.post(f"{path}/link")).json()
                later = utc_now() + timedelta(minutes=11)
                patch.setattr(telegram_service, "utc_now", lambda: later)
                assert await confirm(expiring_link["code"]) == {"status": "expired"}
            assert (await client.get(path)).json() == {"status": "connected"}

            async def create_request(comment=""):
                response = await client.post(
                    "/api/v1/requests",
                    data={"name": "Test customer", "phone": "123", "comment": comment},
                )
                assert response.status_code == 201
                request_id = UUID(response.json()["id"])
                request_ids.append(request_id)
                return response.json()

            created = await create_request("  Втулка 40×60\nНужно 10 штук.  ")
            submitted_at = datetime.fromisoformat(created["createdAt"]).astimezone(
                ZoneInfo("Europe/Moscow")
            )
            expected = (
                "Новая заявка с лендинга\n\n"
                "Имя: Test customer\n"
                "Телефон: 123\n"
                f"Получена: {submitted_at:%d.%m.%Y в %H:%M} (МСК)\n"
                "Категория: не выбрана\n"
                "Вложения: нет\n\n"
                "Комментарий:\nВтулка 40×60\nНужно 10 штук.\n\n"
                f"Открыть заявку: {origin}/requests/{created['id']}"
            )
            assert outbound == [(2**40, expected, True, None)]

            long_comment = "🔧" * 5000
            created = await create_request(long_comment)
            message = outbound[-1][1]
            assert len(message.encode("utf-16-le")) <= 2 * 4096
            assert message.endswith(f"…\n\nОткрыть заявку: {origin}/requests/{created['id']}")
            detail = await client.get(f"/api/v1/admin/requests/{created['id']}")
            assert detail.json()["comment"] == long_comment

            fail_delivery = True
            created = await create_request("  ")
            assert (await client.get(f"/api/v1/admin/requests/{created['id']}")).status_code == 200
            assert "Could not notify about request" in caplog.text
            assert bot_token not in caplog.text
            assert proxy_url is None or proxy_url not in caplog.text
            assert "Комментарий:" not in outbound[-1][1]
            assert (await client.delete(path)).json() == {"status": "disconnected"}
            await create_request()
            assert len(outbound) == 3
        finally:
            await client.delete(path)
            async with database.session_factory() as db:
                stmt = delete(Request).where(Request.id.in_(request_ids))
                await db.execute(stmt)
                await db.commit()
