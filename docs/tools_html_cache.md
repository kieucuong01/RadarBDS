# Tool HTML cache — P2, 21/10/2026

The application opts exactly these public HTML routes into the same short guest
policy used by the homepage: `/dinh-gia-bds`, `/bang-gia-dat-tphcm`,
`/quy-hoach-binh-duong`, `/tin-tuc`, `/bao-cao`. It requires GET/HEAD, HTML,
status 200, guest tier, no current user, no `radar_session` cookie (including an
empty one), no Authorization header, no Set-Cookie, and no existing private or
no-store response policy. Ineligible responses on those routes are private,
no-store. Detail, account, admin and commerce routes are outside this expansion.

No application HTML cache or new origin worker/pool is added. Current Nginx
microcache exact locations remain unchanged; Cloudflare can cache these HTML
responses through the ordinary origin proxy using their response headers.

## Cloudflare rollout

Application eligibility is only the code stage. The additional paths must also
be added to the existing public-read Cache Rule. Keep its private bypass rule
first, all existing settings and original five paths. The resulting public-read
expression is:

```text
(http.host eq "radarbds.vn" and http.request.method in {"GET" "HEAD"} and
 http.request.uri.path in {"/" "/api/signals" "/api/listings" "/api/counts" "/api/dashboard" "/dinh-gia-bds" "/bang-gia-dat-tphcm" "/quy-hoach-binh-duong" "/tin-tuc" "/bao-cao"} and
 not http.cookie contains "radar_session=" and
 not any(http.request.headers["authorization"][*] ne ""))
```

Preserve origin Cache-Control and Set-Cookie behavior: never force an edge TTL
that overrides private/no-store/errors. Keep the full query string in the cache
key, including report `page`, `q`, `city`, `ward`, `period`; different filters
must not share HTML. Browser TTL respects origin. Do not use a wildcard path.

Check all five exact paths for guest MISS then HIT and an Age header, plus
private/no-store and BYPASS/DYNAMIC with a harmless invalid session cookie and
an Authorization probe. Check different `/bao-cao?page=2` and ward result HTML,
and a 404 page number. Verify no session-specific content appears in guest HTML.
No load/capacity claim follows from these single-request checks.

At implementation time the Chrome Cloudflare session required login. Until the
rule is changed and HIT is verified, report CDN activation as pending, even if
the application headers are deployed. Roll back the new rule paths first, then
revert the application eligibility change if necessary. Existing homepage/API
cache behavior is unaffected.

Tests: `tests/test_public_cache_headers.py`. Production edge evidence belongs in
`docs/operations.md` after live verification, not inferred from test results.
