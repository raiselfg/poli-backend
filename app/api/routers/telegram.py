from fastapi import APIRouter, HTTPException, Request, Response

from app.api.dependencies import CurrentSessionDep, SettingsDep, TelegramServiceDep
from app.schemas.telegram import (
    TelegramConfirmationRead,
    TelegramLink,
    TelegramLinkConfirm,
    TelegramStatusRead,
)
from app.services.telegram import TelegramNotConfiguredError
from app.telegram import TelegramError

router = APIRouter(prefix="/admin/telegram", tags=["telegram"])


@router.get("", response_model=TelegramStatusRead)
async def telegram_status(_current_session: CurrentSessionDep, service: TelegramServiceDep):
    return TelegramStatusRead(status=await service.status())


@router.post("/link", response_model=TelegramLink)
async def create_telegram_link(
    _current_session: CurrentSessionDep, service: TelegramServiceDep, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return await service.create_link()
    except TelegramNotConfiguredError:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured") from None
    except TelegramError:
        raise HTTPException(status_code=502, detail="Telegram API unavailable") from None


@router.post("/link/confirm", response_model=TelegramConfirmationRead)
async def confirm_telegram_link(
    _current_session: CurrentSessionDep,
    service: TelegramServiceDep,
    settings: SettingsDep,
    request: Request,
    body: TelegramLinkConfirm,
):
    origin = request.headers.get("origin")
    try:
        status = await service.confirm(
            body.code, origin if origin in settings.allowed_origins else None
        )
    except TelegramNotConfiguredError:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured") from None
    except TelegramError:
        raise HTTPException(status_code=502, detail="Telegram API unavailable") from None
    return TelegramConfirmationRead(status=status)


@router.delete("", response_model=TelegramStatusRead)
async def disconnect_telegram(_current_session: CurrentSessionDep, service: TelegramServiceDep):
    return TelegramStatusRead(status=await service.disconnect())
