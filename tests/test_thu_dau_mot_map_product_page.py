from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
import subprocess
from dataclasses import FrozenInstanceError, replace
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
APPROVED_PACKAGE_SHA256 = (
    "a6516a441afd26463f035ec26aa115ec249284e7f60f22fd2840586207f48fd5"
)
APPROVED_MANIFEST_SHA256 = (
    "fa2bf2a45d9bdafd1a40514839e91b5fdbf61106a652ce7127d62dd3b5a01d8a"
)
EXPECTED_RELEASE_FILES = (
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


def _schema_graph(response) -> list[dict]:
    blocks = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        response.get_data(as_text=True),
        re.S,
    )
    assert blocks
    payload = json.loads(blocks[-1])
    return payload["@graph"]


def _visible_body_text(page_html: str) -> str:
    body_match = re.search(r"<body\b[^>]*>(.*?)</body>", page_html, re.I | re.S)
    assert body_match
    body = re.sub(
        r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>",
        " ",
        body_match.group(1),
        flags=re.I | re.S,
    )
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", body)).split())


def _write_protected_release(
    root: Path,
    *,
    manifest_product: str = "radarbds-thu-dau-mot-map",
    manifest_version: str = "1.0",
    manifest_files: tuple[str, ...] = EXPECTED_RELEASE_FILES,
    package_payload: bytes = b"trusted-test-package",
) -> Path:
    release_dir = root / "thu-dau-mot-map-bundle" / "1.0"
    release_dir.mkdir(parents=True)
    manifest = {
        "product": manifest_product,
        "version": manifest_version,
        "files": {
            name: {
                "byte_length": len(name.encode("utf-8")),
                "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
            }
            for name in manifest_files
        },
    }
    manifest_payload = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    (release_dir / "MANIFEST.json").write_bytes(manifest_payload)
    package = release_dir / "radarbds-thu-dau-mot-map-v1.0.zip"
    with ZipFile(package, "w", compression=ZIP_DEFLATED) as archive:
        for name in manifest_files:
            archive.writestr(name, name.encode("utf-8"))
        archive.writestr("MANIFEST.json", manifest_payload)
        archive.comment = package_payload
    return package


def _trust_test_release(product, package: Path):
    return replace(
        product,
        package_sha256=hashlib.sha256(package.read_bytes()).hexdigest(),
        manifest_sha256=hashlib.sha256(
            (package.parent / "MANIFEST.json").read_bytes()
        ).hexdigest(),
    )


def test_runtime_product_registry_is_immutable_and_versioned():
    from services.digital_products import get_digital_product

    product = get_digital_product("thu-dau-mot-map-bundle")

    assert product.slug == "thu-dau-mot-map-bundle"
    assert product.version == "1.0"
    assert product.price_vnd == 99_000
    assert product.package_filename == "radarbds-thu-dau-mot-map-v1.0.zip"
    assert product.release_product == "radarbds-thu-dau-mot-map"
    assert product.release_files == EXPECTED_RELEASE_FILES
    assert product.package_sha256 == APPROVED_PACKAGE_SHA256
    assert product.manifest_sha256 == APPROVED_MANIFEST_SHA256
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
    package = _write_protected_release(tmp_path)
    trusted_test_product = _trust_test_release(product, package)
    availability = get_release_availability(
        trusted_test_product,
        tmp_path,
        sales_enabled=False,
    )

    assert availability.package_valid is True
    assert availability.sales_enabled is False
    assert availability.can_sell is False
    assert availability.reason == "sales_disabled"

    artifacts_only = tmp_path / "artifacts"
    _write_protected_release(artifacts_only)
    missing = get_release_availability(product, tmp_path / "empty", sales_enabled=True)
    assert missing.package_valid is False
    assert missing.can_sell is False


@pytest.mark.parametrize(
    ("manifest_product", "manifest_version"),
    (
        ("wrong-product", "1.0"),
        ("radarbds-thu-dau-mot-map", "2.0"),
    ),
)
def test_release_gate_rejects_wrong_manifest_identity(
    tmp_path,
    manifest_product,
    manifest_version,
):
    from services.digital_products import (
        get_digital_product,
        get_release_availability,
    )

    product = get_digital_product("thu-dau-mot-map-bundle")
    package = _write_protected_release(
        tmp_path,
        manifest_product=manifest_product,
        manifest_version=manifest_version,
    )
    test_product = _trust_test_release(product, package)

    availability = get_release_availability(test_product, tmp_path, True)

    assert availability.package_valid is False
    assert availability.can_sell is False


@pytest.mark.parametrize(
    "manifest_files",
    (
        EXPECTED_RELEASE_FILES[:-1],
        (*EXPECTED_RELEASE_FILES, "EXTRA.txt"),
    ),
)
def test_release_gate_rejects_incomplete_or_extra_manifest_files(
    tmp_path,
    manifest_files,
):
    from services.digital_products import (
        get_digital_product,
        get_release_availability,
    )

    product = get_digital_product("thu-dau-mot-map-bundle")
    package = _write_protected_release(tmp_path, manifest_files=manifest_files)
    test_product = _trust_test_release(product, package)

    availability = get_release_availability(test_product, tmp_path, True)

    assert availability.package_valid is False
    assert availability.can_sell is False


def test_release_gate_rejects_self_consistent_but_untrusted_package(tmp_path):
    from services.digital_products import (
        get_digital_product,
        get_release_availability,
    )

    product = get_digital_product("thu-dau-mot-map-bundle")
    _write_protected_release(tmp_path)

    availability = get_release_availability(product, tmp_path, True)

    assert availability.package_valid is False
    assert availability.can_sell is False


@pytest.mark.parametrize("trusted_checksum", ("", "not-a-sha256", "f" * 64))
def test_release_gate_requires_the_configured_approved_checksum(
    tmp_path,
    trusted_checksum,
):
    from services.digital_products import (
        get_digital_product,
        get_release_availability,
    )

    product = replace(
        get_digital_product("thu-dau-mot-map-bundle"),
        package_sha256=trusted_checksum,
    )
    package = _write_protected_release(tmp_path)
    product = replace(
        product,
        manifest_sha256=hashlib.sha256(
            (package.parent / "MANIFEST.json").read_bytes()
        ).hexdigest(),
    )

    availability = get_release_availability(product, tmp_path, True)

    assert availability.package_valid is False
    assert availability.can_sell is False


def test_release_validation_cache_reuses_stable_zip_fingerprint_and_reads_small_manifest(
    tmp_path,
    monkeypatch,
):
    from services import digital_products

    product = digital_products.get_digital_product("thu-dau-mot-map-bundle")
    package = _write_protected_release(tmp_path)
    test_product = _trust_test_release(product, package)
    real_sha256_file = digital_products._sha256_file
    real_read_manifest_bytes = digital_products._read_manifest_bytes
    hash_calls = []
    manifest_reads = []

    def counted_sha256_file(path):
        hash_calls.append(Path(path))
        return real_sha256_file(path)

    def counted_read_manifest_bytes(path):
        manifest_reads.append(Path(path))
        return real_read_manifest_bytes(path)

    monkeypatch.setattr(digital_products, "_sha256_file", counted_sha256_file)
    monkeypatch.setattr(
        digital_products,
        "_read_manifest_bytes",
        counted_read_manifest_bytes,
    )

    first = digital_products.get_release_availability(test_product, tmp_path, True)
    second = digital_products.get_release_availability(test_product, tmp_path, True)
    original_stat = package.stat()
    with package.open("r+b") as package_file:
        package_file.seek(-1, os.SEEK_END)
        original_byte = package_file.read(1)
        package_file.seek(-1, os.SEEK_END)
        package_file.write(bytes((original_byte[0] ^ 0x01,)))
    os.utime(
        package,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    third = digital_products.get_release_availability(test_product, tmp_path, True)

    assert first.package_valid is True
    assert second.package_valid is True
    assert package.stat().st_size == original_stat.st_size
    assert package.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert len(manifest_reads) == 3
    assert len(hash_calls) == 2
    assert third.package_valid is False


def test_release_gate_rejects_same_size_same_mtime_manifest_member_mutation(
    tmp_path,
    monkeypatch,
):
    from services import digital_products

    product = digital_products.get_digital_product("thu-dau-mot-map-bundle")
    package = _write_protected_release(tmp_path)
    test_product = _trust_test_release(product, package)
    real_sha256_file = digital_products._sha256_file
    hash_calls = []

    def counted_sha256_file(path):
        hash_calls.append(Path(path))
        return real_sha256_file(path)

    monkeypatch.setattr(digital_products, "_sha256_file", counted_sha256_file)

    first = digital_products.get_release_availability(test_product, tmp_path, True)
    second = digital_products.get_release_availability(test_product, tmp_path, True)
    manifest = package.parent / "MANIFEST.json"
    original_stat = manifest.stat()
    original_payload = manifest.read_text(encoding="utf-8")
    mutated_payload = original_payload.replace(
        hashlib.sha256(EXPECTED_RELEASE_FILES[0].encode("utf-8")).hexdigest(),
        "f" * 64,
        1,
    )
    assert mutated_payload != original_payload
    assert len(mutated_payload.encode("utf-8")) == original_stat.st_size
    manifest.write_text(mutated_payload, encoding="utf-8")
    os.utime(
        manifest,
        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
    )
    third = digital_products.get_release_availability(test_product, tmp_path, True)

    assert first.package_valid is True
    assert second.package_valid is True
    assert manifest.stat().st_size == original_stat.st_size
    assert manifest.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert third.package_valid is False
    assert len(hash_calls) == 1


def test_release_gate_rejects_untrusted_manifest_digest_before_json_parse(
    tmp_path,
    monkeypatch,
):
    from services import digital_products

    product = digital_products.get_digital_product("thu-dau-mot-map-bundle")
    package = _write_protected_release(tmp_path)
    manifest = package.parent / "MANIFEST.json"
    manifest.write_bytes(b"untrusted manifest bytes")

    def fail_if_untrusted_payload_is_parsed(payload):
        raise AssertionError("untrusted manifest reached JSON parser")

    monkeypatch.setattr(
        digital_products.json,
        "loads",
        fail_if_untrusted_payload_is_parsed,
    )

    availability = digital_products.get_release_availability(
        product,
        tmp_path,
        True,
    )

    assert availability.package_valid is False
    assert availability.can_sell is False


def test_release_validation_rehashes_when_native_change_time_is_unavailable(
    tmp_path,
    monkeypatch,
):
    from services import digital_products

    product = digital_products.get_digital_product("thu-dau-mot-map-bundle")
    package = _write_protected_release(tmp_path)
    test_product = _trust_test_release(product, package)
    real_sha256_file = digital_products._sha256_file
    hash_calls = []

    def counted_sha256_file(path):
        hash_calls.append(Path(path))
        return real_sha256_file(path)

    monkeypatch.setattr(digital_products, "_sha256_file", counted_sha256_file)
    monkeypatch.setattr(digital_products, "_file_fingerprint", lambda path: None)

    first = digital_products.get_release_availability(test_product, tmp_path, True)
    second = digital_products.get_release_availability(test_product, tmp_path, True)

    assert first.package_valid is True
    assert second.package_valid is True
    assert len(hash_calls) == 2


def test_product_page_is_indexable_but_checkout_is_disabled_without_sales_flag(monkeypatch):
    import app as radar_app

    monkeypatch.setenv("DIGITAL_PRODUCT_SALES_ENABLED", "0")
    response = radar_app.app.test_client().get(PRODUCT_PATH)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert f'<link rel="canonical" href="{PRODUCT_URL}">' in html
    assert "99.000" in html
    assert "Sắp mở bán" in html
    assert html.count("Sắp mở bán") == 2
    assert 'action="/ban-do-thu-dau-mot/checkout"' not in html
    assert "<form" not in html
    disabled_purchase_buttons = re.findall(
        r"<button\b[^>]*data-product-purchase[^>]*>.*?</button>",
        html,
        re.I | re.S,
    )
    assert len(disabled_purchase_buttons) == 2
    assert all("disabled" in button and 'aria-disabled="true"' in button for button in disabled_purchase_buttons)
    assert html.rfind("data-product-purchase") > html.index('id="cau-hoi-thuong-gap"')
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
        "Tệp font được phép phân phối và giấy phép font",
        "Tệp hướng dẫn sử dụng và giấy phép sản phẩm",
        "Tệp MANIFEST và mã checksum để kiểm tra tính toàn vẹn",
    ):
        assert benefit in html
    assert "Không bao gồm ranh phường cũ, ranh khu phố, bản đồ địa chính" in html
    assert "© OpenStreetMap contributors" in html


def test_product_page_replaces_internal_map_jargon_with_clear_vietnamese():
    import app as radar_app

    html = radar_app.app.test_client().get(PRODUCT_PATH).get_data(as_text=True)
    visible_text = _visible_body_text(html)

    for internal_term in (
        "bundle",
        "preview",
        "raster",
        "legacy",
        "geometry",
        "Polygon",
        "MultiPolygon",
    ):
        assert re.search(rf"\b{internal_term}\b", visible_text, re.I) is None
    for public_format in ("PDF", "SVG", "KML"):
        assert public_format in visible_text


def test_product_source_and_breadcrumb_links_have_touch_target_hooks():
    import app as radar_app

    html = radar_app.app.test_client().get(PRODUCT_PATH).get_data(as_text=True)
    css = Path("static/css/thu_dau_mot_map_product.css").read_text(encoding="utf-8")

    assert 'data-product-source-link' in html
    assert 'data-product-breadcrumb-link' in html
    assert ".tdm-product-source-link" in css
    assert "[data-product-breadcrumb-link]" in css
    assert "min-height: 44px" in css


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


def test_product_tracking_server_drops_sensitive_and_unexpected_context(monkeypatch):
    import app as radar_app
    from auth import core as auth_core

    recorded = []
    monkeypatch.setattr(auth_core, "current_tier", lambda: "admin")
    monkeypatch.setattr(radar_app, "log_audit", lambda **payload: recorded.append(payload))
    monkeypatch.setattr(radar_app, "current_user", lambda: None)
    monkeypatch.setattr(radar_app, "current_tier", lambda: "guest")
    client = radar_app.app.test_client()
    safe_context = {
        "edition": "current",
        "source_surface": "preview_switch",
        "path": PRODUCT_PATH,
        "page_slug": "ban-do-thu-dau-mot",
        "page_title": "Bộ bản đồ TP Thủ Dầu Một",
    }
    forbidden_context = {
        "token": "secret",
        "package_path": "protected/location",
        "filename": "paid-file",
        "order_code": "ORDER-123",
        "public_id": "public-secret",
        "unexpected": {"raw": "value"},
    }

    for action in TRACK_ACTIONS:
        response = client.post(
            "/api/track",
            json={
                "action": action,
                "listing_id": 123,
                "context": {**safe_context, **forbidden_context},
            },
        )
        assert response.status_code == 200

    assert len(recorded) == len(TRACK_ACTIONS)
    assert all(item["context"] == safe_context for item in recorded)
    assert all(item["listing_id"] is None for item in recorded)


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


def test_order_template_has_accessible_vietqr_and_download_contract():
    import app as radar_app

    response = radar_app.app.test_client().get(
        "/ban-do-thu-dau-mot/don-hang/" + ("a" * 32)
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.count('aria-live="polite"') == 1
    assert "data-order-qr" in html
    assert "data-order-download" in html
    assert "data-order-copy" in html
    assert "data-order-new" in html
    assert "data-order-public-id" in html
    assert "thu_dau_mot_map_checkout.js" in html
    assert "seo_tracking.html" not in html
    assert "googletagmanager.com" not in html
    assert "99.000đ" in html


def test_order_styles_enforce_mobile_qr_touch_focus_and_reduced_motion():
    css = Path("static/css/thu_dau_mot_map_product.css").read_text(
        encoding="utf-8"
    )

    assert "min(78vw, 296px)" in css
    assert "min-height: 44px" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
