# Thủ Dầu Một GIS planning pilot — 27 October 2026

Local URL: `http://127.0.0.1:5055/?tab=signals&city=THỦ+DẦU+MỘT`.
Open Maps → **Quy hoạch · Bình Dương**. All available GIS overlays across
Bến Cát and Thủ Dầu Một render immediately, independently of listing filters.
The two map-type toggles start enabled; each has its own source and opacity.
There is no ward/city picker or global enable checkbox. Existing PDFs and the
source inspector remain available for comparison. **Xem vùng có quy hoạch**
fits the currently enabled map types.

## Current coverage after the four-ward gap fix

| Layer | Coverage | Actual source |
|---|---|---|
| Partition baselines | Twelve existing ward plan-outline images, including Phú Mỹ and Định Hòa | Public GIS `SuDungDat_QHPK_HCM_V2`; verified baseline identities at 1/2,000 |
| Regional partition supplement | Previously omitted GIS pixels in Phú Mỹ, Định Hòa, Hòa Phú and Phú Tân | The same QHPK service, four exact native tiles; individual legal editions/scales remain unverified |
| Urban general plan | Existing city view plus reference ward areas previously cut at the north/east edge | `SuDungDat_QHC_HCM`; original colors/grid, unknown legal edition/scale |
| PDF alternatives | Seven retained Bến Cát document overlays | No synthetic TDM document overlays or GIS-to-PDF fallback |

The catalog has31 records:23 ready GIS images,7 retained document overlays
and1 unavailable Mỹ Phước document source. TDM has14 ready GIS records:
12 baseline partition images,1 regional partition supplement and1 general image.
All23 GIS images render by default. Partition-only renders21 images.

### Cause and correction

The earlier display was clipped to individual baseline plan outlines. Those
outlines did not cover all QHPK pixels supplied by the public GIS, particularly
in the north/east. The city general layer also used a reference city boundary
that cut part of the four user-reported ward areas. An unavailable standalone
1/2,000 ward plan did not mean that the QHPK service had no GIS content there.

The supplement uses four1280×1280 native exports on one exact EPSG:3857 grid.
`build_planning_gis_coverage.py` verifies all four source services, image/hash
pairs, dimensions and adjoining extents. It assembles pixels without RGB
resampling, limits display to the four reference ward areas, and removes every
pixel already shown by the20 existing GIS partition images. Source gaps remain
transparent. It uses **QHPK data**, not QHC imagery under a partition label.

Config: `config/thu_dau_mot_gis_supplement.json`. Binary inputs, native requests,
source mosaics and audit are in ignored
`.local/planning-ben-cat/thu-dau-mot/{gap-investigation,supplement}/`.
The four-ward snapshot geometry is a reference display window, not proof of
an approved plan boundary or cadastral completeness. Approximate diagnostic
coverage on that reference geometry changed as follows:

| Reference ward | Earlier QHPK display | QHPK display after restoring source pixels |
|---|---:|---:|
| Phú Mỹ |50.9%|100.0%|
| Định Hòa |59.7%|100.0%|
| Hòa Phú |1.7%|99.2%|
| Phú Tân |0.3%|99.6%|

These are raster-display diagnostics against approximate historic ward
snapshots, not legal planning coverage or survey accuracy. Genuine source gaps
remain. The general display mask is now a union of the old city snapshot and
all14 reference wards; old pixels are retained. Its underlying GIS source image
is unchanged. Previous general artifacts/config are saved in ignored
`general-plan/before-gap-fix/`.

The region supplement has `map_scale:null`; the global partition title no
longer claims every GIS pixel is1/2,000. Per-document known scales remain in the
inspector. Official papers still distinguish the Khu liên hợp1/5,000 context;
this patch does not assert that it has identified its approved legal boundary.

## Partition identity and geometry

| Ward | Original decision | Signing date |
|---|---|---|
| Chánh Mỹ |1270/QĐ-UBND|01/11/2012|
| Chánh Nghĩa |2970/QĐ-UBND|24/07/2014|
| Định Hòa |2309/QĐ-UBND|28/12/2012|
| Hiệp An |2308/QĐ-UBND|28/12/2012|
| Hiệp Thành |2969/QĐ-UBND|24/07/2014|
| Phú Cường |2404/QĐ-UBND|20/04/2012|
| Phú Hòa |2968/QĐ-UBND|24/07/2014|
| Phú Lợi |1669/QĐ-UBND|21/05/2014|
| Phú Mỹ |2307/QĐ-UBND|28/12/2012|
| Phú Thọ |1670/QĐ-UBND|21/05/2014|
| Tân An |1271/QĐ-UBND|01/11/2012|
| Tương Bình Hiệp |1272/QĐ-UBND|01/11/2012|

All twelve original decision/date pairs produced matching official GIS outlines
in the expected historic ward window. Original fields `SoQD`/`NgayKy` are used,
not Bến Cát's `SoQD_DC`/`NgayKy_DC` assumption. The Chánh Mỹ wrong-year
control returned transparent alpha. The builder validates one closed connected
outline, native2400×2400 grid, hashes, geographic bounds and plausible area.
Historic ward GeoJSON provides export-window hints only; it never replaces
these twelve official plan outlines.

Candidate numbers were initially discovered in a nonprimary catalogue mirror.
They were independently matched against the official GIS. The official city
[2022 planning task](https://thudaumot.binhduong.gov.vn/van-ban-du-thao/chi-tiet/moduleId/1840/controller/VBPhapQuy/action/DowloadFile?urlFile=VanBanPhapQuy%2F2022%2F06%2Fb3ac6e96-e39d-4412-94a8-b3d54c5a2ef820220603.pdf)
confirms12 named wards at1/2,000 and separates Hòa Phú/Phú Tân. Individual
original approval PDFs were not found for every ward: do not describe this as
all twelve legal documents independently verified. A baseline outline does not
prove latest land-use amendments are consolidated in the current raster.

## Earlier general-plan provenance and limits (mask superseded above)

- The official menu identifies `SuDungDat_QHC_HCM` as urban general planning.
  The image keeps native EPSG:3857 coordinates and unchanged RGB, saved lossless.
-2400px general exports timed out twice;1200px succeeded. Partition captures
  remain2400px. General is an overview and becomes pixelated sooner when zoomed.
- Only the general image uses a **reference administrative display mask** from
  the tracked geoBoundaries historic-city feature in
  `static/maps/binh-duong/legacy-districts.geojson`. This is explicitly not a
  verified QHC boundary; the config pins both GeoJSON and raster-mask hashes.
- [QĐ3544/2024, page9](https://congbao.binhduong.gov.vn/noi-dung-van-ban/1320/download)
  confirms base1702/QĐ-UBND26/06/2012, title “đồ án điều chỉnh Quy hoạch chung
  xây dựng Đô thị Thủ Dầu Một đến năm2020”. It refers to2045 as being prepared;
  no final approval was located in this research. Map scale for1702 was not
  verified. Do not relabel the GIS image1/10,000 based on another city's plan.
- Hòa Phú/Phú Tân are associated with Khu liên hợp1066/QĐ-UBND26/04/2017,
  actual1/5,000. [Official HĐND/SXD response](https://hdndbinhduong.vn/Media/ResourceAdmin/files/Tra%20loi%20kien%20nghi%20cu%20tri/Sau%20KH10/3.pdf)
  supports the decision identity. Diagnostic outline exports for1066 and522
  were empty; no official separate Khu liên hợp outline/overlay is claimed.
- Partial amendments exist (including106/2024 and3544/2024); GIS edition and
  incorporation of amendments remain unverified. No cadastral accuracy claim.

## Files and rebuild

- Catalog: `config/ben_cat_planning_catalog.json` (shared, name retained).
- Native partition config: `config/thu_dau_mot_gis_partitions.json`.
- General config: `config/thu_dau_mot_gis_general.json`.
- Captures, native masks, exact requests, audit/manifest hashes, research and
  negative control: `.local/planning-ben-cat/thu-dau-mot/` (ignored).
- Rebuild partitions from pinned captures:
  `python scripts/build_ben_cat_gis_partitions.py --config config/thu_dau_mot_gis_partitions.json --output .local/planning-ben-cat/thu-dau-mot/partitions`.
- Rebuild general from pinned captures:
  `python scripts/build_ben_cat_gis_general.py --config config/thu_dau_mot_gis_general.json --output .local/planning-ben-cat/thu-dau-mot/general-plan`.
- Start/restart `python scripts/run_planning_pilot.py` to reload the catalog.
  Loopback5055 only; no normal app/production routes enabled.

Earlier local HTTP proof verified all13 original TDM images200 and matching hashes.
Focused suite currently107 passed,2 standalone-browser cases excluded because
rendered validation uses CUA. Browser checks are recorded after completion below.


## Earlier rendered verification (before removing the ward picker)

Desktop verified thirteen TDM images and 22 GIS images across both cities.
Switching partition sources to PDF retained two general GIS images alongside
seven Bến Cát PDFs; switching back restored 22 GIS images. TDM off/on followed
by zoom restored thirteen loaded images. General opacity 0.30 was independent
of partition opacity 0.65. Selecting only Hòa Phú and Phú Tân showed one shared
city general image, with no substitute partition images.

Mobile CSS 390×844 had a 390×763 canvas, thirteen loaded images after source
switching and off/on/zoom, no horizontal overflow and no console errors. All
24 final desktop Esri street tiles loaded. GIS provider credits are deduplicated.
Viewport overrides were cleared. Screenshot: `thu-dau-mot-gis-planning.png`.
The independent reviewer hit its usage limit before findings; no review pass
is claimed. This remains local on port5055.


## Default-all interface update

The latest user instruction removes ward/city selection. Region-selection
checks above describe the previous UI. The current interface defaults to all
20 partition and2 general GIS images, with only the2 map-type checkboxes.
Source switches preserve the other type; opacity remains independent. Turning
both types off leaves the street/satellite map active. A type off/on retries
failed images while retaining Leaflet zoom cleanup and stale-event guards.

107 focused tests passed. Desktop verified22 images immediately, partition-only20,
general-only2, both off0, PDF partition plus GIS general9, restored GIS22 after
off/on and zoom, independent0.4/0.2 opacity. Mobile reopened Maps without any
selection:22 loaded images,2 type toggles, no horizontal overflow or console
errors (CSS390×845). Temporary viewport settings were cleared.


## Four-ward fix verification

111 focused tests passed, with2 standalone browser cases excluded in favor of
CUA validation. Regressions cover missing/shifted tiles, rejecting a QHC service
under the QHPK supplement, preserving native RGB and transparent source gaps,
excluding previously displayed pixels, and retaining old general-mask pixels
when expanding its reference window. New supplement HTTP200/hash verified.
Browser checks are recorded with the final verification in the task plan.


Final browser proof: default23 GIS images loaded; partition-only21 including the
new four-ward supplement with general planning disabled. PDF source7 -> GIS21;
partition off/on followed by zoom restored21 with the supplement loaded. Mobile
reopened Maps at CSS355×767 with23 loaded images and no horizontal overflow or
console errors. Restored temporary viewport settings. Saved browser screenshot
`tdm-four-wards-coverage-fixed.png` in the task visualization folder; local preview
left open on the partition view. No production deploy or independent review pass
is claimed.
