from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    alt: str = Field(min_length=1, max_length=200)

    @field_validator("alt")
    @classmethod
    def alt_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Alt must not be blank")
        return value
