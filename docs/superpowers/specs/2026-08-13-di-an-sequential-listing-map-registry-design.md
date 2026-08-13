# Dĩ An Sequential Listing Map Registry Design

## Goal

Process every legacy Dĩ An ward one at a time and move active listings from an honest ward-center fallback to a trustworthy road or local-area marker whenever the listing text contains sufficient evidence.

## Production baseline and order

The 2026-08-13 production baseline contains 666 active ward-center listings:

1. Dĩ An: 252
2. Đông Hòa: 160
3. Tân Đông Hiệp: 109
4. Bình An: 68
5. Tân Bình: 61
6. An Bình: 11
7. Bình Thắng: 5

The implementation processes wards in that order. Each ward receives its own before/after audit even when all accepted changes ship in one resolver release.

## Administrative-scope decision

The map resolver must account for both legacy listing wards and the 2025 ward consolidation without mutating canonical listing data:

- New Dĩ An combines legacy Dĩ An, An Bình, and part of Tân Đông Hiệp.
- New Đông Hòa combines legacy Bình An, Bình Thắng, and Đông Hòa.
- New Tân Đông Hiệp combines legacy Tân Bình and the remaining part of Tân Đông Hiệp.

An explicit ward phrase in listing text may select a map lookup scope for road or landmark matching. It never rewrites `listings.ward`, filter behavior, valuation, deduplication, human feedback, or AI review. If no reliable text hint exists, the resolver uses the stored map ward and only the officially configured consolidation scopes.

## Resolution rules

- Preserve priority `exact -> road -> landmark -> ward`.
- Listings using `cách`, `gần`, `sát`, `1 sẹc`, or equivalent wording remain grouped on the named road under the approved product rule.
- Prefer a road in the explicit text ward, then the stored ward, then its official consolidation scopes.
- Same-name OSM fragments inside one ward may be aggregated only when they form one real named road or corridor. Distinct numbered roads remain ambiguous unless a project or area clue disambiguates them.
- Normalize proven aliases such as `ĐT743/743A/743B/743C`, `QL1K`, `Mỹ Phước - Tân Vạn`, and named roads only to a canonical entry in the correct scope.
- Reject price/area prose such as `5 tỷ TL 108m2`, lot dimensions, road widths, generic `kinh doanh`, and truncated marketing copy as road names.
- Correct known extraction collisions such as `Nguyễn Thái Học` being converted to `Nguyễn Thái Bình`.
- A generic or clipped KDC phrase is not a landmark. Only a stable, named residential area or project with OSM/public evidence is accepted.

## Evidence policy

- Use the pinned OpenStreetMap snapshot first.
- Prefer existing OSM geometry and aliases over new point overrides.
- Use browser-assisted Google Maps evidence only when OSM is absent and a unique named road/place or official public address supplies a bounded point.
- Every non-OSM coordinate requires a public source URL, verification date, honest radius, and an explicit boundary-mismatch reason when needed.
- No live geocoder or browser lookup is allowed in crawl, reprocess, API, or page-request paths.

## Implementation boundaries

- `services/listing_map_context.py`: extract road, landmark, and explicit Dĩ An ward hints; clip invalid suffixes and reject dimension/price tokens.
- `services/listing_location_resolver.py`: use map-only ward hints and configured consolidation scopes without altering canonical listing fields.
- `config/listing_map.py`: resolver version and narrowly approved forced OSM aggregates.
- `config/listing_map_location_sources.json`: official map-only ward scope relationships.
- `config/listing_map_location_overrides.json`: evidence-backed aliases and only necessary curated points.
- `static/maps/listing-locations/*.json`: deterministic generated artifacts.

## Testing and release gates

- Every parser/resolver behavior change starts with a literal failing test and a verified RED result.
- Test exact ward-hint precedence, stored-ward fallback, official consolidation scope, same-name ambiguity, invalid `TL` price text, QL1K/ĐT aliases, and accepted named landmarks.
- Build all four registry artifacts twice and require identical SHA-256 hashes.
- Run registry, context, resolver, backfill, and coverage suites plus a full production dry-run.
- Before apply, calculate projected per-ward moves from `ward` to `road/landmark` and inspect representative IDs.
- After apply, require a second dry-run with `updated=0`, exact per-ward counts, origin/public HTTP 200, and Browser Use proof for all seven ward filters.

## Acceptance criteria

- Every one of the seven wards has a recorded production before/after result.
- No accepted candidate uses a dimension, price-negotiation token, generic KDC prose, or arbitrary same-name numbered road.
- Current known roads and accepted local areas appear in the Maps directory instead of the ward-center group.
- Remaining ward-center listings either lack a usable clue or have an explicit deterministic ambiguity/not-found reason.
