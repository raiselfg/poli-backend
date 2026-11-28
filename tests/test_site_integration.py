"""Exercise site API with dedicated PostgreSQL and RustFS test instances."""

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
    suffix = uuid4().hex
    storage_settings = StorageSettings(
        _env_file=None,
        s3_endpoint_url=os.environ["TEST_S3_ENDPOINT"],
        s3_access_key_id="local-access-key",
        s3_secret_access_key="local-secret-key",
        s3_public_bucket=f"test-images-{suffix}",
        s3_private_bucket=f"test-requests-{suffix}",
    )
    monkeypatch.setattr(dependencies, "get_storage_settings", lambda: storage_settings)
    monkeypatch.setattr(storage_configure, "get_storage_settings", lambda: storage_settings)
    app = FastAPI(lifespan=lifespan)
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
    attachment_ids = []
    note_attachment_ids = []
    variant_urls = []
    image = io.BytesIO()
    Image.new("RGB", (2, 3), "red").save(image, format="PNG")
    storage = S3Storage(storage_settings)
    created = []
    try:
        for bucket in (storage_settings.s3_public_bucket, storage_settings.s3_private_bucket):
            storage.client.create_bucket(
                Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": "eu-central-1"}
            )
            created.append(bucket)

        storage_configure.main()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://test"
            ) as client,
        ):
            assert (await client.get("/api/v1/admin/media")).status_code == 401
            login = await client.post(
                "/api/v1/auth/login", json={"login": account.login, "password": "secret"}
            )
            assert login.status_code == 200
            assert (await client.get("/api/v1/contacts")).status_code == 200
            invalid_contact = await client.patch(
                "/api/v1/admin/contacts", json={"latitude": None, "longitude": None}
            )
            assert invalid_contact.status_code == 422
            updated_contact = await client.patch(
                "/api/v1/admin/contacts", json={"latitude": 10, "longitude": 20}
            )
            assert updated_contact.status_code == 200
            response = await client.post(
                "/api/v1/admin/media", data={"alt": "Изображение"},
                files={"file": ("image.png", image.getvalue(), "image/png")}
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
            published = next(item for item in response.json() if item["id"] == category_id)
            variants = published["images"][0]["variants"]
            variant_urls = [variant["url"] for variant in variants]
            assert len(variant_urls) == 3
            assert len(set(variant_urls)) == 3
            assert {(variant["width"], variant["height"]) for variant in variants} == {(2, 3)}
            async with httpx.AsyncClient(trust_env=False) as cdn:
                for url in variant_urls:
                    variant = await cdn.get(url)
                    assert variant.status_code == 200
                    assert variant.headers["content-type"] == "image/webp"
                    assert "immutable" in variant.headers["cache-control"]
            assert (await client.delete(f"/api/v1/admin/media/{media_id}")).status_code == 409
            invalid = await client.post(
                "/api/v1/admin/media", data={"alt": "Изображение"},
                files={"file": ("fake.png", b"not an image", "image/png")}
            )
            assert invalid.status_code == 415
            too_large = await client.post(
                "/api/v1/requests",
                data={"name": "Test", "phone": "123"},
                files={"file": ("drawing.pdf", b"x" * (5 * 1024 * 1024 + 1), "application/pdf")},
            )
            assert too_large.status_code == 413
            too_large_request = await client.post(
                "/api/v1/requests",
                data={"name": "Test", "phone": "123", "comment": "x" * (16 * 1024 * 1024 + 1)},
            )
            assert too_large_request.status_code == 413

            async def oversized_stream():
                for _ in range(17):
                    yield b"x" * (1024 * 1024)

            streamed = await client.post("/api/v1/requests", content=oversized_stream())
            assert streamed.status_code == 413
            upload = S3Storage.upload
            attempts = []

            async def fail_second_upload(self, bucket, key, stream, mime_type):
                attempts.append(key)
                if len(attempts) == 2:
                    raise OSError("Test storage failure")
                await upload(self, bucket, key, stream, mime_type)

            with monkeypatch.context() as patch:
                patch.setattr(S3Storage, "upload", fail_second_upload)
                with pytest.raises(OSError, match="Test storage failure"):
                    await client.post(
                        "/api/v1/requests",
                        data={"name": "Incomplete upload", "phone": "123"},
                        files=[
                            ("file", ("terms.pdf", b"%PDF-1.4\ntest")),
                            ("file", ("drawing.dwg", b"AC1027test")),
                        ],
                    )
            stored = storage.client.list_objects_v2(Bucket=storage_settings.s3_private_bucket)
            assert not stored.get("Contents")
            listed = await client.get("/api/v1/admin/requests")
            assert all(item["name"] != "Incomplete upload" for item in listed.json())

            uploads = [
                ("terms.pdf", b"%PDF-1.4\ntest", "application/pdf"),
                ("product.png", image.getvalue(), "image/png"),
                ("drawing.dwg", b"AC1027test", "application/acad"),
            ]
            uploads = [
                (name, data.ljust(5 * 1024 * 1024, b"\x00"), mime)
                for name, data, mime in uploads
            ]
            response = await client.post(
                "/api/v1/requests",
                data={"name": "Test", "phone": "123"},
                files=[("file", upload) for upload in uploads],
            )
            assert response.status_code == 201, response.text
            request_id = response.json()["id"]
            assert response.json()["hasFile"]
            detail = await client.get(f"/api/v1/admin/requests/{request_id}")
            assert detail.status_code == 200, detail.text
            assert "categoryId" not in detail.json()
            notes_path = f"/api/v1/admin/requests/{request_id}/notes"
            assert (await client.get(notes_path)).json() == []
            assert (await client.post(notes_path, json={"text": "  "})).status_code == 422
            first_note = await client.post(notes_path, json={"text": "  Согласовали размеры  "})
            second_note = await client.post(notes_path, json={"text": "Ждём чертёж"})
            assert first_note.status_code == second_note.status_code == 201
            assert first_note.json()["text"] == "Согласовали размеры"
            assert first_note.json()["createdAt"]
            assert (await client.get(notes_path)).json() == [second_note.json(), first_note.json()]
            upload_path = notes_path + "/with-files"
            pdf = b"%PDF-1.4\n"
            small_pdfs = [("file", (f"{index}.pdf", pdf)) for index in range(6)]
            assert (await client.post(
                upload_path, data={"text": "Слишком много"}, files=small_pdfs
            )).status_code == 400
            assert (await client.post(
                upload_path, data={"text": "Неподдерживаемый файл"},
                files=[("file", ("notes.txt", b"text"))],
            )).status_code == 415
            assert (await client.post(
                upload_path, data={"text": "Слишком большой"},
                files=[("file", ("large.pdf", pdf.ljust(5 * 1024 * 1024 + 1)))],
            )).status_code == 413
            assert len((await client.get(notes_path)).json()) == 2
            note_with_files = await client.post(
                upload_path,
                data={"text": "Заметка с файлами"},
                files=[("file", ("photo.png", image.getvalue())), *small_pdfs[:4]],
            )
            assert note_with_files.status_code == 201, note_with_files.text
            note_files = note_with_files.json()["files"]
            note_attachment_ids = [item["id"] for item in note_files]
            assert len(note_files) == 5
            photo = note_files[0]
            assert photo["mimeType"] == "image/png"
            assert photo["originalName"] == "photo.png"
            downloaded_photo = await client.get(photo["downloadUrl"])
            assert downloaded_photo.status_code == 200
            assert downloaded_photo.headers["cache-control"] == "private, no-store"
            with Image.open(io.BytesIO(downloaded_photo.content)) as optimized:
                assert optimized.format == "PNG"
            assert (await client.get(note_files[1]["downloadUrl"])).content == pdf
            assert (await client.get(notes_path)).json()[0]["files"] == note_files
            wrong_note = photo["downloadUrl"].replace(
                note_with_files.json()["id"], second_note.json()["id"]
            )
            assert (await client.get(wrong_note)).status_code == 404
            missing_request_note = await client.post(
                f"/api/v1/admin/requests/{uuid4()}/notes", json={"text": "Не сохранять"}
            )
            assert missing_request_note.status_code == 404
            attachments = detail.json()["files"]
            attachment_ids = [attachment["id"] for attachment in attachments]
            assert [attachment["originalName"] for attachment in attachments] == [
                name for name, _, _ in uploads
            ]
            assert detail.json()["file"]["id"] == attachment_ids[0]
            listed = await client.get("/api/v1/admin/requests")
            assert any(item["id"] == request_id and item["hasFile"] for item in listed.json())
            assert all("categoryId" not in item for item in listed.json())
            async with httpx.AsyncClient(trust_env=False) as cdn:
                direct = await cdn.get(
                    f"{storage_settings.s3_endpoint_url}/{storage_settings.s3_private_bucket}"
                    f"/requests/{attachment_ids[0]}"
                )
            assert direct.status_code == 403
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://test"
            ) as anonymous_client:
                anonymous_download = await anonymous_client.get(
                    f"/api/v1/admin/requests/{request_id}/file"
                )
                assert (await anonymous_client.get(notes_path)).status_code == 401
                assert (await anonymous_client.get(photo["downloadUrl"])).status_code == 401
                anonymous_note = await anonymous_client.post(notes_path, json={"text": "Тест"})
                assert anonymous_note.status_code == 401
            assert anonymous_download.status_code == 401
            downloaded = await client.get(f"/api/v1/admin/requests/{request_id}/file")
            assert downloaded.status_code == 200
            assert downloaded.content == uploads[0][1]
            assert downloaded.headers["cache-control"] == "private, no-store"
            for attachment, (_, data, _) in zip(attachments, uploads, strict=True):
                downloaded = await client.get(attachment["downloadUrl"])
                assert downloaded.status_code == 200
                assert downloaded.content == data
            unrelated = await client.get(
                f"/api/v1/admin/requests/{request_id}/file", params={"file_id": media_id}
            )
            assert unrelated.status_code == 404
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
            assert (await client.delete(f"/api/v1/admin/media/{media_id}")).status_code == 204
            async with httpx.AsyncClient(trust_env=False) as cdn:
                for url in variant_urls:
                    assert (await cdn.get(url)).status_code == 404
            response = await client.post(
                "/api/v1/requests",
                data={"name": "Test", "phone": "123"},
                files=[("file", (f"{index}.pdf", b"%PDF-1.4\nx")) for index in range(4)],
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
            for item_id in (media_id, *attachment_ids, *note_attachment_ids):
                if item_id:
                    stmt = delete(Media).where(Media.id == item_id)
                    await db.execute(stmt)
            await db.commit()
        if media_id:
            for suffix in ("", "/240.webp", "/800.webp"):
                await storage.delete(
                    storage_settings.s3_public_bucket, f"catalog/{media_id}{suffix}"
                )
        for attachment_id in (*attachment_ids, *note_attachment_ids):
            await storage.delete(storage_settings.s3_private_bucket, f"requests/{attachment_id}")
        for bucket in created:
            storage.client.delete_bucket(Bucket=bucket)


async def test_catalog_policy_is_applied_outside_startup(database, settings, monkeypatch):  # noqa: F811
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
        endpoint = storage_settings.s3_endpoint_url
        private_url = f"{endpoint}/{storage_settings.s3_private_bucket}/test/file"
        public_url = f"{endpoint}/{storage_settings.s3_public_bucket}/test/file"
        async with httpx.AsyncClient(trust_env=False) as client:
            async with app.router.lifespan_context(app):
                assert (await client.get(private_url)).status_code == 403
                assert (await client.get(public_url)).status_code == 403

            storage_configure.main()
            assert (await client.get(private_url)).status_code == 403
            response = await client.get(public_url)
            assert response.status_code == 200
            assert response.content == b"test"
            for bucket in buckets:
                unauthorized_write = await client.put(
                    f"{endpoint}/{bucket}/test/other", content=b"test"
                )
                assert unauthorized_write.status_code == 403
                unauthorized_delete = await client.delete(f"{endpoint}/{bucket}/test/file")
                assert unauthorized_delete.status_code == 403
    finally:
        for bucket in created:
            storage.client.delete_object(Bucket=bucket, Key="test/file")
            storage.client.delete_bucket(Bucket=bucket)
