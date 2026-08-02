# Cloudflare Origin-Shield Design

## Status

This design is the measured continuation of the approved homepage performance plan. Distributed run `30698414443` stopped at `default-100`: all 11,096 HTTP requests and all 33,288 response checks passed, but p95 was 2.24 seconds and p99 was 3.10 seconds. During the same interval the origin stayed healthy: CPU peaked around 14%, PostgreSQL and Redis remained bounded, services stayed active, and listen overflow/drop counters did not increase.

The direct public path is the bottleneck. Compressed external runs plateau around 1.2-2.2 MB/s, while a same-host 500-VU diagnostic delivered about 8 MB/s with p95 below one second. The direct origin therefore cannot satisfy the original 1,000-5,000-VU public gate by increasing Flask, Gunicorn, PostgreSQL, or Redis concurrency.

Cloudflare is not currently active for `radarbds.vn`: DNS resolves directly to `103.90.226.230`, the authoritative nameservers are Vietnix, and public responses do not contain `CF-Ray` or `CF-Cache-Status`. The user's authenticated Vietnix account contains the domain, VPS, and Object Storage service, but no CDN product. The available Chrome session is not authenticated to Cloudflare. No account is created and no service is purchased by this design.

## Goal

Put a globally distributed cache in front of the existing guest read path without changing application URLs, freshness, private behavior, redaction, database bounds, or the release gate:

- cache only `GET`/`HEAD` requests for `/`, `/api/signals`, `/api/listings`, `/api/counts`, and `/api/dashboard`;
- keep the complete normalized query string in the cache key;
- use the origin's 15-second freshness policy and bounded stale revalidation;
- bypass every request carrying `radar_session` or `Authorization`;
- never cache `Set-Cookie`, private, no-store, non-2xx, mutation, admin, saved-listing, phone, or original-source responses;
- require Cloudflare evidence in every capacity shard before resuming the 100/500/1,000/5,000 stages;
- keep Nginx as the origin shield and rollback target.

## Cloudflare zone configuration

The zone must first import every existing DNS record. Before changing nameservers, compare A/AAAA/CNAME/MX/TXT/CAA records against Vietnix and preserve mail and domain-verification records exactly. Proxy only the web records for `radarbds.vn` and `www`; do not proxy mail records.

Use SSL/TLS mode **Full (strict)**. The origin already serves a valid certificate and HTTPS; Flexible mode is forbidden. Keep Always Use HTTPS enabled only after confirming the existing redirect and canonical behavior remain unchanged.

Create the cache rules in this order.

### Rule 1: Radar private bypass

Expression:

```text
(http.host eq "radarbds.vn" and http.request.method in {"GET" "HEAD"} and
 (http.cookie contains "radar_session=" or
  any(http.request.headers["authorization"][*] ne "")))
```

Action: **Bypass cache**.

### Rule 2: Radar public read cache

Expression:

```text
(http.host eq "radarbds.vn" and http.request.method in {"GET" "HEAD"} and
 http.request.uri.path in {"/" "/api/signals" "/api/listings" "/api/counts" "/api/dashboard"} and
 not http.cookie contains "radar_session=" and
 not any(http.request.headers["authorization"][*] ne ""))
```

Settings:

- Cache eligibility: **Eligible for cache**.
- Edge TTL: **Use cache-control header if present, bypass cache if not**.
- Browser TTL: **Respect origin**.
- Cache key: retain the full query string; sorting query parameters is allowed, ignoring them is forbidden.
- Serve stale while revalidating: enabled.

No `Cache Everything` wildcard over `/api/*` is allowed. The five exact paths are the entire public allowlist.

## Origin cache headers

Anonymous allowlisted responses use:

```text
Cache-Control: public, max-age=15, stale-while-revalidate=180, stale-if-error=180
Vary: Cookie
```

`s-maxage` is intentionally omitted. Cloudflare respects the origin `max-age` for edge freshness on Free/Pro/Business plans, while `s-maxage` implies proxy revalidation and disables stale-while-revalidate behavior. Session-cookie and Authorization responses continue to use `private, no-store` and omit the application's public-cache marker.

The Cloudflare rule performs request-time private bypass. The origin still independently enforces the same contract in Nginx and Flask, so a Cloudflare misconfiguration cannot turn an authenticated origin response into a public candidate.

## Verification contract

The public verifier has two modes:

- origin mode: current Nginx HIT/BYPASS, redaction, version, and freshness checks;
- CDN-required mode: all origin checks plus `CF-Ray`; anonymous requests must reach `CF-Cache-Status: HIT` within the retry window, while session-cookie and Authorization requests must never be Cloudflare HIT.

The k6 workflow sets `REQUIRE_CDN=1`. Each shard counts Cloudflare `HIT`, `MISS`, `STALE`/`UPDATING`/`REVALIDATED`, `BYPASS`/`DYNAMIC`, and unknown responses. A shard fails if Cloudflare headers are absent or a guest request is classified BYPASS/DYNAMIC. Cold MISS is allowed; sustained HIT/stale evidence is mandatory in the aggregate.

The existing `X-Radar-Edge-Cache` header remains useful as origin-shield evidence, but it is no longer sufficient for the distributed release gate because Cloudflare can replay the header stored with the cached origin response.

## Cutover and rollback

Before cutover:

1. Export or capture the complete Vietnix DNS record set.
2. Add and validate the Cloudflare zone without changing nameservers.
3. Configure Full (strict), the two rules above, and proxied web records.
4. Lower DNS TTL where supported and record the assigned Cloudflare nameservers.
5. Run the origin verifier directly against the current public site.

Cut over by replacing the Vietnix nameservers only after the Cloudflare zone reports ready. During propagation, verify from multiple resolvers that web, mail, TXT/CAA, HTTPS, canonical, robots, sitemap, API redaction, and logged-in behavior remain correct.

Rollback is deterministic: restore `ns1.vietnix.net`, `ns2.vietnix.net`, and `nsbak.vietnix.net`; the origin A record remains `103.90.226.230`, and Nginx continues serving the same guest-only cache. Do not remove the origin cache during CDN rollout.

## Acceptance

CDN cutover is accepted only when:

- DNS resolves to Cloudflare and public responses contain `CF-Ray`;
- guest retries show Cloudflare HIT on all five allowlisted paths;
- session-cookie and Authorization probes are never Cloudflare HIT and retain `private, no-store` from origin;
- public API output remains redacted and dataset version freshness remains within the approved window;
- desktop and mobile browser flows remain signal-first with filters working;
- the serial distributed workflow passes default 100/500/1,000/5,000 and mixed 100/500/1,000;
- the production observer reports no abort, new listen drops, DB overflow, Redis rejection, service restart, or privacy regression.

Until those checks pass, the original performance goal remains active.
