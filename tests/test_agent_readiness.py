from __future__ import annotations

from services.agent_resources import (
    AGENT_SCHEMA_VERSION,
    build_agent_openapi_document,
    build_agent_site_manifest,
)


BASE_URL = "https://radarbds.vn"


def test_site_manifest_is_read_only_and_points_to_canonical_resources():
    manifest = build_agent_site_manifest(base_url=f"{BASE_URL}/")

    assert manifest["schema_version"] == AGENT_SCHEMA_VERSION
    assert manifest["site"]["url"] == BASE_URL
    assert manifest["markets"]["primary"] == ["Thủ Dầu Một", "Bến Cát"]
    assert manifest["capabilities"] == [
        {
            "id": "find_signals",
            "method": "GET",
            "url": f"{BASE_URL}/api/signals",
        },
        {
            "id": "count_signals",
            "method": "GET",
            "url": f"{BASE_URL}/api/counts",
        },
    ]
    assert manifest["discovery"]["openapi"] == (
        f"{BASE_URL}/agent/openapi.json"
    )
    assert manifest["usage"]["recommended_query"] == {
        "include_total": 0,
        "limit": 30,
        "sort": "score_desc",
    }
    assert manifest["usage"]["guest_rules"]["effective_mos_min"] == 15
    assert manifest["usage"]["guest_rules"]["mos_min_override"] == "ignored"
    assert manifest["usage"]["guest_rules"]["only_drops"] == "ignored"
    assert set(manifest["not_supported"]) >= {
        "authentication",
        "favorites",
        "lead_submission",
        "phone_numbers",
        "original_listing_urls",
        "write_actions",
    }


def test_openapi_exposes_only_guest_safe_get_operations():
    document = build_agent_openapi_document(base_url=f"{BASE_URL}/")

    assert document["openapi"] == "3.1.0"
    assert document["servers"] == [{"url": BASE_URL}]
    assert set(document["paths"]) == {"/api/signals", "/api/counts"}
    assert all(
        set(path_item) == {"get"}
        for path_item in document["paths"].values()
    )
    assert "security" not in document
    assert "securitySchemes" not in document.get("components", {})

    signals_get = document["paths"]["/api/signals"]["get"]
    parameter_names = {
        parameter["name"] for parameter in signals_get["parameters"]
    }
    assert {
        "city",
        "ward",
        "source",
        "prop_type",
        "area_min",
        "area_max",
        "price_min",
        "price_max",
        "q",
        "date_range",
        "page",
        "limit",
        "sort",
        "include_total",
    } <= parameter_names
    assert signals_get["x-radar-guest-rules"] == {
        "effective_mos_min": 15,
        "mos_min_override": "ignored",
        "only_drops": "ignored",
    }
    assert signals_get["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/SignalPage"}


def test_discovery_documents_do_not_advertise_private_or_write_surfaces():
    combined = repr(
        {
            "manifest": build_agent_site_manifest(base_url=BASE_URL),
            "openapi": build_agent_openapi_document(base_url=BASE_URL),
        }
    ).lower()

    for forbidden in (
        "post",
        "patch",
        "delete",
        "authorization",
        "contact_phone",
        "seller_name",
        "source_url",
        "/api/admin",
        "/api/favorites",
    ):
        assert forbidden not in combined
