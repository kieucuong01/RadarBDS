# Satellite basemap labels

## Detailed OSM labels (2026-11-01)

At zoom 15+, satellite labels now use OSM Shortbread `street_labels`,
`place_labels` and (zoom 17+) named `pois`. No street-map background or road
painting is included. Canvas text is laid out again at each display zoom instead
of enlarging old raster text. Local street names are not filtered by road class.

The 100 KB Protomaps Leaflet 4.0.1 renderer is lazy loaded from a local vendored
file. Its one local patch rejects non-2xx vector responses before protobuf parsing;
otherwise an HTTP error could be silently treated as a blank tile. Fetches queue
at two concurrent reads and cancel on base switch/map removal. The raster Hybrid
overlay below remains the overview/failure fallback.

`/api/map-labels/osm/14/{x}/{y}.mvt` is a fixed-host, bounded gateway because both
deployed CSP headers restrict `connect-src`. It never forwards user credentials,
follows redirects, or accepts arbitrary URLs. Scope: mainland Vietnam tiles
intersecting 8–24 N, 102–110 E. Size cap 1 MB; cache 256 entries/32 MB per worker,
7-day lifetime; two upstream sessions per worker; 1,800 requests/hour/IP. Client
responses cache 7 days. No tiles are crawled or packaged for offline use.

Upstream User-Agent identifies RadarBDS with its public URL. A small visible
OpenStreetMap copyright link accompanies this layer. OSM infrastructure is best
effort; at higher sustained traffic migrate to a contracted/self-hosted Shortbread
source. See https://operations.osmfoundation.org/policies/vector/ .

Verified source data at the user's examples:

- 11.022086, 106.617125: native tile 14/13044/7687 contains `Đường ĐX 126`,
  `Đường Đx 127`, and `Đường ĐX 128`.
- 11.137674, 106.654575: native tile 14/13045/7681 contains `Đường NG2`.

## Raster overview and fallback

Satellite imagery in listing Maps uses Esri World Imagery. Road and place labels
use the transparent `World_Hybrid_Overlay` service on `who.maptiles.arcgis.com`.
It includes minor roads and landmarks beyond the former `World_Transportation`
and `World_Boundaries_and_Places` pair, with one tile request instead of two.
Labels attach to the imagery layer lifecycle, so control changes, repeated toggles,
and imagery-error fallback remove labels. Only visible tiles are requested; pan requests wait until idle.
Labels overzoom from level 19 through the existing GIS maximum of 23.

Ordinary Maps entry now starts with satellite and only the partition planning
theme enabled at 50% visibility. Explicit links to another planning theme retain
their requested theme; administrative entries retain the street basemap.

The noninteractive pane (405) sits above planning images and below parcel geometry,
dimensions, and listing markers. Attribution is retained in layer configuration.
Coverage and naming follow the upstream source; not every small road has a name.

This reference service is active but legacy. Esri schedules Hybrid Overlay
retirement for March 2028. Migrate to the
modern Hybrid Reference vector service before then; that needs a vector renderer
and the appropriate Esri access configuration, beyond this targeted fix.

Source checked 2026-11-01: https://www.esri.com/arcgis-blog/products/arcgis-living-atlas/announcements/sunsetting-legacy-basemaps

Same-tile comparison at zoom 17 on 2026-11-01 showed Bạch Đằng at
10.981, 106.650 and Đinh Tiên Hoàng at 10.777, 106.699 in Hybrid, absent from the
old transportation tile. Unnamed alleys remain unnamed; no label is invented.
Metadata: https://who.maptiles.arcgis.com/arcgis/rest/services/World_Hybrid_Overlay/MapServer?f=pjson
