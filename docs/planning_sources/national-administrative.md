# New administrative provinces nationwide

The Địa giới layer covers all 34 new provinces/cities, with 3,321 commune-level
units. TP.HCM's existing official GIS snapshot (168) and Đồng Nai's existing
open snapshot (95) remain. The other 32 provinces add 3,058 units from the
same open source used for Đồng Nai:

- Source: https://github.com/thanglequoc/vietnamese-provinces-database
- GIS provenance: https://github.com/thanglequoc/vietnamese-provinces-database/blob/master/docs/gis/README.md
- Reference publication: https://sapnhap.bando.com.vn/
- Pinned revision: `8b78ba5118715e1fa81769286724db79346abf52`.
- The upstream GIS directory was last changed at revision
  `15723a576946472d44ed3e81f2b89f652fd76885` on 2026-09-20, according to its
  public commit history checked on 2026-10-31.
- MIT copyright/licence is retained in `static/data/admin_vn_2025/LICENSE.txt`.

These are public reference administrative polygons, not cadastral boundaries
or certified legal boundary records. No owner, contact or parcel information
is included. Cadastral source expansion remains paused.

## Build and validation

`python -m scripts.capture_national_administrative --source <audit-folder>`
checks each downloaded ward file against its pinned Git blob SHA-1, matches
every ward code/name against the same revision's province/ward list, and
requires complete counts and valid polygons. Raw files stay in ignored
`.local/administrative-national-20261031/`.

`config/planning_administrative.json` contains all 34 layers and explicit
`coverage_provinces` for the old-province picker. Every one of the 63 old
provinces maps to exactly one new administrative province. A selected old
province can therefore show the broader new province that contains it.

Overview shapes are simplified within a checked 10 m distance. Full detail
retains source coordinates, holes and islands. If rounding makes a very narrow
overview ring invalid, the builder retains unrounded coordinates or the valid
original geometry instead of repairing the source. Commune-level details
are separate files, requested only for the viewport at zoom 13+ (four in flight
per active source). Hover names, click-to-zoom, drawing/parcel/marker priority,
and source-specific caches reuse the existing renderer.

The generated `static/js/main/planning_administrative_sources.js` is the exact
client allowlist: ID, URL, count, bounds, source, code membership and bounded
vertex limits. It loads before the renderer. New provinces do not broaden the
HCM geographic limits or allow arbitrary external URLs. The catalog is bounded
at 160 entries to accommodate the 32 additional layers; Maps does not load all
province geometries together.

Keep the 34-province/count/geometry/old-province coverage checks and the existing
HCM/Đồng Nai tests when refreshing this snapshot.
