from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RequestStatus = Literal["new", "in_progress", "completed"]


class RequestCreated(BaseModel):
    id: UUID
    status: RequestStatus
    has_file: bool = Field(serialization_alias="hasFile")
    created_at: datetime = Field(serialization_alias="createdAt")


class RequestListItem(BaseModel):
    id: UUID
    name: str
    phone: str
    comment: str | None
    category_id: UUID | None = Field(serialization_alias="categoryId")
    status: RequestStatus
    has_file: bool = Field(serialization_alias="hasFile")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class RequestFile(BaseModel):
    id: UUID
    original_name: str = Field(serialization_alias="originalName")
    mime_type: str = Field(serialization_alias="mimeType")
    size_bytes: int = Field(serialization_alias="sizeBytes")
    download_url: str = Field(serialization_alias="downloadUrl")


class RequestDetail(BaseModel):
    id: UUID
    name: str
    phone: str
    comment: str | None
    category_id: UUID | None = Field(serialization_alias="categoryId")
    status: RequestStatus
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    file: RequestFile | None


class RequestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RequestStatus
