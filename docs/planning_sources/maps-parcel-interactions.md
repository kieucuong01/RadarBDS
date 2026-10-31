# Maps interaction update — 2026-10-31

Normal Maps entry opens fullscreen on street tiles with old administrative boundaries enabled. Planning layers remain off; explicit links to a chosen planning layer preserve that selection. Old-boundary hover labels contain ward and district only. A ward filter controls opening bounds and opens one zoom level closer, at least zoom 15.

Multi-listing markers open the right rail on desktop and the existing listing sheet on mobile. Closing that panel preserves Maps. Map work reports loading through a shared, nonblocking status badge; parcel searches, viewport geometry, GIS details, listing requests and basemap tiles clear their own task keys.

Selecting a loaded parcel opens basic information immediately above the layer dock. It does not request planning intersections. The detail button requests the existing GIS endpoint, retains cancellation/newest-selection guards, and reuses the response while that selection remains open. Closing or changing selection cancels the request. Failed requests can be retried.

The selected geometry supplies edge lengths, an interior area label and a RadarBDS pin. Labels use measured geometry; displayed parcel area prefers the existing recorded area. These can differ. Measurement imports the largest exterior polygon, explicitly labels the result as an approximate selected-part measurement, and retains the existing clear action. Google Maps directions use the selected parcel point only when the user follows the link.

No cadastral coverage expansion or data-source replacement is included. Existing uncommitted coordinate/Dong Nai work remains separate.
