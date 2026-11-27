from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ChatType
from aiogram.exceptions import AiogramError
from aiogram.methods import GetMe, GetUpdates, SendMessage, TelegramMethod
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from aiogram.utils.token import TokenValidationError
from aiohttp_socks import ProxyConnectionError, ProxyError, ProxyTimeoutError
from pydantic import SecretStr


class TelegramError(Exception):
    pass


class TelegramBot:
    def __init__(self, token: str, proxy_url: SecretStr | None = None):
        self._token = token
        self._proxy_url = proxy_url

    async def _call[T](self, method: TelegramMethod[T]) -> T:
        try:
            proxy = self._proxy_url.get_secret_value() if self._proxy_url else None
            async with AiohttpSession(proxy=proxy) as session:
                bot = Bot(self._token, session=session)
                return await bot(method, request_timeout=4)
        except (
            AiogramError,
            TokenValidationError,
            ProxyConnectionError,
            ProxyError,
            ProxyTimeoutError,
            ValueError,
        ):
            raise TelegramError(f"Telegram {method.__api_method__} failed") from None

    async def username(self) -> str:
        profile = await self._call(GetMe())
        if not profile.username:
            raise TelegramError("Telegram bot has no username")
        return profile.username

    async def private_start_commands(self) -> list[tuple[int, str]]:
        # This bot is dedicated to notifications, so older queued updates can be discarded.
        updates = await self._call(GetUpdates(offset=-100, allowed_updates=["message"]))
        commands = []
        for update in updates:
            message = update.message
            if message is None or message.chat.type != ChatType.PRIVATE or message.text is None:
                continue
            command, _, code = message.text.partition(" ")
            if command == "/start":
                commands.append((message.chat.id, code))
        return commands

    async def send_message(self, chat_id: int, text: str, *, admin_url: str | None = None) -> None:
        keyboard = None
        if admin_url is not None:
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Вернуться в админку", url=admin_url)]]
            )
        await self._call(
            SendMessage(
                chat_id=chat_id,
                text=text,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                reply_markup=keyboard,
            )
        )
