from __future__ import annotations

import copy
import hashlib
import hmac
import math
import re
from collections.abc import Mapping
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from config.listing_map import LISTING_MAP_BOUNDS


PLANNING_MANIFEST_VERSION = "2026-07-29-v1"
PLANNING_PUBLIC_PATH_PREFIX = "/static/maps/listing-planning/"

REQUIRED_PLANNING_LAYER_IDS = (
    "land-use-thu-dau-mot",
    "land-use-ben-cat",
    "construction-thu-dau-mot",
    "construction-ben-cat",
)
ALLOWED_PLANNING_SOURCE_HOSTS = frozenset(
    {
        "qhkt.hochiminhcity.gov.vn",
        "www.qhkt.hochiminhcity.gov.vn",
        "gisxaydung.tphcm.gov.vn",
        "bencat.binhduong.gov.vn",
        "thudaumot.binhduong.gov.vn",
        "www.binhduong.gov.vn",
        "congbao.binhduong.gov.vn",
        "s3.hcm-1.cloud.cmctelecom.vn",
    }
)
SUPPORTED_PLANNING_AREAS = ("Thủ Dầu Một", "Bến Cát")

_EXPECTED_LAYER_FIELDS = {
    "land-use-thu-dau-mot": ("land_use", "Thủ Dầu Một"),
    "land-use-ben-cat": ("land_use", "Bến Cát"),
    "construction-thu-dau-mot": ("construction", "Thủ Dầu Một"),
    "construction-ben-cat": ("construction", "Bến Cát"),
}
_ALLOWED_CATEGORIES = frozenset({"land_use", "construction"})
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _required_text(record: Mapping, field: str, layer_id: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{layer_id}: {field} is required")
    return value.strip()


def _finite_number(record: Mapping, field: str, layer_id: str) -> float:
    value = record.get(field)
    if isinstance(value, bool):
        raise ValueError(f"{layer_id}: {field} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{layer_id}: {field} must be a finite number"
        ) from exc
    if not math.isfinite(result):
        raise ValueError(f"{layer_id}: {field} must be a finite number")
    return result


def _validate_source_url(record: Mapping, layer_id: str) -> str:
    source_url = _required_text(record, "source_url", layer_id)
    parsed = urlsplit(source_url)
    if parsed.scheme != "https":
        raise ValueError(f"{layer_id}: source_url must use HTTPS")
    if parsed.username or parsed.password:
        raise ValueError(f"{layer_id}: source_url cannot contain credentials")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{layer_id}: source_url has an invalid port") from exc
    if port not in (None, 443):
        raise ValueError(f"{layer_id}: source_url port is not allowed")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname not in ALLOWED_PLANNING_SOURCE_HOSTS:
        raise ValueError(f"{layer_id}: source host is not allowlisted")
    return source_url


def _resolve_public_file(
    record: Mapping,
    field: str,
    layer_id: str,
    static_root: Path,
) -> tuple[str, Path]:
    public_path = _required_text(record, field, layer_id)
    decoded_path = unquote(public_path)
    if (
        decoded_path != public_path
        or "\\" in public_path
        or "?" in public_path
        or "#" in public_path
        or not public_path.startswith(PLANNING_PUBLIC_PATH_PREFIX)
    ):
        raise ValueError(
            f"{layer_id}: {field} must stay under "
            f"{PLANNING_PUBLIC_PATH_PREFIX}"
        )

    posix_path = PurePosixPath(public_path)
    if (
        ".." in posix_path.parts
        or posix_path.suffix.lower() != ".webp"
        or posix_path.name in {"", ".", ".."}
    ):
        raise ValueError(f"{layer_id}: {field} is invalid")

    root = Path(static_root).resolve()
    relative_path = PurePosixPath(
        public_path.removeprefix("/static/")
    )
    resolved_path = root.joinpath(*relative_path.parts).resolve()
    try:
        resolved_path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{layer_id}: {field} escapes static_root") from exc
    return public_path, resolved_path


def _validate_hash(
    record: Mapping,
    field: str,
    layer_id: str,
    path: Path,
    *,
    verify_files: bool,
) -> str:
    expected = record.get(field)
    if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
        raise ValueError(f"{layer_id}: {field} must be a SHA-256 hex digest")
    expected = expected.lower()
    if not verify_files:
        return expected
    if not path.is_file():
        path_field = field.removesuffix("_sha256") + "_path"
        raise ValueError(f"{layer_id}: {path_field} file is missing")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise ValueError(f"{layer_id}: {field} mismatch")
    return expected


def _validate_bounds(record: Mapping, layer_id: str) -> list[list[float]]:
    bounds = record.get("bounds")
    if (
        not isinstance(bounds, (list, tuple))
        or len(bounds) != 2
        or any(
            not isinstance(point, (list, tuple)) or len(point) != 2
            for point in bounds
        )
    ):
        raise ValueError(f"{layer_id}: bounds must contain SW and NE points")
    try:
        south, west = (
            float(bounds[0][0]),
            float(bounds[0][1]),
        )
        north, east = (
            float(bounds[1][0]),
            float(bounds[1][1]),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{layer_id}: bounds must be numeric") from exc
    if not all(math.isfinite(value) for value in (south, west, north, east)):
        raise ValueError(f"{layer_id}: bounds must be finite")
    if south >= north or west >= east:
        raise ValueError(f"{layer_id}: bounds are inverted")

    (service_south, service_west), (service_north, service_east) = (
        LISTING_MAP_BOUNDS
    )
    if (
        south < service_south
        or west < service_west
        or north > service_north
        or east > service_east
    ):
        raise ValueError(f"{layer_id}: bounds fall outside the service area")
    return [[south, west], [north, east]]


def _validate_layer(
    source: Mapping,
    static_root: Path,
    *,
    verify_files: bool,
) -> dict:
    layer_id = source["id"]
    category = source.get("category")
    if category not in _ALLOWED_CATEGORIES:
        raise ValueError(f"{layer_id}: invalid category")
    area = source.get("area")
    if area not in SUPPORTED_PLANNING_AREAS:
        raise ValueError(f"{layer_id}: unsupported area")
    expected_category, expected_area = _EXPECTED_LAYER_FIELDS[layer_id]
    if category != expected_category or area != expected_area:
        raise ValueError(f"{layer_id}: category or area does not match its ID")

    result = copy.deepcopy(dict(source))
    result["source_url"] = _validate_source_url(source, layer_id)
    for field in (
        "approval_decision",
        "effective_period",
        "attribution",
    ):
        result[field] = _required_text(source, field, layer_id)

    approval_date = _required_text(source, "approval_date", layer_id)
    try:
        parsed_date = date.fromisoformat(approval_date)
    except ValueError as exc:
        raise ValueError(
            f"{layer_id}: approval_date must use ISO YYYY-MM-DD"
        ) from exc
    if approval_date != parsed_date.isoformat():
        raise ValueError(
            f"{layer_id}: approval_date must use ISO YYYY-MM-DD"
        )
    result["approval_date"] = approval_date

    map_scale = _finite_number(source, "map_scale", layer_id)
    if map_scale <= 0:
        raise ValueError(f"{layer_id}: map_scale must be positive")
    line_width_mm = _finite_number(source, "line_width_mm", layer_id)
    if line_width_mm <= 0:
        raise ValueError(f"{layer_id}: line_width_mm must be positive")
    result["map_scale"] = map_scale
    result["line_width_mm"] = line_width_mm

    control_point_count = source.get("control_point_count")
    if (
        isinstance(control_point_count, bool)
        or not isinstance(control_point_count, int)
        or control_point_count < 6
    ):
        raise ValueError(
            f"{layer_id}: control_point_count must be at least 6"
        )
    result["control_point_count"] = control_point_count

    rms_error_m = _finite_number(source, "rms_error_m", layer_id)
    if rms_error_m < 0:
        raise ValueError(f"{layer_id}: rms_error_m cannot be negative")
    allowed_rmse_m = min(25.0, map_scale * line_width_mm / 2000.0)
    declared_tolerance = source.get("allowed_rmse_m")
    if declared_tolerance is not None and not math.isclose(
        _finite_number(source, "allowed_rmse_m", layer_id),
        allowed_rmse_m,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise ValueError(
            f"{layer_id}: allowed_rmse_m does not match calculated tolerance"
        )
    if rms_error_m > allowed_rmse_m:
        raise ValueError(f"{layer_id}: RMSE tolerance exceeded")
    result["rms_error_m"] = rms_error_m
    result["allowed_rmse_m"] = allowed_rmse_m
    result["bounds"] = _validate_bounds(source, layer_id)

    for path_field, hash_field in (
        ("artifact_path", "artifact_sha256"),
        ("legend_path", "legend_sha256"),
    ):
        public_path, resolved_path = _resolve_public_file(
            source,
            path_field,
            layer_id,
            static_root,
        )
        result[path_field] = public_path
        result[hash_field] = _validate_hash(
            source,
            hash_field,
            layer_id,
            resolved_path,
            verify_files=verify_files,
        )
    return result


def validate_planning_manifest(
    payload: Mapping,
    static_root: Path,
    *,
    verify_files: bool = True,
) -> tuple[dict, ...]:
    """Validate and return a defensive, required-order planning manifest."""

    if not isinstance(payload, Mapping):
        raise ValueError("planning manifest must be an object")
    if payload.get("version") != PLANNING_MANIFEST_VERSION:
        raise ValueError(
            f"planning manifest version must be {PLANNING_MANIFEST_VERSION}"
        )
    layers = payload.get("layers")
    if not isinstance(layers, list):
        raise ValueError("planning manifest layers must be a list")
    if any(not isinstance(layer, Mapping) for layer in layers):
        raise ValueError("planning manifest layer must be an object")

    layer_ids = [layer.get("id") for layer in layers]
    if any(not isinstance(layer_id, str) for layer_id in layer_ids):
        raise ValueError("planning manifest layer ID must be a string")
    duplicate_ids = {
        layer_id for layer_id in layer_ids if layer_ids.count(layer_id) > 1
    }
    if duplicate_ids:
        raise ValueError(
            "duplicate layer ID: " + ", ".join(sorted(duplicate_ids))
        )
    unexpected_ids = set(layer_ids) - set(REQUIRED_PLANNING_LAYER_IDS)
    if unexpected_ids:
        raise ValueError(
            "unexpected layer ID: " + ", ".join(sorted(unexpected_ids))
        )
    missing_ids = set(REQUIRED_PLANNING_LAYER_IDS) - set(layer_ids)
    if missing_ids:
        raise ValueError(
            "missing layer ID: " + ", ".join(sorted(missing_ids))
        )

    by_id = {layer["id"]: layer for layer in layers}
    return tuple(
        _validate_layer(
            by_id[layer_id],
            Path(static_root),
            verify_files=verify_files,
        )
        for layer_id in REQUIRED_PLANNING_LAYER_IDS
    )
