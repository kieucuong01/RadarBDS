# Satellite basemap labels

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
