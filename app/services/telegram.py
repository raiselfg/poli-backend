import logging
from datetime import timedelta
from urllib.parse import quote
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import new_token, token_hash, utc_now, valid_token
from app.repository.telegram import TelegramRepository
from app.schemas.telegram import TelegramConfirmation, TelegramLink, TelegramStatus
from app.telegram import TelegramBot, TelegramError

logger = logging.getLogger(__name__)


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

    async def create_link(self) -> TelegramLink:
        if self.bot is None:
            raise TelegramNotConfiguredError
        username = await self.bot.username()
        code = new_token()
        binding = await self.bindings.get(for_update=True)
        binding.link_hash = token_hash(f"{self.bot_token_hash}:{code}")
        binding.link_expires_at = utc_now() + timedelta(minutes=10)
        await self.db.commit()
        return TelegramLink(username=username, code=code)

    async def confirm(self, code: str, admin_origin: str | None) -> TelegramConfirmation:
        if self.bot is None or self.bot_token_hash is None:
            raise TelegramNotConfiguredError
        if not valid_token(code):
            return "expired"
        digest = token_hash(f"{self.bot_token_hash}:{code}")
        binding = await self.bindings.get()
        if (
            binding.link_hash != digest
            or binding.link_expires_at is None
            or binding.link_expires_at <= utc_now()
        ):
            return "expired"
        await self.db.rollback()

        chat_id = await self.bot.find_private_chat(code)
        if chat_id is None:
            return "waiting"

        connected = await self.bindings.connect(
            link_hash=digest,
            now=utc_now(),
            chat_id=chat_id,
            admin_origin=admin_origin,
            bot_token_hash=self.bot_token_hash,
        )
        await self.db.commit()
        return "connected" if connected else "expired"

    async def disconnect(self) -> TelegramStatus:
        binding = await self.bindings.get(for_update=True)
        binding.chat_id = None
        binding.admin_origin = None
        binding.bot_token_hash = None
        binding.link_hash = None
        binding.link_expires_at = None
        await self.db.commit()
        return "disconnected" if self.bot else "unavailable"


async def notify_new_request(
    sessions: async_sessionmaker[AsyncSession],
    token: str,
    allowed_origins: list[str],
    request_id: UUID,
    proxy_url: SecretStr | None = None,
) -> None:
    try:
        async with sessions() as db:
            binding = await TelegramRepository(db).get()
            chat_id = binding.chat_id
            if chat_id is None or binding.bot_token_hash != token_hash(quote(token)):
                return
            origin = binding.admin_origin

        text = "Новая заявка с лендинга"
        if origin in allowed_origins:
            text += f"\n{origin}/requests/{request_id}"
        await TelegramBot(token, proxy_url).send_message(chat_id, text)
    except TelegramError as exc:
        logger.warning("Could not notify about request %s: %s", request_id, exc)
    except Exception:
        logger.exception("Could not notify about request %s", request_id)
