# TP.HCM 100-year vision reference layer

Checked 2026-10-29 against the public source page:
https://guland.vn/xem-quy-hoach/quy-hoach-chung-tp-ho-chi-minh-2025-2050-tam-nhin-100-nam

The source labels the layer **QH chung 100 năm (Dự thảo)**. Its rendered native
images use `https://r4gmiynxmeobj.vcdn.cloud/hcm-100-nam-2/sdd/{z}/{x}/{y}.png`.
Observed images are 256 px XYZ cells. The source control advertises native zoom
19. Public probes at HCM, Bến Cát and Bà Rịa returned nonempty 256 px PNGs at
12, 17 and 19; HCM probes verified 10 and 11. Levels 8 and 9 were unavailable,
so Leaflet downsamples native level 10 for overview and overzooms level 19.
Côn Đảo probes at 12, 17 and 19 were unavailable; the display window is mainland
only. The window is a loading envelope, not a verified administrative boundary
or proof of full coverage.

`planning_vision_100.json` is appended to production and local catalogues. The
independent `urban_vision_100` toggle stays off for ordinary map entries and
starts at 35%, retaining per-session opacity. Its button and source notice both
retain the draft designation. It does not replace the official general-plan GIS
family, the default 2030 layer, or the parcel-planning response. No parcel-level
classification is inferred from raster colours. Only viewport tiles load.

The client allowlists the exact template, zoom bounds, draft status and source
URL. Original attribution is retained; no account, paid access or bypass is used.
Approval, legal effect and comprehensive coverage have not been verified.
