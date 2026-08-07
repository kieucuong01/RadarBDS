# Phú Tân Listing Map Road Coverage Design

## Goal

Increase Maps accuracy for the Phú Tân, Thủ Dầu Một scope by moving listings in the `Tin rao` / `Toàn bộ tin rao` tab that currently fall into `THEO PHƯỜNG` back onto the road or landmark mentioned in the listing text, starting with a verified 65-listing regression set from the user's Phú Tân all-listings filter.

Target QA URL:

```text
https://radarbds.vn/?tab=all&city=TH%E1%BB%A6+D%E1%BA%A6U+M%E1%BB%98T&ward=Ph%C3%BA+T%C3%A2n&prop_type=dat_nen&prop_type=nha_dat
```

## Current evidence

Production read-only resolver audit for active `Phú Tân` plus legacy `Phú Chánh` candidates:

- scanned: `1544`
- exact: `124`
- road: `374`
- ward: `890`
- unresolved issues: `514`
- `Phú Tân` static road registry currently has `112` roads
- `TĐC Phú Chánh B` exists as a verified landmark; `TĐC Phú Chánh C/D` are not yet covered

The top failure groups are not random missing coordinates. They fall into repeatable buckets:

- `Phú Chánh` ward alias: `115` candidates hit `ward_not_found`.
- ambiguous road segments: `Đường số 84`, `N5`, `N6`, `N3`, `Nguyễn Văn Linh`.
- missing road aliases: `110 b`, `DB6`, `D5`, `Đường số 41/42/45/53/57/63/66/72/76/97`.
- parser false positives: text fragments like `phuong binh`, `gon le`, `kinh doanh`, `giao thong van tai noi`, `tay anh em oi`.

## Regression set

The implementation must create a deterministic 65-listing regression fixture from the current production sample of listings that are:

- in map scope `Phú Tân` or legacy `Phú Chánh`;
- currently resolved as `precision=ward`;
- have a non-empty `road_candidate`;
- are visible candidates for the Phú Tân `Tin rao` / all-listings map use case.

Initial target IDs:

```text
38822, 38826, 38827, 38922, 38924, 38974, 38996, 39002, 51951, 52788,
52899, 53015, 53347, 54745, 56369, 56468, 56574, 59163, 63135, 63298,
63536, 63752, 64902, 66644, 38863, 52787, 52893, 53014, 38813, 39016,
53373, 39146, 39147, 55536, 55688, 55868, 38895, 51929, 51983, 38804,
38886, 38944, 38977, 53384, 53466, 53525, 53576, 53624, 55862, 56009,
60575, 61547, 61650, 61773, 61845, 62002, 63564, 63825, 53338, 53348,
53378, 54367, 54726, 60526, 60687
```

Acceptance rule for this set:

- At least `60/65` must resolve to non-ward precision after the pilot.
- Any remaining `ward` result must be explicitly classified as unsafe, missing evidence, or parser false-positive; it must not silently pass.
- For listings whose candidate is `Đường số 84`, `N5`, `N6`, `N3`, or another repeated segment, the expected result is `precision=road` using a road aggregate, not fallback to ward.
- The test must assert the location label no longer starts with `Theo trung tâm` for passing rows.

## Design

### 1. Add ward aliasing only inside the map resolver

`Phú Chánh` should resolve as the map ward `Phú Tân` for listing-map purposes. This must not mutate canonical `listings.ward`, valuation wards, human labels, or training feedback.

Implementation shape:

- Add a map-only alias table near listing map config, for example `LISTING_MAP_WARD_ALIASES`.
- Resolver canonicalizes `(city, ward)` before looking up roads, landmarks, and ward centers.
- Coverage rows should preserve both the raw ward and the normalized map ward where useful for debugging.

### 2. Normalize numeric road aliases more aggressively, but only in road context

The parser must recognize common broker forms:

- `110B`, `110 b`, `Đường 110B` -> `duong so 110 b`
- `11B`, `11 b` -> `duong so 11 b`
- `DB6`, `ĐB 6` -> `db 6`
- `D5`, `N5`, `N6` stay as coded road names when the text context says road/frontage/alley.

Guardrails:

- `5m`, `6m`, `đường 5m`, `hẻm 5m` must not become `Đường số 5`.
- Marketing phrases and location filler must not become road candidates.

### 3. Use aggregate road points for same-name multi-segment roads

When the static registry has multiple segments for the same `(city, ward, normalized_road)`, the resolver currently marks it ambiguous and falls back to ward. For Maps display, that is too conservative.

New behavior:

- The registry builder creates a deterministic aggregate road entry for same-name multi-segment roads.
- Aggregate point is the length/point-count weighted center of accepted segments.
- `accuracy_radius_m` covers the segment spread and is capped to a safe maximum for display.
- Source stays auditable: `OpenStreetMap aggregate` plus the underlying OSM way IDs.
- Resolver prefers exact single road; if multiple segments exist, it uses the aggregate instead of ward fallback.

This is acceptable because the requested UX is “gom tin đó vào con đường nói đến trong tin rao”, not exact lot placement.

### 4. Add Phú Chánh C/D landmarks and targeted road overrides

Static/Osm alone is not enough for TĐC Phú Chánh. The pilot must add verified map evidence for:

- `TĐC Phú Chánh C`
- `TĐC Phú Chánh D`
- high-impact roads around these landmarks, starting from the 65-listing set and coverage top groups

Evidence source priority:

1. OSM road geometry if present and inside the Phú Tân/Phú Chánh area.
2. Browser/Google Maps suggestion for missing landmarks or roads.
3. Manual override only when the source URL and point/radius are explicit.

Every manual/auto override must include:

- canonical name
- aliases
- lat/lng
- `accuracy_radius_m`
- `source`
- `source_url`
- `verified_at`
- reason when overriding boundary mismatch

### 5. Strengthen coverage tooling for Phú Tân

The current coverage queue is global. The pilot needs a scoped mode:

```powershell
& $py -X utf8 radar.py map-location-coverage `
  --status unresolved `
  --city "THỦ DẦU MỘT" `
  --ward "Phú Tân" `
  --include-ward-alias "Phú Chánh" `
  --limit 100
```

The research queue should support the same filters so browser work starts from the highest-impact Phú Tân candidates.

### 6. Backfill and UI/API verification

After code and registry changes:

1. Rebuild static registry.
2. Run deterministic registry hash check twice.
3. Run resolver regression for the 65-listing set.
4. Run full map-location dry run.
5. Apply backfill only after the dry run is clean.
6. Smoke the target Phú Tân `Tin rao` URL and Maps APIs.

## Acceptance gates

### Local/code gates

- `tests/test_listing_map_context.py`
- `tests/test_listing_location_resolver.py`
- `tests/test_listing_location_registry.py`
- `tests/test_listing_location_backfill.py`
- `tests/test_listing_location_coverage.py`
- new regression test for the 65 Phú Tân listing IDs
- `py_compile` on touched Python files
- `git diff --check`

### Data gates

- `65` fixture rows loaded from production evidence into a deterministic local test fixture.
- `>=60/65` fixture rows resolve to non-ward precision.
- `Đường số 84` group resolves to road aggregate.
- `Phú Chánh` legacy ward maps through `Phú Tân`.
- `TĐC Phú Chánh C/D` resolve as landmarks or road-scoped landmarks.
- False positives like `kinh doanh`, `phuong binh`, `tay anh em oi`, and `5m` do not become road locations.

### Production gates

- Deploy commit is confirmed on production.
- `radar.py map-locations --full --dry-run` reports expected non-ward improvement.
- `radar.py map-locations --full` is applied after dry-run.
- `/api/map-listings?mode=all` returns HTTP 200.
- The target `tab=all` URL's Maps view no longer places the tested road-bearing rows only at `Theo trung tâm Phú Tân`.

## Out of scope

- Do not call Google Maps or any live geocoder during public page requests.
- Do not mutate canonical listing ward/area fields for this Maps-only improvement.
- Do not reprocess valuation, human feedback, or AI review data.
- Do not attempt every ward in Thủ Dầu Một in this pilot; only Phú Tân plus legacy Phú Chánh alias.

## Rollback

Rollback is data-preserving:

- revert the scoped registry/parser commit;
- redeploy;
- rerun `radar.py map-locations --full`;
- public Maps will return to the previous resolver/registry behavior.
