# Distributed Production Capacity Design

## Status and standing approval

This design continues the already approved homepage performance master plan. The user authorized sequential execution through completion and asked the agent not to pause for further choices. That standing approval selects the recommended diagnostic-first approach below; it does not authorize paid CDN purchases or inventing credentials that are not present.

## Problem

Phases 1-4 made the public read path signal-first, cacheable, bounded, reversible, and privacy-safe. Production passed the normal homepage profile at 100 virtual users and the 50-key mixed filter profile at 500 virtual users. A single Windows load generator missed the normal 500 and mixed 1,000 gates while the origin retained low CPU, bounded PostgreSQL sessions, healthy Redis, and no new accept-queue drops.

The remaining evidence is ambiguous: the direct origin may be limited by its network egress, or the single generator/path may be the dominant bottleneck. Current DNS proves `radarbds.vn` is an A record to `103.90.226.230` under Vietnix nameservers with no CDN response headers. Browser-compressed payloads measured on 2026-08-01 are approximately 17,756 bytes for `/`, 4,819 bytes for `/api/signals?page=1&limit=20`, and 537 bytes for `/api/counts`. At 5,000 default-profile VUs, one homepage plus one signal request per second implies roughly 113 MB/s before protocol overhead, so a direct single-origin 5,000-VU pass is unlikely unless the host has close to gigabit usable egress.

## Goal

Produce authoritative, reproducible evidence for the original Phase 4 release gate using synchronized external generators:

- normal homepage traffic passes 100, 500, 1,000, then 5,000 simultaneous VUs;
- canonical 50-key mixed filters pass 100, 500, then 1,000 simultaneous VUs;
- every active shard independently satisfies the approved latency, failure, and check thresholds;
- production observation proves cache collapse, bounded database work, stable services, and no privacy regression;
- a failed stage stops all later stages;
- evidence is retained as workflow artifacts and in the existing local evidence directory.

If the distributed test still fails while the origin stays resource-stable, the result proves that a CDN/origin shield is required. DNS migration is then a separate control-plane mutation and may proceed only through an authenticated Vietnix/Cloudflare control plane already available to the user; no paid product is purchased automatically.

## Options considered

### 1. Synchronized GitHub-hosted generators first — selected

Run the existing k6 profile from multiple independent GitHub-hosted runners. This removes the single-generator CPU, socket, and egress path from the result, costs no repository minutes for a public repository on standard hosted runners, and preserves the exact Phase 4 traffic contract. It cannot create CDN capacity, but it distinguishes generator limits from origin/network limits before any DNS mutation.

### 2. Move directly to Cloudflare or Vietnix CDN

This is the likely long-term solution for 5,000 cached VUs because it moves repeated response bytes away from the 2-vCPU origin. It is not selected as the first step because the domain currently uses Vietnix DNS, no Cloudflare/CDN token exists in project or process environment, and changing nameservers or buying service without an authenticated control plane would create avoidable availability and account risk.

### 3. Raise Gunicorn, PostgreSQL, Redis, or timeouts again

Rejected. Origin CPU, memory, Redis, and database sessions stayed bounded during the failed tests. Raising backend concurrency would not increase network capacity and would weaken the safety bounds established in Phases 2 and 4.

## Architecture

Two workflows and two focused scripts own the distributed gate:

```text
capacity-test/approved-20260801 push or confirmed manual dispatch
  -> serial caller workflow
       -> reusable stage workflow
            -> prepare synchronized start epoch (+120 s)
            -> matrix of 1, 2, or 5 k6 shards
            -> upload one summary per expected shard
            -> aggregate and conservatively validate the stage
       -> next stage only if prior stage succeeded

local production observer
  -> samples services, sockets, Redis, host pressure, DB sessions, and Nginx errors
  -> writes bounded status-only evidence outside git
```

The serial stages are exact:

| Order | Scenario | Total VUs | Shards | VUs per shard |
|---:|---|---:|---:|---:|
| 1 | default | 100 | 1 | 100 |
| 2 | mixed | 100 | 1 | 100 |
| 3 | default | 500 | 1 | 500 |
| 4 | mixed | 500 | 1 | 500 |
| 5 | default | 1,000 | 2 | 500 |
| 6 | mixed | 1,000 | 2 | 500 |
| 7 | default | 5,000 | 5 | 1,000 |

Every stage uses one shared `RUN_ID` across its shards. Default traffic therefore creates only the approved homepage and signal cache keys. Mixed traffic reuses the fixed 50-key corpus. Each shard runs for two minutes and starts within ten seconds of the coordinator epoch or fails closed.

## Conservative aggregation

The existing k6 thresholds run independently on every shard:

- default: failures `<0.5%`, p95 `<1,000 ms`, p99 `<2,000 ms`, checks `>99.5%`;
- mixed: failures `<0.5%`, p95 `<1,500 ms`, p99 `<2,000 ms`, checks `>99.5%`.

If every shard independently places at least 95% and 99% of its samples below the respective limits, the union of all shard samples also meets those limits. Therefore the aggregate reports the maximum shard p95 and p99 as conservative global bounds, sums request and edge-cache counters, and computes weighted failure/check rates from counts. It never averages percentiles.

`scripts/load/aggregate_k6_shards.py` fails if an expected shard summary is missing, a metric is absent, a threshold reports failure, a private/bypass counter is nonzero, or any shard uses a different scenario, stage, run id, or target URL.

## Workflow safety

- The automatic trigger is restricted to the exact branch `capacity-test/approved-20260801`.
- Manual dispatch requires confirmation text `radarbds.vn`.
- Workflow concurrency group `radar-production-capacity` has `cancel-in-progress: false`, preventing overlapping production tests.
- The target URL is hard-coded to `https://radarbds.vn`; there is no arbitrary URL input.
- Permissions are read-only and no repository or deployment secret is exposed.
- `actions/checkout`, `actions/upload-artifact`, and `actions/download-artifact` use immutable commit SHAs.
- k6 `v2.1.0` is downloaded from the official Grafana release and verified against SHA-256 `295d961ebfca306f295f1133068dcd403a8171c87f387928f5f30b0fbcff858a`.
- A stage failure prevents all dependent stages. No workflow retries a failed load stage automatically.
- The workflow sends no Cookie, Authorization, mutation, admin, saved-listing, phone, or source URL request.

## Production observation and aborts

`scripts/load/observe_production_capacity.ps1` uses the existing deploy SSH key and samples every ten seconds without printing secrets or response bodies. It records timestamped service state, load/memory/swap, socket totals, listen overflow/drop counters, Redis memory/evictions/rejected connections, Radar PostgreSQL session counts, and bounded recent Nginx/Gunicorn error counts.

The observer exits nonzero and writes an `ABORT` record when any Phase 4 host threshold is crossed: service inactive, app DB sessions above 12, Redis above 256 MB, rejected Redis clients, sustained swap activity, new listen overflows/drops, OOM/restart/file-descriptor errors, or sustained CPU above 90%. The operator then cancels the GitHub run through the authenticated GitHub control plane if available; the workflow's own HTTP thresholds still stop subsequent stages independently.

Before and after the workflow, `scripts/verify_public_cache.ps1` must prove guest HIT, Cookie/Bearer BYPASS, dataset version, and redaction. A real browser must still show signal-first ordering on desktop and mobile.

## Evidence and decisions

Each shard artifact contains only k6 summaries and status metadata. The stage artifact contains the conservative aggregate. Host samples remain under `C:\tmp\radar-phase4-evidence-20260801-172749\distributed-<run-id>` and stay uncommitted.

Decision after the run:

1. If all seven stages pass and host/privacy/browser gates pass, Phase 4 and the active goal are complete.
2. If a stage fails and origin host thresholds fail, fix the measured origin bottleneck and repeat from 100 VUs.
3. If a stage fails while origin host thresholds stay healthy, stop direct-origin testing and implement CDN/origin shielding through an authenticated existing control plane. Preserve the exact guest-only cache and private bypass contract, then repeat the same distributed workflow against the public domain.

## Non-goals

- 5,000 sustained origin cache misses per second.
- 5,000 unique cold filters.
- authenticated or administrative load testing.
- automatic purchase of CDN service or creation of an external account.
- weakening redaction, freshness, or database connection bounds to pass a benchmark.
