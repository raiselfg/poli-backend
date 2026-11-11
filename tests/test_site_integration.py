"""Exercise site API with dedicated PostgreSQL and SeaweedFS test instances."""

import io
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy import delete

import app.api.dependencies as dependencies
import app.storage.configure as storage_configure
from app.api.body_limit import UploadBodyLimitMiddleware
from app.api.router import api_router
from app.db.session import get_db
from app.lifespan import lifespan
from app.models.category import Category
from app.models.media import Media
from app.models.request import Request
from app.storage.s3 import S3Storage, StorageSettings
from tests.test_auth_integration import database, migrate_database, register, settings  # noqa: F401

pytestmark = pytest.mark.skipif(
    not os.getenv("AUTH_TEST_DATABASE_URL") or not os.getenv("TEST_S3_ENDPOINT"),
    reason="Set dedicated AUTH_TEST_DATABASE_URL and TEST_S3_ENDPOINT",
)


async def test_site_flow(database, settings, register, monkeypatch):  # noqa: F811
    storage_settings = StorageSettings(
        _env_file=None,
        s3_endpoint_url=os.environ["TEST_S3_ENDPOINT"],
        s3_access_key_id="local-access-key",
        s3_secret_access_key="local-secret-key",
        s3_public_bucket="poli-public",
        s3_private_bucket="poli-private",
    )
    monkeypatch.setattr(dependencies, "get_storage_settings", lambda: storage_settings)
    app = FastAPI()
    app.include_router(api_router)
    app.add_middleware(UploadBodyLimitMiddleware)
    app.state.settings = settings
    account = await register("test_" + uuid4().hex[:20])

    async def session():
        async with database.session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = session
    category_id = None
    media_id = None
    request_id = None
    attachment_id = None
    image = io.BytesIO()
    Image.new("RGB", (2, 3), "red").save(image, format="PNG")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://test"
        ) as client:
            assert (await client.get("/api/v1/admin/media")).status_code == 401
            login = await client.post(
                "/api/v1/auth/login", json={"login": account.login, "password": "secret"}
            )
            assert login.status_code == 200
            assert (await client.get("/api/v1/contacts")).status_code == 200
            await client.patch(
                "/api/v1/admin/contacts", json={"latitude": None, "longitude": None}
            )
            invalid_contact = await client.patch("/api/v1/admin/contacts", json={"latitude": 10})
            assert invalid_contact.status_code == 422
            updated_contact = await client.patch(
                "/api/v1/admin/contacts", json={"latitude": 10, "longitude": 20}
            )
            assert updated_contact.status_code == 200
            assert (
                await client.patch(
                    "/api/v1/admin/contacts", json={"latitude": None, "longitude": None}
                )
            ).status_code == 200
            response = await client.post(
                "/api/v1/admin/media", files={"file": ("image.png", image.getvalue(), "image/png")}
            )
            assert response.status_code == 201, response.text
            media_id = response.json()["id"]
            assert response.json()["width"] == 2
            async with httpx.AsyncClient(trust_env=False) as cdn:
                public_image = await cdn.get(response.json()["url"])
            assert public_image.status_code == 200
            assert public_image.headers["content-type"] == "image/webp"
            assert response.json()["mime_type"] == "image/webp"
            assert response.json()["size_bytes"] == len(public_image.content)
            with Image.open(io.BytesIO(public_image.content)) as optimized:
                assert optimized.format == "WEBP"
                assert optimized.size == (2, 3)
            response = await client.post(
                "/api/v1/admin/categories",
                json={"slug": f"test-{uuid4().hex}", "title": "Test", "mediaIds": [media_id]},
            )
            assert response.status_code == 201, response.text
            category_id = response.json()["id"]
            response = await client.patch(
                f"/api/v1/admin/categories/{category_id}", json={"is_published": True}
            )
            assert response.status_code == 200, response.text
            response = await client.get("/api/v1/categories")
            assert any(item["id"] == category_id for item in response.json())
            assert (await client.delete(f"/api/v1/admin/media/{media_id}")).status_code == 409
            invalid = await client.post(
                "/api/v1/admin/media", files={"file": ("fake.png", b"not an image", "image/png")}
            )
            assert invalid.status_code == 415
            too_large = await client.post(
                "/api/v1/requests",
                data={"name": "Test", "phone": "123"},
                files={"file": ("drawing.pdf", b"x" * (10 * 1024 * 1024 + 1), "application/pdf")},
            )
            assert too_large.status_code == 413
            too_large_request = await client.post(
                "/api/v1/requests",
                data={"name": "Test", "phone": "123", "comment": "x" * (11 * 1024 * 1024)},
            )
            assert too_large_request.status_code == 413

            async def oversized_stream():
                for _ in range(12):
                    yield b"x" * (1024 * 1024)

            streamed = await client.post("/api/v1/requests", content=oversized_stream())
            assert streamed.status_code == 413
            response = await client.post(
                "/api/v1/requests",
                data={"name": "Test", "phone": "123", "categoryId": category_id},
                files={"file": ("drawing.pdf", b"%PDF-1.4\ntest", "application/pdf")},
            )
            assert response.status_code == 201, response.text
            request_id = response.json()["id"]
            assert response.json()["hasFile"]
            detail = await client.get(f"/api/v1/admin/requests/{request_id}")
            assert detail.status_code == 200, detail.text
            attachment_id = detail.json()["file"]["id"]
            async with httpx.AsyncClient(trust_env=False) as cdn:
                direct = await cdn.get(
                    f"{storage_settings.s3_endpoint_url}/poli-private/requests/{attachment_id}"
                )
            assert direct.status_code == 200
            assert direct.content == b"%PDF-1.4\ntest"
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://test"
            ) as anonymous_client:
                anonymous_download = await anonymous_client.get(
                    f"/api/v1/admin/requests/{request_id}/file"
                )
            assert anonymous_download.status_code == 200
            assert anonymous_download.content == b"%PDF-1.4\ntest"
            downloaded = await client.get(f"/api/v1/admin/requests/{request_id}/file")
            assert downloaded.content == b"%PDF-1.4\ntest"
            response = await client.patch(
                f"/api/v1/admin/requests/{request_id}", json={"status": "completed"}
            )
            assert response.json()["status"] == "completed"
            listed = await client.get("/api/v1/admin/categories")
            ids = [item["id"] for item in listed.json()]
            assert (
                await client.put("/api/v1/admin/categories/order", json={"ids": ids})
            ).status_code == 204
            duplicate = await client.put(
                "/api/v1/admin/categories/order", json={"ids": [category_id, category_id]}
            )
            assert duplicate.status_code == 422
            assert (
                await client.delete(f"/api/v1/admin/categories/{category_id}")
            ).status_code == 204
            detail = await client.get(f"/api/v1/admin/requests/{request_id}")
            assert detail.json()["categoryId"] is None
            assert (await client.delete(f"/api/v1/admin/media/{media_id}")).status_code == 204
            response = await client.post(
                "/api/v1/requests",
                data={"name": "Test", "phone": "123"},
                files=[("file", ("a.pdf", b"%PDF-1.4\na")), ("file", ("b.pdf", b"%PDF-1.4\nb"))],
            )
            assert response.status_code == 400
    finally:
        async with database.session_factory() as db:
            if request_id:
                stmt = delete(Request).where(Request.id == request_id)
                await db.execute(stmt)
            if category_id:
                stmt = delete(Category).where(Category.id == category_id)
                await db.execute(stmt)
            for item_id in (media_id, attachment_id):
                if item_id:
                    stmt = delete(Media).where(Media.id == item_id)
                    await db.execute(stmt)
            await db.commit()
        storage = S3Storage(storage_settings)
        if media_id:
            await storage.delete("poli-public", f"catalog/{media_id}")
        if attachment_id:
            await storage.delete("poli-private", f"requests/{attachment_id}")


async def test_lifespan_makes_both_buckets_public(database, settings, monkeypatch):  # noqa: F811
    suffix = uuid4().hex
    storage_settings = StorageSettings(
        _env_file=None,
        s3_endpoint_url=os.environ["TEST_S3_ENDPOINT"],
        s3_access_key_id="local-access-key",
        s3_secret_access_key="local-secret-key",
        s3_public_bucket=f"test-images-{suffix}",
        s3_private_bucket=f"test-requests-{suffix}",
    )
    monkeypatch.setattr(storage_configure, "get_storage_settings", lambda: storage_settings)
    storage = S3Storage(storage_settings)
    buckets = (storage_settings.s3_public_bucket, storage_settings.s3_private_bucket)
    created = []
    try:
        for bucket in buckets:
            storage.client.create_bucket(
                Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "eu-central-1"}
            )
            created.append(bucket)
            storage.client.put_object(Bucket=bucket, Key="test/file", Body=b"test")

        app = FastAPI(lifespan=lifespan)
        app.state.settings = settings
        async with httpx.AsyncClient(trust_env=False) as client:
            for bucket in buckets:
                response = await client.get(
                    f"{storage_settings.s3_endpoint_url}/{bucket}/test/file"
                )
                assert response.status_code == 403
            async with app.router.lifespan_context(app):
                for bucket in buckets:
                    response = await client.get(
                        f"{storage_settings.s3_endpoint_url}/{bucket}/test/file"
                    )
                    assert response.status_code == 200
                    assert response.content == b"test"
                    unauthorized_write = await client.put(
                        f"{storage_settings.s3_endpoint_url}/{bucket}/test/other", content=b"test"
                    )
                    assert unauthorized_write.status_code == 403
                    unauthorized_delete = await client.delete(
                        f"{storage_settings.s3_endpoint_url}/{bucket}/test/file"
                    )
                    assert unauthorized_delete.status_code == 403
    finally:
        for bucket in created:
            storage.client.delete_object(Bucket=bucket, Key="test/file")
            storage.client.delete_bucket(Bucket=bucket)
