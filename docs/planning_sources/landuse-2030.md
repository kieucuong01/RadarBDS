# Reference land-use planning 2030

Checked on 2026-10-28. The public Guland map exposes a distinct `QH 2030`
button whose `data-name` is `Quy hoạch sử dụng đất 2030`. This family is not
substituted with urban-general, partition, annual land-use, or draft layers.
The official construction-GIS services inspected do not establish a separate
district land-use-2030 tile family; construction land-use layers are not renamed.

Public source controls and observed XYZ templates:

| Historic area | Public map | Image template | Source pixels |
|---|---|---|---:|
| Bình Dương | https://guland.vn/soi-quy-hoach?lat=10.9734489&lng=106.6823185 | `https://r4gmiynxmeobj.vcdn.cloud/binh-duong-2030/{z}/{x}/{y}.png` | 256 |
| HCM | https://guland.vn/soi-quy-hoach?lat=10.7758&lng=106.7009 | `https://r4gmiynxmeobj.vcdn.cloud/tp-ho-chi-minh-2030/{z}/{x}/{y}.png` | 256 |
| BRVT, including Côn Sơn | https://guland.vn/soi-quy-hoach?lat=10.358631823279&lng=107.09023345145 | `https://s3.hn-1.cloud.cmctelecom.vn/guland9/qh-brvt/sdd/{z}/{x}/{y}.png` | 512 |

Requests with Radar BDS Referer returned public PNGs without any account,
credential, signed query or paywall bypass. The 512px BRVT images occupy 256px
XYZ cells as on the source. Native zoom is capped at the observed level 17;
Leaflet overzooms those same georeferenced cells through level 23.

A bounded 26-tile audit sampled zooms 13 and 17 at Thủ Dầu Một, Bến Cát, Dĩ An,
Thuận An, Bàu Bàng, Quận 1, Củ Chi, Thủ Đức, Vũng Tàu, Bà Rịa, Phú Mỹ,
Xuyên Mộc and Côn Sơn. Every sample returned 200, valid PNG dimensions and
nontransparent pixels. Coverage ranged from 70.118% to 100% of the sampled
tile. This is not proof of complete area coverage or legal validity.

Border controls: HCM's tile intersecting Tân An contains some source pixels,
but is transparent at the actual tested Tân An coordinate, whereas Bình Dương's
tile is opaque there. HCM's Bến Cát tile is fully transparent. Bình Dương's
tile at Quận 1 is 404, so its display window is tightened to the outward-rounded
union of the existing 91 historical administrative reference windows. The HCM
window similarly contains all 320 source ward windows but stops north at
11.161°. Production QA at Bến Cát found six missing HCM tiles at zoom 12, row
1919 (south edge 11.1784°), outside every historic HCM ward. The tighter window
avoids that unnecessary row rather than hiding real source errors. Mainland
BRVT and island windows stay separate to avoid loading a wide empty sea.

## Integration and limitations

`config/planning_landuse_2030.json` supplies four geographic providers under
one `land_use_2030` UI toggle. Both production and the local pilot append them
to the catalogue. The client allowlists the exact three observed templates,
retains the source as `guland`, and refuses to relabel it official GIS.

The layer is off initially and starts at 35% opacity. Only current-view tiles
and a one-cell buffer are requested, after the user enables the layer; no
server-side snapshot or tile cache is added. The browser loads public image
URLs directly, keeping this traffic off the VPS. Source attribution and an
open-source-page link remain visible. Other sources and their independent
opacity, parcel clicks and listing-marker priority remain unchanged.

Guland aggregates reference material. Approved source documents, all subsequent
amendments, current legal effect and cadastral accuracy have not been verified
for every image. No authoritative per-parcel 2030 intersection is synthesized
from raster colors. Parcel information continues to show only data returned by
the existing official GIS lookup. Empty/failed imagery never establishes that a
location has no planning; failures leave the street map usable.

Rollback: revert this code/config commit. The immutable parcel asset is not
changed and no DB migration or additional service permission is required.
