"""Immutable digital-product registry and protected release availability."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile, ZipFile


@dataclass(frozen=True)
class DigitalProduct:
    slug: str
    version: str
    price_vnd: int
    package_filename: str
    download_filename: str


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


def _manifest_matches_archive(manifest_path: Path, package_path: Path) -> bool:
    if (
        not manifest_path.is_file()
        or manifest_path.is_symlink()
        or not package_path.is_file()
        or package_path.is_symlink()
    ):
        return False

    manifest_payload = manifest_path.read_bytes()
    manifest = json.loads(manifest_payload.decode("utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        return False

    with ZipFile(package_path) as archive:
        if archive.read("MANIFEST.json") != manifest_payload:
            return False
        archive_names = set(archive.namelist())
        if archive_names != {*files, "MANIFEST.json"}:
            return False
        for name, metadata in files.items():
            if not isinstance(metadata, dict):
                return False
            payload = archive.read(name)
            if metadata.get("byte_length") != len(payload):
                return False
            if metadata.get("sha256") != hashlib.sha256(payload).hexdigest():
                return False
    hashlib.sha256(package_path.read_bytes()).hexdigest()
    return True


def get_release_availability(
    product: DigitalProduct,
    storage_root: str | Path,
    sales_enabled: bool,
) -> ProductAvailability:
    """Validate only the immutable protected release directory for a product."""
    root = Path(storage_root).expanduser().resolve()
    release_dir = (root / product.slug / product.version).resolve()
    package_path = (release_dir / product.package_filename).resolve()
    manifest_path = (release_dir / "MANIFEST.json").resolve()

    package_valid = False
    if (
        _is_relative_to(release_dir, root)
        and _is_relative_to(package_path, release_dir)
        and _is_relative_to(manifest_path, release_dir)
        and package_path.name == product.package_filename
    ):
        try:
            package_valid = _manifest_matches_archive(manifest_path, package_path)
        except (BadZipFile, KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError):
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
