param(
    [string] $HostName = "103.90.226.230",
    [string] $User = "deploy",
    [string] $KeyPath = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa",
    [string] $RemotePath = "/opt/radar-bds/current",
    [string] $ExpectedSha = "",
    [ValidateSet("off", "on")]
    [string] $ExpectedFeatureState = "off",
    [ValidatePattern("^(admin|admin,vip|admin,vip,free)$")]
    [string] $ExpectedAllowedTiers = "admin",
    [ValidateSet("foundation", "knowledge")]
    [string] $ReadinessPhase = "foundation",
    [ValidateRange(1, 32)]
    [int] $GunicornWorkers = 3,
    [ValidateRange(1, 4)]
    [int] $WebReadPoolMax = 1,
    [ValidateRange(1, 8)]
    [int] $WorkerProcesses = 1,
    [ValidateRange(1, 4)]
    [int] $WorkerReadPoolMax = 2,
    [switch] $RunAuthenticatedSmoke,
    [switch] $ConfirmLiveCost,
    [string] $AuthCredentialPath = "",
    [switch] $ConfigCheck
)

$ErrorActionPreference = "Stop"
$requiredGates = @(
    "auth-private-cache",
    "budget-thresholds",
    "connection-headroom",
    "deployed-sha",
    "feature-and-tiers",
    "legacy-endpoint-absent",
    "public-health",
    "read-only-grants",
    "redaction",
    "schema",
    "service-and-timer",
    "valuation-trace-coverage"
)
$assistantReadCapacity = ($GunicornWorkers * $WebReadPoolMax) +
    ($WorkerProcesses * $WorkerReadPoolMax)

if ($ExpectedSha -notmatch "^[0-9a-fA-F]{40}$") {
    throw "ExpectedSha must be an exact 40-character Git SHA"
}

$resolvedAuthCredentialPath = ""
if ($RunAuthenticatedSmoke) {
    if (-not $ConfirmLiveCost) {
        throw "RunAuthenticatedSmoke requires ConfirmLiveCost"
    }
    if ($ExpectedFeatureState -ne "on") {
        throw "RunAuthenticatedSmoke requires ExpectedFeatureState on"
    }
    if (-not $AuthCredentialPath -or -not (Test-Path -LiteralPath $AuthCredentialPath -PathType Leaf)) {
        throw "RunAuthenticatedSmoke requires AuthCredentialPath"
    }
    $resolvedAuthCredentialPath = (Resolve-Path -LiteralPath $AuthCredentialPath).Path
    try {
        $credential = Get-Content -LiteralPath $resolvedAuthCredentialPath -Raw -Encoding UTF8 |
            ConvertFrom-Json
        $propertyNames = @($credential.PSObject.Properties.Name | Sort-Object)
        if (($propertyNames -join ",") -ne "identifier,password") {
            throw "invalid shape"
        }
        if (
            -not ($credential.identifier -is [string]) -or
            -not ($credential.password -is [string]) -or
            $credential.identifier.Length -lt 3 -or
            $credential.identifier.Length -gt 320 -or
            $credential.password.Length -lt 8 -or
            $credential.password.Length -gt 256
        ) {
            throw "invalid values"
        }
    }
    catch {
        throw "AuthCredentialPath must contain only bounded identifier/password strings"
    }
    $credential = $null
}

if ($ConfigCheck) {
    [pscustomobject]@{
        assistantReadCapacity = $assistantReadCapacity
        authenticatedSmoke = [bool]$RunAuthenticatedSmoke
        requiredGates = $requiredGates
    } | ConvertTo-Json -Compress
    exit 0
}

if (-not (Test-Path -LiteralPath $KeyPath)) {
    throw "SSH key not found: $KeyPath"
}

$sshTarget = "$User@$HostName"
$sshArgs = @(
    "-i", $KeyPath,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    $sshTarget
)
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$remoteScriptPath = "/tmp/radar-ask-verify-$stamp.sh"
$remoteCredentialPath = "/tmp/radar-ask-auth-$stamp.json"
$localScriptPath = Join-Path $env:TEMP "radar-ask-verify-$stamp.sh"

$remoteScript = @'
set -euo pipefail

cd "__REMOTE_PATH__"
expected_sha="__EXPECTED_SHA__"
expected_feature="__EXPECTED_FEATURE__"
expected_tiers="__EXPECTED_TIERS__"
readiness_phase="__READINESS_PHASE__"
assistant_capacity="__ASSISTANT_CAPACITY__"
auth_mode="__AUTH_MODE__"
auth_credential_path="__AUTH_CREDENTIAL_PATH__"

actual_sha="$(git rev-parse HEAD)"
if [[ "$actual_sha" != "$expected_sha" ]]; then
  echo "deployed SHA mismatch" >&2
  exit 1
fi

systemctl is-active --quiet radar-bds.service
systemctl cat radar-ask-worker.service >/dev/null
systemctl cat radar-ask-retention.service >/dev/null
systemctl cat radar-ask-retention.timer >/dev/null
systemctl is-active --quiet radar-ask-retention.timer
systemctl is-enabled --quiet radar-ask-retention.timer

if [[ "$expected_feature" == "on" ]]; then
  systemctl is-active --quiet radar-ask-worker.service
else
  if systemctl is-active --quiet radar-ask-worker.service; then
    echo "Radar Ask worker must stay inactive while the feature is off" >&2
    exit 1
  fi
fi

headers_file="$(mktemp)"
body_file="$(mktemp)"
temp_files=("$headers_file" "$body_file")
cleanup() {
  rm -f "${temp_files[@]}"
}
trap cleanup EXIT

for url in \
  "http://127.0.0.1:5000/" \
  "http://127.0.0.1:5000/api/dashboard" \
  "http://127.0.0.1:5000/api/signals?page=1&limit=3"; do
  curl -fsS --max-time 20 "$url" >/dev/null
done

auth_status="$(curl -sS --max-time 20 -D "$headers_file" -o "$body_file" -w '%{http_code}' \
  "http://127.0.0.1:5000/api/radar-ask/sessions")"
expected_auth_status=404
if [[ "$expected_feature" == "on" ]]; then
  expected_auth_status=401
fi
if [[ "$auth_status" != "$expected_auth_status" ]]; then
  echo "Radar Ask unauthenticated gate returned an unexpected status" >&2
  exit 1
fi
if ! grep -Eiq '^Cache-Control:.*private.*no-store' "$headers_file"; then
  echo "Radar Ask response is missing private no-store" >&2
  exit 1
fi
if grep -Eiq '^X-Radar-Public-Cache:' "$headers_file"; then
  echo "Radar Ask response entered the public cache path" >&2
  exit 1
fi

legacy_status="$(curl -sS --max-time 20 -o /dev/null -w '%{http_code}' \
  "http://127.0.0.1:5000/api/chat")"
if [[ "$legacy_status" != "404" ]]; then
  echo "legacy Radar Assistant endpoint is still reachable" >&2
  exit 1
fi

sudo -n -u radar env \
  VERIFY_REMOTE_PATH="$PWD" \
  VERIFY_EXPECTED_FEATURE="$expected_feature" \
  VERIFY_EXPECTED_TIERS="$expected_tiers" \
  VERIFY_READINESS_PHASE="$readiness_phase" \
  VERIFY_ASSISTANT_READ_CAPACITY="$assistant_capacity" \
  bash -s <<'RADAR_ENV_CHECK'
set -eo pipefail
cd "$VERIFY_REMOTE_PATH"
set -a
# shellcheck disable=SC1091
source /etc/radar-bds/radar.env
set +a
set -u

feature_raw="${RADAR_ASK_ENABLED:-0}"
feature_normalized="$(printf '%s' "$feature_raw" | tr '[:upper:]' '[:lower:]')"
feature_on=0
case "$feature_normalized" in
  1|true|yes|on) feature_on=1 ;;
  0|false|no|off|'') feature_on=0 ;;
  *) echo "RADAR_ASK_ENABLED is invalid" >&2; exit 1 ;;
esac
if [[ "$VERIFY_EXPECTED_FEATURE" == "on" && "$feature_on" -ne 1 ]]; then
  echo "Radar Ask was expected on" >&2
  exit 1
fi
if [[ "$VERIFY_EXPECTED_FEATURE" == "off" && "$feature_on" -ne 0 ]]; then
  echo "Radar Ask was expected off" >&2
  exit 1
fi
if [[ "$feature_on" -eq 1 && -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "DeepSeek API key is missing" >&2
  exit 1
fi
if [[ "${RADAR_ASK_ALLOWED_TIERS:-admin}" != "$VERIFY_EXPECTED_TIERS" ]]; then
  echo "Radar Ask allowed tiers differ from the rollout gate" >&2
  exit 1
fi
if [[ "${RADAR_ASK_ROUTER_MODEL:-deepseek-v4-flash}" != "deepseek-v4-flash" \
  || "${RADAR_ASK_FREE_MODEL:-deepseek-v4-flash}" != "deepseek-v4-flash" \
  || "${RADAR_ASK_SMART_MODEL:-deepseek-v4-pro}" != "deepseek-v4-pro" ]]; then
  echo "Radar Ask model IDs differ from the reviewed provider contract" >&2
  exit 1
fi
if [[ "${RADAR_ASK_MONTHLY_WARN_USD:-20}" != "20" ]]; then
  echo "Radar Ask monthly warning must be USD 20" >&2
  exit 1
fi
if [[ "${RADAR_ASK_MONTHLY_HARD_USD:-50}" != "50" ]]; then
  echo "Radar Ask monthly hard stop must be USD 50" >&2
  exit 1
fi

/opt/radar-bds/.venv/bin/python -X utf8 scripts/configure_radar_ask_db_role.py check \
  --phase "$VERIFY_READINESS_PHASE"

/opt/radar-bds/.venv/bin/python -X utf8 - <<'PY'
import json
import math
import os

import psycopg

from services.radar_ask.planner import _redact
from services.radar_ask.config import TIER_DAILY_LIMITS


database_url = os.environ.get("DATABASE_URL", "").strip()
if not database_url:
    raise SystemExit("DATABASE_URL is required for production verification")
if TIER_DAILY_LIMITS.get("admin") != 100:
    raise SystemExit("Admin Radar Ask quota is not 100")

required_tables = {
    "radar_ask_sessions",
    "radar_ask_messages",
    "radar_ask_runs",
    "radar_ask_tool_calls",
    "radar_ask_evidence",
    "radar_ask_usage",
    "radar_ask_usage_attempts",
    "radar_ask_feedback",
}
with psycopg.connect(database_url) as conn:
    tables = {
        row[0]
        for row in conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public' AND table_name=ANY(%s::text[])
            """,
            (sorted(required_tables),),
        ).fetchall()
    }
    if tables != required_tables:
        raise SystemExit("Radar Ask schema is incomplete")

    total, covered = conn.execute(
        """
        WITH latest AS (
            SELECT DISTINCT ON (listing_id) valuation_trace
            FROM valuation_results
            WHERE fair_ppm2 IS NOT NULL
            ORDER BY listing_id, computed_at DESC, id DESC
        )
        SELECT COUNT(*), COUNT(*) FILTER (
            WHERE jsonb_typeof(valuation_trace)='object'
              AND valuation_trace <> '{}'::jsonb
        )
        FROM latest
        """
    ).fetchone()
    if total <= 0 or covered != total:
        raise SystemExit("latest eligible valuation trace coverage is not 100 percent")

    max_connections = int(conn.execute("SHOW max_connections").fetchone()[0])
    reserved = int(conn.execute("SHOW superuser_reserved_connections").fetchone()[0])
    active = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM pg_stat_activity
            WHERE datname=current_database() AND pid<>pg_backend_pid()
            """
        ).fetchone()[0]
    )
    assistant_capacity = int(os.environ["VERIFY_ASSISTANT_READ_CAPACITY"])
    required_headroom = math.ceil(max_connections * 0.25)
    remaining = max_connections - reserved - active - assistant_capacity
    if remaining < required_headroom:
        raise SystemExit("PostgreSQL connection headroom is below 25 percent")

probe = "Môi giới Hùng? 0901234567 hung@example.com https://example.com"
safe = _redact(probe, maximum=2000) or ""
for private in ("Hùng", "0901234567", "hung@example.com", "https://example.com"):
    if private.casefold() in safe.casefold():
        raise SystemExit("provider-bound planner redaction failed")

print(json.dumps({"schema": "ok", "valuation_trace": "100%", "headroom": "ok", "redaction": "ok"}))
PY
RADAR_ENV_CHECK

if [[ "$auth_mode" == "1" ]]; then
  cookie_file="$(mktemp)"
  auth_headers="$(mktemp)"
  auth_body="$(mktemp)"
  planner_request="$(mktemp)"
  standard_request="$(mktemp)"
  deep_request="$(mktemp)"
  planner_body="$(mktemp)"
  standard_body="$(mktemp)"
  deep_body="$(mktemp)"
  poll_body="$(mktemp)"
  temp_files+=(
    "$cookie_file" "$auth_headers" "$auth_body"
    "$planner_request" "$standard_request" "$deep_request"
    "$planner_body" "$standard_body" "$deep_body" "$poll_body"
  )

  assert_private_headers() {
    if ! grep -Eiq '^Cache-Control:.*private.*no-store' "$1"; then
      echo "authenticated Radar Ask response is missing private no-store" >&2
      exit 1
    fi
    if grep -Eiq '^X-Radar-Public-Cache:' "$1"; then
      echo "authenticated Radar Ask response entered the public cache path" >&2
      exit 1
    fi
  }

  login_status="$(curl -sS --max-time 20 \
    -D "$auth_headers" -o "$auth_body" -w '%{http_code}' \
    -c "$cookie_file" \
    -H 'Content-Type: application/json' \
    -H 'Origin: http://127.0.0.1:5000' \
    --data-binary "@$auth_credential_path" \
    'http://127.0.0.1:5000/api/auth/login')"
  if [[ "$login_status" != "200" ]]; then
    echo "authenticated Radar Ask smoke login failed" >&2
    exit 1
  fi
  assert_private_headers "$auth_headers"
  /opt/radar-bds/.venv/bin/python -X utf8 - "$auth_body" <<'PY_AUTH'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("ok") is not True or (payload.get("user") or {}).get("tier") != "admin":
    raise SystemExit("authenticated smoke requires an Admin account")
PY_AUTH

  cat >"$planner_request" <<'JSON'
{"question":"Thanh khoản khu vực này hiện thế nào?","requested_depth":"standard"}
JSON
  cat >"$standard_request" <<'JSON'
{"question":"Bảng giá đất TP.HCM có dùng để định giá thực tế không?","requested_depth":"standard"}
JSON
  cat >"$deep_request" <<'JSON'
{"question":"Nghiên cứu sâu Phú Mỹ và Định Hòa giá đất nền khác nhau sao?","requested_depth":"deep"}
JSON

  submit_question() {
    local label="$1"
    local request_file="$2"
    local response_file="$3"
    local request_stamp
    request_stamp="$(date +%s%N)"
    local status
    status="$(curl -sS --max-time 90 \
      -D "$auth_headers" -o "$response_file" -w '%{http_code}' \
      -b "$cookie_file" -c "$cookie_file" \
      -H 'Content-Type: application/json' \
      -H 'Origin: http://127.0.0.1:5000' \
      -H "Idempotency-Key: verify-${actual_sha:0:12}-$label-$request_stamp" \
      --data-binary "@$request_file" \
      'http://127.0.0.1:5000/api/radar-ask/questions')"
    if [[ "$status" != "200" && "$status" != "202" ]]; then
      echo "authenticated Radar Ask question failed" >&2
      exit 1
    fi
    assert_private_headers "$auth_headers"
  }

  submit_question planner "$planner_request" "$planner_body"
  submit_question standard "$standard_request" "$standard_body"
  submit_question deep "$deep_request" "$deep_body"

  for response_file in "$planner_body" "$standard_body" "$deep_body"; do
    /opt/radar-bds/.venv/bin/python -X utf8 - "$response_file" <<'PY_RUN'
import json
import sys
from uuid import UUID
payload = json.load(open(sys.argv[1], encoding="utf-8"))
UUID(str(payload.get("run_id")))
if (payload.get("quota") or {}).get("tier") != "admin":
    raise SystemExit("authenticated smoke did not receive Admin quota policy")
if payload.get("status") not in {
    "created", "queued", "running", "completed", "clarifying", "insufficient"
}:
    raise SystemExit("authenticated smoke returned an invalid run status")
PY_RUN
  done

  deep_run_id="$(/opt/radar-bds/.venv/bin/python -X utf8 - "$deep_body" <<'PY_ID'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["run_id"])
PY_ID
)"
  deep_terminal=0
  for _attempt in $(seq 1 90); do
    poll_status="$(curl -sS --max-time 20 \
      -D "$auth_headers" -o "$poll_body" -w '%{http_code}' \
      -b "$cookie_file" \
      "http://127.0.0.1:5000/api/radar-ask/runs/$deep_run_id")"
    if [[ "$poll_status" != "200" ]]; then
      echo "authenticated Radar Ask exact-run poll failed" >&2
      exit 1
    fi
    assert_private_headers "$auth_headers"
    poll_state="$(/opt/radar-bds/.venv/bin/python -X utf8 - "$poll_body" "$deep_run_id" <<'PY_POLL'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("run_id") != sys.argv[2]:
    raise SystemExit("poll returned a different run")
print(payload.get("status", "invalid"))
PY_POLL
)"
    case "$poll_state" in
      completed|clarifying|insufficient) deep_terminal=1; break ;;
      created|queued|running) sleep 1 ;;
      *) echo "authenticated Radar Ask Deep run failed" >&2; exit 1 ;;
    esac
  done
  if [[ "$deep_terminal" -ne 1 ]]; then
    echo "authenticated Radar Ask Deep run did not finish before the verifier deadline" >&2
    exit 1
  fi

  curl -sS --max-time 20 -o /dev/null \
    -b "$cookie_file" \
    -H 'Origin: http://127.0.0.1:5000' \
    -X POST 'http://127.0.0.1:5000/api/auth/logout'
  echo "authenticated Radar Ask Admin/Flash/Pro/Deep smoke passed"
fi

echo "Radar Ask production verification passed for $actual_sha"
'@

$replacements = @{
    "__REMOTE_PATH__" = $RemotePath
    "__EXPECTED_SHA__" = $ExpectedSha.ToLowerInvariant()
    "__EXPECTED_FEATURE__" = $ExpectedFeatureState
    "__EXPECTED_TIERS__" = $ExpectedAllowedTiers
    "__READINESS_PHASE__" = $ReadinessPhase
    "__ASSISTANT_CAPACITY__" = [string]$assistantReadCapacity
    "__AUTH_MODE__" = if ($RunAuthenticatedSmoke) { "1" } else { "0" }
    "__AUTH_CREDENTIAL_PATH__" = $remoteCredentialPath
}
foreach ($entry in $replacements.GetEnumerator()) {
    if ($entry.Value -match "['`"`r`n]") {
        throw "Verifier argument contains an unsafe character"
    }
    $remoteScript = $remoteScript.Replace($entry.Key, $entry.Value)
}

try {
    $remoteScript = $remoteScript -replace "`r`n?", "`n"
    [System.IO.File]::WriteAllText(
        $localScriptPath,
        $remoteScript,
        [System.Text.UTF8Encoding]::new($false)
    )
    if ($RunAuthenticatedSmoke) {
        & scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 `
            $resolvedAuthCredentialPath "${sshTarget}:$remoteCredentialPath"
        if ($LASTEXITCODE -ne 0) {
            throw "Radar Ask credential upload failed with exit code $LASTEXITCODE"
        }
        & ssh @sshArgs "chmod 600 '$remoteCredentialPath'"
        if ($LASTEXITCODE -ne 0) {
            throw "Radar Ask credential permission hardening failed with exit code $LASTEXITCODE"
        }
    }
    & scp -i $KeyPath -o BatchMode=yes -o ConnectTimeout=15 `
        $localScriptPath "${sshTarget}:$remoteScriptPath"
    if ($LASTEXITCODE -ne 0) {
        throw "Radar Ask verifier upload failed with exit code $LASTEXITCODE"
    }
    & ssh @sshArgs "chmod 700 '$remoteScriptPath' && bash '$remoteScriptPath'"
    if ($LASTEXITCODE -ne 0) {
        throw "Radar Ask production verification failed with exit code $LASTEXITCODE"
    }
}
finally {
    if (Test-Path -LiteralPath $localScriptPath) {
        Remove-Item -LiteralPath $localScriptPath -Force
    }
    & ssh @sshArgs "rm -f '$remoteScriptPath' '$remoteCredentialPath'" 2>$null | Out-Null
}
