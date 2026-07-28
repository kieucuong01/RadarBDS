"""S3 helpers for listing image storage.

The public read path is intentionally string-based so hot API responses never
perform S3 HEAD/GET calls. Upload and verification paths import boto3 lazily.
"""
from __future__ import annotations

import mimetypes
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable
from urllib.parse import quote


CACHE_CONTROL_IMMUTABLE = "public, max-age=2592000, immutable"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def s3_image_storage_enabled() -> bool:
    return os.getenv("RADAR_IMAGE_STORAGE", "local").strip().lower() == "s3"


def s3_public_base_url() -> str:
    return os.getenv("RADAR_IMAGE_PUBLIC_BASE_URL", "").strip().rstrip("/")


def normalize_object_key(key: str) -> str:
    clean = str(key or "").strip().replace("\\", "/").lstrip("/")
    if not clean:
        return ""
    marker = "data/images/"
    if marker in clean:
        return clean[clean.index(marker):]
    return clean


def public_url_for_key(key: str) -> str:
    base_url = s3_public_base_url()
    object_key = normalize_object_key(key)
    if not base_url or not object_key:
        return ""
    return f"{base_url}/{quote(object_key, safe='/-_.~')}"


def content_type_for_path(path: Path) -> str:
    content_type, _encoding = mimetypes.guess_type(str(path))
    if content_type:
        return content_type
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "application/octet-stream"


@lru_cache(maxsize=1)
def s3_client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required for S3 image storage") from exc

    endpoint_url = os.getenv("RADAR_S3_ENDPOINT_URL", "").strip()
    access_key = (
        os.getenv("RADAR_S3_ACCESS_KEY_ID", "").strip()
        or os.getenv("AWS_ACCESS_KEY_ID", "").strip()
    )
    secret_key = (
        os.getenv("RADAR_S3_SECRET_ACCESS_KEY", "").strip()
        or os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
    )
    if not endpoint_url or not access_key or not secret_key:
        raise RuntimeError("S3 image storage env is incomplete")

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def s3_bucket() -> str:
    bucket = os.getenv("RADAR_S3_BUCKET", "").strip()
    if not bucket:
        raise RuntimeError("RADAR_S3_BUCKET is required for S3 image storage")
    return bucket


def s3_object_acl() -> str:
    return os.getenv("RADAR_S3_OBJECT_ACL", "public-read").strip()


def upload_file(path: Path, object_key: str) -> str:
    local_path = Path(path)
    if not local_path.is_file():
        raise FileNotFoundError(str(local_path))
    key = normalize_object_key(object_key)
    if not key:
        raise ValueError("object key is empty")

    extra_args = {
        "CacheControl": CACHE_CONTROL_IMMUTABLE,
        "ContentType": content_type_for_path(local_path),
    }
    acl = s3_object_acl()
    if acl:
        extra_args["ACL"] = acl

    with local_path.open("rb") as body:
        s3_client().put_object(
            Bucket=s3_bucket(),
            Key=key,
            Body=body,
            **extra_args,
        )
    return key


def object_exists(object_key: str) -> bool:
    key = normalize_object_key(object_key)
    if not key:
        return False
    try:
        s3_client().head_object(Bucket=s3_bucket(), Key=key)
        return True
    except Exception as exc:
        response = getattr(exc, "response", {}) or {}
        code = str((response.get("Error") or {}).get("Code") or "")
        status = int((response.get("ResponseMetadata") or {}).get("HTTPStatusCode") or 0)
        if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
            return False
        raise


def list_object_keys(prefix: str = "data/images/") -> set[str]:
    keys: set[str] = set()
    paginator = s3_client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s3_bucket(), Prefix=normalize_object_key(prefix)):
        for obj in page.get("Contents", []) or []:
            key = obj.get("Key")
            if key:
                keys.add(str(key))
    return keys


def iter_image_files(root: Path) -> Iterable[Path]:
    base = Path(root)
    if not base.is_dir():
        return
    for path in base.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            yield path
