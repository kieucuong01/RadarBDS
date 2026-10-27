# Bến Cát planning pilot

User approved a Bến Cát pilot on 2026-10-25, following the proposal to release
verified layers independently. Start with the official Thới Hòa 1:2,000 zoning
plan, decision 2909/QĐ-UBND (2022-12-28), map sheet QH01 (PDF page 4).

The prototype runs on loopback only. Downloaded PDFs and derived images stay
in ignored `.local/planning-ben-cat/`. Public hosting rights and current legal
status remain unverified; no production enablement, commit, push or deploy is
part of this pilot. The old four-artifact gate remains for the legacy production
manifest; the pilot is a separately identified local experiment.

Use the existing listing Maps and Leaflet. Add one opt-in overlay control:
toggle, opacity, fit to coverage, legend, original source, and visible pilot
accuracy/version status. Preserve listings, marker clicks, filters and base
layers. Failure of the overlay must not fail Maps. Do not fabricate geometry,
transform another scale into 1:500, or infer parcel planning from approximate
listing positions.

Georeference from recorded, identifiable reference points. Preserve the source
hash, page, pixel dimensions, mask and transform, fit residuals and independent
check errors. Label alignment experimental until it passes a production accuracy
review. Keep labels/legends outside the geographic raster. Use the original
legend separately. Show only the real available layer.
