# Cloudflare Origin-Shield Implementation Plan

**Goal:** Activate a privacy-safe Cloudflare cache for the four public Radar BDS read paths, then rerun the unchanged distributed 1,000-5,000-VU release gate.

**Architecture:** Cloudflare becomes the public edge, Nginx remains the 15-second origin shield, and Flask/Redis/PostgreSQL retain their existing bounded read path. Request-time rules bypass session and Authorization traffic before cache lookup. The test harness requires independent Cloudflare and origin-cache evidence.

**Constraints:** Do not create an external account, buy a plan, change nameservers, or transmit credentials without an authenticated authorized control plane. Do not cache `/api/*` broadly. Do not weaken private `no-store`, redaction, dataset freshness, DB/Redis bounds, or k6 latency thresholds.

## Task 1: Make origin freshness compatible with stale edge revalidation

- [x] Change the anonymous allowlisted header to `public, max-age=15, stale-while-revalidate=180, stale-if-error=180`.
- [x] Update header tests first and confirm they fail before the application change.
- [x] Preserve `private, no-store` for session-cookie, Authorization, and admin responses.
- [x] Run focused cache/header/privacy tests.

## Task 2: Require real CDN evidence

- [x] Extend the public verifier with an opt-in `-RequireCdn` gate for `CF-Ray` and Cloudflare HIT/private bypass behavior.
- [x] Add Cloudflare status counters to k6 and enable `REQUIRE_CDN=1` in the distributed workflow.
- [x] Extend shard metadata and conservative aggregation so missing CDN headers, guest BYPASS/DYNAMIC, or zero HIT/stale responses fail.
- [x] Add failing tests before each implementation change.
- [x] Keep direct-origin local diagnostics available by leaving CDN requirement opt-in outside the production workflow.

## Task 3: Release CDN-readiness code

- [x] Run the full Phase 4 repository gate, syntax checks, k6 inspect, workflow validation, and `git diff --check`.
- [x] Commit, fetch/rebase current `origin/main`, push, deploy the exact commit, and prove production HEAD and clean state.
- [x] Verify current origin mode still passes before any DNS mutation.

Task 3 release evidence: CDN-readiness commits through `4ad6e79` are on production, the checkout is clean, Radar/Nginx/Redis/PostgreSQL are active, and the non-CDN verifier passes guest HIT, cookie/Authorization BYPASS, redaction, and dataset version checks for all four allowlisted routes. Tasks 4-7 remain intentionally open pending an authenticated Cloudflare control plane and the unchanged distributed capacity rerun.

## Task 4: Configure the authenticated Cloudflare zone

- [ ] Confirm an existing authenticated Cloudflare account or obtain an explicit account handoff; do not auto-create one.
- [ ] Import and compare all Vietnix DNS records, especially MX/TXT/CAA.
- [ ] Set Full (strict) and proxy only apex/www web records.
- [ ] Create the private-bypass rule before the exact public-allowlist cache rule.
- [ ] Use origin Cache-Control, preserve the full query string, and enable stale revalidation.
- [ ] Change Vietnix nameservers only after the zone reports ready.
- [ ] Preserve the Vietnix nameserver tuple and origin A record as rollback evidence.

## Task 5: Verify cutover before load

- [ ] Run the verifier with `-RequireCdn` for guest, session-cookie, Authorization, redaction, and dataset version.
- [ ] Verify DNS, TLS, canonical, robots, sitemap, mail records, and security headers.
- [ ] Verify the real desktop and mobile signal-first/filter flow.
- [ ] Confirm no direct load workflow is active and start one bounded production observer.

## Task 6: Repeat the serial distributed gate

- [ ] Trigger exactly one capacity workflow from the verified commit.
- [ ] Require serial passes at default 100, mixed 100, default 500, mixed 500, default 1,000, mixed 1,000, and default 5,000.
- [ ] Download and independently aggregate every shard artifact.
- [ ] If Cloudflare fails while origin stays healthy, diagnose the exact Cloudflare cache status/rule before retrying; do not raise backend concurrency.
- [ ] If the host observer aborts, stop the workflow and repair the measured origin threshold.

## Task 7: Record final truth

- [ ] Update `AGENTS.md`, `docs/operations.md`, `docs/architecture.md`, `docs/dev_commands.md`, and the Phase 4 master plan with the zone configuration, run ID, per-stage metrics, peak host state, privacy/browser proof, and rollback.
- [ ] Run the full completion audit and repository gate again.
- [ ] Commit, push, and deploy the docs so future agents inherit the exact production truth.
- [ ] Mark the active goal complete only after default 5,000 and mixed 1,000 pass with all host/privacy/browser gates.
