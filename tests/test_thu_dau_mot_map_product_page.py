from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


PRODUCT_PATH = "/ban-do-thu-dau-mot"
PRODUCT_URL = f"https://radarbds.vn{PRODUCT_PATH}"
CURRENT_WARDS = ("Thủ Dầu Một", "Phú Lợi", "Chánh Hiệp", "Bình Dương", "Phú An")
TRACK_ACTIONS = (
    "thu_dau_mot_map_product_viewed",
    "thu_dau_mot_map_preview_selected",
    "thu_dau_mot_map_purchase_clicked",
    "thu_dau_mot_map_dashboard_clicked",
)


def _schema_graph(response) -> list[dict]:
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        response.get_data(as_text=True),
        re.S,
    )
    assert blocks
    payload = json.loads(blocks[-1])
    return payload["@graph"]


def _write_protected_release(root: Path, *, tamper: bool = False) -> Path:
    release_dir = root / "thu-dau-mot-map-bundle" / "1.0"
    release_dir.mkdir(parents=True)
    manifest = {
        "product": "radarbds-thu-dau-mot-map",
        "version": "1.0",
        "files": {
            "HUONG-DAN.pdf": {
                "byte_length": 5,
                "sha256": hashlib.sha256(b"guide").hexdigest(),
            }
        },
    }
    manifest_payload = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    (release_dir / "MANIFEST.json").write_bytes(manifest_payload)
    package = release_dir / "radarbds-thu-dau-mot-map-v1.0.zip"
    with ZipFile(package, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("HUONG-DAN.pdf", b"guide")
        archive.writestr("MANIFEST.json", manifest_payload)
    if tamper:
        (release_dir / "MANIFEST.json").write_text("{}", encoding="utf-8")
    return package


def test_runtime_product_registry_is_immutable_and_versioned():
    from services.digital_products import get_digital_product

    product = get_digital_product("thu-dau-mot-map-bundle")

    assert product.slug == "thu-dau-mot-map-bundle"
    assert product.version == "1.0"
    assert product.price_vnd == 99_000
    assert product.package_filename == "radarbds-thu-dau-mot-map-v1.0.zip"
    with pytest.raises(FrozenInstanceError):
        product.price_vnd = 1
    with pytest.raises(KeyError):
        get_digital_product("missing-product")


def test_release_availability_validates_only_the_protected_version_directory(tmp_path):
    from services.digital_products import (
        get_digital_product,
        get_release_availability,
    )

    product = get_digital_product("thu-dau-mot-map-bundle")
    _write_protected_release(tmp_path)
    availability = get_release_availability(product, tmp_path, sales_enabled=False)

    assert availability.package_valid is True
    assert availability.sales_enabled is False
    assert availability.can_sell is False
    assert availability.reason == "sales_disabled"

    tampered_root = tmp_path / "tampered"
    _write_protected_release(tampered_root, tamper=True)
    tampered = get_release_availability(product, tampered_root, sales_enabled=True)
    assert tampered.package_valid is False
    assert tampered.can_sell is False
    assert tampered.reason == "package_invalid"

    artifacts_only = tmp_path / "artifacts"
    _write_protected_release(artifacts_only)
    missing = get_release_availability(product, tmp_path / "empty", sales_enabled=True)
    assert missing.package_valid is False
    assert missing.can_sell is False


def test_product_page_is_indexable_but_checkout_is_disabled_without_sales_flag(monkeypatch):
    import app as radar_app

    monkeypatch.setenv("DIGITAL_PRODUCT_SALES_ENABLED", "0")
    response = radar_app.app.test_client().get(PRODUCT_PATH)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'<link rel="canonical" href="{PRODUCT_URL}">' in html
    assert "99.000" in html
    assert "Sắp mở bán" in html
    assert 'action="/ban-do-thu-dau-mot/checkout"' not in html
    assert "<form" not in html
    assert 'disabled aria-disabled="true"' in html
    assert "/static/images/seo/thu-dau-mot-map-before.webp" in html
    assert "/static/images/seo/thu-dau-mot-map-after.webp" in html
    lowered = html.lower()
    for leaked_suffix in (".svg", ".kml", ".zip"):
        assert leaked_suffix not in lowered
    for leaked_path in ("artifacts/", "digital_product_storage_dir", "/var/lib/"):
        assert leaked_path not in lowered


def test_product_page_states_the_exact_legacy_and_current_edition_contract():
    import app as radar_app

    html = radar_app.app.test_client().get(PRODUCT_PATH).get_data(as_text=True)

    assert (
        "Đúng 14 tâm điểm tham chiếu có nguồn, không phải ranh giới hành chính cũ."
        in html
    )
    assert (
        "Bản hiện tại có đúng 5 ranh phường đã xác minh: "
        "Thủ Dầu Một, Phú Lợi, Chánh Hiệp, Bình Dương và Phú An."
        in html
    )
    for ward in CURRENT_WARDS:
        assert ward in html
    for benefit in (
        "Hai bản PDF hoàn thiện để in A0",
        "Hai bản SVG giữ đối tượng chữ và nhóm lớp có tên để chỉnh sửa",
        "Hai bản KML để mở các lớp địa lý trong phần mềm tương thích",
        "Bộ font được phép phân phối",
        "Hướng dẫn sử dụng và giấy phép",
    ):
        assert benefit in html
    assert "Không bao gồm ranh phường cũ, ranh khu phố, bản đồ địa chính" in html
    assert "© OpenStreetMap contributors" in html


def test_product_schema_matches_visible_offer_and_stays_out_of_stock():
    import app as radar_app

    response = radar_app.app.test_client().get(PRODUCT_PATH)
    graph = _schema_graph(response)
    product = next(node for node in graph if node["@type"] == "Product")

    assert product["name"] == "Bộ bản đồ TP Thủ Dầu Một"
    assert product["sku"] == "thu-dau-mot-map-bundle-v1.0"
    assert product["offers"]["url"] == PRODUCT_URL
    assert product["offers"]["price"] == "99000"
    assert product["offers"]["priceCurrency"] == "VND"
    assert product["offers"]["availability"] == "https://schema.org/OutOfStock"
    assert "aggregateRating" not in product
    assert "review" not in product

    faq = next(node for node in graph if node["@type"] == "FAQPage")
    html = response.get_data(as_text=True)
    assert len(faq["mainEntity"]) >= 4
    for item in faq["mainEntity"]:
        assert item["name"] in html
        assert item["acceptedAnswer"]["text"] in html


def test_product_discovery_surfaces_include_one_canonical_url_and_contextual_links():
    import app as radar_app

    client = radar_app.app.test_client()
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    llms = client.get("/llms.txt").get_data(as_text=True)
    map_html = client.get("/ban-do-binh-duong").get_data(as_text=True)
    planning_html = client.get("/quy-hoach-binh-duong").get_data(as_text=True)
    product_html = client.get(PRODUCT_PATH).get_data(as_text=True)

    assert sitemap.count(f"<loc>{PRODUCT_URL}</loc>") == 1
    assert llms.count(PRODUCT_URL) == 1
    assert map_html.count(f'href="{PRODUCT_PATH}"') >= 1
    assert planning_html.count(f'href="{PRODUCT_PATH}"') >= 1
    assert product_html.count(f'href="{PRODUCT_PATH}"') >= 1
    assert "Bộ bản đồ Thủ Dầu Một" in product_html


def test_product_tracking_events_are_allowlisted_and_use_safe_context(monkeypatch):
    import app as radar_app
    from auth import core as auth_core

    recorded = []
    monkeypatch.setattr(auth_core, "current_tier", lambda: "admin")
    monkeypatch.setattr(radar_app, "log_audit", lambda **payload: recorded.append(payload))
    monkeypatch.setattr(radar_app, "current_user", lambda: None)
    monkeypatch.setattr(radar_app, "current_tier", lambda: "guest")
    client = radar_app.app.test_client()

    for action in TRACK_ACTIONS:
        assert action in radar_app.ALLOWED_TRACK_ACTIONS
        response = client.post(
            "/api/track",
            json={"action": action, "context": {"edition": "current", "source_surface": "preview"}},
        )
        assert response.status_code == 200

    assert len(recorded) == len(TRACK_ACTIONS)
    assert all(
        set(item["context"]) <= {"edition", "source_surface"} for item in recorded
    )

    javascript = Path("static/js/thu_dau_mot_map_product.js").read_text(
        encoding="utf-8"
    )
    for action in TRACK_ACTIONS[1:]:
        assert action in javascript
    for sensitive_name in (
        "package_filename",
        "package_path",
        "download_filename",
        "order_code",
        "public_id",
        "token",
    ):
        assert sensitive_name not in javascript


def test_edition_switch_updates_pressed_and_hidden_states_without_a_mouse():
    script = r"""
const product = require("./static/js/thu_dau_mot_map_product.js");
function item(value) {
  return {
    dataset: value.edition ? { productEdition: value.edition } : { productPreview: value.preview },
    hidden: false,
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; }
  };
}
const buttons = [item({edition: "legacy"}), item({edition: "current"})];
const previews = [item({preview: "legacy"}), item({preview: "current"})];
const root = {
  querySelectorAll(selector) {
    return selector === "[data-product-edition]" ? buttons : previews;
  }
};
product.setEdition(root, "current");
if (buttons[0].attrs["aria-pressed"] !== "false") process.exit(1);
if (buttons[1].attrs["aria-pressed"] !== "true") process.exit(2);
if (previews[0].hidden !== true || previews[1].hidden !== false) process.exit(3);
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
