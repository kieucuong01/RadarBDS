# Transport reference overlay

Checked 2026-10-29 on the public Guland map:
https://guland.vn/soi-quy-hoach/tp-ho-chi-minh

The visible Metro control (`hcm-metro-layer`) advertises the public XYZ template
`https://s3.hn-1.cloud.cmctelecom.vn/guland7/metro-hcm-3/{z}/{x}/{y}.png`
and native maximum 19. Its rendered transparent PNGs contain rail lines and
station names. The regular construction-map view also renders
`https://r4gmiynxmeobj.vcdn.cloud/hcm-road-2/{z}/{x}/{y}.png`, a transparent
road network with major corridors. The source hides this road overlay while
its Metro mode is active. Radar combines the road layer below metro so both
are available through the requested single transport toggle. It does not
classify route approval, construction progress or existing/planned status
from colours. The two original source attributions remain available.

Actual 256 px PNGs at HCM (10.8, 106.68) verified native 12, 17 and 18 for
both families; metro 19 also returns a valid transparent cell. Levels 9–11
were unavailable. Road 19 was unavailable. The configuration therefore
downsamples native 12 for overview, caps roads at 18, and metro at 19.
Bến Cát samples were empty or unavailable; Bà Rịa and Côn Đảo samples were
unavailable. The loading envelope [[10.35,106.35],[11.2,107.05]] is restricted
to the old HCM vicinity; it is neither an administrative boundary nor proof
of complete coverage. Do not claim coverage across the expanded municipality.

The public official GIS https://gisxaydung.tphcm.gov.vn/tracuuttqh was also
reviewed: QH Chuyên đề → Quy hoạch chuyên ngành → Hệ thống giao thông lists
Tim đường, Chỉ giới and Giao thông. A separate Giao thông hiện trạng group
exists. No corresponding public transport/metro service endpoint, matching
legend or publication status was verified; direct metadata reads timed out.
Those GIS groups have not been relabelled as an independently verified metro
source. Use a verified official service if it becomes available.

`planning_transport.json` supplies two reference entries under `transport`,
with exact URL and native-zoom validation. QH Giao thông starts off on ordinary
Maps; its first enable uses 100%, and subsequent toggles retain the chosen
visibility for that map session. It sits above other planning rasters, below
parcels and listing markers, and does not intercept clicks. Images load only
for the visible viewport. Ordinary Maps still starts with land-use 2030 at
65% on satellite. Direct entry: `/?tab=all&map=1&planning=transport&region=hcm-legacy`.
