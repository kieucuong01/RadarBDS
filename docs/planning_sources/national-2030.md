# National historic-province land-use 2030

Checked 2026-10-30. The Khu vực picker supports 63 former provinces/cities and
710 historic district reference windows. The existing Bình Dương / Thủ Dầu Một
default, satellite, 65% visibility, listing filters and other planning themes
are unchanged. This extends reference 2030 imagery, not cadastral or official
construction-GIS coverage outside the existing HCM service area.

## Source evidence

The public `#btn-2030` control was observed in an ordinary browser on each
province's `https://guland.vn/soi-quy-hoach/<province>` page. Tây Ninh retains
the previously observed Hòa Thành 2030 control. Each explicitly identifies
land-use 2030, rather than annual land-use, partition, general or draft plans.
Examples: [Hà Nội](https://guland.vn/soi-quy-hoach/ha-noi),
[Đà Nẵng](https://guland.vn/soi-quy-hoach/da-nang),
[Cần Thơ](https://guland.vn/soi-quy-hoach/can-tho).

Exact templates and compact image-sample evidence are committed in
`config/planning_landuse_2030_audit.json`. The bounded audit requested 1,199
distinct public tile URLs, at most four simultaneously, without credentials
or access bypass. It includes eight zoom controls per province plus one
reference point in each of 710 source district entries. 694 district points
had nontransparent imagery at the sampled coordinate; every province had
positive samples. Empty point names are retained in the audit. These are point
checks, not proof of continuous coverage, current legal effect or parcel accuracy.

Some sources have no low-zoom pyramid. Their measured native minimum is retained,
with display starting at most one level below it; lower map zooms remove the
provider instead of requesting hundreds of high-resolution cells. The UI asks
the user to zoom in there. The selected province opens at a useful source zoom.
Sources are conservatively capped at checked native levels 17 or 18 and
overzoom through map level 23. The existing Bình Dương native cap remains 17.

## Navigation and rendering

The existing seven provinces/85 district entries are preserved. Additional
reference extents come from the pinned geoBoundaries 2020 ADM1/ADM2 downloads
recorded with hashes in `config/planning_landuse_areas.json` (OCHA ROAP /
Government of Viet Nam via geoBoundaries, CC BY 3.0 IGO). Where no unambiguous
historic shape matched, a small public-source coordinate window is explicitly
marked `verified_source_coordinate_window`. These are navigation aids, not
administrative or cadastral masks. District/city names with identical short
names retain their type to distinguish them. Province overview focuses the
largest mainland polygon; outlying island districts retain separate windows.
Former BRVT uses its verified mainland provider extent for the initial focus,
so the province/island union cannot centre the opening view in the empty sea.

Only the chosen former province's allowlisted provider IDs are eligible.
Combined sources such as Bắc Giang/Bắc Ninh and Đồng Nai/Bình Phước do not
enable a second simultaneous province. Viewport cells and one-cell buffer load
after settled zoom/pan. No raster archive, VPS gateway or nationwide preloading
is introduced. Original source attribution is retained. The 2026-10-31 branding audit covers all 63 registered layers / 61 unique
providers. It retains the previous 13 footprints and replaces 134 visually
confirmed logo footprints in total. Original source links remain accessible.
No arbitrary land-colour matching runs in the browser.

Client validation uses exact server-generated descriptors for each registered
2030 source, including ID, URL, bounds, native/display zooms and coverage windows.
It rejects injected `source_tiles`, changed hosts/queries, draft labels and
expanded bounds. Official GIS and all other families retain their previous
allowlists and geographic limits. Catalogues stay bounded at 256 entries after adding separate old/new nationwide administrative overlays.

Rollback reverts this release's config/code; no DB migration or parcel asset
replacement is needed. Full audit images/DOM captures remain ignored under
`.local/planning-national-2030/`.


## Branding audit, 2026-10-31

Curated coordinates and source mosaic digests: `config/planning_reference_branding.json`.
Publish with `python -m scripts.build_planning_branding`; generated registry
`static/js/main/planning_reference_branding.js` loads before the overlay module.
An explicit empty entry means no logo observed in the sampled imagery, not an
unknown or forgotten provider. Shared providers are deduplicated. The audit
sampled 3,818 overview cells plus 158 mainland-detail cells, at most four source
requests in flight. BRVT/Dong Nai 512-pixel images were normalized to their
256 CSS-pixel footprint. Empty, unavailable and forbidden cells are recorded;
no access restriction was bypassed. Khánh Hòa / Đà Nẵng mainland detail was
checked separately because their low-zoom bounds also include distant islands.

Gold-pixel/template scans only proposed candidates in the offline audit; every
published footprint was reviewed, a Kiên Giang land-colour false positive was
rejected, and small embedded Lâm Đồng / Phú Thọ / Quảng Nam / Quảng Trị logos
were checked separately. Client code only clips those fixed footprints and
places the existing RadarBDS SVG at the same geographic position. No OCR,
image processing, proxy or whole-province raster download is added to Maps.
Toggle/opacity cleanup is unchanged. All source images/contact sheets remain
ignored under `.local/planning-branding-national-20261031/`.

These positions describe the currently sampled provider edition. New source
logos/editions require another review; the renderer does not erase arbitrary
new pixels automatically.
