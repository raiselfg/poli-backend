from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

Slug = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
Title = Annotated[str, Field(min_length=1, max_length=160)]


class CategoryImage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str
    alt: str | None
    width: int | None
    height: int | None


class CategoryPublic(BaseModel):
    id: UUID
    slug: str
    title: str
    description: str
    images: list[CategoryImage]


class CategoryAdmin(CategoryPublic):
    is_published: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    slug: Slug
    title: Title
    description: str = ""
    is_published: bool = False
    sort_order: int = Field(default=0, ge=0)
    media_ids: list[UUID] = Field(default_factory=list, alias="mediaIds")

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title must not be blank")
        return value

    @field_validator("media_ids")
    @classmethod
    def media_not_repeated(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Media IDs must be unique")
        return value


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    slug: Slug | None = None
    title: Title | None = None
    description: str | None = None
    is_published: bool | None = None
    sort_order: Annotated[int, Field(ge=0)] | None = None
    media_ids: list[UUID] | None = Field(default=None, alias="mediaIds")

    @field_validator("slug", "title", "description", "is_published", "sort_order", "media_ids")
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError("Null is not allowed")
        return value

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title must not be blank")
        return value

    @field_validator("media_ids")
    @classmethod
    def media_not_repeated(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Media IDs must be unique")
        return value


class CategoryOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[UUID]
