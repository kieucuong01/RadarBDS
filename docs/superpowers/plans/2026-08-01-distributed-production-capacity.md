# Distributed Production Capacity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove or disprove the original 1,000-5,000 public-request target with synchronized external k6 shards, conservative aggregation, production host observation, and fail-closed serial gates.

**Architecture:** A reusable GitHub Actions workflow runs one synchronized k6 stage across a fixed matrix and aggregates all shard summaries. A caller workflow chains the exact Phase 4 stages so a failure prevents later load. A local observer samples the VPS through the existing deploy SSH key while the workflow runs. If the distributed test fails while the host stays healthy, the evidence gates a later CDN/origin-shield migration instead of unsafe backend tuning.

**Tech Stack:** GitHub Actions, Ubuntu hosted runners, k6 v2.1.0, Python 3.12, PowerShell 5.1+, Bash, Nginx, Redis, Gunicorn, PostgreSQL.

## Global Constraints

- Target only `https://radarbds.vn`; do not accept an arbitrary target input.
- Automatic execution is restricted to `capacity-test/approved-20260801`; manual dispatch requires confirmation `radarbds.vn`.
- Use one non-canceling concurrency group so production load tests never overlap.
- Run stages serially: default 100, mixed 100, default 500, mixed 500, default 1,000, mixed 1,000, default 5,000.
- Use 1/1/1/1/2/2/5 shards respectively, with per-shard VUs 100/100/500/500/500/500/1,000.
- Duration is two minutes per shard. All shards must start no more than ten seconds after the shared epoch.
- Preserve the existing guest-only traffic contract: no Cookie, Authorization, mutation, admin, saved, order, phone, or original-source request.
- Keep Phase 4 thresholds unchanged. A missing artifact, missing metric, crossed threshold, BYPASS/private counter, or nonzero k6 exit is failure.
- Never average percentiles. Report the maximum shard p95/p99 and weighted count-based failure/check rates.
- Pin GitHub actions by immutable SHA and verify the official k6 archive checksum before execution.
- Runtime evidence stays outside git. Do not print env values, credentials, session data, response bodies, phones, or source URLs.
- Do not buy CDN service, create an external account, or change nameservers without an authenticated existing control plane.

---

### Task 1: Add conservative k6 shard aggregation

**Files:**
- Create: `scripts/load/aggregate_k6_shards.py`
- Create: `tests/test_distributed_load_aggregation.py`

**Interfaces:**
- Consumes: `--input-dir PATH`, `--expected-shards INT`, `--scenario default|mixed`, `--stage NAME`, `--run-id VALUE`, `--base-url https://radarbds.vn`, `--output PATH`.
- Each shard directory contains `summary.json` from k6 and `metadata.json` with `scenario`, `stage`, `run_id`, `base_url`, `shard`, `expected_shards`, `vus`, and `k6_exit_code`.
- Produces: one aggregate JSON document and a concise Markdown report on stdout; exits `0` only when every shard and threshold passes.

- [ ] **Step 1: Write failing aggregation tests**

Create fixture helpers in the test file rather than committing runtime JSON:

```python
def write_shard(root, shard, *, scenario="default", p95=500, p99=900,
                failed=0.001, checks=0.999, exit_code=0, bypass=0):
    folder = root / f"shard-{shard}"
    folder.mkdir()
    (folder / "metadata.json").write_text(json.dumps({
        "scenario": scenario,
        "stage": "default-1000",
        "run_id": "run-1-default-1000",
        "base_url": "https://radarbds.vn",
        "shard": shard,
        "expected_shards": 2,
        "vus": 500,
        "k6_exit_code": exit_code,
    }), "utf-8")
    (folder / "summary.json").write_text(json.dumps({"metrics": {
        "http_req_duration": {"p(95)": p95, "p(99)": p99,
                              "thresholds": {"p(95)<1000": p95 >= 1000,
                                             "p(99)<2000": p99 >= 2000}},
        "http_req_failed": {"value": failed, "passes": 10, "fails": 9990,
                            "thresholds": {"rate<0.005": failed >= 0.005}},
        "checks": {"value": checks, "passes": 9990, "fails": 10,
                   "thresholds": {"rate>0.995": checks <= 0.995}},
        "http_reqs": {"count": 10000},
        "radar_edge_hit": {"count": 9990},
        "radar_edge_miss": {"count": 10},
        "radar_edge_stale": {"count": 0},
        "radar_edge_bypass": {"count": bypass},
        "radar_edge_unknown": {"count": 0},
    }}), "utf-8")
```

Cover: two valid shards pass; maximum p95/p99 is retained; counts are summed; missing shard fails; mismatched metadata fails; any `k6_exit_code != 0` fails; any threshold value `true` fails; any bypass count fails; default p95 `>=1000` fails; mixed p95 `>=1500` fails; p99 `>=2000` fails; checks `<=0.995` and failures `>=0.005` fail.

- [ ] **Step 2: Run tests and confirm the module is missing**

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_distributed_load_aggregation.py -q
```

Expected: failure because `scripts/load/aggregate_k6_shards.py` does not exist.

- [ ] **Step 3: Implement strict parsing and aggregation**

Use `argparse`, `json`, `pathlib`, and standard-library-only validation. Reject booleans/strings where numeric values are required. Enumerate `shard-0` through `shard-(expected-1)` exactly, validate metadata equality, then compute:

```python
aggregate = {
    "scenario": args.scenario,
    "stage": args.stage,
    "run_id": args.run_id,
    "base_url": args.base_url,
    "expected_shards": args.expected_shards,
    "total_vus": sum(item["vus"] for item in metadata),
    "http_reqs": sum(metric_count(item, "http_reqs") for item in summaries),
    "max_shard_p95_ms": max(metric_value(item, "http_req_duration", "p(95)") for item in summaries),
    "max_shard_p99_ms": max(metric_value(item, "http_req_duration", "p(99)") for item in summaries),
    "edge": {name: sum(metric_count(item, name) for item in summaries)
             for name in EDGE_METRICS},
}
```

For rate metrics, sum `passes` and `fails` across shards and derive the weighted rate. Treat k6's summary threshold boolean `true` as crossed/failed. Write the output atomically through a sibling `.tmp` file and `Path.replace()`.

- [ ] **Step 4: Run focused tests and syntax validation**

```powershell
& $py -X utf8 -m pytest tests\test_distributed_load_aggregation.py -q
& $py -X utf8 -m py_compile scripts\load\aggregate_k6_shards.py
git diff --check
```

Expected: all aggregation tests pass.

- [ ] **Step 5: Commit the aggregator**

```powershell
git add scripts/load/aggregate_k6_shards.py tests/test_distributed_load_aggregation.py
git commit -m "test: aggregate distributed k6 capacity shards"
```

### Task 2: Add the synchronized reusable load-stage workflow

**Files:**
- Create: `.github/workflows/_radar-distributed-load-stage.yml`
- Modify: `tests/test_deployment_units.py`

**Interfaces:**
- `workflow_call` inputs: `scenario`, `stage`, `total_vus`, `vus_per_shard`, `shards_json`, `expected_shards`, `duration`.
- Produces artifacts `radar-<stage>-shard-<n>` and `radar-<stage>-aggregate`.
- Uses `scripts/load/radar_public_load.js` and `scripts/load/aggregate_k6_shards.py` from the same commit.

- [ ] **Step 1: Add failing static workflow assertions**

Append a test that requires:

```python
def test_reusable_distributed_load_stage_is_pinned_synchronized_and_fail_closed():
    text = Path(".github/workflows/_radar-distributed-load-stage.yml").read_text("utf-8")
    assert "workflow_call:" in text
    assert "shards_json:" in text and "fromJSON(inputs.shards_json)" in text
    assert "date +%s" in text and "+ 120" in text
    assert "late_by" in text and "10" in text
    assert "grafana/k6/releases/download/v2.1.0" in text
    assert "295d961ebfca306f295f1133068dcd403a8171c87f387928f5f30b0fbcff858a" in text
    assert "11bd71901bbe5b1630ceea73d27597364c9af683" in text
    assert "ea165f8d65b6e75b540449e92b4886f43607fa02" in text
    assert "d3f86a106a0bac45b974a628896c90dbdf5c8093" in text
    assert "--summary-export" in text and "p(99)" in text
    assert "aggregate_k6_shards.py" in text
    assert "if: always()" in text
```

- [ ] **Step 2: Run the test and confirm failure**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py::test_reusable_distributed_load_stage_is_pinned_synchronized_and_fail_closed -q
```

Expected: file-not-found failure.

- [ ] **Step 3: Implement the reusable workflow**

Use three jobs:

1. `prepare` outputs `start_epoch=$(($(date +%s) + 120))` and a run id `gha-${GITHUB_RUN_ID}-${stage}`.
2. `load` uses `strategy.fail-fast: true` and `matrix.shard: ${{ fromJSON(inputs.shards_json) }}`. It checks out the exact commit, downloads `k6-v2.1.0-linux-amd64.tar.gz`, verifies the pinned SHA, waits for `start_epoch`, fails when more than ten seconds late, writes metadata, and runs:

```bash
k6 run \
  --summary-trend-stats='avg,min,med,max,p(90),p(95),p(99),count' \
  --summary-export="$result_dir/summary.json" \
  -e BASE_URL=https://radarbds.vn \
  -e SCENARIO='${{ inputs.scenario }}' \
  -e RUN_ID="$run_id" \
  -e VUS='${{ inputs.vus_per_shard }}' \
  -e DURATION='${{ inputs.duration }}' \
  scripts/load/radar_public_load.js
```

Capture the exit code in `metadata.json`, then return the same exit code after the `if: always()` artifact upload.

3. `aggregate` runs `if: always()`, downloads all matching shard artifacts, executes the aggregator with all expected metadata values, uploads aggregate JSON, and fails if any shard artifact or threshold is invalid.

Set workflow permissions to `contents: read`; do not request `id-token`, `actions: write`, packages, deployments, or secrets.

- [ ] **Step 4: Validate static safety and YAML shape**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
& $py -X utf8 -c "import yaml; yaml.safe_load(open(r'.github/workflows/_radar-distributed-load-stage.yml', encoding='utf-8'))"
git diff --check
```

If PyYAML is unavailable, use Ruby's bundled YAML parser from Git for Windows:

```powershell
ruby -e "require 'yaml'; YAML.load_file(ARGV[0]); puts 'yaml=ok'" .github/workflows/_radar-distributed-load-stage.yml
```

- [ ] **Step 5: Commit the reusable workflow**

```powershell
git add .github/workflows/_radar-distributed-load-stage.yml tests/test_deployment_units.py
git commit -m "ci: add synchronized distributed load stage"
```

### Task 3: Add the serial production-capacity caller

**Files:**
- Create: `.github/workflows/radar-distributed-capacity.yml`
- Modify: `tests/test_deployment_units.py`

**Interfaces:**
- Push trigger: exact branch `capacity-test/approved-20260801`.
- Manual trigger: required string input `confirmation`; gate accepts only `radarbds.vn`.
- Calls the reusable stage workflow seven times with exact stage order and shard counts.

- [ ] **Step 1: Add a failing exact-stage contract test**

```python
def test_distributed_capacity_caller_is_serial_fixed_target_and_non_overlapping():
    text = Path(".github/workflows/radar-distributed-capacity.yml").read_text("utf-8")
    assert "capacity-test/approved-20260801" in text
    assert "confirmation" in text and "radarbds.vn" in text
    assert "group: radar-production-capacity" in text
    assert "cancel-in-progress: false" in text
    assert "BASE_URL" not in text
    expected = ["default_100", "mixed_100", "default_500", "mixed_500",
                "default_1000", "mixed_1000", "default_5000"]
    positions = [text.index(f"  {name}:") for name in expected]
    assert positions == sorted(positions)
    assert "shards_json: '[0,1,2,3,4]'" in text
    assert "vus_per_shard: 1000" in text
    assert "needs: mixed_1000" in text
```

- [ ] **Step 2: Run the test and confirm failure**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py::test_distributed_capacity_caller_is_serial_fixed_target_and_non_overlapping -q
```

- [ ] **Step 3: Implement the caller workflow**

Add a `gate` job that accepts the exact push branch or the exact manual confirmation. Chain each workflow-call job with `needs` on the preceding stage. Use:

```yaml
default_1000:
  needs: mixed_500
  uses: ./.github/workflows/_radar-distributed-load-stage.yml
  with:
    scenario: default
    stage: default-1000
    total_vus: 1000
    vus_per_shard: 500
    shards_json: '[0,1]'
    expected_shards: 2
    duration: 2m
```

Repeat with the exact table from the spec. The final `default_5000` uses five shards and 1,000 VUs per shard.

- [ ] **Step 4: Run focused and full workflow static gates**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
git diff --check
```

- [ ] **Step 5: Commit the caller**

```powershell
git add .github/workflows/radar-distributed-capacity.yml tests/test_deployment_units.py
git commit -m "ci: stage distributed production capacity gates"
```

### Task 4: Add bounded production observation

**Files:**
- Create: `scripts/load/production_capacity_sample.sh`
- Create: `scripts/load/observe_production_capacity.ps1`
- Modify: `tests/test_deployment_units.py`
- Modify: `docs/dev_commands.md`

**Interfaces:**
- `production_capacity_sample.sh` emits one compact JSON object and no response body or secret.
- `observe_production_capacity.ps1` accepts `-EvidenceDir`, `-DurationMinutes` (default 30), `-IntervalSeconds` (default 10), `-HostName`, `-User`, and `-KeyPath`.
- Produces `host-samples.jsonl` and `observer-summary.json`; exits nonzero on a host abort threshold.

- [ ] **Step 1: Add failing observer contract tests**

Require static evidence of the exact checks:

```python
def test_capacity_observer_is_status_only_and_enforces_host_abort_thresholds():
    sample = Path("scripts/load/production_capacity_sample.sh").read_text("utf-8")
    observer = Path("scripts/load/observe_production_capacity.ps1").read_text("utf-8")
    for token in ("systemctl is-active", "ListenOverflows", "ListenDrops",
                  "used_memory", "evicted_keys", "rejected_connections",
                  "pg_stat_activity", "vmstat"):
        assert token in sample
    assert "source /etc/radar-bds/radar.env" not in sample
    assert "DB_CONNECTIONS_MAX = 12" in observer
    assert "REDIS_MEMORY_MAX = 268435456" in observer
    assert "CPU_MAX = 90" in observer
    assert "ABORT" in observer
    assert "host-samples.jsonl" in observer
    assert "response.body" not in observer.lower()
```

- [ ] **Step 2: Run and confirm file-not-found failure**

```powershell
& $py -X utf8 -m pytest tests\test_deployment_units.py::test_capacity_observer_is_status_only_and_enforces_host_abort_thresholds -q
```

- [ ] **Step 3: Implement the remote status sampler**

Use `set -Eeuo pipefail`. Read service states, the second `vmstat 1 2` line, `/proc/net/netstat`, Redis INFO fields, and the PostgreSQL session count through the existing passwordless `sudo -n -u postgres psql -d radar_bds`. Emit JSON with Python's standard library from shell arguments. Do not source `/etc/radar-bds/radar.env`, curl application bodies, or print logs.

- [ ] **Step 4: Implement the PowerShell observer**

Resolve the evidence directory to an absolute path outside the repository. Capture the first listen counters as baseline. For each sample, call only the committed sampler through SSH, append compressed JSON to `host-samples.jsonl`, and enforce:

```powershell
$DB_CONNECTIONS_MAX = 12
$REDIS_MEMORY_MAX = 268435456
$CPU_MAX = 90
```

Abort on an inactive service, DB count above 12, Redis rejected connections, Redis memory above the cap, new listen overflow/drop counters, nonzero swap-in/out across three consecutive samples, or CPU above 90 for six consecutive samples. Write `observer-summary.json` even when aborting.

- [ ] **Step 5: Add exact operator commands**

Document starting the observer before pushing the capacity branch:

```powershell
$evidence = "C:\tmp\radar-phase4-evidence-20260801-172749\distributed-$(Get-Date -Format yyyyMMdd-HHmmss)"
.\scripts\load\observe_production_capacity.ps1 -EvidenceDir $evidence -DurationMinutes 30
```

Document that the observer and workflow must not be run twice concurrently.

- [ ] **Step 6: Validate scripts and static gates**

```powershell
& $bash -n scripts/load/production_capacity_sample.sh
$tokens=$null; $errors=$null
[System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path scripts/load/observe_production_capacity.ps1),
  [ref]$tokens, [ref]$errors) | Out-Null
if ($errors.Count) { throw ($errors | Out-String) }
& $py -X utf8 -m pytest tests\test_deployment_units.py -q
git diff --check
```

- [ ] **Step 7: Commit observation tooling**

```powershell
git add scripts/load/production_capacity_sample.sh scripts/load/observe_production_capacity.ps1 tests/test_deployment_units.py docs/dev_commands.md
git commit -m "ops: observe distributed production capacity"
```

### Task 5: Release the tooling and execute the distributed gate

**Files:**
- Runtime evidence only under `C:\tmp\radar-phase4-evidence-20260801-172749\distributed-*`
- No production data mutation

**Interfaces:**
- GitHub repository: `kieucuong01/RadarBDS`.
- Capacity branch: `capacity-test/approved-20260801`.
- Public workflow-run API identifies the push-triggered run; the GitHub connector downloads final artifacts.

- [ ] **Step 1: Run the full pre-release repository gate**

Run the Phase 4 pytest list, aggregation tests, 8 JS tests, Python/JS/shell/PowerShell syntax checks, both k6 inspect scenarios, YAML parsing, and `git diff --check`. Stop on any failure.

- [ ] **Step 2: Fetch/rebase and push tooling to `main`**

Fetch `origin/main`, rebase the isolated branch, rerun focused tests, push `HEAD:main`, and deploy the exact commit through the verified bundle fallback if the VPS Git alias still fails. Confirm production HEAD, clean checkout, active services, cache privacy, and browser flow.

- [ ] **Step 3: Start host observation**

Launch the observer for 30 minutes before triggering load. Preserve its process/cell id and evidence directory. Confirm the first sample is healthy.

- [ ] **Step 4: Trigger exactly one workflow run**

Create the exact branch from the verified `main` commit and push it once:

```powershell
git push origin HEAD:refs/heads/capacity-test/approved-20260801
```

Do not force-push or make a second commit on that branch while a run is queued or active.

- [ ] **Step 5: Monitor workflow and host without bypassing aborts**

Poll the public workflow-run API at no more than once every 20 seconds. Use the GitHub connector for job status, logs, and artifacts. If the host observer writes `ABORT`, cancel the workflow through an authenticated Actions control plane when available; otherwise the workflow thresholds still stop subsequent stages.

- [ ] **Step 6: Preserve and independently verify artifacts**

Download each stage aggregate and shard metadata. Run `aggregate_k6_shards.py` locally against the downloaded shard directories. Compare expected total VUs, stage order, run id, request counts, edge counters, and maximum shard percentiles. A green GitHub badge without these artifacts is not acceptance.

- [ ] **Step 7: Apply the decision gate**

- All seven stages plus host/privacy/browser gates pass: proceed to Task 6 and close Phase 4.
- A load stage and host threshold fail: diagnose that exact origin metric, fix through a new reviewed spec/plan if behavior changes, and restart at 100 VUs.
- A load stage fails while all host thresholds pass: stop direct-origin tests and inspect the user's authenticated Vietnix/Cloudflare control plane. Do not run 5,000 again until CDN/origin shielding is active.

### Task 6: Record final capacity truth and close or continue the master goal

**Files:**
- Modify: `docs/operations.md`
- Modify: `docs/architecture.md`
- Modify: `docs/dev_commands.md`
- Modify: `AGENTS.md`
- Modify: `docs/superpowers/plans/2026-08-01-homepage-performance-phase-4-production-capacity.md`

**Interfaces:**
- Records the workflow run URL/id, commit, evidence directory, per-stage aggregate, peak host state, cache/privacy/browser proof, and exact next decision.

- [ ] **Step 1: Update durable documentation from artifacts, not recollection**

Replace the provisional single-generator boundary with a table of distributed results. State precisely which stages passed, which first failed, and whether the origin or external path crossed an abort threshold. Retain earlier evidence as historical context.

- [ ] **Step 2: Run completion audit against every Phase 4 release gate**

Map each release-gate bullet to its artifact, host sample, cache verifier, browser trace, rollback proof, or doc line. Treat missing evidence as incomplete.

- [ ] **Step 3: Verify, commit, push, and deploy docs**

Run the complete Phase 4 repository gate again, fetch/rebase, commit only the routed docs, push `main`, deploy the exact commit, and verify local HEAD = `origin/main` = production HEAD.

- [ ] **Step 4: Update goal status only when warranted**

Call `update_goal(status="complete")` only if default 5,000 and mixed 1,000 distributed stages pass with host/privacy/browser gates. Otherwise keep the goal active and continue with the measured CDN/origin or origin-bottleneck phase; do not redefine success to the highest passing stage.
