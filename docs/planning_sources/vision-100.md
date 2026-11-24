# TP.HCM 100-year planning layer

On 2026-11-24 the Guland map control “QH chung 100 năm (phê duyệt)” displayed
two XYZ image layers in Gò Vấp. The catalogue loads both from
`https://datacdn2.guland.vn/qh-hcm-100nam/` with land use (`sdd`) underneath
transport (`giao_thong`). The former draft source is retired.

- [Official decision 7308/QĐ-UBND, 31 October 2026](https://qhkt.hochiminhcity.gov.vn/Uploads/Document/Legislation/7308_QD_UBND_Pheduyet_QHTT_TPHCM.pdf)
- [Source map at the verification point](https://guland.vn/soi-quy-hoach?lat=10.847771443414&lng=106.646657911)

Both layers served 256 px tiles at zoom 17. The sampled zoom 9 tiles returned
404 and zoom 10 returned images. The land-use sample also loaded at zoom 19.
The transport sample returned 404 at zooms 18 and 19, so the viewer overzooms
transport from 17. The mainland loading envelope does not establish island or
parcel-level coverage. Both sources share one toggle and opacity control.

A zoom-10 overview of the mainland showed no visible Guland watermark on the
sampled land-use or transport images. Radar BDS uses the raster layers directly,
without the source website's controls, markers or logo. Higher zooms were not
exhaustively inspected for marks embedded in the source pixels.
