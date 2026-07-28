"""Immutable digital-product registry and protected release availability."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 64 * 1024
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
    manifest_sha256: str


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
    manifest_sha256=(
        "fa2bf2a45d9bdafd1a40514839e91b5fdbf61106a652ce7127d62dd3b5a01d8a"
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


def _windows_file_change_time(path: Path) -> int | None:
    """Return NTFS FileBasicInfo.ChangeTime, or None when it cannot be trusted."""
    if os.name != "nt":
        return None

    import ctypes
    from ctypes import wintypes

    class FileBasicInfo(ctypes.Structure):
        _fields_ = (
            ("CreationTime", ctypes.c_longlong),
            ("LastAccessTime", ctypes.c_longlong),
            ("LastWriteTime", ctypes.c_longlong),
            ("ChangeTime", ctypes.c_longlong),
            ("FileAttributes", wintypes.DWORD),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    get_file_information = kernel32.GetFileInformationByHandleEx
    get_file_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    get_file_information.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    file_read_attributes = 0x0080
    file_share_all = 0x0001 | 0x0002 | 0x0004
    open_existing = 3
    file_basic_info_class = 0
    invalid_handle_value = ctypes.c_void_p(-1).value

    handle = create_file(
        str(path),
        file_read_attributes,
        file_share_all,
        None,
        open_existing,
        0,
        None,
    )
    if handle in (None, invalid_handle_value):
        return None
    try:
        info = FileBasicInfo()
        if not get_file_information(
            handle,
            file_basic_info_class,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            return None
        return int(info.ChangeTime)
    finally:
        close_handle(handle)


def _file_fingerprint(path: Path) -> tuple[int, int, int, int, int] | None:
    """Build a cache-safe fingerprint or return None to force ZIP revalidation.

    POSIX ``st_ctime_ns`` is inode change time. Python exposes creation time as
    ``st_ctime`` on Windows, so Windows must use NTFS FileBasicInfo.ChangeTime.
    If that native query is unavailable, callers deliberately bypass the cache.
    """
    stat = path.stat()
    change_time = (
        _windows_file_change_time(path)
        if os.name == "nt"
        else stat.st_ctime_ns
    )
    if change_time is None:
        return None
    return (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        change_time,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as package_file:
        for chunk in iter(lambda: package_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest_bytes(path: Path) -> bytes:
    with path.open("rb") as manifest_file:
        payload = manifest_file.read(_MAX_MANIFEST_BYTES + 1)
    if len(payload) > _MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds protected size limit")
    return payload


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
    package_path_text: str,
    package_fingerprint: tuple[int, int, int, int, int],
    manifest_digest: str,
    product: DigitalProduct,
) -> bool:
    del package_fingerprint, manifest_digest
    return _package_matches_product(package_path_text, product)


def _package_matches_product(
    package_path_text: str,
    product: DigitalProduct,
) -> bool:
    trusted_checksum = product.package_sha256.lower()
    if _SHA256_PATTERN.fullmatch(trusted_checksum) is None:
        return False

    package_path = Path(package_path_text)
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
        manifest_payload = _read_manifest_bytes(manifest_path)
        manifest_digest = hashlib.sha256(manifest_payload).hexdigest()
        trusted_manifest_digest = product.manifest_sha256.lower()
        if (
            _SHA256_PATTERN.fullmatch(trusted_manifest_digest) is None
            or not hmac.compare_digest(manifest_digest, trusted_manifest_digest)
        ):
            raise ValueError("untrusted release manifest")
        manifest = json.loads(manifest_payload.decode("utf-8"))
        if not _manifest_matches_product(manifest, product):
            raise ValueError("invalid release manifest identity or file set")
        package_fingerprint = _file_fingerprint(package_path)
        if package_fingerprint is None:
            package_valid = _package_matches_product(str(package_path), product)
        else:
            package_valid = _validate_release_fingerprint(
                str(package_path),
                package_fingerprint,
                manifest_digest,
                product,
            )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
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
