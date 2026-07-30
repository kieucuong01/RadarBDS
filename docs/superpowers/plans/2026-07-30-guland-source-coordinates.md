# Guland Source Coordinates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lưu tọa độ công khai từ liên kết `Chỉ đường` của Guland vào raw data, backfill riêng các tin Guland đủ điều kiện Maps, và ưu tiên marker `exact` mà không làm mất fallback hiện có.

**Architecture:** JavaScript của crawler chỉ thu URL Google Maps trên card. Module Python thuần xác thực identity, URL, bounds và canonical ward; raw repository lưu provenance trong `raw_json`; map candidate loader đưa tọa độ hợp lệ vào resolver hiện có. Một CLI dry-run mặc định thu candidate cho tập listing Guland đang hiển thị, tạo rollback manifest trước apply, cập nhật đúng changed IDs và không chạy valuation/dedup.

**Tech Stack:** Python 3.12, Playwright sync API, PostgreSQL compatibility layer trong `db.connection`, Shapely 2.1.2, pytest, Flask Maps APIs.

## Global Constraints

- Không thêm cột latitude/longitude vào `raw_listings`; lưu đúng các field `source_lat`, `source_lng`, `source_coordinate_url`, `source_coordinate_provider`, `source_coordinate_captured_at` trong `raw_json`.
- Chỉ `source_lat/source_lng` đã vượt mọi validation gate mới được đưa vào resolver và ghi `listing_map_locations.location_precision='exact'`.
- Chỉ backfill listing thỏa `source='guland'`, `probably_sold=0`, `is_blacklisted=0`, `review_hidden=0`, `possibly_duplicate=0`.
- Không tự đảo, sửa hoặc đoán tọa độ; `110.99336,106.655556689` phải bị từ chối.
- URL accepted phải normalize theo mẫu cụ thể như `https://www.google.com/maps/search/?api=1&query=11.0280996%2C106.6206725`.
- Tọa độ phải nằm trong `LISTING_MAP_BOUNDS` và canonical ward polygon hoặc compatibility zone đã khai báo.
- Tin thiếu/sai tọa độ phải giữ nguyên fallback road/landmark/ward; không được xóa marker hiện có.
- Dry-run là mặc định, stdout chỉ chứa một JSON object parse được; tiến độ/log đi stderr.
- Apply chỉ merge năm field tọa độ vào raw JSON và chạy map-location backfill cho changed IDs; không gọi valuation, dedup, image download, notification hoặc full reprocess.
- `source_coordinate_captured_at` chỉ đổi khi URL hoặc cặp tọa độ đổi; rerun cùng candidate phải là no-op.
- Trước apply phải tạo rollback manifest production-local chỉ chứa raw/listing IDs và năm field tọa độ cũ.
- Giữ source policy và redaction hiện tại; browser production verification dùng tài khoản admin để chọn nguồn Guland.
- Preserve unrelated dirty work; stage và commit đúng paths của từng task.

---

## File Structure

### Files to create

- `services/guland_coordinates.py`: domain types, Guland URL identity normalization, Google Maps query parsing, ward/compatibility validation và raw field construction.
- `db/guland_coordinates.py`: query tập target Maps, snapshot năm field tọa độ, merge/restore raw JSON theo batch.
- `services/guland_coordinate_backfill.py`: orchestration thu cards, match target, dry-run/apply/rollback, manifest atomic write và statistics.
- `cli/guland_coordinates.py`: adapter argparse gọi orchestration và in đúng một JSON object.
- `tests/test_guland_coordinates.py`: unit tests parser/validator/identity.
- `tests/test_guland_coordinate_repository.py`: repository target/merge/restore và map loader tests.
- `tests/test_guland_coordinate_backfill.py`: dry-run/apply/rollback/idempotency orchestration tests.

### Files to modify

- `services/listing_location_auto_registry.py:198-279`: tách predicate compatibility zone dùng chung mà không đổi behavior browser evidence hiện có.
- `crawler/guland_pw.py:43-112,386-424`: thu `source_coordinate_url`, validate và thêm field tọa độ cho tin mới.
- `db/listing_map_locations.py:16-52`: join raw row và đưa tọa độ hợp lệ vào resolver input.
- `radar.py:90-155,325-345`: đăng ký `guland-coordinate-backfill` và route command.
- `tests/test_guland_crawler_stats.py`: bảo vệ behavior tin mới có/không có tọa độ.
- `tests/test_listing_location_auto_registry.py`: regression cho compatibility helper.
- `tests/test_listing_location_backfill.py`: xác nhận raw-sourced coordinate nâng precision thành `exact`.
- `tests/test_cli_command_logging.py`: parser contract cho dry-run/apply/rollback.
- `docs/dev_commands.md`: lệnh local/production dry-run, apply và rollback.
- `docs/daily_crawl_flow.md`: mô tả tọa độ Guland cho tin mới và giới hạn validation.

---

### Task 1: Pure Guland coordinate parser and ward validator

**Files:**

- Create: `services/guland_coordinates.py`
- Modify: `services/listing_location_auto_registry.py:198-279`
- Create: `tests/test_guland_coordinates.py`
- Modify: `tests/test_listing_location_auto_registry.py:1-90`

**Interfaces:**

- Consumes: `config.listing_map.LISTING_MAP_BOUNDS`, `services.listing_location_auto_registry.point_is_in_scoped_ward()`, `LISTING_MAP_LEGACY_COMPATIBILITY_ZONES`.
- Produces:
  - `GulandCoordinateDecision(status: str, reason: str, lat: float | None, lng: float | None, sanitized_url: str)`
  - `normalize_guland_post_url(value: str) -> tuple[str, str] | None`
  - `guland_identity_matches(card_url: str, target_url: str, card_post_id: str, target_source_id: str) -> bool`
  - `evaluate_guland_coordinate_url(source_url: str, *, city: str, ward: str, context_text: str = "") -> GulandCoordinateDecision`
  - `raw_coordinate_fields(decision: GulandCoordinateDecision, captured_at: str) -> dict[str, object]`
  - `point_is_in_legacy_compatibility_zone(city: str, ward: str, lat: float, lng: float, context_text: str) -> bool`

- [ ] **Step 1: Write failing parser and identity tests**

Create `tests/test_guland_coordinates.py` with exact valid, malformed, out-of-bounds and identity cases:

```python
from services.guland_coordinates import (
    evaluate_guland_coordinate_url,
    guland_identity_matches,
    normalize_guland_post_url,
    raw_coordinate_fields,
)


VALID_MAP_URL = (
    "https://www.google.com/maps/search/"
    "?api=1&query=11.028099613958%2C106.6206724626"
)


def test_valid_guland_direction_url_is_sanitized_and_accepted(monkeypatch):
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: True,
    )
    decision = evaluate_guland_coordinate_url(
        VALID_MAP_URL,
        city="THỦ DẦU MỘT",
        ward="Tân An",
    )

    assert decision.status == "valid"
    assert decision.reason == ""
    assert decision.lat == 11.028099613958
    assert decision.lng == 106.6206724626
    assert decision.sanitized_url == (
        "https://www.google.com/maps/search/"
        "?api=1&query=11.0280996%2C106.6206725"
    )


def test_invalid_latitude_is_rejected_without_decimal_repair(monkeypatch):
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: True,
    )
    decision = evaluate_guland_coordinate_url(
        "https://www.google.com/maps/search/"
        "?api=1&query=110.99336%2C106.655556689",
        city="THỦ DẦU MỘT",
        ward="Tân An",
    )

    assert decision.status == "invalid"
    assert decision.reason == "invalid_lat_lng_order"
    assert decision.lat is None
    assert decision.lng is None


def test_wrong_ward_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: False,
    )
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_legacy_compatibility_zone",
        lambda city, ward, lat, lng, context_text: False,
    )
    decision = evaluate_guland_coordinate_url(
        VALID_MAP_URL,
        city="THỦ DẦU MỘT",
        ward="Phú Lợi",
    )

    assert decision.status == "invalid"
    assert decision.reason == "outside_canonical_ward"


def test_guland_identity_requires_url_match_and_no_post_id_conflict():
    assert guland_identity_matches(
        "https://guland.vn/post/dat-tan-an-1231140?ref=home",
        "https://www.guland.vn/post/dat-tan-an-1231140/",
        "1231140",
        "1231140",
    )
    assert not guland_identity_matches(
        "https://guland.vn/post/dat-tan-an-1231140",
        "https://guland.vn/post/dat-khac-9999999",
        "1231140",
        "9999999",
    )
    assert normalize_guland_post_url("https://example.com/post/a-1") is None


def test_raw_fields_require_valid_decision_and_keep_stable_names(monkeypatch):
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: True,
    )
    decision = evaluate_guland_coordinate_url(
        VALID_MAP_URL,
        city="THỦ DẦU MỘT",
        ward="Tân An",
    )

    assert raw_coordinate_fields(
        decision,
        "2026-07-30T12:34:56+07:00",
    ) == {
        "source_lat": 11.028099613958,
        "source_lng": 106.6206724626,
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=11.0280996%2C106.6206725"
        ),
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
    }
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_guland_coordinates.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'services.guland_coordinates'`.

- [ ] **Step 3: Add the compatibility-zone regression first**

Append to `tests/test_listing_location_auto_registry.py`:

```python
from services.listing_location_auto_registry import (
    point_is_in_legacy_compatibility_zone,
)


def test_phu_chanh_context_can_use_declared_legacy_compatibility_zone():
    assert point_is_in_legacy_compatibility_zone(
        "THỦ DẦU MỘT",
        "Phú Tân",
        11.058782,
        106.7015151,
        "Khu tái định cư Phú Chánh B",
    )
    assert not point_is_in_legacy_compatibility_zone(
        "THỦ DẦU MỘT",
        "Phú Tân",
        11.058782,
        106.7015151,
        "Tin bán đất không nêu Phú Chánh",
    )
```

Run:

```powershell
& $py -X utf8 -m pytest tests\test_listing_location_auto_registry.py::test_phu_chanh_context_can_use_declared_legacy_compatibility_zone -q
```

Expected: FAIL because `point_is_in_legacy_compatibility_zone` does not exist.

- [ ] **Step 4: Implement the shared compatibility predicate**

In `services/listing_location_auto_registry.py`, add the reusable predicate and make `legacy_compatibility_reason()` call it:

```python
def point_is_in_legacy_compatibility_zone(
    city: str,
    ward: str,
    lat: float,
    lng: float,
    context_text: str,
) -> bool:
    normalized_city = normalize_location_token(city)
    normalized_ward = normalize_location_token(ward)
    normalized_context = normalize_location_token(context_text)
    for zone in LISTING_MAP_LEGACY_COMPATIBILITY_ZONES:
        token = normalize_location_token(zone["landmark_token"])
        if (
            normalized_city != normalize_location_token(zone["city"])
            or normalized_ward != normalize_location_token(zone["ward"])
            or token not in normalized_context
        ):
            continue
        (south, west), (north, east) = zone["bounds"]
        if south <= float(lat) <= north and west <= float(lng) <= east:
            return True
    return False
```

Keep the existing browser-evidence rule stricter by preserving its requirement
that the token also appears in `result_address` before it returns the configured
reason.

- [ ] **Step 5: Implement the pure coordinate module**

Create `services/guland_coordinates.py` with:

```python
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from config.listing_map import LISTING_MAP_BOUNDS
from services.listing_location_auto_registry import (
    point_is_in_legacy_compatibility_zone,
    point_is_in_scoped_ward,
)


_POST_ID_RE = re.compile(r"-(?P<post_id>\d+)(?:\.html)?$")


@dataclass(frozen=True)
class GulandCoordinateDecision:
    status: str
    reason: str = ""
    lat: float | None = None
    lng: float | None = None
    sanitized_url: str = ""


def normalize_guland_post_url(value: str) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(str(value or "").strip())
        hostname = parsed.hostname
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or hostname not in {"guland.vn", "www.guland.vn"}
        or not parsed.path.startswith("/post/")
    ):
        return None
    path = parsed.path.rstrip("/")
    match = _POST_ID_RE.search(path)
    if match is None:
        return None
    return f"https://guland.vn{path}", match.group("post_id")


def guland_identity_matches(
    card_url: str,
    target_url: str,
    card_post_id: str,
    target_source_id: str,
) -> bool:
    card = normalize_guland_post_url(card_url)
    target = normalize_guland_post_url(target_url)
    if card is None or target is None or card[0] != target[0]:
        return False
    card_id = str(card_post_id or card[1])
    target_id = str(target_source_id or target[1])
    return not card_id or not target_id or card_id == target_id


def _inside_service_bounds(lat: float, lng: float) -> bool:
    (south, west), (north, east) = LISTING_MAP_BOUNDS
    return south <= lat <= north and west <= lng <= east


def evaluate_guland_coordinate_url(
    source_url: str,
    *,
    city: str,
    ward: str,
    context_text: str = "",
) -> GulandCoordinateDecision:
    value = str(source_url or "").strip()
    if not value:
        return GulandCoordinateDecision("missing", "missing_coordinate_url")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError:
        return GulandCoordinateDecision("invalid", "invalid_coordinate_url")
    if (
        parsed.scheme != "https"
        or hostname != "www.google.com"
        or parsed.path.rstrip("/") != "/maps/search"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        return GulandCoordinateDecision("invalid", "invalid_coordinate_url")
    params = parse_qs(parsed.query, keep_blank_values=True)
    if params.get("api") != ["1"] or len(params.get("query", [])) != 1:
        return GulandCoordinateDecision("invalid", "missing_coordinate_pair")
    parts = [part.strip() for part in params["query"][0].split(",")]
    if len(parts) != 2:
        return GulandCoordinateDecision("invalid", "missing_coordinate_pair")
    try:
        lat, lng = (float(parts[0]), float(parts[1]))
    except ValueError:
        return GulandCoordinateDecision("invalid", "invalid_number")
    if not math.isfinite(lat) or not math.isfinite(lng):
        return GulandCoordinateDecision("invalid", "invalid_number")
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return GulandCoordinateDecision("invalid", "invalid_lat_lng_order")
    if not _inside_service_bounds(lat, lng):
        return GulandCoordinateDecision("invalid", "outside_service_bounds")
    if not str(ward or "").strip():
        return GulandCoordinateDecision("invalid", "missing_canonical_ward")
    if not (
        point_is_in_scoped_ward(city, ward, lat, lng)
        or point_is_in_legacy_compatibility_zone(
            city,
            ward,
            lat,
            lng,
            context_text,
        )
    ):
        return GulandCoordinateDecision("invalid", "outside_canonical_ward")
    query = f"{lat:.7f},{lng:.7f}"
    sanitized = urlunsplit((
        "https",
        "www.google.com",
        "/maps/search/",
        urlencode({"api": "1", "query": query}),
        "",
    ))
    return GulandCoordinateDecision(
        "valid",
        lat=lat,
        lng=lng,
        sanitized_url=sanitized,
    )


def raw_coordinate_fields(
    decision: GulandCoordinateDecision,
    captured_at: str,
) -> dict[str, object]:
    if decision.status != "valid" or decision.lat is None or decision.lng is None:
        return {}
    return {
        "source_lat": decision.lat,
        "source_lng": decision.lng,
        "source_coordinate_url": decision.sanitized_url,
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": str(captured_at),
    }
```

- [ ] **Step 6: Run parser, compatibility and existing auto-registry tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_guland_coordinates.py `
  tests\test_listing_location_auto_registry.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```powershell
git add services/guland_coordinates.py services/listing_location_auto_registry.py tests/test_guland_coordinates.py tests/test_listing_location_auto_registry.py
git commit -m "feat: validate Guland source coordinates"
```

---

### Task 2: Capture source coordinates for newly crawled Guland listings

**Files:**

- Modify: `crawler/guland_pw.py:43-112,386-424`
- Modify: `tests/test_guland_crawler_stats.py`

**Interfaces:**

- Consumes: `evaluate_guland_coordinate_url()`, `raw_coordinate_fields()`, `services.market_data.get_city_for_ward()`.
- Produces: `_JS_EXTRACT_CARDS` card field `source_coordinate_url: str`; `_build_record()` raw fields for valid source coordinates.
- Reuses the existing Guland crawl post-processing path: after normalization, the
  current changed-listing map backfill reads the validated raw fields and upgrades
  those listings to `exact`; do not add a second reprocess or valuation pass.

- [ ] **Step 1: Write failing crawler record tests**

Append to `tests/test_guland_crawler_stats.py`:

```python
from unittest import mock


def test_build_record_adds_valid_source_coordinate_fields():
    crawler = GulandCrawler()
    card = {
        "url": "https://guland.vn/post/dat-tan-an-1231140",
        "source_list_url": (
            "https://guland.vn/mua-ban-dat-tho-cu-"
            "phuong-tan-an-thanh-pho-thu-dau-mot-binh-duong"
        ),
        "post_id": "1231140",
        "title": "Bán đất Tân An",
        "price_raw": "2 tỷ",
        "area_raw": "100 m²",
        "pm2_raw": "20 tr/m²",
        "date_raw": "Hôm nay",
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=11.028099613958%2C106.6206724626"
        ),
    }
    decision = mock.Mock(
        status="valid",
        lat=11.028099613958,
        lng=106.6206724626,
        sanitized_url=(
            "https://www.google.com/maps/search/"
            "?api=1&query=11.0280996%2C106.6206725"
        ),
    )
    with (
        mock.patch(
            "crawler.guland_pw.evaluate_guland_coordinate_url",
            return_value=decision,
        ),
        mock.patch(
            "crawler.guland_pw.raw_coordinate_fields",
            return_value={
                "source_lat": decision.lat,
                "source_lng": decision.lng,
                "source_coordinate_url": decision.sanitized_url,
                "source_coordinate_provider": "guland_directions",
                "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
            },
        ),
    ):
        record = crawler._build_record(card, {})

    assert record["source_lat"] == 11.028099613958
    assert record["source_lng"] == 106.6206724626
    assert record["source_coordinate_provider"] == "guland_directions"
    assert record["ward"] == "Tân An"


def test_build_record_keeps_listing_when_coordinate_is_invalid():
    crawler = GulandCrawler()
    card = {
        "url": "https://guland.vn/post/dat-tan-an-1231140",
        "source_list_url": (
            "https://guland.vn/mua-ban-dat-tho-cu-"
            "phuong-tan-an-thanh-pho-thu-dau-mot-binh-duong"
        ),
        "post_id": "1231140",
        "title": "Bán đất Tân An",
        "price_raw": "2 tỷ",
        "area_raw": "100 m²",
        "pm2_raw": "20 tr/m²",
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=110.99336%2C106.655556689"
        ),
    }
    decision = mock.Mock(
        status="invalid",
        reason="invalid_lat_lng_order",
        lat=None,
        lng=None,
        sanitized_url="",
    )
    with mock.patch(
        "crawler.guland_pw.evaluate_guland_coordinate_url",
        return_value=decision,
    ):
        record = crawler._build_record(card, {})

    assert record["url"].endswith("-1231140")
    assert "source_lat" not in record
    assert "source_lng" not in record
```

- [ ] **Step 2: Run the tests and verify failure**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_crawler_stats.py -q
```

Expected: FAIL because `crawler.guland_pw` does not import or call the coordinate helpers.

- [ ] **Step 3: Capture the Google Maps URL in card JavaScript**

In `_JS_EXTRACT_CARDS`, locate the coordinate anchor inside the current card and
add it to the returned object:

```javascript
const coordinateLink = [...card.querySelectorAll(
  'a[href^="https://www.google.com/maps/search/"]'
)].find(link => {
  const text = (link.textContent || '').trim().toLowerCase();
  return text.includes('chỉ đường') || link.href.includes('api=1');
});

return {
  url: a.href,
  post_id: postId,
  title: (titleEl || a).textContent.trim(),
  price_raw: priceEl?.textContent.trim() || '',
  area_raw: infBs[0]?.textContent.trim() || '',
  pm2_raw: infBs[1]?.textContent.trim() || '',
  date_raw: dateEl?.textContent.trim() || '',
  source_coordinate_url: coordinateLink?.href || '',
  imgs,
};
```

Do not parse coordinates in JavaScript.

- [ ] **Step 4: Preserve list-page ward context and add validated fields**

Immediately after `_scroll_all_cards()` returns in `_run_crawl()`, preserve the
category URL that provides the ward context:

```python
for card in all_cards:
    card.setdefault("source_list_url", base_url)
```

At the start of `_build_record()`, infer the configured ward from
`source_list_url`, not the `/post/` URL:

```python
url = card["url"]
ward_source_url = str(card.get("source_list_url") or "")
m_ward = re.search(
    r"phuong-([a-z0-9-]+)-thanh-pho",
    ward_source_url,
)
ward_slug = m_ward.group(1) if m_ward else ""
ward_display = self.WARD_MAP.get(
    ward_slug,
    ward_slug.replace("-", " ").title(),
)
```

This is required for the ward-polygon validation; do not fall back to a guessed
ward when the configured list URL has no supported ward slug.

Import `datetime`, `ZoneInfo`, `evaluate_guland_coordinate_url`,
`raw_coordinate_fields`, and `get_city_for_ward`. Build the existing record
first, then merge only valid fields:

```python
record = {
    "url": url,
    "post_id": card.get("post_id", ""),
    "title": card.get("title", ""),
    "description": detail.get("description", ""),
    "address": detail.get("address", ""),
    "price_ty": price_ty,
    "area_m2": area_m2,
    "price_per_m2": ppm2,
    "area_name": ward_display or "TDM",
    "ward": ward_display,
    "property_type_raw": detail.get("property_type_raw", ""),
    "road_type_raw": detail.get("road_type_raw", ""),
    "road_width_raw": detail.get("road_width_raw", ""),
    "location_type_raw": detail.get("location_type_raw", ""),
    "legal_raw": detail.get("legal_raw", ""),
    "contact_phone": detail.get("contact_phone", ""),
    "imgs": detail.get("detail_imgs", []) or card.get("imgs", []),
    "date_raw": card.get("date_raw", ""),
    "tx_type": "ban",
    "province": "Bình Dương",
    "district": "Thủ Dầu Một",
    "source": self.SOURCE_NAME,
}
city = get_city_for_ward(ward_display)
context_text = " ".join(filter(None, (
    record["title"],
    record["description"],
    record["address"],
)))
decision = evaluate_guland_coordinate_url(
    card.get("source_coordinate_url", ""),
    city=city,
    ward=ward_display,
    context_text=context_text,
)
if decision.status == "valid":
    captured_at = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat()
    record.update(raw_coordinate_fields(decision, captured_at))
elif decision.status == "invalid":
    self.logger.warning(
        "Rejected Guland coordinate post_id=%s reason=%s",
        record["post_id"],
        decision.reason,
    )
return record
```

- [ ] **Step 5: Run crawler unit and syntax tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_crawler_stats.py tests\test_guland_coordinates.py -q
& $py -X utf8 -m py_compile crawler\guland_pw.py services\guland_coordinates.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```powershell
git add crawler/guland_pw.py tests/test_guland_crawler_stats.py
git commit -m "feat: capture coordinates for new Guland listings"
```

---

### Task 3: Active-target repository, raw merge and map candidate integration

**Files:**

- Create: `db/guland_coordinates.py`
- Modify: `db/listing_map_locations.py:16-52`
- Create: `tests/test_guland_coordinate_repository.py`
- Modify: `tests/test_listing_location_backfill.py`

**Interfaces:**

- Consumes: `db.connection.get_conn()`, `GulandCoordinateDecision`, `raw_coordinate_fields()`.
- Produces:
  - `GulandCoordinateTarget(listing_id, raw_id, url, source_id, ward, city, context_text, existing_coordinate_fields, existing_map_precision, raw_json_valid)`
  - `GulandCoordinateUpdate(raw_id, listing_id, fields)`
  - `load_active_guland_coordinate_targets() -> list[GulandCoordinateTarget]`
  - `snapshot_raw_coordinate_fields(raw_ids: Sequence[int]) -> list[dict]`
  - `merge_raw_coordinate_updates(updates: Sequence[GulandCoordinateUpdate]) -> list[int]`
  - `restore_raw_coordinate_snapshot(rows: Sequence[Mapping]) -> list[int]`
  - `iter_location_candidates()` returns raw-backed `source_lat/source_lng`.

- [ ] **Step 1: Write failing target-scope and merge tests**

Create `tests/test_guland_coordinate_repository.py` using a recording connection
factory:

```python
import json
from contextlib import contextmanager

from db.guland_coordinates import (
    GulandCoordinateUpdate,
    load_active_guland_coordinate_targets,
    merge_raw_coordinate_updates,
)


class Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.rowcount = len(self.rows)

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        rows = self.responses.pop(0) if self.responses else []
        return Cursor(rows)


@contextmanager
def connection_factory(connection):
    yield connection


def test_target_query_uses_exact_maps_visibility_gate():
    connection = Connection([[]])

    result = load_active_guland_coordinate_targets(
        conn_factory=lambda: connection_factory(connection)
    )

    assert result == []
    sql = " ".join(connection.executed[0][0].split())
    assert "l.source = 'guland'" in sql
    assert "COALESCE(l.probably_sold, 0) = 0" in sql
    assert "COALESCE(l.is_blacklisted, 0) = 0" in sql
    assert "COALESCE(l.review_hidden, 0) = 0" in sql
    assert "COALESCE(l.possibly_duplicate, 0) = 0" in sql


def test_raw_merge_preserves_existing_keys_and_is_idempotent():
    existing = {
        "title": "Bán đất Tân An",
        "price_ty": 2.0,
    }
    updated = {
        **existing,
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=11.0280996%2C106.6206725"
        ),
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
    }
    connection = Connection([
        [{"id": 7, "raw_json": json.dumps(existing)}],
        [],
        [{"id": 7, "raw_json": json.dumps(updated)}],
    ])
    update = GulandCoordinateUpdate(
        raw_id=7,
        listing_id=70,
        fields={key: updated[key] for key in updated if key.startswith("source_")},
    )

    first = merge_raw_coordinate_updates(
        [update],
        conn_factory=lambda: connection_factory(connection),
    )
    second = merge_raw_coordinate_updates(
        [update],
        conn_factory=lambda: connection_factory(connection),
    )

    assert first == [70]
    assert second == []
    update_sql, update_params = next(
        item for item in connection.executed if item[0].startswith("UPDATE")
    )
    merged = json.loads(update_params[0])
    assert merged["title"] == "Bán đất Tân An"
    assert merged["price_ty"] == 2.0
    assert merged["source_lat"] == 11.0280996
```

- [ ] **Step 2: Run repository tests and verify failure**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_coordinate_repository.py -q
```

Expected: collection fails because `db.guland_coordinates` does not exist.

- [ ] **Step 3: Implement focused repository functions**

Create `db/guland_coordinates.py` with frozen dataclasses and injectable
`conn_factory=get_conn`. The target query must select only internal fields:

```python
SELECT l.id AS listing_id,
       l.raw_id,
       l.url,
       r.source_id,
       l.ward,
       l.title,
       l.description,
       r.raw_json,
       ml.location_precision AS existing_map_precision
FROM listings l
JOIN raw_listings r ON r.id = l.raw_id
LEFT JOIN listing_map_locations ml ON ml.listing_id = l.id
WHERE l.source = 'guland'
  AND COALESCE(l.probably_sold, 0) = 0
  AND COALESCE(l.is_blacklisted, 0) = 0
  AND COALESCE(l.review_hidden, 0) = 0
  AND COALESCE(l.possibly_duplicate, 0) = 0
ORDER BY l.id
```

Construct `city` with `get_city_for_ward(ward)`, `context_text` from title,
description and raw `address`, `existing_coordinate_fields` from the five
coordinate keys, and `raw_json_valid=True`. If raw JSON cannot be parsed, return
the target with `existing_coordinate_fields={}`, `raw_json_valid=False`, and
context from title/description only; orchestration must count and skip it. Do
not expose context strings in CLI output or manifest.

Implement merge with these exact rules:

```python
_COORDINATE_KEYS = (
    "source_lat",
    "source_lng",
    "source_coordinate_url",
    "source_coordinate_provider",
    "source_coordinate_captured_at",
)


def _coordinate_subset(raw: dict) -> dict:
    return {key: raw.get(key) for key in _COORDINATE_KEYS}


def _merge_fields(existing: dict, fields: dict) -> tuple[dict, bool]:
    previous = _coordinate_subset(existing)
    candidate = {key: fields.get(key) for key in _COORDINATE_KEYS}
    stable_keys = tuple(
        key
        for key in _COORDINATE_KEYS
        if key != "source_coordinate_captured_at"
    )
    if all(previous[key] == candidate[key] for key in stable_keys):
        candidate["source_coordinate_captured_at"] = previous[
            "source_coordinate_captured_at"
        ]
    if previous == candidate:
        return existing, False
    merged = dict(existing)
    for key in _COORDINATE_KEYS:
        if candidate[key] is None:
            merged.pop(key, None)
        else:
            merged[key] = candidate[key]
    return merged, True
```

Reject malformed JSON for that row with a counted repository exception; do not
replace malformed raw with `{}`.

Append a repository regression where the same lat/lng/URL/provider arrives with
a later `source_coordinate_captured_at`; assert
`merge_raw_coordinate_updates()` returns `[]` and performs no `UPDATE`.

- [ ] **Step 4: Test and implement coordinate-only snapshot/restore**

Append to `tests/test_guland_coordinate_repository.py`:

```python
from db.guland_coordinates import (
    restore_raw_coordinate_snapshot,
    snapshot_raw_coordinate_fields,
)


def test_snapshot_contains_only_ids_and_five_coordinate_fields():
    raw = {
        "title": "Bán đất",
        "contact_phone": "0900000000",
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
        "source_coordinate_url": "https://www.google.com/maps/search/?api=1&query=11.0280996%2C106.6206725",
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
    }
    connection = Connection([[
        {"raw_id": 7, "listing_id": 70, "raw_json": json.dumps(raw)}
    ]])

    rows = snapshot_raw_coordinate_fields(
        [7],
        conn_factory=lambda: connection_factory(connection),
    )

    assert rows == [{
        "raw_id": 7,
        "listing_id": 70,
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
        "source_coordinate_url": raw["source_coordinate_url"],
        "source_coordinate_provider": "guland_directions",
        "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00",
    }]
    assert "title" not in rows[0]
    assert "contact_phone" not in rows[0]


def test_restore_removes_only_coordinate_fields_and_preserves_raw_content():
    current = {
        "title": "Bán đất",
        "price_ty": 2.0,
        "source_lat": 11.0280996,
        "source_lng": 106.6206725,
    }
    connection = Connection([
        [{"id": 7, "raw_json": json.dumps(current)}],
        [],
    ])
    snapshot = [{
        "raw_id": 7,
        "listing_id": 70,
        "source_lat": None,
        "source_lng": None,
        "source_coordinate_url": None,
        "source_coordinate_provider": None,
        "source_coordinate_captured_at": None,
    }]

    restored = restore_raw_coordinate_snapshot(
        snapshot,
        conn_factory=lambda: connection_factory(connection),
    )

    assert restored == [70]
    update_params = next(
        params
        for sql, params in connection.executed
        if sql.startswith("UPDATE")
    )
    merged = json.loads(update_params[0])
    assert merged == {"title": "Bán đất", "price_ty": 2.0}
```

Implement `snapshot_raw_coordinate_fields()` with a parameterized
`raw_listings`/`listings` join and `_coordinate_subset()`. Implement
`restore_raw_coordinate_snapshot()` by parsing the current raw JSON, removing
keys whose manifest value is `None`, restoring non-null coordinate values, and
updating only changed rows. Return unique sorted listing IDs.

- [ ] **Step 5: Write failing map-loader regression**

Append to `tests/test_guland_coordinate_repository.py`:

```python
def test_map_candidate_loader_reads_validated_coordinates_from_raw(monkeypatch):
    from db import listing_map_locations

    row = {
        "id": 70,
        "title": "Bán đất",
        "description": "",
        "ward": "Tân An",
        "road_name": "",
        "source": "guland",
        "raw_json": json.dumps({
            "source_lat": 11.0280996,
            "source_lng": 106.6206725,
        }),
        "existing_resolver_version": None,
        "existing_signature": None,
    }
    connection = Connection([[row]])
    monkeypatch.setattr(
        listing_map_locations,
        "get_conn",
        lambda: connection_factory(connection),
    )

    candidates = listing_map_locations.iter_location_candidates([70])

    assert candidates[0]["source_lat"] == 11.0280996
    assert candidates[0]["source_lng"] == 106.6206725
```

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_coordinate_repository.py::test_map_candidate_loader_reads_validated_coordinates_from_raw -q
```

Expected: FAIL because the query still emits `NULL` coordinates.

- [ ] **Step 6: Join raw JSON in `iter_location_candidates()`**

Modify `db/listing_map_locations.py` to select `l.source`, `r.raw_json`, and join
raw:

```sql
SELECT l.id,
       l.title,
       l.description,
       l.ward,
       l.road_name,
       l.source,
       r.raw_json,
       ml.resolver_version AS existing_resolver_version,
       ml.listing_location_signature AS existing_signature
FROM listings l
LEFT JOIN raw_listings r ON r.id = l.raw_id
LEFT JOIN listing_map_locations ml ON ml.listing_id = l.id
```

After fetching, parse raw JSON in Python and attach coordinates only when both
values are finite numbers:

```python
def _source_coordinates(row: dict) -> tuple[float | None, float | None]:
    if str(row.get("source") or "") != "guland":
        return None, None
    try:
        raw = json.loads(row.get("raw_json") or "{}")
        lat = float(raw["source_lat"])
        lng = float(raw["source_lng"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, None
    if not math.isfinite(lat) or not math.isfinite(lng):
        return None, None
    return lat, lng
```

Do not cast raw JSON inside SQL; one malformed raw row must not abort the batch.

- [ ] **Step 7: Add exact-upgrade backfill regression**

Append to `tests/test_listing_location_backfill.py`:

```python
def test_raw_sourced_coordinate_upgrades_existing_ward_marker_to_exact():
    patches = _patch_backfill()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3] as upsert_rows,
        patches[4],
        patches[5],
        patches[6] as iter_candidates,
    ):
        from services.listing_location_backfill import backfill_listing_locations

        iter_candidates.return_value = [
            _candidate(
                80,
                source_lat=11.0280996,
                source_lng=106.6206725,
                existing_resolver_version="old-v1",
                existing_signature="ward-signature",
            )
        ]
        stats = backfill_listing_locations(listing_ids=[80])

    assert stats["exact"] == 1
    assert stats["updated"] == 1
    written = upsert_rows.call_args.args[0]
    assert written[0].listing_id == 80
    assert written[0].precision == "exact"
```

- [ ] **Step 8: Run repository and location tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_guland_coordinate_repository.py `
  tests\test_listing_location_backfill.py `
  tests\test_listing_location_resolver.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```powershell
git add db/guland_coordinates.py db/listing_map_locations.py tests/test_guland_coordinate_repository.py tests/test_listing_location_backfill.py
git commit -m "feat: persist Guland coordinates into map locations"
```

---

### Task 4: Idempotent backfill orchestration and rollback manifest

**Files:**

- Create: `services/guland_coordinate_backfill.py`
- Create: `tests/test_guland_coordinate_backfill.py`

**Interfaces:**

- Consumes:
  - `load_active_guland_coordinate_targets()`
  - `merge_raw_coordinate_updates()`
  - `snapshot_raw_coordinate_fields()`
  - `restore_raw_coordinate_snapshot()`
  - `GulandCrawler.TARGET_URLS`, `_launch()`, `_scroll_all_cards()`
  - `backfill_listing_locations(listing_ids: Sequence[int])`
- Produces:
  - `run_guland_coordinate_backfill(*, apply: bool = False, rollback_run: str = "", manifest_root: Path = Path(".local/guland-coordinate-backfill"), now: datetime | None = None) -> dict[str, object]`
  - `_atomic_write_manifest(path: Path, rows: Sequence[Mapping]) -> None`
  - safe stats keys from the approved spec.

- [ ] **Step 1: Write failing dry-run orchestration test**

Create `tests/test_guland_coordinate_backfill.py`:

```python
from datetime import datetime, timezone

from db.guland_coordinates import GulandCoordinateTarget
from services.guland_coordinate_backfill import run_guland_coordinate_backfill


def _target():
    return GulandCoordinateTarget(
        listing_id=70,
        raw_id=7,
        url="https://guland.vn/post/dat-tan-an-1231140",
        source_id="1231140",
        ward="Tân An",
        city="THỦ DẦU MỘT",
        context_text="Bán đất Tân An",
        existing_coordinate_fields={},
        existing_map_precision="ward",
        raw_json_valid=True,
    )


def _cards():
    return [{
        "url": "https://guland.vn/post/dat-tan-an-1231140",
        "post_id": "1231140",
        "source_coordinate_url": (
            "https://www.google.com/maps/search/"
            "?api=1&query=11.028099613958%2C106.6206724626"
        ),
    }]


def test_dry_run_builds_plan_without_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.load_active_guland_coordinate_targets",
        lambda: [_target()],
    )
    monkeypatch.setattr(
        "services.guland_coordinate_backfill._collect_cards",
        lambda targets: _cards(),
    )
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: True,
    )
    merge_calls = []
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.merge_raw_coordinate_updates",
        lambda updates: merge_calls.append(updates),
    )

    result = run_guland_coordinate_backfill(
        manifest_root=tmp_path,
        now=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    assert result["eligible"] == 1
    assert result["matched"] == 1
    assert result["valid"] == 1
    assert result["would_update"] == 1
    assert result["would_upgrade_to_exact"] == 1
    assert result["raw_updated"] == 0
    assert merge_calls == []
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run dry-run test and verify failure**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_coordinate_backfill.py::test_dry_run_builds_plan_without_writing -q
```

Expected: collection fails because `services.guland_coordinate_backfill` does not exist.

- [ ] **Step 3: Implement card collection and plan construction**

Implement `_collect_cards(targets)` with Playwright sync lifecycle copied from
the existing `_repair_guland()` pattern:

```python
def _collect_cards(targets):
    from playwright.sync_api import sync_playwright

    crawler = GulandCrawler()
    target_urls = {
        normalized[0]
        for target in targets
        if (normalized := normalize_guland_post_url(target.url)) is not None
    }
    cards_by_url = {}
    with sync_playwright() as playwright:
        browser, context = crawler._launch(playwright, headless=True)
        try:
            page = context.new_page()
            page.set_default_timeout(30_000)
            for base_url in crawler.TARGET_URLS:
                cards = crawler._scroll_all_cards(
                    page,
                    base_url,
                    incremental=False,
                )
                for card in cards:
                    normalized = normalize_guland_post_url(card.get("url", ""))
                    if normalized is not None:
                        cards_by_url.setdefault(normalized[0], card)
                if target_urls.issubset(cards_by_url):
                    break
        finally:
            browser.close()
    return list(cards_by_url.values())
```

Normalize target URLs before comparing the stop set. Deduplicate by canonical
Guland URL; never use title similarity.

Build one update per valid matched target. Increment:

- `eligible` from target count;
- `cards_scanned` from deduplicated cards;
- `matched` after identity match;
- `coordinate_links` when the card has a non-empty coordinate URL;
- `valid`, `invalid`, `outside_ward`, `missing`, `errors`;
- `would_update`, `would_upgrade_to_exact`.

Apply these exact decisions while building the plan:

```python
if not target.raw_json_valid:
    stats["invalid"] += 1
    stats["errors"] += 1
    continue
decision = evaluate_guland_coordinate_url(
    card.get("source_coordinate_url", ""),
    city=target.city,
    ward=target.ward,
    context_text=target.context_text,
)
if decision.status == "missing":
    stats["missing"] += 1
    continue
if decision.status == "invalid":
    stats["invalid"] += 1
    if decision.reason == "outside_canonical_ward":
        stats["outside_ward"] += 1
    continue
fields = raw_coordinate_fields(decision, captured_at)
stable_keys = {
    key
    for key in fields
    if key != "source_coordinate_captured_at"
}
needs_update = any(
    target.existing_coordinate_fields.get(key) != fields[key]
    for key in stable_keys
)
if needs_update:
    updates.append(GulandCoordinateUpdate(
        raw_id=target.raw_id,
        listing_id=target.listing_id,
        fields=fields,
    ))
    stats["would_update"] += 1
    if target.existing_map_precision != "exact":
        stats["would_upgrade_to_exact"] += 1
```

Do not include title, description, phone or original listing URL in the result.

- [ ] **Step 4: Write failing apply/idempotency test**

Append:

```python
def test_apply_writes_manifest_then_raw_then_exact_map(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.load_active_guland_coordinate_targets",
        lambda: [_target()],
    )
    monkeypatch.setattr(
        "services.guland_coordinate_backfill._collect_cards",
        lambda targets: _cards(),
    )
    monkeypatch.setattr(
        "services.guland_coordinates.point_is_in_scoped_ward",
        lambda city, ward, lat, lng: True,
    )
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.snapshot_raw_coordinate_fields",
        lambda raw_ids: [{
            "raw_id": 7,
            "listing_id": 70,
            "source_lat": None,
            "source_lng": None,
            "source_coordinate_url": None,
            "source_coordinate_provider": None,
            "source_coordinate_captured_at": None,
        }],
    )
    events = []
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.merge_raw_coordinate_updates",
        lambda updates: events.append("merge") or [70],
    )
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.backfill_listing_locations",
        lambda listing_ids: events.append(("map", listing_ids))
        or {"exact": 1, "updated": 1},
    )

    result = run_guland_coordinate_backfill(
        apply=True,
        manifest_root=tmp_path,
        now=datetime(2026, 7, 30, tzinfo=timezone.utc),
    )

    manifests = list(tmp_path.glob("*-before.jsonl"))
    assert len(manifests) == 1
    assert events == ["merge", ("map", [70])]
    assert result["raw_updated"] == 1
    assert result["map_exact_updated"] == 1
    assert result["run_id"] in manifests[0].name
```

- [ ] **Step 5: Implement atomic manifest before any DB update**

Use `tempfile.mkstemp()` in the target directory, write one JSON object per line
with `ensure_ascii=False`, flush, `os.fsync()`, then `os.replace()`.

Allow only these keys:

```python
_MANIFEST_KEYS = (
    "raw_id",
    "listing_id",
    "source_lat",
    "source_lng",
    "source_coordinate_url",
    "source_coordinate_provider",
    "source_coordinate_captured_at",
)
```

Fail before merge if the manifest cannot be written. Use run ID format
`YYYYMMDDTHHMMSSZ`; for example `20260730T120000Z-before.jsonl`.

After the manifest succeeds, apply in this order:

```python
changed_ids = merge_raw_coordinate_updates(updates)
map_stats = (
    backfill_listing_locations(listing_ids=changed_ids)
    if changed_ids
    else {"inserted": 0, "updated": 0, "unchanged": 0}
)
stats["raw_updated"] = len(changed_ids)
stats["map_exact_updated"] = (
    int(map_stats.get("inserted", 0))
    + int(map_stats.get("updated", 0))
)
stats["map_unchanged"] = int(map_stats.get("unchanged", 0))
stats["run_id"] = run_id
```

Every `changed_id` came from a valid source coordinate, so every inserted or
updated map row in this scoped call must resolve as `exact`. Raise and leave the
manifest available when `map_stats["exact"] != len(changed_ids)`.

- [ ] **Step 6: Write failing rollback/path traversal tests**

Append:

```python
def test_rollback_restores_only_manifest_coordinate_fields(monkeypatch, tmp_path):
    run_id = "20260730T120000Z"
    manifest = tmp_path / f"{run_id}-before.jsonl"
    manifest.write_text(
        '{"raw_id":7,"listing_id":70,"source_lat":null,'
        '"source_lng":null,"source_coordinate_url":null,'
        '"source_coordinate_provider":null,'
        '"source_coordinate_captured_at":null}\n',
        encoding="utf-8",
    )
    events = []
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.restore_raw_coordinate_snapshot",
        lambda rows: events.append(rows) or [70],
    )
    monkeypatch.setattr(
        "services.guland_coordinate_backfill.backfill_listing_locations",
        lambda listing_ids: events.append(listing_ids)
        or {"updated": 1, "exact": 0},
    )

    result = run_guland_coordinate_backfill(
        rollback_run=run_id,
        manifest_root=tmp_path,
    )

    assert result["rollback_restored"] == 1
    assert events[1] == [70]


def test_rollback_rejects_path_traversal(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="invalid rollback run id"):
        run_guland_coordinate_backfill(
            rollback_run="../secrets",
            manifest_root=tmp_path,
        )
```

- [ ] **Step 7: Implement bounded rollback**

Accept only `re.fullmatch(r"\d{8}T\d{6}Z", rollback_run)`. Resolve the manifest
path and assert `path.parent == manifest_root.resolve()`. Reject files larger
than 5 MB, invalid UTF-8, non-object lines, duplicate raw IDs or keys outside
`_MANIFEST_KEYS`. Restore only the coordinate subset, then call
`backfill_listing_locations(listing_ids=restored_listing_ids)`.

- [ ] **Step 8: Run orchestration tests**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_guland_coordinate_backfill.py -q
& $py -X utf8 -m py_compile services\guland_coordinate_backfill.py
```

Expected: PASS.

- [ ] **Step 9: Commit Task 4**

```powershell
git add services/guland_coordinate_backfill.py tests/test_guland_coordinate_backfill.py
git commit -m "feat: add safe Guland coordinate backfill"
```

---

### Task 5: CLI contract and operational documentation

**Files:**

- Create: `cli/guland_coordinates.py`
- Modify: `radar.py:90-155,325-345`
- Modify: `tests/test_cli_command_logging.py`
- Modify: `docs/dev_commands.md`
- Modify: `docs/daily_crawl_flow.md`

**Interfaces:**

- Consumes: `run_guland_coordinate_backfill()`.
- Produces:
  - `cmd_guland_coordinate_backfill(args) -> dict[str, object]`
  - CLI:
    - `radar.py guland-coordinate-backfill --dry-run`
    - `radar.py guland-coordinate-backfill --apply`
    - `radar.py guland-coordinate-backfill --rollback-run RUN_ID`

- [ ] **Step 1: Write failing parser contract tests**

Append to `tests/test_cli_command_logging.py`:

```python
def test_guland_coordinate_backfill_defaults_to_dry_run():
    import radar

    args = radar.build_parser().parse_args(["guland-coordinate-backfill"])

    assert args.cmd == "guland-coordinate-backfill"
    assert args.apply is False
    assert args.rollback_run == ""


def test_guland_coordinate_backfill_apply_and_rollback_are_mutually_exclusive():
    import pytest
    import radar

    parser = radar.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "guland-coordinate-backfill",
            "--apply",
            "--rollback-run",
            "20260730T120000Z",
        ])
```

- [ ] **Step 2: Run parser tests and verify failure**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_cli_command_logging.py::test_guland_coordinate_backfill_defaults_to_dry_run `
  tests\test_cli_command_logging.py::test_guland_coordinate_backfill_apply_and_rollback_are_mutually_exclusive -q
```

Expected: FAIL because the subcommand is unknown.

- [ ] **Step 3: Implement CLI adapter and parser wiring**

Create `cli/guland_coordinates.py`:

```python
import json

from services.guland_coordinate_backfill import (
    run_guland_coordinate_backfill,
)


def cmd_guland_coordinate_backfill(args):
    result = run_guland_coordinate_backfill(
        apply=bool(getattr(args, "apply", False)),
        rollback_run=str(getattr(args, "rollback_run", "") or ""),
    )
    print(json.dumps(
        result,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    ))
    return result
```

In `radar.build_parser()` add:

```python
p_guland_coordinates = sub.add_parser(
    "guland-coordinate-backfill",
    help="Backfill validated source coordinates for active Guland map listings",
)
mode = p_guland_coordinates.add_mutually_exclusive_group()
mode.add_argument(
    "--dry-run",
    action="store_true",
    help="Explicit dry-run; this is already the default",
)
mode.add_argument("--apply", action="store_true")
mode.add_argument("--rollback-run", default="")
```

Import `cmd_guland_coordinate_backfill` and route:

```python
elif args.cmd == "guland-coordinate-backfill":
    cmd_guland_coordinate_backfill(args)
```

`--dry-run` is explicit documentation of the default read-only mode. Its
placement in the mutually exclusive group rejects `--dry-run --apply` and
`--dry-run --rollback-run`.

- [ ] **Step 4: Test one-JSON stdout contract**

Append:

```python
def test_guland_coordinate_cli_prints_one_json_object(monkeypatch, capsys):
    from argparse import Namespace
    from cli import guland_coordinates

    monkeypatch.setattr(
        guland_coordinates,
        "run_guland_coordinate_backfill",
        lambda **kwargs: {"eligible": 2, "valid": 1, "raw_updated": 0},
    )

    result = guland_coordinates.cmd_guland_coordinate_backfill(
        Namespace(apply=False, rollback_run="", dry_run=True)
    )
    output = capsys.readouterr().out.strip().splitlines()

    assert result["valid"] == 1
    assert len(output) == 1
    assert output[0] == '{"eligible": 2, "raw_updated": 0, "valid": 1}'
```

- [ ] **Step 5: Document exact commands and invariants**

Add to `docs/dev_commands.md`:

```powershell
# Read-only by default
& $py -X utf8 radar.py guland-coordinate-backfill --dry-run

# Apply only after reviewing dry-run JSON
& $py -X utf8 radar.py guland-coordinate-backfill --apply

# Restore the five coordinate fields from one run manifest
& $py -X utf8 radar.py guland-coordinate-backfill `
  --rollback-run 20260730T120000Z
```

Document that a manifest such as
`.local/guland-coordinate-backfill/20260730T120000Z-before.jsonl` is
gitignored/runtime data and contains no
title/description/phone/image/original listing URL.

Update `docs/daily_crawl_flow.md` to state:

- Guland card extraction now captures public `Chỉ đường`;
- valid source coordinates become `exact`;
- invalid/missing coordinates retain road/ward fallback;
- no external LLM or paid geocoding is introduced;
- the one-time backfill is separate from daily crawl.

- [ ] **Step 6: Run CLI and docs-focused tests**

Run:

```powershell
& $py -X utf8 -m pytest `
  tests\test_cli_command_logging.py `
  tests\test_guland_coordinate_backfill.py -q
& $py -X utf8 radar.py guland-coordinate-backfill --help
```

Expected: tests PASS; help lists mutually exclusive
`--dry-run | --apply | --rollback-run`.

- [ ] **Step 7: Commit Task 5**

```powershell
git add cli/guland_coordinates.py radar.py tests/test_cli_command_logging.py docs/dev_commands.md docs/daily_crawl_flow.md
git commit -m "docs: wire Guland coordinate operations"
```

---

### Task 6: Full local verification and narrow release preparation

**Files:**

- Verify all Task 1-5 paths.
- No new production mutation in this task.

**Interfaces:**

- Consumes: completed implementation.
- Produces: local release evidence and exact task-scoped path list.

- [ ] **Step 1: Run syntax checks**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile `
  crawler\guland_pw.py `
  services\guland_coordinates.py `
  services\guland_coordinate_backfill.py `
  services\listing_location_auto_registry.py `
  db\guland_coordinates.py `
  db\listing_map_locations.py `
  cli\guland_coordinates.py `
  radar.py
```

Expected: exit 0 with no output.

- [ ] **Step 2: Run the focused feature suite**

```powershell
& $py -X utf8 -m pytest `
  tests\test_guland_coordinates.py `
  tests\test_guland_crawler_stats.py `
  tests\test_guland_coordinate_repository.py `
  tests\test_guland_coordinate_backfill.py `
  tests\test_listing_location_auto_registry.py `
  tests\test_listing_location_backfill.py `
  tests\test_listing_location_resolver.py `
  tests\test_cli_command_logging.py -q
```

Expected: PASS with zero failed tests.

- [ ] **Step 3: Run Maps regression tests**

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_ui.py `
  tests\test_signal_detail_ui.py `
  tests\test_source_policy.py -q
```

Expected: PASS; existing source visibility/redaction behavior remains unchanged.

- [ ] **Step 4: Run static diff gates**

```powershell
git diff --check
git status --short
git diff --name-only HEAD~5..HEAD
```

Expected: no whitespace errors; only approved Task 1-5 paths plus the design and
plan documents are in scope. Do not stage unrelated dirty files.

- [ ] **Step 5: Review the default dry-run locally when DB credentials work**

```powershell
& $py -X utf8 radar.py guland-coordinate-backfill --dry-run
```

Expected: one JSON object; `raw_updated=0`; `map_exact_updated=0`. If local
PostgreSQL authentication is unavailable, record the environment blocker and do
not substitute production credentials into local `.env`.

- [ ] **Step 6: Commit any final test/doc corrections**

If Step 1-5 required changes, stage only the corrected task paths:

```powershell
git add crawler/guland_pw.py services/guland_coordinates.py services/guland_coordinate_backfill.py services/listing_location_auto_registry.py db/guland_coordinates.py db/listing_map_locations.py cli/guland_coordinates.py radar.py tests/test_guland_coordinates.py tests/test_guland_crawler_stats.py tests/test_guland_coordinate_repository.py tests/test_guland_coordinate_backfill.py tests/test_listing_location_auto_registry.py tests/test_listing_location_backfill.py tests/test_cli_command_logging.py docs/dev_commands.md docs/daily_crawl_flow.md
git commit -m "test: verify Guland coordinate backfill"
```

If no corrections were needed, do not create an empty commit.

---

### Task 7: Deploy code, production dry-run, approval-gated apply and browser proof

**Files:**

- Deploy only commits from Tasks 1-6.
- Runtime manifest example: `/opt/radar-bds/current/.local/guland-coordinate-backfill/20260730T120000Z-before.jsonl`

**Interfaces:**

- Consumes: pushed implementation commit and production DB.
- Produces: deployed code, read-only dry-run evidence, approval-gated DB update, API/browser proof or rollback.

- [ ] **Step 1: Confirm release scope before push**

```powershell
git status --short
git log --oneline origin/main..HEAD
git diff --name-only origin/main...HEAD
```

Expected: no unrelated dirty files or commits. If unrelated work exists, use the
repo's explicit `-Path` release mode; never use `-All`.

- [ ] **Step 2: Push committed scope and deploy the code-only release**

All implementation tasks already create intentional commits. Push those commits,
then deploy the pushed `main`:

```powershell
git push origin main
.\scripts\deploy_production.ps1
```

Expected: commit pushed, VPS fast-forwarded or guarded bundle fallback used,
`radar-bds.service` active, dashboard/signals smoke 200.

- [ ] **Step 3: Run production dry-run only**

```powershell
$ssh = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa"
ssh -i $ssh deploy@103.90.226.230 "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py guland-coordinate-backfill --dry-run"
```

Expected: one JSON object with `eligible > 0`, `raw_updated=0`,
`map_exact_updated=0`, and no sensitive fields.

- [ ] **Step 4: Stop for explicit user approval**

Report the dry-run counters:

```text
eligible
cards_scanned
matched
coordinate_links
valid
invalid
outside_ward
missing
would_update
would_upgrade_to_exact
```

Do not run `--apply` until the user explicitly approves these production
counters.

- [ ] **Step 5: Apply after approval and capture the returned run ID**

```powershell
$applyJson = ssh -i $ssh deploy@103.90.226.230 "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py guland-coordinate-backfill --apply"
$applyResult = $applyJson | ConvertFrom-Json
$runId = [string]$applyResult.run_id
if ($runId -notmatch '^\d{8}T\d{6}Z$') {
    throw "Production apply did not return a valid run_id"
}
$applyResult | ConvertTo-Json -Depth 5
```

Expected:

- `raw_updated == map_exact_updated`;
- `raw_updated <= valid`;
- `errors == 0`;
- response contains a valid `run_id`;
- manifest exists under `.local/guland-coordinate-backfill/`.

- [ ] **Step 6: Verify production DB precision counts**

Run a read-only SSH query using production Python and `DATABASE_URL`:

```sql
SELECT COUNT(*) AS listings,
       COUNT(ml.listing_id) AS mapped,
       COUNT(*) FILTER (WHERE ml.location_precision='exact') AS exact,
       COUNT(*) FILTER (WHERE ml.location_precision='road') AS road,
       COUNT(*) FILTER (WHERE ml.location_precision='ward') AS ward
FROM listings l
LEFT JOIN listing_map_locations ml ON ml.listing_id=l.id
WHERE l.source='guland'
  AND COALESCE(l.probably_sold,0)=0
  AND COALESCE(l.is_blacklisted,0)=0
  AND COALESCE(l.review_hidden,0)=0
  AND COALESCE(l.possibly_duplicate,0)=0;
```

Expected: `exact` increases by `map_exact_updated`; total mapped does not
decrease.

- [ ] **Step 7: Smoke APIs**

```powershell
Invoke-RestMethod "https://radarbds.vn/api/map-listings?mode=signals"
Invoke-RestMethod "https://radarbds.vn/api/map-listings?mode=all&complete=1"
Invoke-WebRequest -UseBasicParsing "https://radarbds.vn/api/dashboard"
Invoke-WebRequest -UseBasicParsing "https://radarbds.vn/api/signals?page=1&limit=3"
```

Expected: HTTP 200; no source URL/phone leakage; map payload coordinates are
finite and inside supported bounds.

- [ ] **Step 8: Verify real browser behavior**

Using the logged-in admin browser:

1. Open both `Săn Deal` and `Tin rao`.
2. Select source `Guland`.
3. Open at least three markers upgraded to `exact`.
4. Confirm the marker coordinates match the sanitized
   `source_coordinate_url`.
5. Confirm a Guland listing without coordinates still uses its existing
   road/ward marker.
6. Confirm modal/detail Maps show the same exact marker.
7. Confirm closing the modal preserves tab, filters and map viewport.

Expected: exact listings use source coordinates; fallback listings remain
visible; no regression on either tab.

- [ ] **Step 9: Roll back only if a stop gate fails**

Stop gates:

- production `exact` delta differs from `map_exact_updated`;
- total mapped count decreases;
- coordinates appear outside the validated ward;
- API returns non-200 or leaks sensitive fields;
- browser marker/detail mismatch;
- apply reports any DB error.

Use the validated `$runId` captured in Step 5:

```powershell
ssh -i $ssh deploy@103.90.226.230 "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py guland-coordinate-backfill --rollback-run $runId"
```

After rollback, repeat Steps 6-8 and confirm `exact` returns to the pre-apply
count without reducing fallback coverage.
