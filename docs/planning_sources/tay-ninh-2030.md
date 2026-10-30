# Tây Ninh mới: land-use 2030 reference imagery

Checked 2026-10-30. The supported area includes former Tây Ninh (9 districts)
and former Long An (15 districts). Khu vực lists the two former provinces
separately, in keeping with the historic source maps. Bình Dương / Thủ Dầu Một
remains the default; neither western provider loads until its province is chosen.

Public source controls were observed on
[Hòa Thành, Tây Ninh](https://guland.vn/soi-quy-hoach/tay-ninh/huyen-hoa-thanh)
and [Long An](https://guland.vn/soi-quy-hoach/long-an). Both explicitly name the
button `Quy hoạch sử dụng đất 2030`. They expose these distinct XYZ families:

- `https://r4gmiynxmeobj.vcdn.cloud/tay-ninh-2030/{z}/{x}/{y}.png`
- `https://r4gmiynxmeobj.vcdn.cloud/long-an-2030/{z}/{x}/{y}.png`

The Tây Ninh city page instead initially highlights general/partition planning.
Its separately named 2030 document was inspected, but is not overlaid as a second
copy: the province aggregate returned nontransparent pixels at the city control
point too. No 2050 general-planning or annual-plan layer is relabeled as 2030.

The bounded audit used one inside-district reference point for each of the 24
former districts at zoom 13 and 17: all 48 responses were valid nontransparent
256px PNGs, including the actual sampled point. A second zoom audit at Hòa Thành
and Cần Giuộc returned valid images at all 22 controls from levels 8 through 18.
Both level-19 requests returned 404, despite a Long An UI hint of 19. Native zoom
is therefore capped at 18, with Leaflet overzooming those same cells to 23.
These are sampled coverage checks, not proof that every location has a current
or legally effective plan. Audit JSON, source-control observations and images
stay ignored under `.local/planning-tay-ninh-2030/`.

Bounds are rounded outward from the existing geoBoundaries historic district
reference windows; they are navigation extents, not cadastral masks. Attribution
and original source links are retained. Sources are public image requests with
the Radar BDS Referer, without credentials, signed access or a gateway. Loading
retains current-view cells, one-cell buffer, settled zoom updates and independent
65% opacity. Parcel/GIS coverage outside the supported HCM area is not inferred.

The client allowlists these two exact families and their observed native zoom
separately; it does not widen the bounds allowed for existing HCM/GIS providers.
Rollback removes these two catalogue records and province/district entries.
