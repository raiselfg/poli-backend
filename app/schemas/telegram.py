from typing import Literal

from pydantic import BaseModel

TelegramStatus = Literal["unavailable", "disconnected", "connected"]
TelegramConfirmation = Literal["waiting", "expired", "connected"]


class TelegramStatusRead(BaseModel):
    status: TelegramStatus


class TelegramLink(BaseModel):
    username: str
    code: str


class TelegramLinkConfirm(BaseModel):
    code: str


class TelegramConfirmationRead(BaseModel):
    status: TelegramConfirmation
