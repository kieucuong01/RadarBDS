#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-check}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_SOURCE="$REPO_ROOT/deployment/ubuntu24"
UNIT_TARGET="/etc/systemd/system"
UNITS=(
  radar-ask-worker.service
  radar-ask-retention.service
  radar-ask-retention.timer
)

usage() {
  echo "Usage: $0 [check|install]" >&2
}

if [[ "$ACTION" != "check" && "$ACTION" != "install" ]]; then
  usage
  exit 2
fi

for unit in "${UNITS[@]}"; do
  if [[ ! -f "$UNIT_SOURCE/$unit" ]]; then
    echo "Missing Radar Ask unit: $unit" >&2
    exit 1
  fi
done

if ! command -v systemd-analyze >/dev/null 2>&1; then
  echo "systemd-analyze is required" >&2
  exit 1
fi

systemd-analyze verify \
  "$UNIT_SOURCE/radar-ask-worker.service" \
  "$UNIT_SOURCE/radar-ask-retention.service" \
  "$UNIT_SOURCE/radar-ask-retention.timer"

if [[ "$ACTION" == "check" ]]; then
  echo "Radar Ask units passed systemd verification"
  exit 0
fi

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "install requires root" >&2
  exit 1
fi

for unit in "${UNITS[@]}"; do
  install -m 0644 "$UNIT_SOURCE/$unit" "$UNIT_TARGET/$unit"
done

systemctl daemon-reload
systemctl enable --now radar-ask-retention.timer
systemctl is-active --quiet radar-ask-retention.timer

# The worker is deliberately only installed. Its feature flag and lifecycle are
# controlled by the staged Admin -> VIP -> Free rollout.
echo "Radar Ask units installed; retention timer active; worker lifecycle unchanged"
