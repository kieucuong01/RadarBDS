# Ranh desktop: hover lỗi lặp và giảm heap — 2026-11-03

User link: Tân An 11.025369,106.621156, zoom18, street, SDĐ2030, listings on.
Chrome headless 1100×700 with production APIs and baseline renderer: heap after
GC off7.55MB/on18.17MB/pan15.96MB/off11.53MB. Mouse movements produced repeated
`Cannot read properties of undefined (reading 'close')`. No long tasks were
observed in this harness; it did not reproduce a permanent browser hang.

Root bug in recently introduced hover forwarding: DOM hit-stack can resolve to
the Leaflet map container. Map has closeTooltip(tooltip), unlike a polygon's
closeTooltip(), and calling it without a tooltip throws. Guard every forwarded
close with getTooltip() and a real tooltip. This also explains why desktop hover
can fail while touch interaction appears fine; it does not prove all RAM symptoms
have one cause.

Memory changes: detach the single Polygon/MultiPolygon child from the temporary
GeoJSON wrapper before adding to visible group. Create tooltips on first hover,
not on all visible parcels. Preserve original feature, click selection and
original-geometry endpoint. Center cells first; live supplement of a loaded
snapshot precedes remaining snapshot queue. Still two requests, same cache/grid,
same geometry, max4000 displayed features and75 additions/frame.

Controlled same1200 synthetic polygons, same viewport, Chrome CPU4x, GC before
heap samples: before2402 layers/9.997MB incremental heap/981ms render; after1202
layers/7.080MB/517ms. About29% less incremental JS heap,47% shorter render in
one controlled run. This is not browser-process/GPU RAM, cold GIS latency,
physical-mobile evidence or a guaranteed FPS improvement.

Ignored evidence: `.local/parcel-memory-controlled.json`,
`.local/hcm-parcels-{before,patched}.json`, `.local/tan-an-parcels-{before,patched}.json`.
HCM center10.78,106.69 zoom17 profile also halved layer count; its network runs
are not controlled timing comparisons. Graphify structural query ran; source and
tests were checked directly. Changes local, not yet committed/deployed.

Retest exact Tân An URL with local patched module: heap on15.49MB,1115 layers;
pan14.94MB/907 layers; off11.51MB/10 layers. No page errors during the same
hover/pan sequence (baseline had repeated errors).154 JS tests and24 UI tests
passed. Heap retention after off includes the existing bounded warm cell cache;
not claimed to be a leak or total process RAM. Same-view network timings were
not controlled; no cold-GIS speedup claim.
