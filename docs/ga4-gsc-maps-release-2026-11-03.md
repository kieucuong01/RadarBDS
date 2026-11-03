# GA4, GSC priorities and Maps defaults — 2026-11-03

## GA4 root cause and repair

The public edge returned two enforced CSP headers. Flask allowed
`https://analytics.google.com`, but Nginx did not. Multiple CSP policies are
intersected, so allowing the collector only in Flask was insufficient.

Both the existing tracking snippet and Google's standard snippet sent collect
requests successfully in isolated local pages. Production loaded gtag.js with
HTTP 200 but sent no successful collect until Nginx was corrected. No tracking
snippet rewrite, extra tag, API secret or Measurement Protocol proxy is needed.

Added only `https://analytics.google.com` to connect-src in all four Nginx CSP
copies. Retained existing CSP restrictions, privacy/cache rules and deployment
settings. The regression test checks both Flask and every checked-in Nginx
policy. Do not remove CSP or add wildcard destinations to work around this.

The live change was applied by root to `/etc/nginx/sites-available/radar-bds.conf`
after asserting its exact SHA and preserving a copy. `nginx -t` passed, then
Nginx reloaded. A public browser subsequently observed GA4 collect HTTP 204.

- Backup: `/root/radar-nginx-before-ga4-20261103T043457Z.conf`
- Before SHA-256: `ba4df9fccca0cb8fbd6709cc7a4a5ca6258edb8a58c0d7f56b85808fd0d77fc6`
- After SHA-256: `c07e325509cbcd1a498a2720eb2c2237b2302a89c8712b80e7c6134e5888253b`
- Rollback only if needed: restore that exact backup, run `nginx -t`, reload.

Do not infer historical recovery from new collection. GA4 cannot retroactively
reconstruct visits that were never received. Standard reports may lag; verify
network collection separately from Realtime and processed reporting.

## GSC-driven page work

The private 3-month/28-day review lives in ignored `.local/analytics-review-20261103/`.
It predates these releases. No OAuth credentials or private exports are published.

- Retain city-map URLs and existing free administrative maps. Clarify old/new
  ward lookup and add a geographically scoped route into planning Maps, with a
  FAQ distinguishing administrative boundaries from planning/parcel evidence.
- Improve Mỹ Phước–Tân Vạn title, description and answer-first text; explicitly
  distinguish the illustrative route from a parcel/legal planning extract. Add
  Maps and the tờ/thửa/coordinate guide as next actions.
- Keep the land-price tool's legal source, effective date and numerical dataset;
  explain the search → correct road segment → position-calculation workflow.
- Do not delete low-sample pages or historic reports based only on zero clicks.
  Do not generate more pairwise ward articles without distinct evidence/intent.

These are hypotheses for improving usefulness and clicks, not measured gains.

## Requested Maps defaults

Ordinary Maps and generic planning entries now open **QH sử dụng đất 2030**.
Its existing opacity remains 65%. Keep explicit/shared layer selections intact.
The planning hub defaults to the same layer. Ranh thửa starts off, including
its dock aria-pressed state; config/search remain available. No viewport parcel
geometry is requested until the user enables boundaries. Explicit parcel search
can still focus a result and turn boundaries on consistently.

Tests cover default selection, explicit layer preservation, generic entry links,
no initial parcel viewport fetch and manual re-enabling. Changed JS URLs are
versioned. The normal Maps street base, area/filter preservation and separate
listing visibility controls remain unchanged.

References: [Google CSP guidance](https://developers.google.com/tag-platform/security/guides/csp),
[multiple enforced policies](https://www.w3.org/TR/CSP/#multiple-policies).
