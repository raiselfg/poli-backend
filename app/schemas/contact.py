from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class ContactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    phone: str
    email: str | None
    address: str
    latitude: Decimal | None
    longitude: Decimal | None
    working_hours: str | None
    telegram_url: str | None
    whatsapp_url: str | None
    updated_at: datetime


class ContactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = None
    latitude: Annotated[Decimal, Field(ge=-90, le=90)] | None = None
    longitude: Annotated[Decimal, Field(ge=-180, le=180)] | None = None
    working_hours: str | None = Field(default=None, max_length=255)
    telegram_url: str | None = None
    whatsapp_url: str | None = None
