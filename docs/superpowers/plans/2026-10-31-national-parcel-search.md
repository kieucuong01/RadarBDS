# Nationwide parcel search

The active goal remains real parcel-boundary lookup nationwide, not merely
province selection, planning imagery, sample polygons or external links.

Requirements:

1. Users can locate real parcels by map position and sheet/parcel identifiers
   across all historic provinces supported by the national navigation.
2. Render source boundaries faintly on demand for the viewport, keep listing
   markers clickable, and show the selected source geometry and available
   sheet/parcel/area fields. Retain source provenance and independent planning
   overlays. Do not derive a cadastre from planning-map colours.
3. Use public sources only, as the user explicitly confirmed. No private
   credentials, paywall/403 bypass, copied sessions or owner/contact fields.
4. Preserve current HCM/Bình Dương functionality and its privacy, bounds,
   concurrency, cache, geometry-validation and cancellation contracts.
5. Persist accepted geometry with source identifiers/revisions; expose coverage
   gaps and source errors separately from a genuine not-found result. Never
   repair, relocate or infer source vertices silently.
6. Completion needs source/provider checks covering all provinces, real point
   and sheet/parcel samples, relevant automated tests, browser desktop/mobile
   interactions, exact-SHA CI, preserved VPS edits, deploy and live evidence.

Execution:

- Inspect existing catalogue/live-parcel interfaces and reuse their accepted
  feature shape. Audit public provincial GIS and third-party public providers
  for real queryable geometry before registering adapters.
- Test each discovered provider independently: public metadata, current
  geometry/schema/CRS, point and identifier lookups, bounds, not-found and
  service failures. Keep only sanitized non-personal evidence.
- Implement bounded adapters and register verified geographic coverage. Extend
  national search/selection and caching around actual working providers.
- Continue filling coverage; partial provider delivery is progress, never
  completion of the nationwide goal. Existing Guland browser samples prove
  data exists, but the direct HTTP 403 does not prove a usable server API.

Current research: public Bến Tre GIS exposes district/ward and parcel routes
in its own application bundles; its browser currently fails to populate the
district selector. Verify the public routes directly before treating that
application failure as source unavailability.
