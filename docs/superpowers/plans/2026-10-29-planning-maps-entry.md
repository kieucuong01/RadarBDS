# Planning entry and discovery

Keep `/quy-hoach-binh-duong` and its five existing specialist articles. The hub
becomes an entry to live Maps first, with the article library below. Do not
redirect or delete indexed routes or merge illustrative article maps into GIS.

- Lead with an explicit Maps headline, region/layer selection and one clear
  action: open planning on Maps. Explain parcel lookup, measurement and symbols.
- Reuse `map=1` entry; add a `planning` presentation parameter for one of the four
  existing themes. Strip it before restoring/saving dashboard filters or calling
  feed APIs. Only an explicit planning entry enables that theme at 35%; ordinary
  Maps still opens with planning off.
- Hub city choices use the five supported dashboard cities. Maps' existing
  area selector handles the other GIS areas; do not pretend unsupported listing
  filters frame those areas correctly.
- Dashboard Tools opens Maps directly and retains the current filters. A real
  href supports new tabs and fallback navigation. Other dashboard tabs switch
  to Tin rao before opening Maps. Existing tracking and modal history remain.
- Public navigation names the Maps functionality clearly, while keeping links
  to the hub, articles, source material and administrative-boundary tools.
- Editorial update dates belong to the article library, not a GIS freshness
  claim. Preserve canonical/schema, privacy, source notices and source limits.

Verify hub render/schema, filters/links, explicit-layer startup, ordinary Maps
defaults, dashboard filter retention, shared-map close and desktop/mobile flows.
Deploy only after the exact commit's CI succeeds; preserve unrelated VPS files.
