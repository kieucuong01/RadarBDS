# Historic area selection for QH SDĐ 2030

Updated 2026-10-30. Ordinary Maps starts at Bình Dương / Thủ Dầu Một, with
land-use 2030 at 65% on satellite. Explicit historical province links remain
usable. Expanded Đồng Nai/HCM links select the corresponding former province
for this layer; other planning themes keep their explicit opening bounds.

The Khu vực popover follows Bộ lọc. Province and district selectors use former
names; applying them frames Maps without changing the frozen listing filters.
Dragging, zooming and switching the layer off/on keep the selected province.
Only its allowlisted land-use providers are eligible. Other planning themes,
parcel lookup and their sources remain independent. The picker works before
the parcel catalogue finishes loading.

The seven supported former provinces have 85 navigation districts: Bình Dương
9, TP.HCM 22, BRVT 8, Đồng Nai 11, Bình Phước 11, Tây Ninh 9 and Long An 15.
The last two cover Tây Ninh mới; see [2030 source evidence](tay-ninh-2030.md).
Provider readiness controls
the province list. Côn Đảo is a district of former BRVT. Đồng Nai and Bình Phước
share one source template, so changing between them recreates that layer with
the selected province's existing coverage window, preserving opacity. No whole
province image archive or new tile service is introduced.

`config/planning_landuse_areas.json` is navigation metadata, not administrative
mask geometry. Bình Dương and HCM district windows are unions of the existing
official historic ward reference windows. The other district windows are
derived from the pinned geoBoundaries VNM ADM2 snapshot, represented year 2020,
OCHA ROAP / Government of Viet Nam, CC BY 3.0 IGO. The metadata records its exact
download URL, shape identifiers and SHA-256; the area menu retains attribution.
Phú Mỹ uses the snapshot's former Tân Thành geometry/name correspondence.
The snapshot does not separate Phú Riềng, so its entry is explicitly marked
`verified_2030_sample_window`, centred on the previously checked source sample
11.714, 106.953 with a 0.09-degree navigation margin. That window is not called
a district boundary; Bù Gia Mập's older navigation window can overlap it.

No district window clips raster planning pixels. Single-province providers
keep their existing bounds; only the already combined Đồng Nai source uses
separate former-province loading windows. All windows remain reference extents,
with edge-tile overlap, rather than a claim of cadastral or administrative
accuracy. See [2030 source evidence](landuse-2030.md).

Verification covers initial Thủ Dầu Một framing, independent listing filters,
all province/district counts, province-only providers at wide zoom, BRVT/island
selection, shared-source replacement, tile eligibility, opacity and popover
exclusivity. Browser checks exercise switching provinces and phone layout.

## Province-centre framing — 2026-10-30

Choosing the whole historic province now fills the viewport with its centre
instead of shrinking the image to fit every outside edge. This uses Leaflet's
inside-bounds zoom, at least one level closer than the whole-extent fit and
capped at zoom 13. It applies to province deep links, the Khu vực form and
the active 2030 layer's area shortcut. District selections retain their
fitted bounds. Province locking and current-view-only tile loading remain.
