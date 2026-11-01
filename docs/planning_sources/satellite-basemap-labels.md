# Satellite basemap labels

Satellite imagery in listing Maps uses Esri World Imagery. Road and place labels
are separate transparent Esri Reference tiles: `World_Transportation` and
`World_Boundaries_and_Places`. They attach to the imagery layer lifecycle, so
control changes, repeated toggles, and imagery-error fallback remove both label
layers together. Only visible tiles are requested; pan requests wait until idle.
Labels overzoom from level 19 through the existing GIS maximum of 23.

Ordinary Maps entry now starts with satellite and only the partition planning
theme enabled at 50% visibility. Explicit links to another planning theme retain
their requested theme; administrative entries retain the street basemap.

The noninteractive pane (405) sits above planning images and below parcel geometry,
dimensions, and listing markers. Attribution is retained in layer configuration.
Coverage and naming follow the upstream source; not every small road has a name.

These reference services are active but legacy. Esri schedules transportation
retirement for March 2028 and boundaries/places for December 2029. Migrate to the
modern Hybrid Reference vector service before then; that needs a vector renderer
and the appropriate Esri access configuration, beyond this targeted fix.

Source checked 2026-11-01: https://www.esri.com/arcgis-blog/products/arcgis-living-atlas/announcements/sunsetting-legacy-basemaps
