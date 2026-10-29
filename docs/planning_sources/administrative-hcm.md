# HCM post-2025 administrative overlay

Reference requested by the user:
https://diaocthongthai.com/ban-do-tp-hcm-new-2025/

The public page identifies GIS Sở QH-KT as its boundary source and presents
168 units. Its public iframe uses OpenStreetMap as the base with a separately
processed administrative overlay. The rendering asset uses encrypted payloads;
GeoJSON/KML downloads are paid products, not an open raw-data endpoint. No
payload was decrypted and no paid download was obtained. The user explicitly
approved official GIS as the fallback when the ready-made source cannot be used.
Radar therefore reuses its OSM base and independently captures the same public
GIS source, rather than labelling GIS data as the publisher's processed shapes.

Verified 2026-10-29 via the public guest handshake:
`https://api-gisxaydung.tphcm.gov.vn/arcgis/rest/services/HCM/HanhChinhXa/FeatureServer/0`

The count and full geometry query returned exactly 168 distinct administrative
codes: 113 wards, 54 communes and Đặc khu Côn Đảo. Source names are retained,
including decomposed Unicode in Phường Hòa Hưng. Source geometry is WGS84 and
valid; holes and offshore islands remain. Do not replace these shapes with
old-district parcel/filter boundaries or infer an administrative split.

Capture deliberately with `python -m scripts.capture_administrative_boundaries`.
The curated public assets contain only code, source object ID, name, former
province, bounds, label point, colour and geometry. Full ward geometry keeps
source coordinates. Labels are inside the largest polygon; neighbouring
intersecting polygons get different palette entries. No owner/contact fields
or credentials are captured.

`static/data/admin_hcm_2025/overview.json` is below 1 MB uncompressed. Overview
geometry uses projected simplification with a checked 10 m display-distance
bound, then 7-decimal coordinate rounding. At zoom 13 and above the client
loads individual original ward files only for the current viewport, with at
most four requests in flight. Pending queues follow the newest viewport.
Validated data is cached for toggling/panning; hidden late responses never
restore a layer. Invalid visible detail fails closed. Full detail files total
about 7 MB but are never all requested for a province-level overview. Bump the
version query in the manifest and module when recapturing published assets.

The independent Địa giới toggle starts off on ordinary Maps and at 100% when
selected, with light 17% polygon fills and source names. Its vectors and labels
are below parcel/listing panes and do not intercept clicks. Labels are culled
when crowded. Enabling it selects the existing OSM street base; other planning
entries retain their satellite default. Users can still choose satellite.

Direct entry:
`/?tab=all&map=1&planning=administrative&region=hcm-expanded`

The mainland and Côn Đảo are included in the full-view bounds, so the first
province-wide view is broad. Enabling the layer on an existing filtered map
keeps that viewport. This is a reference display, not a certified boundary
record or a replacement for official administrative documentation.
