"""Immutable digital-product registry and protected release availability."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_THU_DAU_MOT_RELEASE_FILES = (
    "thu-dau-mot-truoc-2025-a0.pdf",
    "thu-dau-mot-sau-2025-a0.pdf",
    "thu-dau-mot-truoc-2025.svg",
    "thu-dau-mot-sau-2025.svg",
    "thu-dau-mot-truoc-2025.kml",
    "thu-dau-mot-sau-2025.kml",
    "fonts/BeVietnamPro-Regular.ttf",
    "fonts/BeVietnamPro-SemiBold.ttf",
    "fonts/OFL.txt",
    "HUONG-DAN.pdf",
    "GIAY-PHEP.txt",
)


@dataclass(frozen=True)
class DigitalProduct:
    slug: str
    version: str
    price_vnd: int
    package_filename: str
    download_filename: str
    release_product: str
    release_files: tuple[str, ...]
    package_sha256: str


@dataclass(frozen=True)
class ProductAvailability:
    package_valid: bool
    sales_enabled: bool
    can_sell: bool
    reason: str


_THU_DAU_MOT_MAP = DigitalProduct(
    slug="thu-dau-mot-map-bundle",
    version="1.0",
    price_vnd=99_000,
    package_filename="radarbds-thu-dau-mot-map-v1.0.zip",
    download_filename="radarbds-thu-dau-mot-map-v1.0.zip",
    release_product="radarbds-thu-dau-mot-map",
    release_files=_THU_DAU_MOT_RELEASE_FILES,
    package_sha256=(
        "a6516a441afd26463f035ec26aa115ec249284e7f60f22fd2840586207f48fd5"
    ),
)

_PRODUCTS = {_THU_DAU_MOT_MAP.slug: _THU_DAU_MOT_MAP}


def get_digital_product(slug: str) -> DigitalProduct:
    """Return one immutable product definition."""
    normalized = str(slug or "").strip()
    if normalized not in _PRODUCTS:
        raise KeyError(normalized)
    return _PRODUCTS[normalized]


def _is_relative_to(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _file_fingerprint(path: Path) -> tuple[int, int, int, int, int]:
    stat = path.stat()
    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as package_file:
        for chunk in iter(lambda: package_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_matches_product(manifest: object, product: DigitalProduct) -> bool:
    if not isinstance(manifest, dict):
        return False
    if manifest.get("product") != product.release_product:
        return False
    if manifest.get("version") != product.version:
        return False

    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(product.release_files):
        return False
    for name in product.release_files:
        metadata = files.get(name)
        if not isinstance(metadata, dict):
            return False
        byte_length = metadata.get("byte_length")
        checksum = metadata.get("sha256")
        if (
            isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or byte_length <= 0
            or not isinstance(checksum, str)
            or _SHA256_PATTERN.fullmatch(checksum) is None
        ):
            return False
    return True


@lru_cache(maxsize=64)
def _validate_release_fingerprint(
    manifest_path_text: str,
    package_path_text: str,
    manifest_fingerprint: tuple[int, int, int, int, int],
    package_fingerprint: tuple[int, int, int, int, int],
    product: DigitalProduct,
) -> bool:
    del manifest_fingerprint, package_fingerprint
    trusted_checksum = product.package_sha256.lower()
    if _SHA256_PATTERN.fullmatch(trusted_checksum) is None:
        return False

    manifest_path = Path(manifest_path_text)
    package_path = Path(package_path_text)
    try:
        manifest = _read_manifest(manifest_path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not _manifest_matches_product(manifest, product):
        return False

    try:
        actual_checksum = _sha256_file(package_path)
    except OSError:
        return False
    return hmac.compare_digest(actual_checksum, trusted_checksum)


def get_release_availability(
    product: DigitalProduct,
    storage_root: str | Path,
    sales_enabled: bool,
) -> ProductAvailability:
    """Validate the immutable protected release metadata and package path."""
    root = Path(storage_root).expanduser().resolve()
    release_candidate = root / product.slug / product.version
    package_candidate = release_candidate / product.package_filename
    manifest_candidate = release_candidate / "MANIFEST.json"

    package_valid = False
    try:
        if (
            release_candidate.is_symlink()
            or package_candidate.is_symlink()
            or manifest_candidate.is_symlink()
        ):
            raise OSError("symlinked release path")
        release_dir = release_candidate.resolve()
        package_path = package_candidate.resolve()
        manifest_path = manifest_candidate.resolve()
        if (
            not _is_relative_to(release_dir, root)
            or not _is_relative_to(package_path, release_dir)
            or not _is_relative_to(manifest_path, release_dir)
            or package_path.name != product.package_filename
            or not package_path.is_file()
            or not manifest_path.is_file()
        ):
            raise OSError("invalid release path")
        package_valid = _validate_release_fingerprint(
            str(manifest_path),
            str(package_path),
            _file_fingerprint(manifest_path),
            _file_fingerprint(package_path),
            product,
        )
    except OSError:
        package_valid = False

    enabled = bool(sales_enabled)
    can_sell = package_valid and enabled
    if can_sell:
        reason = "available"
    elif not package_valid:
        reason = "package_invalid"
    else:
        reason = "sales_disabled"
    return ProductAvailability(
        package_valid=package_valid,
        sales_enabled=enabled,
        can_sell=can_sell,
        reason=reason,
    )
