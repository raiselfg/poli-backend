"""Check bucket availability and provide a command to configure public catalog reads."""

import json

from botocore.exceptions import ClientError

from app.storage.s3 import S3Storage, get_storage_settings

PUBLIC_READ_SID = "PoliPublicObjectRead"


def allow_public_read(client, bucket: str) -> None:
    try:
        response = client.get_bucket_policy(Bucket=bucket)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") not in {"NoSuchBucketPolicy", "404"}:
            raise
        policy = {"Version": "2012-10-17", "Statement": []}
    else:
        policy = json.loads(response["Policy"])

    statements = policy["Statement"]
    if isinstance(statements, dict):
        statements = [statements]
    statements = [statement for statement in statements if statement.get("Sid") != PUBLIC_READ_SID]
    statements.append(
        {
            "Sid": PUBLIC_READ_SID,
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{bucket}/*",
        }
    )
    policy["Statement"] = statements
    client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))


def check_buckets() -> None:
    settings = get_storage_settings()
    storage = S3Storage(settings)
    client = storage.client
    for bucket in (settings.s3_public_bucket, settings.s3_private_bucket):
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in {"NoSuchBucket", "404"}:
                raise
            raise RuntimeError(
                f"Create S3 bucket {bucket!r} before starting the application"
            ) from error


def main() -> None:
    settings = get_storage_settings()
    storage = S3Storage(settings)
    allow_public_read(storage.client, settings.s3_public_bucket)
    print("Enabled anonymous reads for the catalog bucket.")


if __name__ == "__main__":
    main()
