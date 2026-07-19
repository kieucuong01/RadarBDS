# Facebook Broker Crawl Governance Design

**Date:** 2026-07-19
**Status:** Approved
**Scope:** Admin Facebook Crawl screen and scheduled Facebook profile selection

## Goal

Give admins three controls backed by existing Radar BDS data:

1. Filter the broker list by city.
2. Crawl each broker daily, every three days, or weekly.
3. Review cross-broker duplicate rates and approve a recommendation to reduce the weaker broker's crawl cadence.

The system must never disable a broker automatically.

## Existing Boundaries

- `data/facebook_profiles.json` remains the source of truth for broker crawl configuration.
- `POST /admin/api/facebook-crawl/config` continues to save the complete profile list through `services/admin_quality.py::write_facebook_profile_config()`.
- `crawler/facebook_apify.py::load_profiles()` remains the runtime loader.
- Existing Facebook dedup output in `listings.duplicate_of_id` is the only same-lot signal used by this feature.
- Existing `facebook_profile_data_quality()` remains the measure of how complete and parseable a broker's posts are.
- Manual crawl jobs remain independent from the production schedule.

## Profile Configuration

Each configured profile gains one field:

```json
{
  "url": "https://www.facebook.com/example",
  "broker_name": "Example Broker",
  "tier": 10,
  "daily_limit": 10,
  "range_days": 7,
  "crawl_every_days": 3,
  "active": true
}
```

Allowed values are `1`, `3`, and `7`. Missing or invalid values normalize to `1`, which preserves the behavior of existing files.

## Scheduled Profile Selection

The production daily flow still starts once per day. Before calling Apify, it keeps only active profiles due on that UTC date.

Due dates are deterministic and stateless:

- `crawl_every_days = 1`: due every day.
- `crawl_every_days = 3`: due when the UTC ordinal date matches a stable URL-derived slot modulo 3.
- `crawl_every_days = 7`: due when the UTC ordinal date matches a stable URL-derived slot modulo 7.

The stable slot uses a standard-library cryptographic digest of the normalized profile URL, not Python's process-randomized `hash()`. This spreads broker requests across days without adding a state table or rewriting the config after every run.

Only the production daily Facebook-first path applies due-date selection. Admin manual crawl, CLI profile crawl, range crawl, and explicit retry operations run the requested profiles immediately.

If no profile is due, the Facebook phase returns a successful zero-work result and logs that no scheduled profile was due. It is not treated as a source failure.

## Duplicate Comparison

### Source data

The comparison uses Facebook listings from the latest 90 days. Each listing belongs to a lot cluster identified by `COALESCE(listings.duplicate_of_id, listings.id)`.

The broker is resolved from `raw_listings.raw_json.profile_url`, with `_apify_raw.inputUrl` as the existing fallback. URLs are normalized by trimming whitespace and a trailing slash.

### Eligibility

A pair is evaluated only when:

- both profiles still exist in the current config;
- both profiles belong to the same configured city;
- each broker has at least 10 distinct lot clusters in the 90-day window;
- the pair shares at least 5 distinct lot clusters.

Same-profile reposts do not create cross-broker overlap. Orphaned profiles and unlinked raw rows are ignored.

### Metrics

For brokers A and B:

```text
shared_lots = distinct clusters containing both A and B
overlap_a_pct = shared_lots / total distinct clusters for A
overlap_b_pct = shared_lots / total distinct clusters for B
```

Both percentages are returned because overlap is directional. Thirty shared lots may represent most of a small broker's inventory but only a small part of a larger broker's inventory.

### Recommendation

The broker to keep is selected by:

1. Higher existing data-quality score.
2. More non-shared lot clusters when quality scores tie or are unavailable.
3. More recent crawl activity when the first two signals tie.

The other broker receives a cadence recommendation based on that broker's directional overlap:

- `50%` through `69.9%`: recommend `crawl_every_days = 3`.
- `70%` or higher: recommend `crawl_every_days = 7`.
- Below `50%`: show the comparison but make no cadence recommendation.

The API returns evidence and recommendation text only. It never mutates profile configuration.

## API Shape

`GET /admin/api/facebook-crawl/config` continues to return `profiles`, `summary`, and `apify_tokens`. Each profile includes its existing activity and quality fields plus its strongest eligible overlap summary. The response also includes `duplicate_comparisons`, sorted for the recommendation panel.

Each comparison includes city, both broker URLs and names, both total-lot counts, both directional overlap percentages, both quality scores, shared-lot count, `keep_url`, `reduce_url`, and `recommended_crawl_every_days`.

If database analysis fails, config loading still succeeds with an empty comparison list and no overlap summaries.

## Admin UI

### City filter

The broker panel gets a select control populated from the distinct non-empty `profile.city` values in the loaded config. Options are `Tất cả` followed by cities in display order. The filter affects the broker table and duplicate recommendation panel only; it does not modify the configuration.

### Cadence control

Each broker row gets a `Chu kỳ` select with `Hàng ngày` (`1`), `3 ngày` (`3`), and `7 ngày` (`7`). The existing save action reads the selected value into `crawlProfiles` and posts the full profile list.

### Duplicate recommendation panel

A compact `Cặp môi giới trùng nhiều` panel appears above the broker table. It follows the selected city filter and sorts comparisons by the reduced broker's overlap percentage, then by shared lot count.

Each comparison shows both broker names, shared lot count, both directional percentages, both data-quality scores when available, the recommended broker to keep, and the proposed cadence for the other broker.

`Áp dụng gợi ý` updates only the in-memory `crawlProfiles` entry and corresponding cadence select. The existing `Lưu danh sách` button remains the explicit persistence step. The existing active toggle remains the only way for an admin to disable a broker.

When no comparison qualifies, the panel shows `Chưa đủ dữ liệu trùng để khuyến nghị`.

## Error Handling

- Invalid cadence input normalizes to daily on the backend.
- Missing profile URLs remain rejected by the existing config validation.
- Missing quality scores do not block comparison; unique-lot count becomes the next tie-breaker.
- Missing broker names fall back to the Facebook URL handle.
- Database/statistics errors do not block reading or saving profile config.
- A scheduled day with no due profiles is a successful no-op, not an operations alert condition.

## Verification

Automated checks cover:

1. Reading and writing `crawl_every_days`, including backward compatibility and invalid-value normalization.
2. Deterministic due-profile selection for 1-, 3-, and 7-day cadences.
3. Production daily crawl applying due selection while manual and retry paths bypass it.
4. Same-city and minimum-sample comparison eligibility.
5. Directional overlap percentages and shared-cluster counting.
6. Quality, unique-lot, and recency recommendation tie-breakers.
7. API fallback when database analysis fails.
8. Admin UI markers for city filtering, cadence selection, draft-only recommendation application, and explicit save.

Implementation verification also runs focused backend tests, `node --check static/js/admin.js`, Python compilation for touched modules, and a manual smoke of `/admin/facebook-crawl` at desktop and mobile widths.

## Out of Scope

- A new duplicate-detection algorithm.
- A new analytics or scheduling table.
- Automatic broker deactivation.
- Automatic saving when a recommendation is applied.
- Cross-city broker comparison.
- Historical trend charts for overlap.
- Changing Apify quota selection or per-profile post limits.
