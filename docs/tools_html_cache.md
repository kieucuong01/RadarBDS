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

## Production activation verified — 21/10/2026

After the account owner signed in, the existing `Radar public read cache` rule
(`1f30c8afdd144b49bd32fcc8c76b0650`) was expanded with the five exact paths.
`Radar private bypass` (`0e0a0f0f8c674a8d9fea1bc7a1da43ed`) remains first and
unchanged. Both rules are Active. Edge TTL still uses origin Cache-Control and
bypasses when absent; Browser TTL still respects origin. Only the public rule's
expression was edited; cache-key and other settings were preserved.

All five guest routes returned MISS then HIT, with Age 0 and no Set-Cookie.
For every route, invalid-session-cookie and Authorization probes returned
`private, no-store`, `CF-Cache-Status: DYNAMIC`, and no Age. Separately warmed
`/bao-cao?page=2` and `/bao-cao?ward=Ph%C3%BA+T%C3%A2n` both returned HIT with
Age 1 while retaining 12 page-2 cards versus four Phú Tân cards and distinct
canonical URLs. `/bao-cao?page=999` returned 404, private/no-store and BYPASS.

The existing production verifier also passed after this change:

```powershell
.\scripts\verify_public_cache.ps1 -BaseUrl "https://radarbds.vn" -RequireCdn
```

It observed guest Cloudflare HIT for the homepage and all four existing public
APIs, private cookie/Authorization bypass, and valid JSON redaction. This is a
bounded functional verification, not a new load/capacity result. Application
release remains `5e8a0050f67d81d0acec85b19b2344126dd10d5f`; this activation
required no service restart, origin config change, or cache-wide purge.

For future tool-route smoke checks, request each public URL twice and inspect
Cache-Control, CF-Cache-Status and Age. Repeat with harmless probe credentials
(never copy real session values into logs). For example:

```powershell
curl.exe -sS -D - -o NUL https://radarbds.vn/bao-cao
curl.exe -sS -D - -o NUL https://radarbds.vn/bao-cao
curl.exe -sS -D - -o NUL -H "Cookie: radar_session=invalid-probe" https://radarbds.vn/bao-cao
curl.exe -sS -D - -o NUL -H "Authorization: Bearer cache-bypass-probe" https://radarbds.vn/bao-cao
```

Rollback: remove only the five new HTML paths from the public rule's expression,
retaining the original homepage/four-API allowlist and private bypass rule. Then
revert application eligibility if needed. Do not disable the whole cache rule.

Tests: `tests/test_public_cache_headers.py`. Production edge evidence belongs in
`docs/operations.md` after live verification, not inferred from test results.
