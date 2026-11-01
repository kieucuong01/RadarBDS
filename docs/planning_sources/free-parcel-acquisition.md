# Free parcel acquisition: verified paths, 2026-11-02

User scope: collect original parcel corners for former Đồng Nai and Bình Phước,
retain available planning results, and use no paid APIs/services. No nationwide
parcel expansion or production UI activation is implied by this investigation.

## Former Bình Phước: anonymous official GIS batches

The existing allowlisted source at `https://gis.dongnai.gov.vn/` returned
618,668 parcel records and exactly 618,668 unique source IDs in the verified
former-Bình-Phước administrative scope. A test for former Biên Hòa district
731 returned zero, so this does not cover former Đồng Nai.

Source query: `/arcgis/rest/services/NenDiaChinh/MapServer/1/query`.
Metadata advertises 1,000 records/query. The operator uses 500, serially, with
at least one second between request starts. A 500-ID `where ... IN (...)` GET
hit an HTTP 404 because of the long URL. Ordinary read-only ArcGIS POST using
`objectIds` succeeded: 500/500 valid source polygons, zero exclusions, 238,402
response bytes, about 1.86 seconds in that run. This is a sample timing, not a
province-wide throughput guarantee or load test.

`scripts/capture_binh_phuoc_parcels.py` is the resumable acquisition tool:

```powershell
# Default is one bounded 500-record batch.
& $py -X utf8 scripts/capture_binh_phuoc_parcels.py
# Continue all remaining batches; only after confirming no other writer is running.
& $py -X utf8 scripts/capture_binh_phuoc_parcels.py --max-batches 0
```

The ignored archive is `data/planning/binh-phuoc-parcels/`:

- `identifiers.json`: one verified sorted source ID set.
- `manifest.json`: source/scope, capture interval, ID hash, batch hashes and
  accepted/excluded/quarantined progress. `collecting` is not `complete`.
- `<offset>.geojson`: sanitized original WGS84 features; explicit invalid-source
  exclusions by source ID. Public identifiers retain the existing 10^12 offset.

Geometry batches request only OBJECTID, sheet, parcel, source area and the two
administrative codes. They never request owner/certificate/contact fields.
`DongNaiParcels` performs the existing CRS, original-ring validity, extent,
membership, field and namespace validation. Original vertices, holes and
disconnected pieces are retained. Geometry failures are not repaired.

The first long run stopped after 84,000 processed records on an unknown source
ward code. The collector now separates unverified localities without weakening
the live adapter: valid original geometry and the six allowlisted attributes
remain in `quarantined_features`, with `locality_verified=false`. No ward name
is guessed. Quarantined records are a subset of `excluded`, not accepted public
features; their IDs are raw source IDs. Never merge them into the live feature
array or treat them as verified administrative membership. Invalid geometry
and unverified locality have explicit per-source-ID exclusion reasons.

Writes replace completed files atomically; a batch only enters the manifest
after its file is complete. Resume checks every recorded batch hash and skips
its network request. Raw returned ID membership must exactly equal the requested
set; silently capped, duplicated, truncated or mismatched batches fail closed.
Completion rechecks the entire upstream ID set. A changed source leaves an
explicit incomplete/source-changed archive. This is a capture interval over a
mutable source, not a cadastral revision certificate.

Transient connection/timeouts and HTTP 500/502/503/504 retry at most twice.
403/419/429 do not retry or switch endpoints/proxies. Other source/schema errors
stop the job; the previous checkpoint remains intact.

The live trial imported 1,500 valid parcels, then resumed with two further
batches to 2,500, without redownloading prior geometry. A background local job
was then started for the remaining records. Its PID/start timestamp and logs
are recorded under `.local/free-parcel-source-20261102/`:

- `binh-phuoc-job.json`
- The receipt's `stdout` and `stderr` paths (these change on a resumed run).

Always recheck that PID/process and the current manifest. These files describe
a local job; do not call it completed, deployed or still running from this dated
note. **Only one writer may use this archive directory.**
The resumed run preserved all earlier batch hashes and passed the formerly
blocking batch. Inspect the current manifest/logs for counts rather than using
the pilot counts above as a current snapshot.

## Former Đồng Nai: boundary-image seeds plus ordinary browser clicks

The verified Guland flow exposes full polygon vertices per actual map click,
but no bulk vector/list endpoint has been verified. The former-province public
map page works through the authorized Chrome session. A new administrative-area
selector requested VIP; that locked selector was not used. No paid feature,
denied endpoint or CAPTCHA was bypassed, and no browser credential was exported.

To reduce random queries and per-parcel AI reasoning:

1. Take only boundary tiles actually observed in the rendered page. The tested
   family is `.../guland9/qh-dong-nai/thuadat/{z}/{x}/{y}.png` on the public CMC
   object store. The tested zoom-18 images contain **512 pixels**, although the
   Leaflet tile is declared as 256 CSS pixels and may be transformed again.
2. Use `scripts/create_parcel_candidate_points.py` on a small contiguous tile
   mosaic. It finds connected transparent regions, ignores the outer incomplete
   regions, and chooses a point with clearance from visible boundary pixels.
   OpenCV/NumPy are optional local operator dependencies, already installed on
   this workstation; they are not added to the web runtime.
3. Convert that pixel point to WGS84 using tile XYZ and the actual image pixel
   size. These are **lookup candidates only**, never traced parcel corners.
4. Check the local polygon archive first and skip candidate points already
   covered by a stored original polygon. Recompute screen positions from the
   currently rendered tile rectangles and reject targets under map controls,
   popups, markers or outside the visible viewport.
5. Wait for the actual tile rectangle to remain unchanged for at least 350 ms
   before clicking. Waiting only for `.leaflet-pan-anim` was insufficient: the
   site's animated recenter/zoom could still move the target by 6–16 metres.
6. Perform ordinary clicks through the authorized `cua_repl` browser API, and
   observe the corresponding `get-bound-2` response. Never replay copied
   cookies/tokens in a terminal or invoke hidden application functions.
7. Match the response sheet/parcel identity to the current popup. Retain only
   approved parcel/land-use/planning fields and record the actual requested
   `marker_lat`/`marker_lng`, without persisting other form fields or headers.
8. Require the **actual clicked point** to fall in a valid returned original
   polygon. Validate/archive with `scripts/archive_guland_parcels.py`, not with
   raster-derived geometry. Deduplicate source IDs and keep snapshot history.

The two tested boundary tiles generated 44 candidates. Three bounded browser
batches collected 15 distinct valid source polygons, all containing their actual
clicked points; those 15 are now in the ignored reference archive, in addition
to the six earlier samples. The final calibrated five-click batch took about
12.45 seconds and hit all five intended seed polygons; residual pixel-to-click
distance was about 0.23–0.24 metres. Earlier uncalibrated batches often selected
a neighbouring parcel: their source polygons were still valid for their actual
clicks, but that phase must not be presented as correct seed targeting.

The loops run deterministic image/DOM/network processing inside a browser tool
call; they do not require an LLM decision for each parcel. This amortizes agent
tokens, not source/network time. A production acquisition controller and
province-wide scheduling/coverage verification are still unfinished. Keep
browser use within supported tooling, a valid session and the requested scope.

The seeds are not a completeness proof: very small parcels, line gaps, unknown
image coverage and outer mosaic regions can be missed. Use overlapping mosaics
and coverage bookkeeping before making any province-wide claim. Stop on access
denial/rate limit, unavailable imagery or inconsistent geometry. Do not infer
source features from planning-map colours or treat a failed lookup as no parcel.

Diagnostics, actual-click checks, sanitized captures and the two tested browser
helper function sources are under `.local/free-parcel-source-20261102/`.
`browser-helpers.js` is an operator template for an authorized `cua_repl` session,
not a standalone login/crawler service or a public Maps dependency.

```powershell
& $py -X utf8 scripts/create_parcel_candidate_points.py <observed-tile-manifest.json> --output <seed-points.json>
& $py -X utf8 -m pytest tests/test_capture_binh_phuoc_parcels.py tests/test_parcel_candidate_points.py tests/test_archive_guland_parcels.py -q
```

## Planning data and release limits

Keep previously captured planning results, their exact source labels, capture
dates and unavailable states. The Guland sample label “Quy hoạch xây dựng” does
not establish a detailed 1/500 plan or an authoritative current decision.

For former Bình Phước, the existing GIS general-planning layer
`SuDungDat/ThongTinQuyHoachSDD_Cache/MapServer/6/query` returned a count of 11,853
objects anonymously. This supports investigating a one-time polygon download
and local spatial intersections instead of one GIS request per parcel, but its
complete geometry has **not** been downloaded or verified in this investigation.
The detailed-planning layer count query timed out and remains unresolved.
The background parcel job does **not** download those planning layers.

Neither archive is activated in production Maps by these tools. Do not widen
source coverage, replace existing GIS/PDF sources or expose an incomplete
archive as complete. Free anonymous responses/ordinary UI availability establish
the tested technical access path; they do not establish survey accuracy, full
coverage or a redistribution licence.
