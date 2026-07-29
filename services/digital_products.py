"""Immutable digital-product registry and protected release availability."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_PROTECTED_PACKAGE_BYTES = 64 * 1024 * 1024
def _city_map_release_files(city_slug: str) -> tuple[str, ...]:
    return (
        f"{city_slug}-truoc-2025-a0.pdf",
        f"{city_slug}-sau-2025-a0.pdf",
        f"{city_slug}-truoc-2025.svg",
        f"{city_slug}-sau-2025.svg",
        f"{city_slug}-truoc-2025.kml",
        f"{city_slug}-sau-2025.kml",
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


class ProtectedPackageUnavailable(RuntimeError):
    """The immutable protected release cannot be trusted for delivery."""


class ProtectedPackageSnapshot:
    """Immutable, non-serializable delivery bytes with a safe representation."""

    __slots__ = ("_payload", "sha256", "size")

    def __init__(self, payload: bytes):
        if type(payload) is not bytes or not payload:
            raise ProtectedPackageUnavailable()
        sha256 = hashlib.sha256(payload).hexdigest()
        object.__setattr__(self, "_payload", payload)
        object.__setattr__(self, "sha256", sha256)
        object.__setattr__(self, "size", len(payload))

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise AttributeError("ProtectedPackageSnapshot is immutable")

    def __delattr__(self, name: str) -> None:
        del name
        raise AttributeError("ProtectedPackageSnapshot is immutable")

    def __repr__(self) -> str:
        return (
            "ProtectedPackageSnapshot("
            f"size={self.size}, sha256='{self.sha256}')"
        )

    def open_bytes_io(self) -> BytesIO:
        return BytesIO(self._payload)


_THU_DAU_MOT_MAP = DigitalProduct(
    slug="thu-dau-mot-map-bundle",
    version="1.0",
    price_vnd=99_000,
    package_filename="radarbds-thu-dau-mot-map-v1.0.zip",
    download_filename="radarbds-thu-dau-mot-map-v1.0.zip",
    release_product="radarbds-thu-dau-mot-map",
    release_files=_city_map_release_files("thu-dau-mot"),
    package_sha256=(
        "afb2f735f7b153290f37a7f832bf6e31349c9310c6e4c7c47600470bd9e399da"
    ),
    manifest_sha256=(
        "cfa4451eb3473dd3bbc6d83e56ae6a3c253fdaf44e831f86a7e651995ab0b63a"
    ),
)

_THUAN_AN_MAP = DigitalProduct(
    slug="thuan-an-map-bundle",
    version="1.0",
    price_vnd=99_000,
    package_filename="radarbds-thuan-an-map-v1.0.zip",
    download_filename="radarbds-thuan-an-map-v1.0.zip",
    release_product="radarbds-thuan-an-map",
    release_files=_city_map_release_files("thuan-an"),
    package_sha256=(
        "1b54528c2309a20d7c9467f0296b2f49b85b5edcba03516733dbc57a036e479e"
    ),
    manifest_sha256=(
        "336979e7ec801204da0769e96d976a1ef0c98d9a9df5289dee92b8d225b2f044"
    ),
)

_DI_AN_MAP = DigitalProduct(
    slug="di-an-map-bundle",
    version="1.0",
    price_vnd=99_000,
    package_filename="radarbds-di-an-map-v1.0.zip",
    download_filename="radarbds-di-an-map-v1.0.zip",
    release_product="radarbds-di-an-map",
    release_files=_city_map_release_files("di-an"),
    package_sha256=(
        "6bdf6d59e60206cf6cb1df6dc36911e7e185a4b930ba3c12a4aad00740bc38a1"
    ),
    manifest_sha256=(
        "061f546f81d3a6f6a90f796c576e52a4ac20822c7ce6e2916974ad14dddc02f0"
    ),
)

_BEN_CAT_MAP = DigitalProduct(
    slug="ben-cat-map-bundle",
    version="1.0",
    price_vnd=99_000,
    package_filename="radarbds-ben-cat-map-v1.0.zip",
    download_filename="radarbds-ben-cat-map-v1.0.zip",
    release_product="radarbds-ben-cat-map",
    release_files=_city_map_release_files("ben-cat"),
    package_sha256=(
        "0ba475aa8a7e3ec65bce0ea8289d8637572f1ca49ae5d1467687529d03db819a"
    ),
    manifest_sha256=(
        "55b463346d4d192ae1b6a1827a63974aeb9926796e9fbc3ea64bd660a6081c34"
    ),
)

_PRODUCTS = {
    product.slug: product
    for product in (
        _THU_DAU_MOT_MAP,
        _THUAN_AN_MAP,
        _DI_AN_MAP,
        _BEN_CAT_MAP,
    )
}


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


def _is_single_path_component(value: object) -> bool:
    return bool(
        type(value) is str
        and value not in {"", ".", ".."}
        and Path(value).name == value
        and "/" not in value
        and "\\" not in value
    )


def _protected_storage_root_allowed(root: Path) -> bool:
    project_root = Path(__file__).resolve().parent.parent
    unsafe_roots = [project_root]
    for candidate in project_root.parents:
        if (candidate / ".git").is_dir():
            unsafe_roots.append(candidate.resolve())
            break
    return not any(
        _is_relative_to(root, unsafe_root)
        for unsafe_root in unsafe_roots
    )


def resolve_protected_package(
    product: DigitalProduct,
    storage_root: Path,
) -> Path:
    """Resolve one immutable server-registered release path and manifest."""
    try:
        root_candidate = Path(storage_root).expanduser()
        if (
            not root_candidate.is_absolute()
            or root_candidate.is_symlink()
        ):
            raise OSError("symlinked storage root")
        root = root_candidate.resolve(strict=True)
        if (
            not root.is_dir()
            or not _protected_storage_root_allowed(root)
        ):
            raise OSError("invalid storage root")
        if not all(
            _is_single_path_component(value)
            for value in (
                product.slug,
                product.version,
                product.package_filename,
            )
        ):
            raise ValueError("invalid release identity")

        product_candidate = root / product.slug
        release_candidate = product_candidate / product.version
        package_candidate = release_candidate / product.package_filename
        manifest_candidate = release_candidate / "MANIFEST.json"
        if any(
            candidate.is_symlink()
            for candidate in (
                product_candidate,
                release_candidate,
                package_candidate,
                manifest_candidate,
            )
        ):
            raise OSError("symlinked release path")

        product_dir = product_candidate.resolve(strict=True)
        release_dir = release_candidate.resolve(strict=True)
        package_path = package_candidate.resolve(strict=True)
        manifest_path = manifest_candidate.resolve(strict=True)
        if (
            not _is_relative_to(product_dir, root)
            or not _is_relative_to(release_dir, product_dir)
            or not _is_relative_to(package_path, release_dir)
            or not _is_relative_to(manifest_path, release_dir)
            or package_path.name != product.package_filename
            or manifest_path.name != "MANIFEST.json"
            or not package_path.is_file()
            or not manifest_path.is_file()
        ):
            raise OSError("invalid release path")

        manifest_payload = _read_manifest_bytes(manifest_path)
        manifest_digest = hashlib.sha256(manifest_payload).hexdigest()
        trusted_manifest_digest = product.manifest_sha256.lower()
        if (
            _SHA256_PATTERN.fullmatch(trusted_manifest_digest) is None
            or not hmac.compare_digest(
                manifest_digest,
                trusted_manifest_digest,
            )
        ):
            raise ValueError("untrusted release manifest")
        manifest = json.loads(manifest_payload.decode("utf-8"))
        if not _manifest_matches_product(manifest, product):
            raise ValueError("invalid release manifest")

        if package_path.stat().st_size <= 0:
            raise OSError("empty package")
        return package_path
    except (
        OSError,
        RuntimeError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise ProtectedPackageUnavailable() from exc


def snapshot_protected_package(
    product: DigitalProduct,
    storage_root: Path,
) -> ProtectedPackageSnapshot:
    """Read and hash the exact bounded bytes that will be delivered."""
    try:
        package_path = resolve_protected_package(product, storage_root)
        with package_path.open("rb") as package_file:
            file_size = os.fstat(package_file.fileno()).st_size
            if (
                file_size <= 0
                or file_size > _MAX_PROTECTED_PACKAGE_BYTES
            ):
                raise OSError("protected package exceeds delivery cap")
            payload = package_file.read(_MAX_PROTECTED_PACKAGE_BYTES + 1)
        if (
            not payload
            or len(payload) > _MAX_PROTECTED_PACKAGE_BYTES
            or len(payload) != file_size
        ):
            raise OSError("protected package changed during snapshot")

        snapshot = ProtectedPackageSnapshot(payload)
        trusted_package_digest = product.package_sha256.lower()
        if (
            _SHA256_PATTERN.fullmatch(trusted_package_digest) is None
            or not hmac.compare_digest(
                snapshot.sha256,
                trusted_package_digest,
            )
        ):
            raise ValueError("untrusted protected package")
        return snapshot
    except ProtectedPackageUnavailable:
        raise
    except (
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        raise ProtectedPackageUnavailable() from exc


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
