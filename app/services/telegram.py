import asyncio
import logging
from datetime import timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import new_token, token_hash, utc_now, valid_token
from app.repository.request import RequestRepository
from app.repository.telegram import TelegramRepository
from app.schemas.request import RequestCreated
from app.schemas.telegram import TelegramConfirmation, TelegramLink, TelegramStatus
from app.telegram import TelegramBot, TelegramError

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096


class TelegramNotConfiguredError(Exception):
    pass


class TelegramService:
    def __init__(self, db: AsyncSession, token: str, proxy_url: SecretStr | None = None):
        self.db = db
        self.bindings = TelegramRepository(db)
        self.bot = TelegramBot(token, proxy_url) if token else None
        self.bot_token_hash = token_hash(quote(token)) if token else None

    async def status(self) -> TelegramStatus:
        if self.bot is None:
            return "unavailable"
        binding = await self.bindings.get()
        if binding.chat_id is not None and binding.bot_token_hash == self.bot_token_hash:
            return "connected"
        return "disconnected"

    async def create_link(self, admin_origin: str | None) -> TelegramLink:
        if self.bot is None:
            raise TelegramNotConfiguredError
        username = await self.bot.username()
        code = new_token()
        binding = await self.bindings.get(for_update=True)
        binding.link_hash = token_hash(f"{self.bot_token_hash}:{code}")
        binding.link_expires_at = utc_now() + timedelta(minutes=10)
        binding.link_admin_origin = admin_origin
        await self.db.commit()
        return TelegramLink(username=username, code=code)

    async def confirm(self, code: str, admin_origin: str | None) -> TelegramConfirmation:
        if self.bot is None or self.bot_token_hash is None:
            raise TelegramNotConfiguredError
        if not valid_token(code):
            return "expired"
        digest = token_hash(f"{self.bot_token_hash}:{code}")
        binding = await self.bindings.get()
        if binding.link_hash != digest:
            return "expired"
        if binding.link_expires_at is None:
            if binding.chat_id is not None and binding.bot_token_hash == self.bot_token_hash:
                return "connected"
            return "expired"
        if binding.link_expires_at <= utc_now():
            return "expired"
        return await self._confirm_link(digest, admin_origin)

    async def confirm_pending_link(self, allowed_origins: list[str]) -> None:
        binding = await self.bindings.get()
        if (
            binding.link_hash is None
            or binding.link_expires_at is None
            or binding.link_expires_at <= utc_now()
        ):
            return
        origin = binding.link_admin_origin
        await self._confirm_link(binding.link_hash, origin if origin in allowed_origins else None)

    async def _confirm_link(self, digest: str, admin_origin: str | None) -> TelegramConfirmation:
        if self.bot is None or self.bot_token_hash is None:
            raise TelegramNotConfiguredError
        await self.db.rollback()

        for chat_id, code in await self.bot.private_start_commands():
            if not valid_token(code) or token_hash(f"{self.bot_token_hash}:{code}") != digest:
                continue
            connected = await self.bindings.connect(
                link_hash=digest,
                now=utc_now(),
                chat_id=chat_id,
                admin_origin=admin_origin,
                bot_token_hash=self.bot_token_hash,
            )
            await self.db.commit()
            if connected:
                await self._send_connection_confirmation(chat_id, admin_origin)
                return "connected"
            binding = await self.bindings.get()
            if binding.link_hash == digest and binding.link_expires_at is None:
                return "connected"
            return "expired"
        return "waiting"

    async def _send_connection_confirmation(self, chat_id: int, admin_origin: str | None) -> None:
        if self.bot is None:
            return
        text = "Telegram успешно подключён. Новые заявки будут приходить в этот чат."
        admin_url = None
        if admin_origin:
            text += "\n\nВернитесь в раздел «Заявки», чтобы проверить статус подключения."
            if admin_origin.startswith("https://"):
                admin_url = f"{admin_origin}/requests"
            else:
                text += f"\n{admin_origin}/requests"
        try:
            await self.bot.send_message(chat_id, text, admin_url=admin_url)
        except TelegramError as exc:
            logger.warning("Could not send Telegram connection confirmation: %s", exc)

    async def disconnect(self) -> TelegramStatus:
        binding = await self.bindings.get(for_update=True)
        binding.chat_id = None
        binding.admin_origin = None
        binding.bot_token_hash = None
        binding.link_hash = None
        binding.link_expires_at = None
        binding.link_admin_origin = None
        await self.db.commit()
        return "disconnected" if self.bot else "unavailable"


async def poll_telegram_links(
    sessions: async_sessionmaker[AsyncSession],
    token: str,
    proxy_url: SecretStr | None,
    allowed_origins: list[str],
) -> None:
    while True:
        try:
            async with sessions() as db:
                await TelegramService(db, token, proxy_url).confirm_pending_link(allowed_origins)
        except TelegramError as exc:
            logger.warning("Could not check pending Telegram link: %s", exc)
        except Exception:
            logger.exception("Could not check pending Telegram link")
        await asyncio.sleep(3)


async def notify_new_request(
    sessions: async_sessionmaker[AsyncSession],
    token: str,
    allowed_origins: list[str],
    created: RequestCreated,
    proxy_url: SecretStr | None = None,
) -> None:
    try:
        async with sessions() as db:
            binding = await TelegramRepository(db).get()
            chat_id = binding.chat_id
            if chat_id is None or binding.bot_token_hash != token_hash(quote(token)):
                return
            origin = binding.admin_origin
            request = await RequestRepository(db).by_id(created.id)
            if request is None:
                return

        submitted_at = created.created_at.astimezone(ZoneInfo("Europe/Moscow"))
        phone = " ".join(request.phone.split())
        compact_phone = phone.translate(str.maketrans("", "", " -()"))
        digits = compact_phone.removeprefix("+")
        if compact_phone.startswith("+") and digits.isascii() and digits.isdecimal():
            phone = compact_phone
        lines = [
            "Новая заявка с лендинга",
            "",
            f"Имя: {' '.join(request.name.split())}",
            f"Телефон: {phone}",
            f"Получена: {submitted_at:%d.%m.%Y в %H:%M} (МСК)",
            f"Вложения: {'есть' if created.has_file else 'нет'}",
        ]
        text = "\n".join(lines)
        link = ""
        if origin in allowed_origins:
            link = f"\n\nОткрыть заявку: {origin}/requests/{created.id}"
        comment = (request.comment or "").strip()
        if comment:
            label = "\n\nКомментарий:\n"
            # Reserve space for the admin link and count emoji conservatively as UTF-16.
            available_bytes = 2 * TELEGRAM_MAX_MESSAGE_LENGTH - len(
                (text + label + link).encode("utf-16-le")
            )
            encoded_comment = comment.encode("utf-16-le")
            if available_bytes > 0:
                if len(encoded_comment) > available_bytes:
                    comment = encoded_comment[: available_bytes - 2].decode(
                        "utf-16-le", errors="ignore"
                    )
                    comment += "…"
                text += label + comment
        text += link
        await TelegramBot(token, proxy_url).send_message(chat_id, text)
    except TelegramError as exc:
        logger.warning("Could not notify about request %s: %s", created.id, exc)
    except Exception:
        logger.exception("Could not notify about request %s", created.id)
