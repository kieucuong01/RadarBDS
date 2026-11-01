# Coordinate lookup and province-specific planning controls

Release note (2026-11-01): coordinate/corner/OCR features are included in the
committed baseline described by [Maps agent guide](../maps-agent-guide.md).
“No production deployment” in the original verification section is historical.
This does not promote the separate, still-local Dong Nai source-adapter work to
a released feature. Recheck HEAD/worktree/deployed SHA before reporting status.

User decision, 2026-10-31: stop expanding parcel sources here. Missing provinces
and former Dong Nai remain future work. Keep the existing sources working; do
not restart national-source research as part of routine Maps work. A requested
memory note was written to Codex's ad-hoc notes folder.

## Planning choices

`RadarPlanningArea.coversProvince()` uses the selected historical province's
land-use layer IDs and explicit regional coverage. Overlapping bounding boxes
are not evidence that a different province's planning source exists.

- Former Binh Phuoc: show only land-use-2030 planning; parcel boundaries remain
  independently available from the existing source.
- Former Binh Duong: retain regional new-HCM planning, vision and administrative
  layers, historical local documents and HCM transport/corridor layers.
- New-HCM region-wide layers remain eligible in former HCM, Binh Duong and BRVT.
- Unsupported theme cards, quick buttons, opacity choices and inspector options
  are hidden. Unavailable active overlays are detached. The supported old administrative
  layer becomes the fallback when changing province would leave no active layer.
- Switching every layer off manually remains possible. Panning retains the
  selected province; district navigation does not manufacture new coverage.
- `planning-layer-dock` has no outer white fill, border or shadow on desktop or
  mobile. Individual buttons retain their own backgrounds.

## Coordinate lookup

Tờ/thửa > Tra cứu theo > Tọa độ supports:

- WGS84: latitude then longitude in decimal degrees.
- VN-2000: X/northing then Y/easting, in metres. Users must explicitly select
  a projection; the application does not silently guess from the current map.
- Whitelist: EPSG 9210 (TM-3 105°45′), 9212 (TM-3 106°15′), 5899 (TM-3 107°45′),
  3405 (UTM 48N), 3406 (UTM 49N). No arbitrary EPSG/PROJ input is accepted.
- Pyproj uses a published non-ballpark VN-2000/WGS84 datum transformation.
  Available operations report metre-level accuracy; this is not a survey
  calibration or a guarantee of cadastral boundary accuracy.
- Decimal dot or decimal comma is accepted in each separate field. Thousands
  separators, NaN, infinity, missing projection and reversed invalid axes fail
  validation. WGS84 inputs are bounded to the Vietnam reference window.

`/local-planning/parcels/coordinates.json` (production prefix `/api/planning/`)
converts coordinates before looking up actual source polygons. Existing local
catalogue hits return immediately; remote GIS is consulted only when no local
parcel covers the point. Source candidates must geometrically cover the point,
not merely have a nearby centroid or bounding box. New source coverage is not
introduced. The endpoint shares current GIS concurrency/cache/error guards.

The UI uses the existing cancellation/sequence controls, opens the actual parcel
and its basic card (planning details remain on demand), or navigates to the point with an explicit no-source-result
message. Multiple boundary hits are listed for user selection. A late coordinate
response cannot recenter the map after a manual pan.

## Verification

- Unit and route checks cover input/axis/projection guards, real catalogue hits,
  outside-source points, remote point-query membership and local-first behavior.
- JS runtime checks cover province switch/hide/restore, broader HCM coverage,
  coordinate selection independent of the sheet-search ward, and stale-response
  cancellation.
- Local HTTP and rendered UI: WGS84 (11.019333467739227, 106.61686068570627) and
  VN-2000 TM-3 105°45′ (X=1218731.680068968, Y=594528.2989532772) both select source
  ID 33013, sheet 1713 / parcel 4686, Tân An. These are public GIS test coordinates.
- No production deployment or additional province-source integration performed.

## Corner-coordinate outlines — 2026-11-01

Tờ/thửa > Tra cứu theo > Góc ranh accepts 3–100 ordered corners using the same
WGS84/VN-2000 selector. Paste two columns (first/second coordinate), optionally
preceded by sequential point numbers, separated by spaces, tabs or semicolons.
A repeated closing point is accepted. Decimal commas work within each number.

POST `/api/planning/parcels/corners.json` converts and validates the outline
locally (16 KB request cap), rejects duplicate vertices, crossed/empty rings,
invalid projections and implausibly large extents. It makes no upstream GIS
request and stores no submitted coordinates. The response has user provenance
and no cadastral ID. The existing measurement tool draws the ring and reports
edge lengths, area and perimeter; its clear button removes it. Enable the desired
planning overlay to compare. This outline is not proof of a cadastral parcel or
an automatic GIS planning-intersection result.

Scope: coordinate/corner lookup only. The unrelated Dong Nai source integration
remains outside this commit. The coordinate feature and OCR follow-up are released together when requested.

## Image scan — 2026-11-01

Góc ranh > Đọc góc ranh từ ảnh previews a local JPEG/PNG/WebP (up to 12 MB,
24 MP), supports drag cropping and 90-degree rotation, then sends only the crop
(re-encoded JPEG, up to 4 MB) to the same-origin `corners/scan.json?system=...`.
The original file and filename are not uploaded. There is no third-party OCR.

The route reads a raw body into memory, validates the raster and 8 MP cap,
normalizes with Pillow, and runs the installed native `tesseract` through
stdin/stdout. There are no image temp files, storage writes or raw OCR logs.
One OCR subprocess per Gunicorn worker, OMP thread limit 1, timeout 20 seconds,
output cap 100 KB; busy/unavailable responses fail closed. Requires the native
Tesseract CLI and `eng` data (verified on the current VPS: 5.3.4).

Only plausible numeric coordinate pairs are returned. Alphabetic/identity rows
are discarded; skipped/numbered gaps produce warnings. No letter-to-digit or
axis guessing is performed. Users edit a separate draft and explicitly confirm
they checked every coordinate before copying it into Góc ranh. OCR never draws
or requests GIS planning automatically. Existing projection and polygon guards
still apply when the user chooses Xem ranh từ tọa độ.

Closing the parcel search, changing coordinate system, selecting another image,
cancel and Maps teardown invalidate pending OCR. Uploaded pixels are not cached;
responses are `private, no-store`. Test artifacts use a synthetic four-point
coordinate table and no actual certificate/person data.
