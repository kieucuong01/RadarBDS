# Protomaps Leaflet 4.0.1

Upstream browser bundle: https://unpkg.com/protomaps-leaflet@4.0.1/dist/protomaps-leaflet.js

Source: https://github.com/protomaps/protomaps-leaflet

License: BSD-3-Clause, in `protomaps-leaflet-LICENSE.txt`; embedded dependency
notices are in `protomaps-leaflet-THIRD-PARTY.txt`.

Local modification: the `ZxySource` fetch checks `Response.ok` before decoding the
body. Non-2xx responses throw `Vector tile HTTP <status>` instead of potentially
decoding an error body into an empty vector tile. Covered by the satellite label
tests. No other upstream code is modified.

Dependency audit: 2026-11-01, `npm audit` for protomaps-leaflet@4.0.1 resolved
dependency tree reported zero known vulnerabilities. No npm runtime install is
required on the web server.
