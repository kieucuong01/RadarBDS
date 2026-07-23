#!/usr/bin/env bash
set -euo pipefail

CLI="/home/hermesops/radar-browser-use/.venv/bin/browser-use"
CDP_URL="${BU_CDP_URL:-http://127.0.0.1:9224}"

curl -fsS "$CDP_URL/json/version" >/dev/null
BU_CDP_URL="$CDP_URL" "$CLI" <<'PY'
new_tab('https://example.com')
wait_for_load()
info = page_info()
print(info)
assert 'example.com' in info.get('url', ''), info
assert 'Example Domain' in info.get('title', ''), info
PY
