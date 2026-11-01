# Public parcel source audit

Checked 2026-10-31. This document records source verification, not delivered
nationwide parcel coverage. Planning imagery is independent of cadastral data.

The user confirmed that no additional dataset/API credentials are available and
asked to continue with public sources. Do not use embedded third-party secrets,
copied browser sessions or bypass denied access to build an adapter.

| Source | Verified result | Integration status |
| --- | --- | --- |
| Existing HCM public GIS | Count-only queries for tested districts outside its current coverage (Bien Hoa, Long Thanh, Tay Ninh, Ben Tre and Dong Da) returned zero. | Keep current coverage guards. Widening those guards does not supply national data. |
| Guland public map | Ordinary logged-out map clicks returned candidate geometry in Dong Nai, Long An and Hanoi. Dong Nai and Long An samples also exposed sheet/parcel identifiers. Hanoi sample identity was not confirmed as a cadastral parcel. Direct cookieless HTTP request returned 403. | Public browser availability does not establish a stable server integration or nationwide coverage. No access bypass attempted. |
| Ben Tre public planning GIS | Public application scripts describe district/ward and parcel lookup routes. A boundary/planning tile response was PNG, not vector geometry. District REST requests timed out; the public UI had empty district/ward selectors and a JavaScript error. | No working geometry/search adapter verified. |
| Tay Ninh public GIS | Anonymous WFS capabilities and schema requests succeeded. The catalogue lists `cite:thuadat_chauthanh4326`, covering approximately 106.4124–106.5878 E, 10.3958–10.5325 N (Chau Thanh, former Long An). Geometry type is MultiSurface; fields include sheet, parcel, commune code and area. | GetFeature requests using WFS 1.0.0 and 2.0.0 returned HTTP 500. A WFS 1.1.0 count-only request also returned HTTP 500. Do not register based only on metadata. |
| GIS Viet Nam | The public developer page documents `vn2000.vn/api/location-info` and a sample coordinate. A normal anonymous request to that exact example returned HTTP 401, with JSON keys `success,message`. No parcel geometry was obtained. | Requires a permitted authentication path; no credentials were reused or guessed. |
| GMap Cloud | Public product documentation describes real geometry lookup by sheet/parcel and coordinate. It explicitly says parcel data does not cover every province. The public demo key is for evaluation; operational keys and parcel data access are arranged separately. | Not a verified open nationwide source. Do not ship the evaluation key as a production dependency. |
| Dong Nai GIS, former Binh Phuoc | The current official portal exposes an anonymous ArcGIS cadastral query. Count-only response: 618668 source records. Exact identifier and viewport queries returned real polygons. | Integrated in a local pilot with 111 historical administrative references; no claim of former Dong Nai or nationwide cadastral coverage. See `dongnai-parcel-pilot.md`. |

## Primary public endpoints

- HCM: https://gisxaydung.tphcm.gov.vn/tracuuttqh
- Ben Tre: https://bentre.thongtinquyhoach.vn/ban-do-quy-hoach
- Tay Ninh: https://gis.tayninh.gov.vn/
- Tay Ninh WFS metadata:
  https://geo.tayninh.gov.vn/geoserver/wfs?service=WFS&request=GetCapabilities
- GIS Viet Nam API examples: https://gis.vn/api
- GMap parcel product and coverage limitations:
  https://cloud.gmap.vn/products/parcels/
- GMap demo versus operational access: https://cloud.gmap.vn/

The Tay Ninh schema includes owner/address fields. Sample queries explicitly
requested only `featureid,sohieutoba,sothututhu,maxa,dientich,geom`; no owner or
address records were requested. The schema identifies administrative coverage,
not survey accuracy, completeness, currency or permission for redistribution.

## Remaining acceptance gates

Before enabling a source, verify real point and sheet/parcel lookups, field
allowlisting, coordinate reference system, polygon validity, coverage and source
provenance. Then implement bounded viewport loading, cancellation, cache limits,
explicit unavailable/not-found responses and tests. Preserve the current HCM
implementation until a replacement is independently verified.

Local diagnostic files are ignored under `.local/national-parcels-20261031/` and
`.local/external-parcels-20261030/`. Do not commit downloaded application bundles,
credentials, raw owner responses or runtime cadastral assets.
