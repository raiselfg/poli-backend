from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MediaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    original_name: str
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None
    alt: str | None
    created_at: datetime


class MediaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alt: str | None = Field(max_length=200)
