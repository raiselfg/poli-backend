import json
from unittest.mock import Mock

from app.storage.configure import allow_public_read


def test_public_read_keeps_existing_bucket_rules():
    existing = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ExistingRule",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:ListBucket",
                "Resource": "arn:aws:s3:::example",
            }
        ],
    }
    client = Mock()
    client.get_bucket_policy.return_value = {"Policy": json.dumps(existing)}

    allow_public_read(client, "example")

    policy = json.loads(client.put_bucket_policy.call_args.kwargs["Policy"])
    assert existing["Statement"][0] in policy["Statement"]
    assert any(
        statement.get("Action") == "s3:GetObject"
        and statement.get("Resource") == "arn:aws:s3:::example/*"
        for statement in policy["Statement"]
    )


def test_storage_uses_one_endpoint_for_client_and_file_links(monkeypatch):
    from uuid import uuid4

    from app.storage.s3 import S3Storage, StorageSettings

    values = {
        "S3_ENDPOINT_URL": "https://cdn.example.com/",
        "S3_ACCESS_KEY_ID": "test-key",
        "S3_SECRET_ACCESS_KEY": "test-secret",
        "S3_PUBLIC_BUCKET": "public",
        "S3_PRIVATE_BUCKET": "private",
    }
    monkeypatch.delenv("S3_CDN_URL", raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    storage = S3Storage(StorageSettings(_env_file=None))
    media_id = uuid4()

    assert storage.client.meta.endpoint_url.rstrip("/") == "https://cdn.example.com"
    assert storage.url("public", "catalog", media_id) == (
        f"https://cdn.example.com/public/catalog/{media_id}"
    )


def test_configure_public_read_updates_both_buckets(monkeypatch):
    from types import SimpleNamespace

    import app.storage.configure as configure

    settings = SimpleNamespace(s3_public_bucket="images", s3_private_bucket="requests")
    client = object()
    allow = Mock()
    monkeypatch.setattr(configure, "get_storage_settings", lambda: settings)
    monkeypatch.setattr(configure, "S3Storage", lambda _: SimpleNamespace(client=client))
    monkeypatch.setattr(configure, "allow_public_read", allow)

    configure.configure_public_read()

    assert allow.call_count == 2
    allow.assert_any_call(client, "images")
    allow.assert_any_call(client, "requests")
