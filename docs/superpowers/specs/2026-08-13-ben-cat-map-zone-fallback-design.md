# Bến Cát Maps Zone Fallback Design

## Goal

Reduce honest ward-center fallbacks for Bến Cát listings that lack a usable road but explicitly name a local zone, while preserving the resolver priority `exact -> road -> zone/landmark -> ward`.

## Decisions

- Listings with a resolvable road remain grouped on that road even when they also mention a zone.
- A listing with exactly one letter zone `Khu F` through `Khu L` in Mỹ Phước 3 resolves to that zone's OSM road-grid centroid.
- A listing mentioning multiple different letter zones is not assigned arbitrarily; it falls back to the Mỹ Phước 3 area.
- Listings in Mỹ Phước 1, 2, 3, or 4 with neither a usable road nor a single letter zone resolve to a distinct area landmark for that numbered Mỹ Phước zone.
- The Mỹ Phước 4 fallback is moved south from the reused Mỹ Phước ward center to the Thới Hòa/Vành đai 4 road-grid area corroborated by Google Maps results.
- Tân Định listings with exactly one `Khu`, `Khu phố`, or `KP` number 1 through 4 resolve to a separately verified area anchor. Multiple different khu phố numbers remain at the Tân Định ward fallback.
- `Đường Chợ Bến Lớn` is registered as a road; near/alley wording still groups the listing on that road under the existing product rule.
- All generated registry files remain deterministic and provenance-bearing. No listing's canonical ward or road fields are mutated.

## Evidence and confidence

- Mỹ Phước 3 letter-zone points are centroids of the existing OSM road grids `DF/NF` through `DL/NL`.
- Mỹ Phước 1 and 2 anchors use named Google Maps public places inside each numbered zone.
- Mỹ Phước 4 uses the N10/N12/NE8/Vành đai 4 grid and public Google Maps places rather than the legacy parent-ward point.
- Tân Định khu phố anchors use named Google Maps khu phố offices/places. Accuracy radii remain deliberately broad because these are areas, not parcel coordinates.

## Acceptance criteria

- Context tests cover single-zone, multiple-zone, and road-plus-zone precedence.
- Resolver tests cover Khu F-L, all four Mỹ Phước defaults, the corrected Mỹ Phước 4 point, Tân Định KP1-4, and Chợ Bến Lớn.
- Registry builds twice with identical hashes.
- Local dry-run shows the expected shift from `ward` to `landmark` without reducing `road` coverage.
- Full targeted tests and production backfill complete before live API/browser verification.
