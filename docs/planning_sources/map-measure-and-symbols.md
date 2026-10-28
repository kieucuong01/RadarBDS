# Drawing measurements and land symbols

The three controls sit below the planning-opacity slider: draw, delete and land
symbols. No additional map library or server geometry storage is used.

## Drawing

Click/tap to add vertices. Edge labels show metres/kilometres; moving the pointer
previews the next edge. Click the first vertex or choose **Khép ranh** to close
the polygon and show area in m² (also hectares above 10,000 m²) and perimeter.
**Lùi điểm** removes the last draft vertex. Escape pauses the draft, and drawing
again resumes it. Opening a lookup or legend panel also pauses the draft. Enter on the focused map adds its current centre, allowing
keyboard panning plus point placement. Delete clears the entire manual outline.
Starting another outline after closing replaces the previous manual drawing.

Measurements use great-circle edge lengths and a spherical area with radius
6,371,000 m, matching Leaflet's earth-distance convention. They are approximate
map measurements, not cadastral/legal areas. Geometry uses geographic coordinates,
so zooming or dragging does not alter the completed result. Crossing edges,
duplicate vertices, zero-area shapes and more than 100 draft points are rejected.

While drawing, parcel and listing targets yield clicks to the map; existing
parcel selection closes and its pending response is cancelled. The original
double-click zoom state is restored when drawing stops. Closing Maps disposes
the outline, preview animation and listeners. Drafts are session-local and are
not transmitted to a new API.

## Symbols and provenance

`static/data/planning_symbols.json` is a 2026-10-29 reference snapshot, loaded
only when the symbol panel first opens. It includes:

- 333 original renderer entries and 20 × 20 PNG legend swatches from the exact
  six GIS service families used by partition/general/detailed overlays. Primary
  and supplementary groups remain separate. Detailed hatching and picture fills
  use original source legend images rather than invented flat colours.
- 67 land-use codes and reference RGB colours from section 9.7, PDF pages 81–83
  (printed pages 82–84), of the [official gazette copy of 08/2024/TT-BTNMT](https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2024/7/42595/51505-1-2024991-99208-2024-tt-btnmt.pdf#page=81).
  This dated reference is identified separately from each planning scheme's own
  legend; it is not a claim that every plan or 2030 raster uses this palette.

Each group includes its source URL and captured-source SHA-256. GIS metadata and
legend capture used the same public guest handshake as the official app; no
guest token or user/parcel information is included in the asset. Sources:

| Theme | Primary renderer | Supplementary renderer |
|---|---|---|
| Partition | `SuDungDat_QHPK_HCM_V2/MapServer/2` | `QHXD_SDD_2025_QHPK_V3/MapServer/0` |
| General | `SuDungDat_QHC_HCM/MapServer/1` | `QHXD_SDD_2025_QHCDT/MapServer/0` |
| Detailed | `SuDungDat_QHCT_HCM/MapServer/1` | `QHXD_SDD_2025_QHCT/MapServer/0` |

Renderer URLs start at `https://api-gisxaydung.tphcm.gov.vn/arcgis/rest/services/HCM/`;
swatches come from each service's `/MapServer/legend?f=json`, matched by source
value and layer ID. The official [GIS user guide](https://api-gisxaydung.tphcm.gov.vn/resources/LuuTruQuyHoach/document/Tai%20lieu%20HDSD%20ung%20dung_Tra%20cuu%20thong%20tin%20QH.pdf)
also distinguishes purpose-code lookup and source colour legends.

Search matches unaccented code/name text. If no planning layer is enabled, or
2030 is selected, the panel defaults to common land codes. An enabled GIS theme
opens its own legend; PDF/image alternatives expose existing original legend
images and source links. Unknown symbols remain unknown rather than being
silently assigned another scheme's colour. Existing cache/privacy rules and
planning-layer defaults remain unchanged.
