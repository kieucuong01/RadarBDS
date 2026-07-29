import copy
import hashlib
from pathlib import Path

import pytest

from config.listing_planning import (
    REQUIRED_PLANNING_LAYER_IDS,
    validate_planning_manifest,
)


LAYER_SPECS = (
    ("land-use-thu-dau-mot", "land_use", "Thủ Dầu Một"),
    ("land-use-ben-cat", "land_use", "Bến Cát"),
    ("construction-thu-dau-mot", "construction", "Thủ Dầu Một"),
    ("construction-ben-cat", "construction", "Bến Cát"),
)


def _manifest(tmp_path: Path) -> tuple[dict, Path]:
    static_root = tmp_path / "static"
    output_dir = static_root / "maps" / "listing-planning"
    output_dir.mkdir(parents=True)
    layers = []
    for layer_id, category, area in LAYER_SPECS:
        artifact = output_dir / f"{layer_id}-v1.webp"
        legend = output_dir / f"{layer_id}-v1-legend.webp"
        artifact.write_bytes(f"overlay:{layer_id}".encode())
        legend.write_bytes(f"legend:{layer_id}".encode())
        layers.append(
            {
                "id": layer_id,
                "category": category,
                "area": area,
                "artifact_path": (
                    f"/static/maps/listing-planning/{artifact.name}"
                ),
                "legend_path": (
                    f"/static/maps/listing-planning/{legend.name}"
                ),
                "artifact_sha256": hashlib.sha256(
                    artifact.read_bytes()
                ).hexdigest(),
                "legend_sha256": hashlib.sha256(
                    legend.read_bytes()
                ).hexdigest(),
                "source_url": (
                    "https://bencat.binhduong.gov.vn/"
                    f"cong-khai-thong-tin/{layer_id}"
                ),
                "approval_decision": "04/QĐ-UBND",
                "approval_date": "2022-01-05",
                "effective_period": "2022-2030",
                "map_scale": 25_000,
                "line_width_mm": 0.5,
                "control_point_count": 8,
                "rms_error_m": 3.0,
                "bounds": [[10.80, 106.40], [11.30, 106.90]],
                "attribution": "Nguồn: cơ quan nhà nước có thẩm quyền",
            }
        )
    return {"version": "2026-07-29-v1", "layers": layers}, static_root


def test_valid_manifest_returns_required_order_without_mutating_input(tmp_path):
    payload, static_root = _manifest(tmp_path)
    payload["layers"].reverse()
    original = copy.deepcopy(payload)

    layers = validate_planning_manifest(payload, static_root)

    assert tuple(item["id"] for item in layers) == REQUIRED_PLANNING_LAYER_IDS
    assert all(item["allowed_rmse_m"] == 6.25 for item in layers)
    assert payload == original


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload["layers"].pop(), "missing layer ID"),
        (
            lambda payload: payload["layers"].append(
                copy.deepcopy(payload["layers"][0])
            ),
            "duplicate layer ID",
        ),
        (
            lambda payload: payload["layers"].append(
                {
                    **copy.deepcopy(payload["layers"][0]),
                    "id": "unexpected-layer",
                }
            ),
            "unexpected layer ID",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"category": "zoning"}
            ),
            "invalid category",
        ),
        (
            lambda payload: payload["layers"][0].update({"area": "Dĩ An"}),
            "unsupported area",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"source_url": "http://bencat.binhduong.gov.vn/map"}
            ),
            "HTTPS",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"source_url": "https://commercial-planning.example/map"}
            ),
            "source host",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"artifact_path": "/static/private/overlay.webp"}
            ),
            "artifact_path",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"legend_path": "/static/maps/listing-planning/../secret.webp"}
            ),
            "legend_path",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"artifact_sha256": "not-a-hash"}
            ),
            "artifact_sha256",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"approval_decision": ""}
            ),
            "approval_decision",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"approval_date": "05/01/2022"}
            ),
            "approval_date",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"effective_period": ""}
            ),
            "effective_period",
        ),
        (
            lambda payload: payload["layers"][0].update({"map_scale": 0}),
            "map_scale",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"control_point_count": 5}
            ),
            "control_point_count",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"rms_error_m": -0.1}
            ),
            "rms_error_m",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"rms_error_m": 7}
            ),
            "RMSE tolerance",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"bounds": [[11.2, 106.4], [11.1, 106.9]]}
            ),
            "bounds",
        ),
        (
            lambda payload: payload["layers"][0].update(
                {"bounds": [[9.0, 106.4], [11.1, 106.9]]}
            ),
            "service area",
        ),
    ],
)
def test_manifest_rejects_invalid_contract(tmp_path, mutate, message):
    payload, static_root = _manifest(tmp_path)
    mutate(payload)

    with pytest.raises(ValueError, match=message):
        validate_planning_manifest(payload, static_root)


def test_manifest_rejects_missing_overlay_or_legend(tmp_path):
    payload, static_root = _manifest(tmp_path)
    layer = payload["layers"][0]
    artifact = static_root / layer["artifact_path"].removeprefix("/static/")
    artifact.unlink()

    with pytest.raises(ValueError, match="artifact_path.*missing"):
        validate_planning_manifest(payload, static_root)

    artifact.write_bytes(b"restored")
    layer["artifact_sha256"] = hashlib.sha256(b"restored").hexdigest()
    legend = static_root / layer["legend_path"].removeprefix("/static/")
    legend.unlink()

    with pytest.raises(ValueError, match="legend_path.*missing"):
        validate_planning_manifest(payload, static_root)


@pytest.mark.parametrize("hash_field", ["artifact_sha256", "legend_sha256"])
def test_manifest_rejects_file_hash_mismatch(tmp_path, hash_field):
    payload, static_root = _manifest(tmp_path)
    payload["layers"][0][hash_field] = "0" * 64

    with pytest.raises(ValueError, match=f"{hash_field} mismatch"):
        validate_planning_manifest(payload, static_root)


def test_manifest_can_validate_shape_without_public_files(tmp_path):
    payload, static_root = _manifest(tmp_path)
    for path in static_root.rglob("*.webp"):
        path.unlink()

    layers = validate_planning_manifest(
        payload,
        static_root,
        verify_files=False,
    )

    assert len(layers) == 4
