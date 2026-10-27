# Thủ Dầu Một GIS planning extension

**Goal:** Extend the existing local planning picker to all fourteen historic Thủ Dầu Một wards, using the same native GIS sources and independent partition/general controls as Bến Cát.

**Architecture:** Reuse the partition export/outline builder and the city general-plan builder. Add hash-pinned configs and catalog rows; keep binary captures ignored. Only verified plan identities can be labelled ready; missing standalone ward plans remain visible with an explicit reason.

**Constraints:** Local5055 only. Preserve Bến Cát GIS/PDF artifacts and unrelated dirty changes. Do not bypass GIS authentication/WAF or infer a map scale from a different plan category. Historic wards match the dashboard's valuation geography.

- [x] Research official partition decision/date pairs, general-plan reference and actual map scale.
- [x] Capture native GIS data and validate footprints, pixel grids, hashes and coverage; record missing-source evidence.
- [x] Add Thủ Dầu Một catalog entries and make the shared picker title cover both cities. Keep source toggles and opacity independent; open on the dashboard's city where possible.
- [x] Add focused regressions for both-city selection, same-area identity, native captures and missing-source behavior. Run relevant tests and verify desktop/mobile rendering, source switching, off/on and zoom.
- [x] Document current coverage, source dates and limitations; leave local preview available.


## Verified outcome

- Twelve native QHPK 1/2,000 layers and one public QHC GIS image cover the
  historic city view. Hòa Phú and Phú Tân explicitly lack verified standalone
  1/2,000 sources; their general view remains available. Diagnostic filters did
  not find a separate Khu liên hợp outline.
- General scale and legal edition remain unverified (`map_scale: null`). Its
  display mask is the hash-pinned geoBoundaries administrative snapshot, with
  an explicit statement that it is not an official plan boundary. A 1,200 px
  general export succeeded after two 2,400 px timeouts. Partition images remain
  2,400 px. No authentication or WAF bypass was attempted.
- All 107 focused tests passed; two standalone browser cases were excluded
  because rendered verification used CUA. All thirteen TDM image endpoints
  returned 200 and matched manifest hashes.
- Desktop: 22 GIS images across both cities; switching partition sources gave
  seven retained PDFs plus two general GIS images, then restored 22 GIS images.
  TDM off/on followed by zoom restored thirteen loaded images. General opacity
  0.30 remained independent of partition opacity 0.65. The two new-town wards
  selected one shared city general image.
- Mobile CSS 390×844: canvas 390×763, thirteen loaded images after source
  switching and off/on/zoom, no horizontal overflow or console errors. All
  24 final desktop street tiles loaded. GIS provider credits are deduplicated.
- Viewport overrides were cleared and the local TDM preview was left open.
  Screenshot: `thu-dau-mot-gis-planning.png` in the task visualization folder.
- The independent reviewer hit its usage limit before returning findings, so
  no independent review pass is claimed. Source distinctions, runtime changes
  and test/browser evidence were reviewed by the coordinator.
- Local only: no commit, push, deployment or scheduled task.


## Superseding user instruction: all areas by default

Removed ward/city checkboxes and master toggle. Both GIS map types now render
all available overlays automatically, without consulting the dashboard city
filter. Retained independent type/source/opacity, source inspection and a
fit-to-coverage button. Removed obsolete area-picker state and CSS. Replaced
selection-specific runtime tests with default-all, independent-type, missing
source, retry/zoom, stale callback and disposal regressions.

107 focused tests passed. Browser:22 default GIS images;20 partition only;
2 general only;0 when both types off;9 when partition switches to retained PDFs;
22 after restoring GIS and type off/on plus zoom. Independent opacity0.4/0.2.
Mobile CSS390×845 reopened directly with22 loaded images, no area picker,
no horizontal overflow or console errors. Local-only; no deployment.


## User-reported gaps: Phú Mỹ, Định Hòa, Hòa Phú, Phú Tân

Investigation confirmed real QHPK source pixels outside the baseline plan
outlines. The general administrative display mask also cut northern/eastern
reference ward areas. Broad exports timed out; four small public GIS exports
succeeded on an exact shared native grid, with no authentication/WAF bypass.

Added a QHPK regional supplement containing only real source pixels not already
shown by existing partition images. It preserves native RGB and source gaps;
it does not use general-plan data as a partition substitute. Retained all twelve
TDM baseline captures. Replaced the two unavailable ward-placeholder rows with
one explicit regional GIS supplement, whose legal scale/edition remain unknown.
Global type titles no longer force1/2,000 onto that supplement. General display
window expanded by union with reference ward geometries, retaining old pixels.

Current catalog31 rows;23 GIS and7 PDF overlays ready,1 document unavailable.
Partition-only21 images.111 focused tests pass; source/hash/grid/exclusion and
source-classification regressions included. HTTP supplement200/hash verified.
All binary source inputs, requests, mosaic, backups and pixel coverage audit are
ignored under `.local/planning-ben-cat/thu-dau-mot/`. Only local5055 updated.


Final browser proof: default23 GIS images loaded; partition-only21 including the
new four-ward supplement with general planning disabled. PDF source7 -> GIS21;
partition off/on followed by zoom restored21 with the supplement loaded. Mobile
reopened Maps at CSS355×767 with23 loaded images and no horizontal overflow or
console errors. Restored temporary viewport settings. Saved browser screenshot
`tdm-four-wards-coverage-fixed.png` in the task visualization folder; local preview
left open on the partition view. No production deploy or independent review pass
is claimed.
