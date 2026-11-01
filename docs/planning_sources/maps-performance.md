# Maps performance rollout — 2026-11-01

## Scope and boundaries

Maps has **not** passed a 1,000-concurrent-user public-edge test. The previous
listing/homepage capacity result does not cover parcel/GIS traffic or phone FPS.
No large load is sent to a third-party GIS during verification.

Baseline public Tân An viewport (106.614,11.020,106.620,11.025): 1,408 parcels,
15,602 vertices, 933,195 uncompressed bytes, 204,845 bytes over gzip. Two separate
requests took about 2 and 5 seconds. These are samples, not percentiles.

## Delivered application changes

* Fixed z17 public cells replace exact floating-point bbox requests. The old
  viewport route remains as rollback. Only visible cells are requested (max 36),
  two concurrent reads per browser, obsolete requests cancelled.
* An 8 MB / 32-cell browser LRU and incremental Canvas layers retain existing
  features. At most 75 features are added per animation frame, at most 4,000 in
  the current display; a dense/truncated view tells the user to zoom in.
* Shared on-disk SQLite WAL cache coordinates workers. Leases bound cold work to
  two snapshot cells plus two live cells, with no unbounded wait queue. Slow live
  requests cannot occupy the snapshot slots. Cell payloads are bounded to 32 MB / 2,048
  entries. Remote original geometry has its own 32 MB / 4,096-entry bound, retained up to
  15 minutes so a recently cached display can still resolve exact geometry.
* Snapshot and live supplementation are separate: snapshot never waits for GIS.
  Snapshot cells cache 24 hours; live cells five minutes. A 503 gets one delayed
  retry; repeated live failures cool down for 30 seconds and keep existing ranh.
* Display geometry is simplified with topology preserved (3e-6 degrees, roughly
  0.33 m at the equator). It is **not** used for edge measurements or selected-lot
  highlighting. Basic metadata appears first, then original geometry comes from
  the local snapshot/cache. Original reads never contact GIS. A missing original
  does not invent measurements. Closing/selecting another parcel cancels stale work.
* Only allowlisted basic attributes are published. No owner, contact, token, OCR
  image, or detailed planning result is added to a public cache.
* Anonymous successful cell and GIS image responses can cache in the browser.
  Cookie/Authorization/Set-Cookie/error/lookup/OCR responses remain no-store.
  No endpoint is added to `X-Radar-Public-Cache` or the listing Redis namespace.
* GIS can use one cached server composite rather than two direct images. This is
  gated by `RADAR_PLANNING_GATEWAY_FIRST=1`: code default is 0; production was
  enabled after Nginx installation on 2026-11-01. Do not funnel every user's cold image requests into
  the shared 3x4 Flask workers without that gate.

Tradeoff: a cold fixed grid can download more geometry than an exact viewport.
The benefit is sharing cells across people/pans and avoiding repeated work.
Do not claim the first cold view is always smaller or faster.

## Verification evidence

`scripts/benchmark_parcel_cells.py` runs against the local read-only snapshot,
never public GIS. A run of 1,000 warm cache reads at **16 threads** took about
0.64 s, median 6.5 ms, p95 30.6 ms. It is not HTTP or 1,000 simultaneous users.
The cold z17 grid in that run used 12 cells and 451 KB gzip in aggregate versus
201 KB for the old exact bbox. Cold per-cell simplification took about 1.67 s
total in a sequential benchmark; sharing/bounded loads are essential.

Browser pilot: Tân An snapshot cells returned in approximately 93–302 ms;
1,027 parcels remained visible despite live GIS failures. Clicking a parcel
fetched its exact original locally in 10.5 ms and made zero `/planning.json`
requests. Local listing DB/OSM source errors are separate and prevent treating
this run as complete end-to-end production performance proof.

## Origin cache installation (root, after deploying the application)

Review `scripts/install_maps_origin_cache.py` and the two `nginx-radar-maps-*`
files. The installer only changes the Maps cache include/zone and the gateway
flag, backs up exact existing files in a root-only directory, validates Nginx
before reload, and restores those files if installation fails.

```sh
cd /opt/radar-bds/current
sudo python3 scripts/install_maps_origin_cache.py --apply
```

This is a new exact-path, geometry-only cache zone, 128 MB, separate from listing
microcache. All cookies and Authorization bypass it. Upstream Cache-Control,
Vary, Set-Cookie and error responses remain authoritative. It does not touch the
Cloudflare rules. Do not claim edge caching from browser headers alone.

Before enabling a large public test, verify anonymous warm hits, cookie and
Authorization bypass, error non-caching, security headers, source failure and
recovery. Observe upstream request counts and CPU/memory/queues under 25, then
100, then 250 users; proceed to 1,000 only after those gates pass and the source
traffic is bounded. Test warm repeated regions AND distinct cold regions, pan,
zoom, cancellation, mobile rendering and p95 latency. Use mock sources or a
staging host for cold/failure tests. Never claim 1,000 RPS from 1,000 sessions.

## Rollback

Set `RADAR_PARCEL_CELLS_ENABLED=0` and restart the service to restore the original
viewport flow. Set `RADAR_PLANNING_GATEWAY_FIRST=0` and restart to retain direct
GIS image composition. Neither flag changes the immutable parcel snapshot.
For origin configuration rollback, restore the four files recorded by the root
installer, run `nginx -t`, reload Nginx and restart the app. Do not remove data or
unrelated VPS edits. Missing-province cadastral expansion remains paused.

## Public edge activation, 2026-11-01

The user completed the root install: Nginx validation/reload passed and the
service restarted active. Backup: `/var/backups/radar-bds/maps-cache-20261101-085534`.
Maps is inside the dashboard; `/maps` is not an application route.

Cloudflare rule `Radar Maps public geometry cache`
(`078d2d43fdc04c96948aea7c8ed573a8`) is active after the existing private bypass
and public-read rules. Its reviewable configuration is
`deployment/cloudflare/maps-public-geometry-cache.json`. It matches only the
named public geometry/metadata routes, GET/HEAD, no query, no Cookie and no
Authorization. Origin Cache-Control is authoritative; absent policy bypasses
cache. Lookup, original geometry, OCR, errors and private responses are excluded.
Metadata (catalog and parcel config) is public for 60 seconds for anonymous
requests only. Rollback/coverage changes may remain visible for up to 60 seconds.

The browser omits credentials on public cell, metadata, GIS composite and OSM
MVT fetches, so dashboard analytics/session cookies cannot accidentally bypass
the shared public cache. Original geometry and detailed lookups retain their
private request behavior. GIS composite blobs are aborted on layer removal and
their object URLs released after drawing. No external GIS credential is exposed.

Live checks confirmed snapshot and OSM Cloudflare HIT, Nginx GIS image HIT, and
cookie/Authorization private/no-store bypass. Invalid-release 404s remain
uncached. `X-Radar-Edge-Cache` is an origin Nginx header replayed by Cloudflare;
on a CF HIT its historical MISS value does not represent a new origin request.

Bounded external probe: 75/75 snapshot responses were CF HIT, median 137 ms,
p95 1,690 ms including fresh TLS connections. A gzip k6 probe with 100 sessions,
two cells and one cached GIS image delivered 1,563 reads with 100% HTTP 200/HIT,
read p95 528 ms and p99 753 ms. These are warm delivery measurements, not a
full browser or cold-source capacity claim. A later four-resource run stopped
at 25 sessions due to a dashboard connection timeout on the Windows client.

`radar-maps-cache-capacity.yml` repeats the complete four-resource warm profile
from an independent Ubuntu runner, gated sequentially at 25/100/250/1,000 VUs.
Each 30-second stage must pass before increasing load. It uses gzip, two parallel
requests per session and 5–6 seconds think time, requires all keys prewarmed,
and aborts on cache/privacy/error violations. Results are retained even on
failure. It does not exercise cold regions, live GIS or detailed lookups, and
1,000 VUs does not mean 1,000 simultaneous requests or 1,000 RPS. Mobile render,
cold-source/failure scenarios and mixed real browsing require separate evidence.
