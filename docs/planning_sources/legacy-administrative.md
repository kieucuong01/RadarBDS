# Old administrative boundaries (63 provinces)

The independent `administrative_legacy` theme is labelled **Địa giới (cũ)**.
The existing `administrative` theme is now **Địa giới (mới)**; existing links
using `planning=administrative` remain compatible. Enabling either boundary
theme switches off the other boundary theme, without changing other planning
layers. Both use the street basemap by default and 100% visibility.

## Reference snapshot

- Public source: https://github.com/phuongnt-oe/vietnam-polygon-export-tool
- Revision: `f5ea3e3225b9af3534d293ac42dafa0ab82f9c85` (archive added 2026-05-21).
- Archive: `data/ward_polygons.zip`; Git blob SHA-1:
  `d9bb9e9705603b2ce555543834e8740ba025156b`.
- 10,038 unique ward polygons in 63 old provinces and 692 district names.
- All source geometries are valid MultiPolygons; coordinates are retained in
  individual detail files. No geometry repair or inferred subdivisions.
- The upstream does not specify an exact survey/effective date or a data
  licence. Do not describe this as certified government GIS or as a complete
  legal snapshot immediately before 1 July 2025. Old names and divisions can
  differ from subsequent adjustments. Source attribution is retained.
- `wardCode` is the upstream identifier, **not** an official GSO commune code.
  It must not be joined to cadastral lookup or cadastral area IDs.

`config/planning_administrative_legacy.json` contains 63 province-scoped layers.
The existing old-province picker selects exactly one. Full geometry files and
10-metre simplified overview files live under `static/data/admin_vn_legacy/`.
Only the selected province's overview is fetched; full wards load in the visible
viewport at zoom 13+, with at most four detail requests in flight per source.
Hover shows ward, old district and province; click zooms to that ward. Drawing
and listing-marker priority reuse the existing boundary renderer.

Rebuild with:

```powershell
python -m scripts.capture_legacy_administrative --archive <ward_polygons.zip>
```

The builder verifies the pinned archive's Git hash, unique source IDs, all 63
province-name matches, geometry validity, geographic bounds, and the exact
10,038 count. `capture_national_administrative.publish_registry` includes both
eras while retaining their individual code allowlists, counts, geographic
limits and bounded geometry complexity. The higher polygon-part limit for
Tuần Châu preserves its 747 island parts; it does not relax unrelated datasets.

The combined planning catalog cap is 256 entries (197 on the live setup).
No nationwide cadastral/parcel expansion is part of this change.
