"""Cache licensed source snapshots used by downloadable map products."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from .models import MapSource


_REPO_ROOT = Path(__file__).resolve().parents[1]
_USER_AGENT = "Radar BDS Map Product Builder/1.0 (+https://radarbds.vn)"
_JSON_SOURCE_KEYS = {
    "current_boundaries",
    "legacy_boundaries",
    "legacy_ward_centers",
    "osm_detail",
}


def _http_get(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": _USER_AGENT})
    with urlopen(request, timeout=60) as response:
        return response.read()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _cache_suffix(source: MapSource) -> str:
    suffix = Path(urlparse(source.source_url).path).suffix.lower()
    if source.key in _JSON_SOURCE_KEYS:
        return (
            ".geojson"
            if source.key in {
                "current_boundaries",
                "legacy_boundaries",
                "legacy_ward_centers",
            }
            else ".json"
        )
    return suffix if suffix and len(suffix) <= 8 else ".bin"


def _cache_path(cache_dir: Path, source: MapSource) -> Path:
    return cache_dir / f"{source.key}{_cache_suffix(source)}"


def _repo_source_path(source: MapSource) -> Path:
    path = Path(source.source_url)
    return path if path.is_absolute() else _REPO_ROOT / path


def _validate_dated_query(source: MapSource) -> None:
    if source.snapshot_strategy != "dated_query":
        return
    decoded_url = unquote(source.source_url)
    marker = f'[date:"{source.snapshot_at}"]'
    if marker not in decoded_url:
        raise ValueError(
            f"{source.key} dated query does not contain recorded timestamp "
            f"{source.snapshot_at}"
        )


def _validate_payload(source: MapSource, payload: bytes) -> None:
    if not payload:
        raise ValueError(f"{source.key} returned an empty payload")
    if source.key not in _JSON_SOURCE_KEYS:
        return
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source.key} returned invalid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{source.key} JSON root must be an object")
    if "remark" in document:
        raise ValueError(f"{source.key} Overpass failure: {document['remark']}")
    if source.key in {
        "current_boundaries",
        "legacy_boundaries",
        "legacy_ward_centers",
    }:
        if document.get("type") != "FeatureCollection" or not isinstance(
            document.get("features"), list
        ):
            raise ValueError(
                f"{source.key} must be a GeoJSON FeatureCollection"
            )
    elif not isinstance(document.get("elements"), list):
        raise ValueError(f"{source.key} must contain an Overpass elements array")


def _read_existing_manifest(cache_dir: Path) -> dict[str, dict]:
    path = cache_dir / "source-snapshots.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _metadata(
    source: MapSource,
    payload: bytes,
    *,
    fetched_timestamp: str,
) -> dict:
    return {
        "url": source.source_url,
        "fetched_timestamp": fetched_timestamp,
        "byte_length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "license": source.license_name,
        "license_url": source.license_url,
        "query_timestamp": (
            source.snapshot_at
            if source.snapshot_strategy == "dated_query"
            else None
        ),
    }


def _cache_record_matches_source(
    source: MapSource,
    payload: bytes,
    record: object,
) -> bool:
    if not isinstance(record, dict):
        return False
    expected_query_timestamp = (
        source.snapshot_at
        if source.snapshot_strategy == "dated_query"
        else None
    )
    return (
        record.get("url") == source.source_url
        and record.get("query_timestamp") == expected_query_timestamp
        and record.get("license") == source.license_name
        and record.get("license_url") == source.license_url
        and record.get("byte_length") == len(payload)
        and record.get("sha256") == hashlib.sha256(payload).hexdigest()
        and isinstance(record.get("fetched_timestamp"), str)
    )


def fetch_source_snapshots(
    registry: tuple[MapSource, ...],
    cache_dir: Path,
    *,
    refresh: bool = False,
    http_get: Callable[[str], bytes] = _http_get,
) -> dict[str, Path]:
    """Fetch licensed inputs cache-first and atomically freeze their bytes."""

    if not registry:
        raise ValueError("source registry cannot be empty")
    if len({source.key for source in registry}) != len(registry):
        raise ValueError("source registry contains duplicate keys")

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    existing_manifest = _read_existing_manifest(cache_dir)
    staged_payloads: dict[str, bytes] = {}
    snapshot_paths: dict[str, Path] = {}
    fetched_timestamps: dict[str, str] = {}

    for source in registry:
        _validate_dated_query(source)
        snapshot_path = _cache_path(cache_dir, source)
        snapshot_paths[source.key] = snapshot_path

        cached_payload: bytes | None = None
        if snapshot_path.exists():
            try:
                candidate = snapshot_path.read_bytes()
                _validate_payload(source, candidate)
                if _cache_record_matches_source(
                    source,
                    candidate,
                    existing_manifest.get(source.key),
                ):
                    cached_payload = candidate
            except (OSError, ValueError):
                cached_payload = None

        if cached_payload is not None and not refresh:
            staged_payloads[source.key] = cached_payload
            fetched_timestamps[source.key] = existing_manifest[source.key][
                "fetched_timestamp"
            ]
            continue

        try:
            if source.snapshot_strategy == "repo_snapshot":
                payload = _repo_source_path(source).read_bytes()
            else:
                payload = http_get(source.source_url)
            _validate_payload(source, payload)
        except Exception as exc:
            raise ValueError(f"Unable to fetch valid {source.key}: {exc}") from exc
        staged_payloads[source.key] = payload
        fetched_timestamps[source.key] = _utc_now()

    for source in registry:
        path = snapshot_paths[source.key]
        payload = staged_payloads[source.key]
        if not path.exists() or path.read_bytes() != payload:
            _atomic_write(path, payload)

    manifest = {
        source.key: _metadata(
            source,
            staged_payloads[source.key],
            fetched_timestamp=fetched_timestamps[source.key],
        )
        for source in registry
    }
    manifest_payload = (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_write(cache_dir / "source-snapshots.json", manifest_payload)
    return snapshot_paths
