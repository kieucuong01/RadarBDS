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

### Exterior source annotations — 2026-10-29

The Bình Dương reference raster has two yellow provider labels on transparent
background outside its planning footprint. The client clips only those two
verified polygons, defined in the source zoom-11 world-pixel grid, when creating
the affected native XYZ images. The clip scales with native coordinates, including
overzoom, without canvas processing, extra requests or replacement imagery.
The original source URLs and attribution remain available. Other providers are
not altered; this is not automatic text removal from planning maps.

Inspected original cells: `11/1630/960`, `11/1630/961`, `11/1631/961`, and
`11/1632/961`. The diagonal-label exclusions intersect 424 and 2,299 visible
pixels in the first two cells; none of their opaque pixels is a non-yellow
planning colour. The second label lies on the transparent southern margin in
the latter two cells. Source revisions must be rechecked before changing these
polygons. No cadastral boundary, map title, land symbol or source colour is
reconstructed or inferred.

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

## Đồng Nai mới — 2026-10-29

The public source's QH 2030 button (`data-name="Quy hoạch sử dụng đất 2030"`)
was checked on both `https://guland.vn/soi-quy-hoach/dong-nai` and
`https://guland.vn/soi-quy-hoach/binh-phuoc`. Both load the same combined XYZ
family: `https://s3.hn-1.cloud.cmctelecom.vn/guland9/qh-dong-nai/sdd/{z}/{x}/{y}.png`.
One layer covers both former provinces; adding two overlapping copies would
incorrectly darken their overlap at partial opacity. It remains a reference
source, never relabeled official GIS or the newly approved provincial plan.

A bounded audit sampled two zooms (13 and 17) at representative points in all
22 former district/city areas: 11 in Đồng Nai and 11 in Bình Phước. All 44
responses were 512px PNGs with 99.595–100% nontransparent tile area. A separate
four-location zoom audit found all 36 samples at levels 9–17 available; all
four level-8 samples were 403. Leaflet therefore uses native levels 9–17 in
256px XYZ cells, downsampling level 9 for a level-8 overview and overzooming
level 17 through map level 23. No authentication, paid access or bypass is used.
These are bounded samples, not proof of complete legal/cadastral coverage.

The whole-region display window is rounded outward from the coordinate range
in the official [05/NQ-HĐND annex](https://dongnai.gov.vn/uploads/binhphuoc/news/2026_03/nghi-quyet-05-thong-qua-dcqhdnai.pdf):
10°30′–12°19′ N, 106°24′–107°35′ E. Two smaller reference windows cover the
former provinces for viewport and tile eligibility, avoiding unnecessary source
requests over central Bình Dương. These rectangles are navigation windows, not
administrative or cadastral boundaries. Four negative checks at Bến Cát/Thủ Dầu
Một returned 403, supporting exclusion of those unrelated cells.

The Khu vực menu offers the combined region and each former province. A direct
entry is `/?tab=all&map=1&planning=land_use_2030&region=dong-nai-expanded`.
The allowlisted region frames Maps directly; `region` is stripped before listing
filters are restored and removed when the initial shared map closes. It retains
the planning-entry defaults: fullscreen, listings hidden, 35% visibility.
Existing listing coverage and official HCM planning/parcel bounds are unchanged.
The region notice explicitly states that Đồng Nai parcel data is not integrated.

Runtime evidence stays ignored under `.local/planning-dong-nai/`; no raster
archive, cadastral asset replacement, schema migration or server gateway is added.
