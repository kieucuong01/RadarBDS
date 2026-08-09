# Read-only AI Agent Discovery Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a small, stable, machine-readable contract that lets an AI agent discover Radar BDS, search and filter public signals, compare returned candidates, and cite or open the canonical signal detail page without gaining any write capability or private data.

**Architecture:** Add two deterministic JSON documents generated from pure Python builders, expose them through thin public Flask routes, and link them from the existing `llms.txt` and crawler policy. The contract documents only the existing Guest-safe `/api/signals` and `/api/counts` read paths; it does not create a database query, authentication flow, action endpoint, or alternate signal-quality rule.

**Tech Stack:** Python 3.12, Flask, pytest, OpenAPI 3.1 JSON, existing Radar BDS public API/cache/redaction helpers.

## Global Constraints

- The agent surface is read-only. Do not add `POST`, `PUT`, `PATCH`, or `DELETE` operations.
- Do not expose authentication, saved searches, favorites, watchlists, lead submission, checkout, telephone numbers, seller names, original listing URLs, admin URLs, or private/session endpoints.
- `/api/signals` remains the sole signal-card query. It must continue to use current filter bounds, actionable-signal SQL, tier redaction, cache keys, dataset versions, and backpressure.
- `/api/counts` remains the current shared filtered count. Do not recreate a signal count or latest-valuation query in the discovery layer.
- Describe Guest behavior truthfully: the effective minimum margin of safety is 15%, an attempted Guest `mos_min` override is ignored, and `only_drops` is ignored for Guest.
- Describe only current production sources (`facebook`, `guland`). Do not reintroduce BatDongSan.
- The discovery documents must be deterministic and database-free.
- Keep `.playwright-cli/` and all unrelated dirty files untouched. Stage only files named in the active task.

---

## Task 1: Define and lock the pure discovery documents

**Files:**

- Create: `services/agent_resources.py`
- Create: `tests/test_agent_readiness.py`

**Interfaces:**

- Consumes: `base_url: str`, supplied from the existing `PUBLIC_BASE_URL` configuration.
- Produces: `build_agent_site_manifest(*, base_url: str) -> dict[str, object]`.
- Produces: `build_agent_openapi_document(*, base_url: str) -> dict[str, object]`.
- Produces constants `AGENT_SCHEMA_VERSION = "1.0"` and `AGENT_CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=86400"`.
- Must not consume: Flask request state, `get_conn()`, Redis, session state, environment secrets, or live listing rows.

- [ ] Write failing builder-contract tests in `tests/test_agent_readiness.py`:

```python
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
    assert manifest["discovery"]["openapi"] == f"{BASE_URL}/agent/openapi.json"
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
    assert all(set(path_item) == {"get"} for path_item in document["paths"].values())
    assert "security" not in document
    assert "securitySchemes" not in document.get("components", {})

    signals_get = document["paths"]["/api/signals"]["get"]
    parameter_names = {parameter["name"] for parameter in signals_get["parameters"]}
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
    assert signals_get["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SignalPage"
    }


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
```

- [ ] Run the test and confirm it fails because `services.agent_resources` does not exist:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_agent_readiness.py -q
```

- [ ] Create `services/agent_resources.py` with a trailing-slash normalizer and the two deterministic builders. Use these exact top-level shapes and values:

```python
from __future__ import annotations

from typing import Any


AGENT_SCHEMA_VERSION = "1.0"
AGENT_CACHE_CONTROL = "public, max-age=300, stale-while-revalidate=86400"


def _base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _guest_rules() -> dict[str, object]:
    return {
        "effective_mos_min": 15,
        "mos_min_override": "ignored",
        "only_drops": "ignored",
    }


def build_agent_site_manifest(*, base_url: str) -> dict[str, Any]:
    base = _base_url(base_url)
    return {
        "schema_version": AGENT_SCHEMA_VERSION,
        "site": {
            "name": "Radar BDS",
            "url": base,
            "language": "vi-VN",
            "description": (
                "Radar BDS chuẩn hóa tin rao bất động sản Bình Dương và cung cấp "
                "signal công khai để sàng lọc trước khi người dùng tự thẩm định."
            ),
        },
        "markets": {
            "country": "VN",
            "province": "Bình Dương",
            "primary": ["Thủ Dầu Một", "Bến Cát"],
            "sources": ["facebook", "guland"],
        },
        "capabilities": [
            {"id": "find_signals", "method": "GET", "url": f"{base}/api/signals"},
            {"id": "count_signals", "method": "GET", "url": f"{base}/api/counts"},
        ],
        "not_supported": [
            "authentication",
            "favorites",
            "lead_submission",
            "phone_numbers",
            "original_listing_urls",
            "saved_searches",
            "watchlists",
            "write_actions",
        ],
        "discovery": {
            "openapi": f"{base}/agent/openapi.json",
            "llms": f"{base}/llms.txt",
            "robots": f"{base}/robots.txt",
            "sitemap": f"{base}/sitemap.xml",
        },
        "usage": {
            "recommended_flow": [
                "Translate the user's need into public filters.",
                "Call /api/signals with include_total=0 and limit no greater than 30.",
                "Compare only fields returned in the same response.",
                "Explain that a signal is a screening aid, not a purchase recommendation.",
                "Send the user to detail_href for verification and next steps.",
            ],
            "recommended_query": {"include_total": 0, "limit": 30, "sort": "score_desc"},
            "guest_rules": _guest_rules(),
        },
        "freshness": {
            "dataset_header": "X-Radar-Dataset-Version",
            "cache_header": "X-Radar-Public-Cache",
            "record_dates": ["card_date_reason", "days_ago"],
        },
        "citation": {
            "canonical_link_field": "detail_href",
            "recommended_fields": [
                "title",
                "ward",
                "price_label",
                "area_m2",
                "mos_pct",
                "signal_score",
                "detail_href",
            ],
        },
        "limitations": [
            "Signals are screening aids, not purchase recommendations.",
            "Listing data can be incomplete, stale, duplicated, or changed by the publisher.",
            "Users must independently verify location, planning, legal status, dimensions, and price.",
        ],
    }
```

- [ ] In the same file, define reusable parameter helpers and `build_agent_openapi_document()`. The document must include only the following operations and parameter contracts:

```python
def _parameter(
    name: str,
    schema: dict[str, Any],
    description: str,
    *,
    repeated: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "in": "query",
        "required": False,
        "description": description,
        "schema": schema,
    }
    if repeated:
        result["style"] = "form"
        result["explode"] = True
    return result


def _filter_parameters() -> list[dict[str, Any]]:
    return [
        _parameter("city", {"type": "string"}, "City name; defaults to Thủ Dầu Một."),
        _parameter("ward", {"type": "array", "items": {"type": "string"}}, "Repeat to select wards.", repeated=True),
        _parameter("source", {"type": "array", "items": {"type": "string", "enum": ["facebook", "guland"]}}, "Repeat to select public sources.", repeated=True),
        _parameter("prop_type", {"type": "array", "items": {"type": "string", "enum": ["dat_nen", "nha_dat", "chung_cu", "nha_tro"]}}, "Repeat to select property types.", repeated=True),
        _parameter("area_min", {"type": "number", "minimum": 0}, "Minimum lot area in square metres."),
        _parameter("area_max", {"type": "number", "minimum": 0}, "Maximum lot area in square metres."),
        _parameter("price_min", {"type": "number", "minimum": 0}, "Minimum listing price in billion VND."),
        _parameter("price_max", {"type": "number", "minimum": 0}, "Maximum listing price in billion VND."),
        _parameter("q", {"type": "string"}, "Bounded public keyword search."),
        _parameter("date_range", {"type": "string", "enum": ["1w", "1m", "3m", "6m", "1y", "all"]}, "Listing activity window."),
    ]


def build_agent_openapi_document(*, base_url: str) -> dict[str, Any]:
    base = _base_url(base_url)
    signal_parameters = _filter_parameters() + [
        _parameter("page", {"type": "integer", "minimum": 1, "maximum": 2000, "default": 1}, "Result page."),
        _parameter("limit", {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}, "Page size; agents should use at most 30."),
        _parameter("sort", {"type": "string", "enum": ["newest", "price_m2_asc", "price_asc", "mos_desc", "score_desc"], "default": "newest"}, "Signal ordering."),
        _parameter("include_total", {"type": "integer", "enum": [0, 1], "default": 1}, "Use 0 for the first agent query; call /api/counts separately when a count is needed."),
    ]
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Radar BDS Read-only Agent API",
            "version": AGENT_SCHEMA_VERSION,
            "description": "Guest-safe signal discovery. No authentication or write actions are supported.",
        },
        "servers": [{"url": base}],
        "tags": [{"name": "signals", "description": "Public, redacted Bình Dương signal discovery."}],
        "paths": {
            "/api/signals": {
                "get": {
                    "operationId": "findSignals",
                    "summary": "Find public actionable signals",
                    "tags": ["signals"],
                    "parameters": signal_parameters,
                    "x-radar-guest-rules": _guest_rules(),
                    "responses": {
                        "200": {"description": "Paginated, redacted public signal cards.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SignalPage"}}}},
                        "503": {"description": "Temporary public-read backpressure; retry with bounded exponential backoff."},
                    },
                }
            },
            "/api/counts": {
                "get": {
                    "operationId": "countSignals",
                    "summary": "Count signals for the current public filters",
                    "tags": ["signals"],
                    "parameters": _filter_parameters(),
                    "x-radar-guest-rules": _guest_rules(),
                    "responses": {
                        "200": {"description": "Public filtered counters.", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/CountSummary"}}}},
                        "503": {"description": "Temporary public-read backpressure; retry with bounded exponential backoff."},
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "SignalCard": {
                    "type": "object",
                    "required": ["id", "detail_href", "title", "ward"],
                    "properties": {
                        "id": {"type": "integer"},
                        "detail_href": {"type": "string", "description": "Canonical public handoff path."},
                        "title": {"type": "string"},
                        "ward": {"type": "string"},
                        "price_ty": {"type": ["number", "null"]},
                        "price_label": {"type": ["string", "null"]},
                        "area_m2": {"type": ["number", "null"]},
                        "actual_ppm2": {"type": ["number", "null"]},
                        "fair_ppm2": {"type": ["number", "null"]},
                        "mos_pct": {"type": ["number", "null"]},
                        "signal_score": {"type": ["number", "null"]},
                        "source": {"type": ["string", "null"]},
                        "days_ago": {"type": ["integer", "null"]},
                        "card_date_reason": {"type": ["string", "null"]},
                    },
                    "additionalProperties": True,
                },
                "SignalPage": {
                    "type": "object",
                    "properties": {
                        "signals": {"type": "array", "items": {"$ref": "#/components/schemas/SignalCard"}},
                        "page": {"type": "integer"},
                        "limit": {"type": "integer"},
                        "total": {"type": ["integer", "null"]},
                    },
                    "additionalProperties": True,
                },
                "CountSummary": {"type": "object", "additionalProperties": True},
            }
        },
    }
```

- [ ] Run the builder tests and confirm they pass:

```powershell
& $py -X utf8 -m pytest tests\test_agent_readiness.py -q
```

- [ ] Commit only the builder and its tests:

```powershell
git add -- services/agent_resources.py tests/test_agent_readiness.py
git commit -m "feat: define read-only agent discovery contract"
```

---

## Task 2: Expose database-free public JSON routes

**Files:**

- Modify: `app.py`
- Modify: `routes/public.py`
- Modify: `tests/test_agent_readiness.py`

**Interfaces:**

- Consumes: `PUBLIC_BASE_URL` already imported by `app.py`.
- Produces: anonymous `GET /agent/site.json` with `application/json`.
- Produces: anonymous `GET /agent/openapi.json` with `application/json`.
- Produces response header `Cache-Control: public, max-age=300, stale-while-revalidate=86400`.
- Must not produce: cookies, authentication challenges, database calls, Redis calls, or `X-Radar-Public-Cache: 1`.

- [ ] Extend `tests/test_agent_readiness.py` with failing route tests. Patch the application-level connection symbol to prove these endpoints stay database-free:

```python
import app as radar_app


def test_agent_json_routes_are_public_cacheable_and_database_free(monkeypatch):
    def fail_if_database_is_touched(*args, **kwargs):
        raise AssertionError("agent discovery must not touch the database")

    monkeypatch.setattr(radar_app, "get_conn", fail_if_database_is_touched)
    client = radar_app.app.test_client()

    site_response = client.get("/agent/site.json")
    openapi_response = client.get("/agent/openapi.json")

    for response in (site_response, openapi_response):
        assert response.status_code == 200
        assert response.content_type == "application/json"
        assert response.headers["Cache-Control"] == (
            "public, max-age=300, stale-while-revalidate=86400"
        )
        assert "Set-Cookie" not in response.headers
        assert response.headers.get("X-Radar-Public-Cache") != "1"

    assert site_response.get_json()["discovery"]["openapi"].endswith(
        "/agent/openapi.json"
    )
    assert set(openapi_response.get_json()["paths"]) == {
        "/api/signals",
        "/api/counts",
    }
```

- [ ] Run the focused test and confirm route-level 404 failures:

```powershell
& $py -X utf8 -m pytest tests\test_agent_readiness.py -q
```

- [ ] Import the builders and cache constant in `app.py`:

```python
from services.agent_resources import (
    AGENT_CACHE_CONTROL,
    build_agent_openapi_document,
    build_agent_site_manifest,
)
```

- [ ] Place these thin handlers next to `robots_txt()` and `llms_txt()` in `app.py`:

```python
def _agent_json_response(payload):
    response = jsonify(payload)
    response.headers["Cache-Control"] = AGENT_CACHE_CONTROL
    return response


def agent_site_json():
    return _agent_json_response(
        build_agent_site_manifest(base_url=PUBLIC_BASE_URL)
    )


def agent_openapi_json():
    return _agent_json_response(
        build_agent_openapi_document(base_url=PUBLIC_BASE_URL)
    )
```

- [ ] Add these delegates immediately before the existing `/robots.txt` route in `routes/public.py`:

```python
@bp.route("/agent/site.json")
def agent_site_json(**kwargs):
    return _impl("agent_site_json", **kwargs)


@bp.route("/agent/openapi.json")
def agent_openapi_json(**kwargs):
    return _impl("agent_openapi_json", **kwargs)
```

- [ ] Run route tests and the existing public cache-header tests:

```powershell
& $py -X utf8 -m pytest tests\test_agent_readiness.py tests\test_public_cache_headers.py -q
```

- [ ] Commit only the route exposure changes:

```powershell
git add -- app.py routes/public.py tests/test_agent_readiness.py
git commit -m "feat: expose public agent discovery resources"
```

---

## Task 3: Link the contract from crawler and LLM discovery files

**Files:**

- Modify: `app.py`
- Modify: `tests/test_agent_readiness.py`
- Modify: `tests/test_public_seo.py`
- Modify: `tests/test_traffic_seo_aio.py`

**Interfaces:**

- Produces: `robots.txt` with an explicit `OAI-SearchBot` allow block while preserving the wildcard allow block and sitemap.
- Produces: `llms.txt` links to `/agent/site.json` and `/agent/openapi.json` plus a plain-language read-only usage boundary.
- Preserves: all existing priority pages, caveats, planning links, news links, and sitemap behavior.

- [ ] Add failing discovery assertions without replacing existing SEO assertions:

```python
def test_agent_resources_are_linked_from_llms_and_allowed_for_search_crawlers():
    client = radar_app.app.test_client()
    robots = client.get("/robots.txt").get_data(as_text=True)
    llms = client.get("/llms.txt").get_data(as_text=True)

    assert "User-agent: OAI-SearchBot\nAllow: /" in robots
    assert "User-agent: *\nAllow: /" in robots
    assert "https://radarbds.vn/sitemap.xml" in robots
    assert "https://radarbds.vn/agent/site.json" in llms
    assert "https://radarbds.vn/agent/openapi.json" in llms
    assert "chỉ đọc" in llms.lower()
    assert "/api/signals" in llms
    assert "detail_href" in llms
```

- [ ] Run the three discovery/SEO test files and confirm the new assertions fail:

```powershell
& $py -X utf8 -m pytest tests\test_agent_readiness.py tests\test_public_seo.py tests\test_traffic_seo_aio.py -q
```

- [ ] Change only the body prefix of `robots_txt()` in `app.py`; preserve the existing sitemap line:

```python
def robots_txt():
    body = f"""User-agent: OAI-SearchBot
Allow: /

User-agent: *
Allow: /

Sitemap: {_public_url('/sitemap.xml')}
"""
    return Response(body, mimetype="text/plain")
```

- [ ] Add this section near the top of the existing `llms.txt` body, after the product summary and before priority geography. Do not remove or reorder the current public content inventory:

```text
## Dành cho AI agent
- Phạm vi: chỉ đọc, tìm, lọc, so sánh signal công khai và dẫn người dùng đến trang chi tiết phù hợp.
- Hướng dẫn máy đọc: https://radarbds.vn/agent/site.json
- OpenAPI chỉ đọc: https://radarbds.vn/agent/openapi.json
- Tìm signal: GET https://radarbds.vn/api/signals?include_total=0&limit=30
- Khi dẫn nguồn, dùng detail_href của signal; không suy đoán số điện thoại hoặc URL tin gốc.
```

Use `_public_url()` for every absolute URL instead of hard-coding the production domain in the Python template.

- [ ] Run the focused tests and confirm all discovery/SEO assertions pass:

```powershell
& $py -X utf8 -m pytest tests\test_agent_readiness.py tests\test_public_seo.py tests\test_traffic_seo_aio.py -q
```

- [ ] Commit only the discovery-link changes:

```powershell
git add -- app.py tests/test_agent_readiness.py tests/test_public_seo.py tests/test_traffic_seo_aio.py
git commit -m "feat: advertise read-only agent discovery"
```

---

## Task 4: Run contract, security, and regression verification

**Files:**

- Verify: `services/agent_resources.py`
- Verify: `app.py`
- Verify: `routes/public.py`
- Verify: `tests/test_agent_readiness.py`
- Verify: `tests/test_public_cache_headers.py`
- Verify: `tests/test_public_seo.py`
- Verify: `tests/test_traffic_seo_aio.py`

**Interfaces:**

- Verifies the JSON documents are syntactically valid, deterministic, Guest-safe, and read-only.
- Verifies current public signal caching/redaction behavior has not regressed.
- Does not verify production deployment; that is a separate release boundary.

- [ ] Compile touched Python modules:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile app.py routes\public.py services\agent_resources.py
```

- [ ] Run the focused suite:

```powershell
& $py -X utf8 -m pytest tests\test_agent_readiness.py tests\test_public_cache_headers.py tests\test_public_seo.py tests\test_traffic_seo_aio.py -q
```

- [ ] Inspect the generated documents from pure builders and assert there are no write verbs or forbidden fields:

```powershell
& $py -X utf8 -c "import json; from services.agent_resources import build_agent_openapi_document, build_agent_site_manifest; docs=[build_agent_site_manifest(base_url='https://radarbds.vn'),build_agent_openapi_document(base_url='https://radarbds.vn')]; text=json.dumps(docs, ensure_ascii=False).lower(); assert all(v not in text for v in ['\"post\"','\"put\"','\"patch\"','\"delete\"','contact_phone','seller_name','source_url']); print('AGENT_CONTRACT_READ_ONLY_OK')"
```

- [ ] Inspect scope before any final commit or handoff:

```powershell
git status --short
git diff --check
git diff --stat
```

- [ ] If verification required a correction, commit only that correction with a narrow message; otherwise do not create an empty commit:

```powershell
git add -- services/agent_resources.py app.py routes/public.py tests/test_agent_readiness.py tests/test_public_cache_headers.py tests/test_public_seo.py tests/test_traffic_seo_aio.py
git commit -m "test: verify read-only agent discovery"
```

---

## Production Verification Boundary

After this implementation is reviewed, merged, pushed, and deployed through the normal Radar BDS release process, verify each boundary separately:

1. `GET https://radarbds.vn/agent/site.json` returns `200`, JSON, the intended cache header, and production-domain links.
2. `GET https://radarbds.vn/agent/openapi.json` returns `200` and exactly two GET paths.
3. `GET https://radarbds.vn/llms.txt` links both resources.
4. `GET https://radarbds.vn/robots.txt` contains both the explicit `OAI-SearchBot` block and wildcard block.
5. A Guest query to `/api/signals?include_total=0&limit=3` still redacts phone, seller, and original URL fields and returns canonical `detail_href` values.
6. Record the deployed commit SHA separately from local test evidence. HTTP `200` alone is not proof that the intended commit reached production.
