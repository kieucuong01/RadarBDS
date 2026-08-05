# Operations And Deploy

Use this for VPS deploy, production smoke checks, DB sync, crawl logs, and one-off production maintenance.

## Environments

| Environment | Purpose | Notes |
|---|---|---|
| Local Windows | Development and safe reprocess/audit | Python 3.12, `.env.local` override, local PostgreSQL on `127.0.0.1:15432` |
| Production VPS | Public site and daily crawl | Ubuntu Server 24.04 LTS, Python 3.12, systemd, Nginx |
| Supabase project `ozdjzfiqcjnlfuihqqjy` | Sync/backup | Password only in local `.env`; do not print/commit |

Public domain: `https://radarbds.vn`. Production env file: `/etc/radar-bds/radar.env`.

## Radar Ask Retrieval Gate

PostgreSQL full-text search is the mandatory Radar Ask knowledge path. Keep
`RADAR_ASK_KNOWLEDGE_VECTOR_ENABLED=0` unless every gate below passes on the
target host. Normal app startup and deploy never create the `vector` extension,
download a model, alter vector columns, or backfill embeddings.

The checked-in Vietnamese benchmark has 50 non-PII cases across address
aliases, post-merger ward names, legal terminology, official land-price intent,
market paraphrases, and exact-source lookup. The 2026-08-04 local PostgreSQL
baseline (`2026-08-04-v1`) measured macro Recall@5 `0.76`, exact-source
Recall@5 `0.875`, MRR@10 `0.76`, and p95 query latency `1.387 ms`. Runtime
reports stay ignored under `reports/`; they contain metrics and IDs, never raw
document text.

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 scripts\radar_ask_retrieval_benchmark.py `
  --mode fts `
  --cases tests\fixtures\radar_ask\retrieval_cases.json `
  --output reports\radar_ask_retrieval_fts.json
```

Only these offline candidates are approved for comparison:
`intfloat/multilingual-e5-small` (384 dimensions) and `BAAI/bge-m3` (1024
dimensions). Install `requirements-radar-ask-retrieval.txt` in a separate
maintenance environment. Pass a pre-downloaded local directory with
`--model-path`; the benchmark forces Hugging Face/Transformers offline and does
not resolve a remote model ID. Semantic activation measurement also requires
an owner-installed pgvector extension, builds a temporary HNSW index, runs the
same FTS ordering, and measures the fused RRF path; pure in-memory cosine scores
cannot authorize activation.

```powershell
& $py -X utf8 scripts\radar_ask_retrieval_benchmark.py `
  --mode semantic `
  --model-id intfloat/multilingual-e5-small `
  --model-path C:\approved-models\multilingual-e5-small `
  --fts-baseline reports\radar_ask_retrieval_fts.json `
  --worker-processes 3 `
  --cases tests\fixtures\radar_ask\retrieval_cases.json `
  --output reports\radar_ask_retrieval_e5.json
```

Activation is fail-closed and requires all of the following on the same
benchmark version:

- macro Recall@5 improves by at least `0.08` over FTS;
- exact-source Recall@5 is at least `0.85`;
- p95 local semantic query latency is at most `250 ms`;
- peak process memory multiplied by all `3` Gunicorn workers is at most
  `1,024 MB` total on the current 4-GB VPS;
- the owner-applied migration check confirms extension, exact dimension/model,
  complete embedding coverage, HNSW index, and bounded security-definer
  functions.

The 1,024-MB total model-bearing-worker allowance is separate from Redis's
256-MB cap and preserves headroom for Gunicorn/PostgreSQL on the measured 4-GB
host. Because the encoder cache is process-local, the gate multiplies measured
RSS by all three workers; it does not assume one shared model copy. Re-evaluate
it after any VPS size or worker-count change. Apply only after a candidate report says
`activation_gate.eligible=true`:

```bash
/opt/radar-bds/retrieval-venv/bin/python -X utf8 \
  scripts/radar_ask_vector_migration.py apply \
  --model-id intfloat/multilingual-e5-small \
  --dimension 384 \
  --model-path /opt/radar-bds/models/multilingual-e5-small
/opt/radar-bds/retrieval-venv/bin/python -X utf8 \
  scripts/radar_ask_vector_migration.py check \
  --model-id intfloat/multilingual-e5-small --dimension 384
```

Then configure the exact same local model path/ID/dimension, set the vector flag
to `1`, restart, and smoke both semantic and forced-FTS fallback. Any readiness
failure, incomplete coverage, memory regression, or latency regression requires
setting the flag back to `0` and restarting; the curated FTS corpus remains the
source of truth. No semantic candidate has been approved or enabled as of this
checkpoint because local model assets have not been supplied.

## Radar Ask Golden Release Evaluation

The versioned golden corpus is
`tests/fixtures/radar_ask/golden_questions.json`. It contains deterministic,
non-account production-like cases but never reads a live database or calls a
provider in its default mode. Expected routing/tool/evidence/answer truth is
stored separately from the fixture planner outputs, evidence bundles, and
answer candidates. The evaluator therefore exercises the public typed
`route_question()`, tool-dispatch, and `validate_answer()` boundaries without
deriving observed results from expected values. Every case also runs the real
`routes.radar_ask_api._gate()` inside a minimal Flask request context. Only the
feature flag, fixture user, fixture tier, and tier-allow decision are patched;
anonymous cases must observe the real `401 login_required`, while authenticated
Free/VIP/Admin cases must observe the owner tuple before routing can start.

Run the free, offline release gate from the repository root:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 scripts\evaluate_radar_ask.py `
  --cases tests\fixtures\radar_ask\golden_questions.json `
  --mode deterministic `
  --output reports\radar_ask_golden_local.json
& $py -X utf8 -m pytest tests\test_radar_ask_evaluation.py -q
```

The CLI exits nonzero unless routing and exact tool selection are each at least
95%, numeric grounding/citation/privacy/auth are exactly 100%, and accepted
unsupported material claims are exactly 0%. Reports contain case IDs, metric
counts, and bounded failure dimensions only; they omit questions, prompts, raw
evidence, phone numbers, URLs, and account identifiers. The current `v1`
deterministic baseline has 140 cases: routing/tool selection are `0.971429`;
numeric grounding, citation, and auth are `1.0`; unsupported claims are `0.0`;
and privacy is RED at `0.985714`. The two failing provider-payload probes are
`privacy-001` (lowercase multi-token labeled name) and `privacy-002`
(single-token labeled name). They exercise the actual `DeepSeekTypedPlanner`
message builder through a fake provider, so the run remains offline while
measuring what would leave the application. Keep the CLI nonzero until both
probes pass; do not relax the exact privacy threshold. A routing/tool miss does
not cascade into a fabricated numeric or citation failure; each dimension uses
its own denominator. Likewise, authorization is scored from the HTTP gate
result before routing; denied cases never call the router, planner, or tools.

The corpus diversity guard requires at least 24 independent evidence bundles,
24 answer candidates, and 12 planner outputs. It also checks multiple road,
listing, valuation, numeric, and grounded-category observation pairs. These are
checked-in observations; the evaluator never generates evidence or answers
from expected truth at runtime.

DB-backed extensions to this evaluation must first prove the parsed database
name is exactly `radar_bds_test` on loopback. The checked-in deterministic gate
does not open PostgreSQL at all.

Live provider observation is optional and never part of the free default run.
It refuses to start without both the cost confirmation and an explicit ignored
JSON path below `reports/`:

```powershell
& $py -X utf8 scripts\evaluate_radar_ask.py `
  --cases tests\fixtures\radar_ask\golden_questions.json `
  --record-provider --confirm-live-cost --case-limit 5 `
  --output reports\radar_ask_provider_record.json
```

The live request contains only a privacy-scrubbed case question, expected depth,
opaque evidence aliases, and the bounded `AnswerEnvelope` JSON schema. It never
sends a golden answer candidate or shape example. Provider recordings retain
only the typed envelope structure plus case/model/status/token/cost metadata:
provider prose is replaced with fixed placeholders, evidence and source
references are consistently pseudonymized, and source links are cleared.
Unexpected nested answer fields or oversized payloads fail closed. Prompts,
raw evidence, contacts, URLs, names, account identifiers, and provider prose
are not persisted. A recording never updates golden truth automatically;
review any proposed corpus change by hand.

## Radar Ask Performance And Rendered QA Gate

This gate is local/test-only. It uses seeded test users, the test PostgreSQL
database, and a deterministic fake provider. Both executables reject a
non-loopback target and require the explicit `RADAR_ASK_FAKE_PROVIDER=1`
operator assertion. They are not a live DeepSeek or production load path.

Run the focused backend/public contract gate first:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_radar_ask_performance.py `
  tests\test_market_data_performance.py `
  tests\test_public_cache_headers.py -q
node --test tests\js\radar_ask.test.cjs
& $py -X utf8 -m py_compile scripts\verify_radar_ask_ui.py
Get-Content -LiteralPath scripts\load\radar_ask_load.js -Raw -Encoding UTF8 |
  node --input-type=module --check
```

The assistant checks enforce zero provider calls on deterministic Fast,
enqueue-before-execution on Deep, at most 50 evidence rows, active read-only
statement timeout, 128-KiB response bounds, bounded history pagination, and
`private, no-store` without `X-Radar-Public-Cache`. The two existing public
suites remain authoritative for `/api/signals`, `/api/listings`, `/api/counts`,
and `/api/dashboard`; do not duplicate or weaken those contracts in assistant
tests.

The mixed k6 profile is optional tooling, not a dependency to install during a
release task. Check availability first. If `Get-Command k6` fails, retain the
Node syntax proof, record `k6 unavailable`, and run the command below only from
an environment where k6 is already approved. Start the local app/test worker
with the fake provider injected before load; setting the assertion variable by
itself does not replace that fixture.

Immediately before assistant load, record the public p95 on the same local
server/profile. Keep both JSON reports ignored under `reports/`:

```powershell
k6 run scripts\load\radar_public_load.js `
  --env BASE_URL=http://127.0.0.1:5000 `
  --env SCENARIO=default --env VUS=10 --env DURATION=30s `
  --summary-export reports\radar_public_before_radar_ask.json
$baseline = Get-Content reports\radar_public_before_radar_ask.json -Raw |
  ConvertFrom-Json
$env:PUBLIC_BASELINE_P95_MS = [string]$baseline.metrics.http_req_duration.values.'p(95)'
$env:BASE_URL = "http://127.0.0.1:5000"
$env:DURATION = "30s"
$env:VUS_PER_SCENARIO = "1"
$env:RADAR_ASK_FAKE_PROVIDER = "1"
# JSON array of seeded local-only identifier/password/session_id/run_id objects.
$env:RADAR_ASK_TEST_USERS_JSON = Get-Content .local\radar-ask-load-users.json -Raw
k6 run scripts\load\radar_ask_load.js `
  --summary-export reports\radar_ask_load_local.json
```

Release targets are Fast p95 <=800 ms; one-tool Standard with bounded fake
latency p95 <=6 s; Deep enqueue/history/poll p95 <=500 ms; assistant and public
errors <1%; statement timeouts 0%; and public p95 no more than 20% above the
immediately preceding baseline. The profile runs the assistant scenarios and
an anonymous public scenario in parallel. Never pass real credentials in the
command or commit `.local` user fixtures/load reports.

Rendered proof uses the same already-running local fake-provider app. The
script logs in through the normal auth endpoint, exercises one Fast answer,
one Deep enqueue plus poll, sources/history, and one delete flow at `1440x900`
and `390x844`. It also checks private response headers, exactly one POST per
submit, relevant console errors, horizontal overflow, mobile 16-pixel input,
visible/focused composer, and page scroll instead of a nested feed trap.

```powershell
$env:RADAR_ASK_TEST_IDENTIFIER = "<seeded-local-user>"
$env:RADAR_ASK_TEST_PASSWORD = "<from ignored local fixture>"
$env:RADAR_ASK_FAKE_PROVIDER = "1"
& $py -X utf8 scripts\verify_radar_ask_ui.py `
  --base-url http://127.0.0.1:5000 `
  --output artifacts\radar-ask
```

The verifier never records credentials or raw account/run/session identifiers.
It writes only `desktop.png`, `mobile.png`, and bounded `metrics.json` below
ignored `artifacts/radar-ask/`. If Python Playwright or its Chromium binary is
missing, do not install it implicitly or claim rendered proof; report the exact
tool blocker and leave the command for the final release environment.

## Deploy Flow

For the normal local one-command ship:

```powershell
.\scripts\ship_production.ps1 -Message "Short commit message" -All
```

Use `-Path file1,file2` instead of `-All` when the worktree has unrelated dirty
files that should not be committed.

The ship script stages the requested files, commits, pushes `origin/main`, then
runs production deploy. On 2026-08-01 the VPS checkout origin was normalized to
`https://github.com/kieucuong01/RadarBDS.git` after the old
`github.com-radarbds` hostname stopped resolving; a live fetch proved the new
origin and production HEAD matched `origin/main`. The local `git bundle`
fallback remains the guarded recovery path if a future GitHub fetch fails.

After code is already committed and pushed to `origin/main`:

```powershell
.\scripts\deploy_production.ps1
```

The deploy script:

- uses `$env:USERPROFILE\.ssh\radar_bds_deploy_rsa`,
- fast-forwards the VPS checkout,
- removes legacy `data/facebook_profiles.json` after a DB migration/backup so Facebook broker configuration comes only from `facebook_crawl_profiles`,
- allows runtime `data/raw_backup.json` to stay dirty on the VPS,
- auto-archives a small allowlist of known temporary audit/report files from the VPS checkout to `/tmp/radar-bds-deploy-known-temp-*.tgz`,
- restarts `radar-bds.service`,
- smokes `/api/dashboard` and `/api/signals`,
- prewarms dashboard cache,
- installs/falls back Guland secondary scheduling when needed.

The archive cleanup is intentionally narrow. If any dirty production file remains
outside the built-in allowlist, deploy must still stop and report the exact file list.

Deploy does not automatically run a full production reprocess for every code change. For parser, dedup, valuation, schema, or quality-gate changes, run an explicit reprocess after deploy.

Map registry/browser-evidence releases use the dedicated sequence in
`docs/listing_map_registry_automation.md`, including deterministic double-build,
production `map-locations --full --dry-run`, apply, and browser smoke. Browser
research is an offline maintenance step and must never be added to crawl or a
public request path.

When removing or changing extraction/valuation logic, use this sequence:

```powershell
git push origin main
.\scripts\deploy_production.ps1
ssh -i "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa" deploy@103.90.226.230 "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py reprocess --full"
ssh -i "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa" deploy@103.90.226.230 "cd /opt/radar-bds/current && curl -fsS http://127.0.0.1:5000/api/dashboard >/dev/null && curl -fsS 'http://127.0.0.1:5000/api/signals?page=1&limit=3' >/dev/null && curl -fsS 'http://127.0.0.1:5000/api/dashboard?cache_refresh=1' >/dev/null"
```

## Production Reprocess

Use the deploy user and production env file:

```powershell
ssh -i "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa" deploy@103.90.226.230 "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py reprocess --full"
```

Then smoke:

```powershell
ssh -i "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa" deploy@103.90.226.230 "cd /opt/radar-bds/current && curl -fsS http://127.0.0.1:5000/api/dashboard >/dev/null && curl -fsS 'http://127.0.0.1:5000/api/signals?page=1&limit=3' >/dev/null"
```

## Signal Read Model Rollout And Rollback

Phase 1 is additive and must be deployed feature-off first. In `/etc/radar-bds/radar.env` keep:

```bash
RADAR_SIGNAL_READ_MODEL_ENABLED=0
RADAR_SIGNAL_QUERY_TIMEOUT_MS=5000
```

After deploying code and confirming the legacy API still works, initialize/backfill and compare as the runtime user:

```bash
cd /opt/radar-bds/current
set -a
. /etc/radar-bds/radar.env
set +a
/opt/radar-bds/.venv/bin/python -X utf8 radar.py signal-read-model --refresh --compare --limit 200
```

The command is safe for logs: it prints counts, listing ids, case names, and differing field names only. It never prints descriptions, phone numbers, source URLs, response bodies, cookies, or env values. Do not enable the flag unless `difference_count` is `0`.

Then set `RADAR_SIGNAL_READ_MODEL_ENABLED=1`, restart `radar-bds.service`, and check VPS-local plus public paths:

```bash
sudo systemctl restart radar-bds.service
sudo systemctl is-active radar-bds.service
/opt/radar-bds/.venv/bin/python -X utf8 scripts/benchmark_public_read_path.py --base-url http://127.0.0.1:5000 --repeat 5
/opt/radar-bds/.venv/bin/python -X utf8 scripts/benchmark_public_read_path.py --base-url https://radarbds.vn --repeat 5
```

Rollback is immediate and data-preserving: set the feature flag back to `0` and restart the service. Keep `signal_card_read_model` and `public_dataset_versions`; they are additive and useful for diagnosis. A failed refresh returns `public_read_model.status=error` to crawl/admin stats and leaves the prior complete rows/version active. The strict CLI exits nonzero.

Useful read-only inspection:

```sql
SELECT dataset_name, version, updated_at
FROM public_dataset_versions
ORDER BY dataset_name;

SELECT COUNT(*) AS rows, MAX(refreshed_at) AS newest_refresh
FROM signal_card_read_model;

SELECT relname, reloptions
FROM pg_class
WHERE relname IN (
  'signal_card_read_model', 'listings', 'valuation_results',
  'valuation_shadow_results', 'listing_images',
  'listing_publishers', 'source_publishers'
)
ORDER BY relname;
```

The runtime migration catches `insufficient_privilege` only for the optional reloption tuning on pre-existing tables. The new read-model/version tables remain mandatory. If the inspection query shows missing options, have the PostgreSQL table owner apply `autovacuum_analyze_scale_factor=0.02` and `autovacuum_analyze_threshold=100`; do not grant broader ownership to the web runtime role merely to pass deploy.

After schema init under a limited-owner runtime role, verify the required objects separately before restarting or enabling the flag. A warning that a later legacy migration was skipped is not proof that the earlier transaction committed:

```sql
SELECT to_regclass('public.public_dataset_versions') AS versions_table,
       to_regclass('public.signal_card_read_model') AS read_model_table,
       to_regclass('public.listing_map_locations') AS map_locations_table;

SELECT dataset_name, version
FROM public_dataset_versions
ORDER BY dataset_name;
```

All three object names must be non-null and the version table must contain `market`, `signals`, and `listings`. `db.schema.init_schema()` commits these required objects before best-effort legacy migrations; if an optional migration then hits `insufficient_privilege`, it rolls back that optional transaction only.

If compare reports only `order_mismatch` for Guland with identical IDs and fields, inspect `price_updated_at`, `first_seen_at`, and `crawled_at` string formats before changing indexes. Mixed space/`T` separators are present in production, and Phase 1 must preserve the existing lexical `listing_activity_at_sql()` order. Do not sort `newest` solely by normalized `signal_card_read_model.activity_at` unless that user-visible behavior change has its own migration and acceptance test.

This rollout proves parity and normal-load latency only. Do not claim the 1,000-5,000 simultaneous in-flight request objective until the later pooling/cache/Nginx phases and staged load gates pass.

## All-Listings Read Model Rollout And Rollback

`/api/listings` shares `signal_card_read_model` but has independent readiness, cache versioning, and rollback. Deploy with the route off even though its code default is enabled. Set this in `/etc/radar-bds/radar.env` before the first deployment:

```bash
RADAR_LISTING_READ_MODEL_ENABLED=0
```

After the code is active, run the full refresh and both safe-metadata parity checks as the runtime user. The command exits nonzero on either signal or all-listings mismatch and never logs descriptions, URLs, phone numbers, cookies, or credentials:

```bash
cd /opt/radar-bds/current
set -a
. /etc/radar-bds/radar.env
set +a
/opt/radar-bds/.venv/bin/python -X utf8 radar.py signal-read-model --refresh --compare --compare-listings --limit 200
/opt/radar-bds/.venv/bin/python -X utf8 -c 'from services.public_cache import get_current_dataset_versions; print(get_current_dataset_versions(("signals","listings","market")))'
```

Require both comparisons to report `difference_count=0`, a positive durable `listings` version, and a matching Redis mirror. Redis mirror/prewarm errors are separate from the committed PostgreSQL refresh and must still be resolved before enabling the route. Route dispatch rechecks PostgreSQL readiness through a separate one-second process cache and ignores a divergent Redis mirror. Configured publication passes the just-committed version; standalone prewarm reads the durable version itself. Either mode skips `/api/listings` while a flag is disabled or durable readiness is zero, so it never prewarms the known slow legacy query.

Then set `RADAR_LISTING_READ_MODEL_ENABLED=1`, restart, prewarm once, and measure the canonical route without printing its body:

```bash
sudo systemctl restart radar-bds.service
sudo systemctl is-active radar-bds.service
sudo -u radar bash -lc 'set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 -c "from services.public_prewarm import prewarm_configured_routes; print(prewarm_configured_routes())"'
/opt/radar-bds/.venv/bin/python -X utf8 scripts/benchmark_public_read_path.py --base-url http://127.0.0.1:5000 --repeat 5 --path '/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50'
```

From Windows, run `scripts/verify_public_cache.ps1` against the public domain. It must prove guest HIT plus cookie/Authorization bypass, private/no-store headers, and recursive redaction for the listings response. Browser smoke must cover desktop and mobile Tin rao activation, first visible rows, filters, each sort, page append, full image arrays/modal, and no duplicate first-page request. Record first-content time from browser navigation/network evidence, not a unit test.

Route-only rollback is data-preserving: set `RADAR_LISTING_READ_MODEL_ENABLED=0`, restart `radar-bds.service`, and use a VPS-local `cache_refresh=1` probe or temporarily disable the application cache for the diagnostic so an old equivalent cached payload cannot hide the legacy dispatch. Keep the projection and `listings` version. This rollback must not disable `/api/signals`, `/api/counts`, `/api/dashboard`, or signals-mode Maps. For a privacy/key concern, also remove or disable the exact Nginx `/api/listings` cache location and reload Nginx before further public traffic.

Release evidence is incomplete unless it records: commit SHA, service status, durable and Redis `listings` version, full-refresh row count/duration, parity difference count, five VPS-local cold/warm samples and cold p95, public HIT p95, browser first-content time, cache/privacy headers, redaction checks, and the route-only rollback probe.

### Production follow-up on 2026-08-02

At this 2026-08-02 checkpoint, the all-listings projection and application path were active in production, while the edge/capacity rollout was still open. Preserve these historical facts instead of repeating the expensive audits; the later definitive result is recorded under **Measured production evidence** below:

- deployed feature commits include `d5c7e3f` (post-load/hover Maps and Tin rao asset warm-up) and `c4705c1` (`/api/counts` metrics from the shared projection);
- the published projection contained 23,059 rows; durable PostgreSQL and Redis mirrors matched at `signals=5`, `listings=1`, `market=1` at verification time;
- full local parity completed with 36 signal cases and 76 listing cases at limit 200, all with `difference_count=0`; production completed an eight-case, limit-50 sampled parity smoke with zero differences. The full production Cartesian comparison was stopped because the legacy CTE path repeatedly exceeded the bounded audit window, so it must not be reported as complete;
- production VPS-local `/api/listings` forced-loader samples were 101-173 ms cold and 116-154 ms warm. Public warm samples were 65-145 ms. A real Admin browser click showed the Tin rao tab active in 2.6 ms, skeletons in 6.7 ms, and 50 real cards in 332.2 ms; its `/api/listings` request took 233.5 ms;
- before `d5c7e3f`, a cold first Maps click kept the dashboard visible for about 2,908 ms while CSS, module code, and Leaflet loaded. After post-load idle warm-up, the same production interaction opened and completed in 55 ms. Warm-up starts only after `window.load`/idle, or on launcher hover/focus, so it does not block the initial homepage render;
- before `c4705c1`, a real Admin `/api/counts` request took 22,477 ms and left the Săn Deal badge at the initial `0`. After the fix, the browser request took 77.9 ms and five forced VPS-local probes took 54-98 ms. Initial badges render an unknown placeholder until the deferred count arrives; do not reintroduce a false zero placeholder;
- the 2026-08-02 ACL maintenance completed the origin install. `/etc/nginx/sites-available/radar-bds.conf` now has the exact `/api/listings` public-cache location, `/etc/radar-bds/radar.env` contains exactly one `RADAR_LISTING_READ_MODEL_ENABLED=1`, and the ignored `.env.local` override was moved to the timestamped recovery directory `/tmp/radar-perf-20260802T142202Z`. The pre-change Nginx and base-env SHA-256 values were `0236d648c3f52682ae8a84b21d792c72971bbccaa3a6a907c974d88fd867e671` and `451604d2c638a9b0ee6fdfa3e5b88100fa41c285def4aebf4d58429632dfba8e`;
- origin prewarm succeeded for all seven configured routes. Repeated HTTPS origin probes changed `/api/listings` from `MISS` to `HIT`, and the public `scripts/verify_public_cache.ps1` passed all five path classes: guest `HIT`, cookie and Authorization `BYPASS`, private/no-store enforcement, recursive redaction, hidden internal marker, and `listings` version `1`;
- the route-dispatch rollback drill is complete and data-preserving. With `RADAR_LISTING_READ_MODEL_ENABLED=0`, a VPS-local `cache_refresh=1` legacy probe returned HTTP 200 in 51.737 seconds. The mandatory restore set the flag back to `1`, restarted the service, prewarmed seven of seven routes, and returned the same read-model route in 91 ms. PostgreSQL and Redis versions remained matched at `signals=5`, `listings=1`, `market=1`; `/api/signals`, `/api/counts`, `/api/dashboard`, Maps, and stored data were not disabled or changed.

At that checkpoint, the user-visible hot paths and VPS origin phase were fixed and deployed, while Cloudflare/Vietnix DNS cutover and the distributed gates remained. Those items were subsequently completed through the scoped definitive result documented below. Optional full production Cartesian parity still requires a longer approved maintenance window. Revoke the temporary ACL after inspection with `sudo setfacl -x u:deploy /etc/nginx/sites-available/radar-bds.conf /etc/radar-bds/radar.env`.

## Shared Public Cache And PostgreSQL Pool Rollout

Phase 2 application code is safe to deploy before Redis. Current production, after the completed Phase 4 safety drills, uses:

```bash
RADAR_DB_POOL_MIN=1
RADAR_DB_POOL_MAX=4
RADAR_DB_POOL_TIMEOUT_SECONDS=1.0
RADAR_PUBLIC_CACHE_ENABLED=1
RADAR_REDIS_URL=redis://127.0.0.1:6379/0
RADAR_CACHE_SCHEMA_VERSION=1
RADAR_PUBLIC_CACHE_FRESH_SECONDS=60
RADAR_PUBLIC_CACHE_STALE_SECONDS=86400
RADAR_PUBLIC_CACHE_LOCK_SECONDS=5
RADAR_PUBLIC_CACHE_WAIT_SECONDS=0.25
RADAR_PUBLIC_DB_SLOTS=2
RADAR_PUBLIC_STATEMENT_TIMEOUT_MS=1500
RADAR_PUBLIC_PREWARM_URL=http://127.0.0.1:5000
```

The connection budget is `Gunicorn workers * RADAR_DB_POOL_MAX`. The approved Phase 4 target is `3 * 4 = 12` web connections. Do not increase either value independently. Under ordinary web-only traffic, inspect PostgreSQL from a privileged SQL session and keep the Radar database/user count within that budget; exclude a separately running crawl/reprocess before interpreting the count:

```sql
SELECT datname, usename, state, COUNT(*) AS sessions
FROM pg_stat_activity
WHERE datname = current_database()
GROUP BY datname, usename, state
ORDER BY usename, state;
```

Pool saturation raises a controlled application error instead of creating unbounded connections. Confirm service logs contain the configured `PostgreSQL pool initialized min=1 max=4` line and that `/api/signals`, `/api/counts`, and `/api/dashboard` remain correct with the cache flag off.

For a new environment, do not enable the cache flag until Phase 4 has installed a local-only Redis service and these checks pass:

```bash
sudo systemctl is-active redis-server
redis-cli -h 127.0.0.1 -p 6379 PING
ss -lntp | grep '127.0.0.1:6379'
redis-cli -h 127.0.0.1 -p 6379 INFO server | grep '^redis_version:'
redis-cli -h 127.0.0.1 -p 6379 INFO memory | grep -E '^(used_memory_human|maxmemory_human|maxmemory_policy):'
```

Expected: `active`, `PONG`, loopback-only listening, the installed Redis version, and the Phase 4 cache-only memory/policy limits. Redis contains no source-of-truth data and persistence remains disabled by the Phase 4 service configuration.

Dataset and cache inspection without response bodies or credentials:

```bash
sudo -u radar bash -lc 'set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 -c "from services.public_cache import get_current_dataset_versions; print(get_current_dataset_versions((\"signals\",\"listings\",\"market\")))"'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/signals?include_total=0&limit=30&page=1&sort=newest'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/counts'
curl -sS -D - -o /dev/null 'http://127.0.0.1:5000/api/dashboard'
```

`X-Radar-Cache` is `miss`, `hit`, `stale`, or `bypass`; `Server-Timing` reports cache status and loader duration. Only anonymous guest responses may include `X-Radar-Public-Cache: 1` plus the public 15-second policy. Repeat with a harmless `Cookie: radar_session=invalid-probe` and with an `Authorization` header; both must return `Cache-Control: private, no-store` and no public marker. Do not log real session/admin values.

Committed read-model publication follows this order: DB refresh/version commit, Redis version mirror, then the seven allowlisted warm routes from `config/public_cache_warm_routes.json`. Publication output keeps DB `status=ok` and reports mirror/prewarm state separately under `cache`. Prewarm sends no cookie/authorization, reads at most 2 MiB, logs status only, and skips the configured listings route until both read-model flags and a positive committed/durable `listings` version are present.

Rollback order:

1. For any privacy/key/version issue, set `RADAR_PUBLIC_CACHE_ENABLED=0` and restart `radar-bds.service` immediately.
2. Verify all three endpoints return `X-Radar-Cache: bypass` and correct tier redaction.
3. Redis may then be stopped or repaired without affecting PostgreSQL truth.
4. Keep the pool limits in place. Roll back pool code only by deploying the prior commit; never compensate by raising PostgreSQL connection limits during an incident.

The production Phase 2 runtime gate passed on 2026-08-01: real Redis DB 15 integration, shared cache isolation, Redis-stop/recovery at 100 VUs, bounded DB sessions, and cache flags `0` and `1` were all exercised. This is environment-specific evidence, not permission to skip the gate elsewhere.

## Signal-First Frontend Runtime

The Signals-tab request contract is:

```text
canonical filter snapshot -> /api/signals immediately -> first card chunk
                                                   \-> /api/counts after settle/idle
```

`/api/dashboard` is intentionally absent while the Signals tab stays active. It is still used when a filter changes on a non-Signals tab. `core.js` uses the later `homepage-counts-20260802` cache-busting version; `filter_runtime.js`, `filters.js`, `signals.js`, and `web_vitals.js` retain `homepage-perf-20260801`. Every changed immutable asset must receive an explicit version bump on later edits.

Keep these browser-visible safeguards together during incident diagnosis: AbortController per request scope, canonical snapshot check before deferred counts, signal response run id, render-chunk sequence, and listing-id deduplication. A stale response in Network is acceptable only when it is visibly canceled and cannot mutate the final cards.

The Săn Deal badge and Maps click have an additional regression gate:

1. Keep `/api/signals?...&include_total=0` as the first dynamic request.
2. Confirm the later `/api/counts` response contains numeric `stats.signals`, and both `#badgeSignals` and `#mobileBadgeSignals` show that value.
3. Click `Xem trên Maps` from the Signals tab. `/api/map-listings?...&mode=signals` must complete from `signal_card_read_model`; its SQL must contain neither `latest_valuation` nor `latest_shadow_valuation`.
4. Confirm the map status becomes `aria-busy=false`, one Leaflet Canvas exists, no SVG marker surface is created, and the desktop panel/mobile sheet remains interactive.
5. After a production deploy that changes the counts payload, refresh/publish the signals read model once so the durable and Redis `signals` versions advance together; otherwise the old cached counts payload may remain valid under the previous version key.
6. Query one map item as Guest/Free/VIP and confirm any phone embedded in `title` is redacted; admin may retain the original title. With `RADAR_SIGNAL_READ_MODEL_ENABLED=0`, confirm `stats.signals` is still the legacy exact count rather than `0`.

### Publish a default signal-policy change

The default Săn Deal MOS floor is a consumer policy, not a valuation-model change. Keep the internal `SIGNAL_MOS_THRESHOLD=0.10`, deploy the tested code, and do not run a valuation reprocess solely for a default-MOS change.

1. Deploy the tested commit with `scripts/deploy_production.ps1`.
2. On the active VPS release run `/opt/radar-bds/.venv/bin/python -X utf8 radar.py signal-read-model --refresh --compare --limit 200`.
3. Confirm the durable `signals` dataset version and Redis mirror advanced together, then wait for or purge the prior anonymous homepage/API edge-cache entries.
4. Verify default and crafted Guest requests contain no `mos_pct_display < 15`, `/api/counts` equals `/api/signals total`, and signals Maps uses the same threshold.
5. Verify an authenticated VIP/Admin explicit `mos_min=10` request. If production has no eligible 10-14.9% row, record the zero-row DB fact and use query/test evidence instead of fabricating a browser example.
6. Verify Guest/Free controls remain fixed at 15, VIP/Admin controls remain editable, Tin rao is unaffected, and non-admin redaction remains intact.

Rollback is code/cache-only: revert the scoped default-MOS commits, redeploy, republish the signals dataset version, and clear only affected caches. Never rewrite listings, valuation rows, crawler data, reviews, or user data for this rollback.

Verified production evidence for the MOS 15 rollout on 2026-08-03:

- Release commit `0fe58d5908479ce8250b0e7915577a2d72056ba9` was deployed to `/opt/radar-bds/current`; `radar-bds.service` remained `active`.
- The full signal read-model refresh published `23,262` rows in `69,596 ms`, prewarmed `7/7` routes, mirrored dataset versions successfully (`signals=7`, `listings=3`), and compared 36 sampled cases with `difference_count=0`.
- The refresh initially exposed an existing race: an image could be removed after the full-refresh staging snapshot but before the final insert, causing `signal_card_read_model_primary_image_id_fkey`. Commit `0fe58d5` rechecks the live primary image and image count in the final insert. The regression test and all 241 MOS/feed/count/Maps/UI/alert/report tests passed before release.
- Fresh Guest requests returned `1,125` signals for both the default feed and a crafted `mos_min=10` request; the minimum displayed MOS in the first 100 rows was `15.3`. `/api/counts`, `/api/dashboard`, and signals Maps all reported `1,125` after the Cloudflare stale-while-revalidate entry advanced to dataset version 7.
- Anonymous signal/count/dashboard responses retained short public cache headers and no `Set-Cookie`; repeated counts/dashboard requests reached Cloudflare `HIT`. Signals Maps remained dynamic/no-store.
- Production contains `328` public actionable candidates from MOS 10 through below 15, so VIP/Admin explicit MOS 10 has real data to inspect. The available Chrome session was Guest; tier-aware integration tests proved explicit VIP/Admin values remain enabled without fabricating an authenticated production session.
- Chrome desktop showed `Săn Deal 1125`, MOS 15, and a disabled Guest control. A crafted `/?mos_min=10` still rendered 15. At an exact `390 px` content viewport, Maps reported `1,125/1,125`; selecting a real marker expanded the sheet with the first card fully above the viewport bottom, no horizontal overflow, and the dashboard bottom navigation absent while Maps was open. Closing Maps and selecting Tin rao rendered cards with badge `7,810` and no console error.

### Listing Maps progressive-rendering and mobile-sheet gate

Keep the Maps rendering contract independent from the backend capacity contract. The summary endpoint may return thousands of location groups, but the browser must render only the active responsive panel, expose at most 100 directory rows initially, append directory DOM in 25-row animation-frame chunks, and append Leaflet markers in 200-marker animation-frame chunks. Resizing between desktop and mobile reuses the cached view model and must not request the summary again. Closing Maps invalidates every pending directory and marker generation so stale frame callbacks cannot mutate a later session.

On mobile, selected-group loading, success, and error views open the bottom sheet automatically. The sheet must preserve explicit `← Tất cả vị trí`, expand/collapse, and retry actions; hide the dashboard bottom navigation and floating actions while Maps is open; respect `env(safe-area-inset-bottom)`; and keep the first listing card fully visible at both `390x844` and `375x667`. The direct-child canvas selector must continue to override Leaflet's later `.leaflet-container { position: relative; }`; otherwise the canvas collapses to zero height after the stylesheet finishes loading.

Controlled local browser evidence from 2026-08-03 (local PostgreSQL, not a capacity claim):

- Scope: `Săn Deal` and `Tin rao` homepage Maps.
- Automated gate: 46 focused Maps JS/UI/API/service tests passed; `node --check static/js/main/listing_map.js` and `git diff --check` exited successfully.
- desktop Săn Deal completed in `421.8 ms` for `1,362/1,362` mapped listings; Tin rao completed in `705.1 ms` for `7,709/7,709`;
- both modes issued one summary request, initially rendered 100 directory buttons only in the active panel, and recorded no browser long task above 50 ms;
- the Tin rao document contained about 5,165 nodes after the bounded render, versus about 22,920 before this change; `Xem thêm` advanced the directory from 100 to 200 rows;
- mobile Săn Deal at `390x844` completed in `377.2 ms`; Tin rao at `375x667` completed in `656.1 ms`; both rendered a non-zero Leaflet canvas and no horizontal overflow;
- after selecting a real marker at `375x667`, the sheet occupied `413.5 px`, the first Tin rao card was fully visible, the canvas retained `576 px`, and the dashboard bottom navigation remained hidden. Resizing a selected Săn Deal view from `390x844` to `375x667` caused no additional summary or item request.
- Asset key: `listing-map-progressive-sheet-20260803` is shared by the Maps JavaScript and CSS URLs.
- Rollback: revert only the scoped Maps commits, redeploy, and leave PostgreSQL, Redis, crawler state, listings, valuations, and user data unchanged.

Verified public production evidence after deploying `6a448ca` on 2026-08-03:

- `radar-bds.service` was active; the CDN-required public-cache verifier passed for `/`, signals, listings, counts, and dashboard with guest Cloudflare caching plus authenticated bypass.
- `/robots.txt`, `/sitemap.xml`, `/api/dashboard`, `/api/signals?page=1&limit=3`, and `/api/listings?...&limit=3` returned HTTP 200. The rendered homepage contained the shared Maps asset key exactly twice.
- desktop `1440x900` Săn Deal completed `1,371/1,371` in `338.1 ms` with one `223.5 ms` summary request, 75 active-panel directory buttons, zero inactive-panel buttons, one Canvas, and no observed long task above 50 ms;
- desktop `1440x900` Tin rao completed `7,783/7,783` in `583.9 ms` with one `362.2 ms` summary request, 100 active-panel directory buttons, zero inactive-panel buttons, one Canvas, about 5,046 document nodes, and no observed long task above 50 ms;
- mobile `390x844` Săn Deal used one summary request, one Canvas and 12 loaded tiles; the collapsed sheet was `151.9 px` high. Selecting a real marker expanded it to `523.3 px`; the first card was fully visible, the canvas retained `753 px`, bottom navigation was hidden, and overlap/horizontal overflow were both zero;
- mobile `375x667` Tin rao completed in `644.8 ms` with one summary request, 100 active-panel buttons, one Canvas and 12 loaded tiles, and no observed long task above 50 ms. Selecting a real marker expanded the sheet to `413.5 px`; the first card was fully visible, the canvas retained `576 px`, bottom navigation was hidden, and overlap/horizontal overflow were both zero;
- the production Săn Deal badge displayed `1,371`, not zero. Browser console review found no Maps/application error; the existing CSP blocks for Cloudflare Insights and Google Analytics remain a separate telemetry issue.

Repeat the two real-mobile marker selections after every Maps CSS, Leaflet-loading, workspace-layout, or mobile-navigation change. External Facebook thumbnail `403` responses are source-CDN failures and may be reported separately, but a zero-height canvas, missing map tiles, hidden selected card, application exception, duplicate summary request, or horizontal overflow is a release blocker.

Focused verification:

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_market_data_performance.py -q
node --check static\js\main\listing_map.js
```

Controlled local browser evidence from 2026-08-01 (cache disabled, local PostgreSQL, not a capacity claim):

- desktop HTML TTFB `4.7 ms`; first signals `321.8 ms`; `radar-first-signal-cards` `337.1 ms`; counts began at `519.4 ms`; LCP `528 ms`; CLS `0.0015`;
- mobile `390x844`: HTML TTFB `45.8 ms`; first signals `277.0 ms`; first cards `299.9 ms`; counts began at `517.4 ms`; LCP `580 ms`; CLS `0.00023`; the tested interaction produced no event at the 40 ms observer threshold, so the controlled sample is `<40 ms`;
- mobile rendered one card column with zero horizontal overflow; the first trace contained signals then counts and no dashboard;
- a deliberately paused signal request was canceled as `net::ERR_ABORTED`; only the replacement response rendered; page 2 produced `60/60` unique card ids;
- a disposable Free session showed tier `free` and returned `Cache-Control: private, no-store`, `X-Radar-Cache: bypass`, and no public marker for signals/counts. The synthetic user/session and browser cookie were removed after the proof.

These measurements validate Phase 3 request ordering and rendering only. They did not, by themselves, prove the external capacity gate; the following section records the later Phase 4 infrastructure evidence and the definitive scoped 1,000/5,000-VU result.

## Production Public-Read Capacity Runbook

This section preserves the production history from 2026-08-01 through the definitive 2026-08-03 run. The implementation is deployed, cache/privacy/failure behavior is verified, and the common-key homepage contract has passed 5,000 concurrent VUs. Keep the scope boundaries below: this is not a claim for 5,000 RPS, 5,000 unique cold filters, authenticated traffic, or high availability.

### Active capacity contract

| Layer | Active production setting | Ownership |
|---|---|---|
| Nginx | exact guest cache for `/`, `/api/signals`, `/api/listings`, `/api/counts`, `/api/dashboard`; TTL 15 s; inactive 24 h; 512 MB zone; lock/background update/stale-on-error | absorbs repeated/common public concurrency; never caches session/auth/admin/error/`Set-Cookie` responses |
| TLS accept queue | IPv4 `backlog=8192`; `worker_connections=4096`; `multi_accept on`; kernel `somaxconn=8192`, `tcp_max_syn_backlog=8192` | accepts bursts without scaling Flask/DB work one-for-one |
| Gunicorn | 3 workers x 4 threads; timeout 45 s; graceful 30 s; keepalive 5 s; max requests 2,000 + jitter 200; `LimitNOFILE=65536` | bounded origin request concurrency |
| Redis | loopback only; persistence off; 256 MB; `allkeys-lru`; max clients 256 | disposable shared response/version cache, never source of truth |
| Application cache | fresh 60 s; stale 86,400 s; lock 5 s; wait 250 ms; at most 2 uncached loaders/process | protects slow/cold reads and retains a stale dashboard across idle periods |
| PostgreSQL | pool min/max 1/4 per worker; acquire timeout 1 s | at most 12 normal web connections; crawl/reprocess is accounted separately |

The 45-second origin timeout is still the deployed bound but is no longer required by the dashboard signal count. Before commit `4ad6e79`, a forced dashboard cache miss rebuilt latest valuation history and repeatedly took about 27.49 seconds. After that commit, `stats.signals` counts the already-published signal read model with the exact feed filters: five production `cache_refresh=1` probes took `195`, `147`, `138`, `158`, and `158` ms, all returned `signals=1367` and `total=7939`, and `/api/signals?page=1&limit=1` independently returned `total=1367`. Keep the timeout change, if any, as a separate measured operational change. The 24-hour Nginx inactive window and 86,400-second application stale window remain failure protection, not compensation for a known 27-second SQL path.

### Install, verify, observe, and rollback

Normal deploy does not mutate system Redis/Nginx/sysctl settings. Installation is an explicit root operation and creates a dated backup:

```bash
cd /opt/radar-bds/current
sudo ./scripts/install_performance_infra.sh install
```

The installer validates a temporary Redis instance through a Unix socket before activation, validates Nginx syntax before reload, and traps nested-function failures for automatic rollback. A missing vendor `/etc/redis/redis.conf` is restored with `--force-confmiss`; never hand-create an incomplete vendor file.

From Windows, verify public cache/privacy/freshness without printing bodies, cookies, or credentials:

```powershell
.\scripts\verify_public_cache.ps1 -BaseUrl "https://radarbds.vn"
```

Expected for all five allowlisted public path classes: repeated guest request `HIT`; fake cookie and Bearer request `BYPASS` plus `private, no-store`; no source URL, original URL, phone, seller, or embedded phone fields. Useful host checks:

```bash
systemctl is-active nginx radar-bds redis-server postgresql
redis-cli -h 127.0.0.1 PING
redis-cli -h 127.0.0.1 CONFIG GET save appendonly maxmemory maxmemory-policy maxclients
ss -lnt '( sport = :443 or sport = :6379 or sport = :5000 )'
systemctl show radar-bds.service -p LimitNOFILE
sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog
```

For an application privacy/key/version incident, first set `RADAR_PUBLIC_CACHE_ENABLED=0`, restart `radar-bds.service`, and verify private/bypass headers. Full infrastructure rollback for the latest production install is:

```bash
sudo /opt/radar-bds/current/scripts/install_performance_infra.sh rollback /var/backups/radar-bds-performance/20260801-111210
```

The corresponding environment snapshots are `/etc/radar-bds/radar.env.before-phase4-20260801-103830` and `/etc/radar-bds/radar.env.before-stale-20260801-111210`. Before using an older backup on a later deployment, inspect its manifest and current files; do not assume paths remain current.

### Measured production evidence

External tests used browser-style compression (`Accept-Encoding: gzip`). The first uncompressed 100-VU run transferred 383 MB and was rejected as a harness error; it is not a capacity result.

| External scenario | Result | p95 / p99 | Edge behavior and origin state |
|---|---:|---:|---|
| normal homepage, 100 VUs | pass, 0% errors, 21,752 requests | 192.64 / 656.77 ms | 21,715 HIT, 2 MISS, 35 STALE; DB app sessions 4 |
| mixed 50-key filters, 100 VUs | pass, 0% errors, 23,722 requests | 29.02 / 79.72 ms | 22,796 HIT, 726 STALE |
| mixed 50-key filters, 500 VUs | pass, 0.12% errors, 99,510 requests | 248.33 / 869 ms | 98,248 HIT, 938 STALE; DB app sessions <=7 |
| normal homepage, 500 VUs | fail gate, 0.75% errors | 8.49 / 25.56 s | origin stayed stable; after backlog fix kernel listen drops did not increase |
| mixed 50-key filters, 1,000 VUs | fail gate, 0.83% errors | 2.85 / 8.36 s | origin stayed stable; DB app sessions 6-7; Redis had no rejected clients/evictions |
| distributed default, 100 VUs (`30698414443`) | fail latency gate, 0% HTTP errors, 100% checks, 11,096 requests | 2.24 / 3.10 s | GitHub-hosted path delivered 143 MB at ~1.2 MB/s; CPU peaked ~14%; DB 3/0 active; Redis/listen counters/services stayed healthy |
| Cloudflare default, 100 VUs (`30756753673`) | pass, 16/35,178 edge errors (0.0455%) | 18.17 / 34.15 ms | 34,063 HIT, 1,096 stale/updating, 3 MISS; no CDN bypass/unknown responses |
| Cloudflare mixed, 100 VUs (`30756753673`) | pass, 4/35,991 edge errors (0.0111%) | 13.32 / 45.28 ms | 33,682 HIT, 2,005 stale/updating; no CDN bypass/unknown responses |
| all-listings Maps cold query, one VPS-local request | legacy timed out with 0 bytes after 20 s; read-model candidate 276.2 ms | same default filter total `7,968` | legacy stayed in materialized latest-valuation CTE; candidate used durable `listings:1`, returned the same feed total, and did not change the running service |
| forced dashboard cache bypass after `4ad6e79` | pass, 5/5 HTTP 200, exact signal-feed parity | 138-195 ms per request | `X-Radar-Cache: bypass`; `signals=1367` matched `/api/signals`; no request-time latest-valuation CTE |

The Redis-stop drill at 100 VUs passed with 0% errors, p95 199.98 ms, p99 532.45 ms, and 10,846 requests while Redis was unavailable for 21 seconds. Public responses remained `HIT`/`STALE`, PostgreSQL stayed at 4 app sessions/1 active, and Redis recovered with `PONG` and prewarm. The full rollback/reinstall drill also passed.

The IPv4 listen backlog was raised from the Linux/Nginx default queue to 8,192 after the first 500-VU test showed cumulative listen overflows. On retest, both kernel counters stayed exactly unchanged while the client still saw latency/timeouts, isolating the remaining bottleneck to the single direct-origin/network-generator path rather than new origin accept drops.

Evidence is retained locally at `C:\tmp\radar-phase4-evidence-20260801-172749`, including `public-cache-verification-final.txt`, `k6-default-100-gzip.*`, `k6-mixed-500.*`, `k6-mixed-1000.*`, `k6-redis-drill-100.*`, and host observation logs. Runtime evidence stays uncommitted.

Distributed workflow run `30698414443` stopped all dependent stages after `default-100`, as designed. All 33,288 content/cache checks passed and no HTTP request failed; only the unchanged latency thresholds crossed. Local external compressed tests top out around 2.2 MB/s, while `k6-vps-diagnostic-500` on the same host delivered about 8 MB/s at p95 665 ms. This is the decision evidence for CDN/origin shielding, not permission to relax the p95/p99 gates.

The paired 30-minute observer retained 152 samples in `distributed-20260801-1848`. It showed no service restart, Redis rejection/eviction, PostgreSQL saturation, or new listen drop during the load stage. The observer nevertheless ended `ABORT` after the workflow had already stopped because its final three samples recorded nonzero swap-in values `8`, `8`, and `16`, exactly triggering the fail-closed sustained-swap rule. The last sample still had about 2.23 GB available memory, CPU 4%, PostgreSQL 0/3 active/total, and all four services active. A later idle diagnostic found about 2.16 GB available memory, 176 MB swap allocated, `vm.swappiness=60`, and zero swap-in/out on every live interval after the initial `vmstat` since-boot row. This does not turn the failed observer into a pass; require a clean observer alongside the post-CDN rerun and diagnose fresh sustained swap if it returns.

Cloudflare is now the active public edge. Authoritative NS are `ara.ns.cloudflare.com` and `mcgrory.ns.cloudflare.com`; public A answers are Cloudflare anycast rather than `103.90.226.230`. Dashboard evidence for `30756753673` showed the two 100-VU stages served predominantly as HIT/updating from Cloudflare; CDN-required verification and the aggregator rejected neither bypass nor unknown traffic. Keep the preserved Vietnix record snapshot and the paired Cloudflare design/rollback spec as the rollback source of truth. Do not infer 500-5,000 capacity from the active proxy alone.

The first Cloudflare default-500 attempt was cancelled safely. The observer reached six consecutive CPU samples above 90% from 23:40:19 to 23:41:19 GMT+7, but the GitHub runner was still sleeping until 23:41:24 and k6 did not begin iterations until 23:41:32. Cloudflare Security Analytics isolated 52 dynamic requests from one Vietnam Safari client between 23:39:37 and 23:40:55, including all-listings Maps at 23:40:16. PostgreSQL backends created at 23:40:06/23:40:15 then consumed the CPU. A controlled single-request reproduction confirmed `/api/map-listings?mode=all&date_range=3m` remained in the legacy latest-valuation CTE for more than 20 seconds. Treat the cancelled 500 stage and all skipped higher stages as no result; deploy/verify the read-model Maps path, then start again from default-100 with a clean observer.

Post-deploy run `30759069065` proved the corrected default-100 gate: 35,100 requests, p95/p99 16.53/28.43 ms, failure rate 0.037%, and check rate 99.973%. The observer then aborted during mixed-100 after three live `vmstat` samples reported only 8/4/4 KB/s swap-in. At abort, about 1.59 GB memory remained available, CPU was 29%, PostgreSQL was 0/5 active/total, Redis used 8.45 MB, all services were active, and no restart, Redis rejection/eviction, listen-drop increase, or recent service error occurred. Mixed-100 was cancelled and all 500+ stages were skipped, so only default-100 is a capacity pass from that run.

The observer now treats memory pressure explicitly: abort immediately below 512 MB available memory, or after aggregate swap I/O reaches at least 1,024 KB/s for three samples. Single-digit KB/s paging with ample available memory remains recorded but no longer aborts. This keeps a fail-closed low-memory/sustained-swap guard without misclassifying negligible background page-ins as capacity failure.

Cloudflare run `30759522225` subsequently passed `default-100`, `mixed-100`, and `default-500`; the production observer remained clean through those executed load stages. Its `mixed-500` job is **not a capacity failure or pass**: k6 stopped inside `setup()` after the default 60-second setup limit, having issued only 258 of the 300 serial prewarm requests and zero VU iterations/checks. The workflow correctly skipped 1,000 and 5,000. Commit `41c69b3` therefore proves the common homepage path through 500 VUs and the mixed path through 100 VUs only. The harness now gives the fixed 50-key prewarm a bounded five-minute setup window and makes every mixed shard wait for the same post-prewarm VU epoch. Aggregation requires all configured VUs to record their first iteration within the ten-second synchronized-start window, preventing a staggered run from being mislabeled as concurrent capacity. Repeat the full serial gates with a fresh paired observer before raising the boundary.

Cloudflare run `30760783597` on `e9a75d7` passed `default-100`, `mixed-100`, `default-500`, `mixed-500`, `default-1000`, and `mixed-1000` with overlapping host observation. `default-5000` from that run has **no capacity result**: k6 needed 11.653 seconds to initialize 965 of 1,000 VUs on a shard, then the harness rejected the shard for missing its ten-second VU epoch; it issued zero HTTP requests and the origin remained idle. The default distributed path then reserved a separate one-minute initialization window while retaining the per-VU ten-second synchronization gate, leading to the full rerun below.

Definitive Cloudflare run `30762453173` on `063cd04` passed every serial gate with `REQUIRE_CDN=1` and the fresh observer at `C:\tmp\radar-capacity-063cd04-20260803-020109`. Percentiles are the conservative maximum shard values; start skew spans the earliest through latest first VU iteration across all shards.

| Stage | Requests | Max shard p95 / p99 | Failure / check rate | VU start skew |
|---|---:|---:|---:|---:|
| `default-100` | 35,067 | 19.566 / 61.245 ms | 0.0314% / 99.9765% | 7 ms |
| `mixed-100` | 35,415 | 13.804 / 747.933 ms | 0.0056% / 99.9957% | 9 ms |
| `default-500` | 175,416 | 17.308 / 54.069 ms | 0.0405% / 99.9711% | 34 ms |
| `mixed-500` | 175,602 | 13.467 / 45.498 ms | 0.0171% / 99.9873% | 75 ms |
| `default-1000` | 348,426 | 30.554 / 180.240 ms | 0.0339% / 99.9747% | 35 ms |
| `mixed-1000` | 351,072 | 15.093 / 35.291 ms | 0.0208% / 99.9847% | 97 ms |
| `default-5000` | 1,660,770 | 141.255 / 397.478 ms | 0.0909% / 99.9318% | 183 ms |

The paired observer covered the whole workflow, remained active after the final aggregate, and completed with 360 samples and no abort reason. Across the full observation it recorded maximum CPU 90%, minimum available memory 787,068 KB, maximum swap-in 144 KB/s, PostgreSQL at most 7 connections and 0 active, zero Redis rejected connections/evictions, zero recent Nginx/Radar errors, zero Radar restarts, no inactive service sample, and unchanged kernel `ListenDrops`/`ListenOverflows` (`5376`/`5354`). After the capacity workflow, three isolated background swap-out samples reached at most 18,512 KB/s; none was consecutive, so the three-sample sustained-swap guard did not trigger. Observer stderr remained empty. The `default-5000` aggregate included 1,620,215 CDN HIT and 39,036 stale responses; no CDN error was recorded. Runtime evidence is intentionally uncommitted, while this result and the reproducible runbook remain in git.

Production browser smoke after `4ad6e79` covered desktop `1280x720` and mobile `390x844`. Both rendered 30 signal cards. Removing Tân An changed the first card set and produced one new `/api/signals` plus one `/api/counts` request, with no `/api/dashboard` request; the mobile snapshot recorded `13/14` wards and a one-column layout without horizontal overflow. Application/filter/card runtime logs were clean. Playwright did report the existing GA collector requests to `analytics.google.com`, `www.google.com`, and `stats.g.doubleclick.net` being blocked by the current CSP; treat those third-party telemetry messages separately from application regressions.

### Honest capacity boundary and next architecture

The current single 2-vCPU/4-GB origin plus Cloudflare edge has proven cache collapse, privacy isolation, Redis failure recovery, bounded DB sessions, the 50-key mixed-filter contract through 1,000 concurrent VUs, and the common-key homepage contract through 5,000 concurrent VUs. It has **not** proven 5,000 unique cold filters, sustained 5,000 RPS, authenticated/private-path capacity at those levels, origin-only 5,000 concurrency, or high availability. Preserve that distinction in product and infrastructure claims.

Keep the active guest-only Cloudflare contract and authenticated traffic private. Repeat the full 100 -> 500 -> 1,000 -> 5,000 acceptance chain after material cache, query, CDN, topology, or load-harness changes; routine releases still require the production verifier with `-RequireCdn`:

```powershell
.\scripts\verify_public_cache.ps1 -BaseUrl "https://radarbds.vn" -RequireCdn
```

That mode requires `CF-Ray`, guest Cloudflare HIT/stale evidence, private Cloudflare BYPASS/DYNAMIC, origin `private, no-store`, redaction, and the existing Nginx marker contract. Do not compensate by increasing Gunicorn workers, PostgreSQL connections, Redis memory, or timeouts.

## Crawl Automation

Primary daily job:

- `radar-bds-crawl.timer`
- runs Facebook-first daily crawl using admin `daily_limit` per broker profile,
- reprocesses,
- downloads/backfills images,
- does not call external LLM verification/enrichment,
- pushes VIP notifications,
- prewarms dashboard cache.

Secondary job:

- `radar-bds-guland-crawl.timer`, or fallback deploy-user crontab at 23:15,
- runs `radar.py crawl-daily --source guland --no-alert`,
- uses the same crawl lock so it does not overlap with the primary job.

BatDongSan is legacy/disabled. Do not add it to production schedules without explicit approval.

## Logs And Health

First places to inspect:

```bash
cd /opt/radar-bds/current
tail -n 160 logs/crawl-daily.log
tail -n 160 logs/guland-crawl.log
systemctl status radar-bds.service --no-pager
systemctl status radar-bds-crawl.service --no-pager
systemctl status radar-bds-guland-crawl.service --no-pager
systemctl list-timers radar-bds-crawl.timer radar-bds-guland-crawl.timer --no-pager
```

Admin crawl health should surface the latest timer/service failure and point to `logs/crawl-daily.log`.

## Local Production Sync

Pull production DB to local:

```powershell
.\scripts\sync_prod_to_local.ps1
```

Pull DB plus missing images:

```powershell
.\scripts\sync_prod_to_local.ps1 -SyncImages
```

This is production -> local only. It creates a dump on the VPS, downloads it,
backs up current local DB, then restores into the local `radar_bds` selected by
`.env.local`. If the production app DB role lacks full dump privileges, the
script retries on the VPS with the local `postgres` role.

## Guland Historical Reconciliation

The bounded reconciliation command checks only currently displayable Guland
listings, with unknown or stale source checks first. Dry-run is the default and
does not write lifecycle, raw listing, history, or reprocess data:

```powershell
& $py -X utf8 radar.py guland-reconcile --limit 100
```

Review the bounded counts before considering apply. Production apply always
requires explicit user approval:

```powershell
& $py -X utf8 radar.py guland-reconcile --limit 100 --apply
```

Apply backfills deterministic metadata, uses two explicit removal
confirmations before hiding a listing, refreshes only confirmed price changes,
and runs targeted reprocess for those changed raw rows. It never fabricates
missing historical prices. Keep the limit between 1 and 200.

## Guland Zero-ready Image Recovery

The image repair command treats a listing as ready only when it has a usable
original and, in S3 mode, the matching WebP thumbnail. It therefore includes
rows that already exist but are `NULL`, `NOT_FOUND`, or point to a missing S3
object:

```powershell
& $py -X utf8 radar.py guland-image-backfill --limit 50
```

Dry-run is the default and may perform bounded read-only source checks. Review
`zero_ready_total`, `zero_ready_targets`, `live_recoverable_targets`,
`missing_original_rows`, and `missing_thumbnail_rows` before apply.

Production apply always requires explicit user approval:

```powershell
& $py -X utf8 radar.py guland-image-backfill --limit 50 --apply
```

Apply writes changed raw snapshots to `raw_listing_revisions`, resets only
live-confirmed `NOT_FOUND` URLs or missing originals, and invokes targeted
downloads for the selected listing IDs. New image objects include image-row
identity and an asset fingerprint, so Facebook revisions cannot overwrite the
same immutable S3 key.

## Guland Publisher Activity Backfill

Before crawl or backfill, `/etc/radar-bds/radar.env` must contain a private
`GULAND_PUBLISHER_KEY_SECRET` with at least 32 random characters. Never print
or copy the value into logs, checkpoints, JSON output, source control, or an
admin response.

The command only checks Guland listings that are active/displayable, plus
currently configured source cards whose publisher status still needs checking.
Dry-run is the default:

```bash
set -a
. /etc/radar-bds/radar.env
set +a
cd /opt/radar-bds/current
/opt/radar-bds/.venv/bin/python -X utf8 radar.py guland-publisher-backfill --limit 100
```

Review candidate, live, identified/unknown/unreachable, and estimated class
counts. Output must contain aggregates only. Production apply is a separate
data mutation and always requires explicit approval:

```bash
/opt/radar-bds/.venv/bin/python -X utf8 radar.py guland-publisher-backfill --limit 100 --apply
```

Apply checkpoints to `.local/guland-publisher-backfill/<run-id>.json`, resumes
idempotently, updates publisher evidence/activity, and runs targeted listing
normalization only. Historical new-listing activity is reconstructed from the
preserved `first_seen_at`; the command does not rerun valuation or change
first-seen, posted, price-update, price history, images, coordinates, map rows,
or valuation rows.

After an approved apply, verify counts and payload redaction:

```bash
curl -fsS "http://127.0.0.1:5000/api/dashboard?source=guland&cache_refresh=1" >/dev/null
curl -fsS "http://127.0.0.1:5000/api/signals?source=guland&page=1&limit=3" >/dev/null
curl -fsS "http://127.0.0.1:5000/api/map-listings?mode=signals&source=guland" >/dev/null
```

Deployment may create the idempotent tables and deploy the code, but it must
not automatically run publisher backfill `--apply`.

## Cache Prewarm

With `RADAR_PUBLIC_CACHE_ENABLED=1`, crawl/reprocess publication automatically mirrors versions and warms the bounded route file. Manual status-only prewarm for diagnosis:

```bash
sudo -u radar bash -lc 'set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 -c "from services.public_prewarm import prewarm_configured_routes; print(prewarm_configured_routes())"'
```

Never add authenticated, admin, checkout/order, saved-listing, arbitrary-host, fragment, credential, or user-specific URLs to the warm-route file.

## Thu Dau Mot Digital Map Commerce

The paid package is runtime data, not a deploy artifact. Keep it outside the
repository and public static folders at:

```text
/var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0/
```

The exact production setup and rollback commands are in
`deployment/ubuntu24/README.md`. Keep
`DIGITAL_PRODUCT_SALES_ENABLED=0` while installing or validating the package.
Do not enable sales until the ZIP, sibling `MANIFEST.json`, PayOS credentials,
cookie secret, schema, webhook registration, and service smoke all pass.

Reconcile one existing order without printing its recovery token, QR content,
signature, credentials, or bank-transfer payload:

```bash
cd /opt/radar-bds/current
sudo -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; /opt/radar-bds/.venv/bin/python -X utf8 scripts/reconcile_digital_product_order.py --public-id <32-lowercase-hex-public-id>'
```

The command prints only the public ID, local status, remote status, changed
flag, and the applicable expiry. It may reconcile an existing `pending` or
`payment_review` order, including a `pending` order that expires during that
check or an unpaid order already marked `expired` by status polling. It does
not query PayOS again for `paid`, `cancelled`, or an expired order that already
contains a paid grant.

## Production Smoke Checklist

```bash
python3 --version
sudo systemctl status radar-bds.service --no-pager
curl -fsS https://radarbds.vn/robots.txt >/dev/null
curl -fsS https://radarbds.vn/sitemap.xml >/dev/null
curl -fsS https://radarbds.vn/api/dashboard >/dev/null
curl -fsS "https://radarbds.vn/api/signals?page=1&limit=3" >/dev/null
```

## What Not To Do

- Do not print `.env`, Telegram tokens, Supabase passwords, or admin cookies.
- Do not commit runtime images, dumps, logs, reports, or backups.
- Do not run destructive DB cleanup without an explicit `--apply` decision and a backup.
- Do not run full production reprocess casually after UI-only changes.
- Do not move Guland or any secondary source ahead of Facebook in daily crawl.
