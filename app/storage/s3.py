from functools import lru_cache
from urllib.parse import urlsplit
from uuid import UUID

import boto3
from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.concurrency import run_in_threadpool


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    s3_endpoint_url: str
    s3_access_key_id: SecretStr
    s3_secret_access_key: SecretStr
    s3_public_bucket: str
    s3_private_bucket: str

    @model_validator(mode="after")
    def validate_urls(self):
        parts = urlsplit(self.s3_endpoint_url)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or parts.query
            or parts.fragment
        ):
            raise ValueError("S3 endpoint must be an absolute HTTP(S) URL")
        if self.s3_public_bucket == self.s3_private_bucket:
            raise ValueError("Public and private buckets must differ")
        return self


@lru_cache
def get_storage_settings() -> StorageSettings:
    return StorageSettings()


class S3Storage:
    def __init__(self, settings: StorageSettings):
        self.settings = settings
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            region_name="eu-central-1",
        )

    def url(self, bucket: str, namespace: str, media_id: UUID) -> str:
        return f"{self.settings.s3_endpoint_url.rstrip('/')}/{bucket}/{namespace}/{media_id}"

    async def upload(self, bucket: str, key: str, file, mime_type: str) -> None:
        await run_in_threadpool(
            self.client.upload_fileobj,
            file,
            bucket,
            key,
            ExtraArgs={"ContentType": mime_type},
        )

    async def delete(self, bucket: str, key: str) -> None:
        await run_in_threadpool(self.client.delete_object, Bucket=bucket, Key=key)

    async def get(self, bucket: str, key: str):
        return await run_in_threadpool(self.client.get_object, Bucket=bucket, Key=key)
