#!/usr/bin/env bash
set -Eeuo pipefail

service_state() {
  systemctl is-active "$1" 2>/dev/null || true
}

redis_value() {
  local section="$1"
  local key="$2"
  redis-cli -h 127.0.0.1 INFO "$section" \
    | tr -d '\r' \
    | awk -F: -v wanted="$key" '$1 == wanted { print $2; exit }'
}

vm_line="$(vmstat 1 2 | tail -n 1)"
read -r _ _ _ _ _ _ swap_in swap_out _ _ _ _ cpu_user cpu_system cpu_idle _ _ <<<"$vm_line"
cpu_percent=$((100 - cpu_idle))
memory_available_kb="$(awk '$1 == "MemAvailable:" { print $2 }' /proc/meminfo)"
load_1m="$(awk '{ print $1 }' /proc/loadavg)"

read -r listen_overflows listen_drops < <(python3 - <<'PY'
from pathlib import Path

lines = Path("/proc/net/netstat").read_text(encoding="ascii").splitlines()
values = {}
for index in range(0, len(lines) - 1, 2):
    if not lines[index].startswith("TcpExt:") or not lines[index + 1].startswith("TcpExt:"):
        continue
    names = lines[index].split()[1:]
    counts = lines[index + 1].split()[1:]
    values = dict(zip(names, counts, strict=True))
    break
print(values.get("ListenOverflows", "0"), values.get("ListenDrops", "0"))
PY
)

used_memory="$(redis_value memory used_memory)"
evicted_keys="$(redis_value stats evicted_keys)"
rejected_connections="$(redis_value stats rejected_connections)"
keyspace_hits="$(redis_value stats keyspace_hits)"
keyspace_misses="$(redis_value stats keyspace_misses)"

read -r db_connections db_active < <(
  sudo -n -u postgres psql -d radar_bds -At -F ' ' -c \
    "SELECT COUNT(*), COUNT(*) FILTER (WHERE state = 'active') FROM pg_stat_activity WHERE datname = current_database() AND backend_type = 'client backend' AND usename <> 'postgres'"
)

tcp_total="$(ss -Htan | wc -l | tr -d ' ')"
tcp_established="$(ss -Htan state established | wc -l | tr -d ' ')"
radar_restarts="$(systemctl show radar-bds.service -p NRestarts --value)"
redis_restarts="$(systemctl show redis-server.service -p NRestarts --value)"
nginx_restarts="$(systemctl show nginx.service -p NRestarts --value)"
radar_errors="$({
  sudo -n journalctl -u radar-bds.service --since '30 seconds ago' --no-pager -q 2>/dev/null \
    | grep -Eic 'out of memory|oom|too many open files|worker failed|traceback' || true
} | tail -n 1)"
nginx_errors="$({
  sudo -n journalctl -u nginx.service --since '30 seconds ago' --no-pager -q 2>/dev/null \
    | grep -Eic 'out of memory|oom|too many open files|emerg|alert' || true
} | tail -n 1)"

export CAPTURED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
export CPU_PERCENT="$cpu_percent"
export CPU_SYSTEM="$cpu_system"
export CPU_USER="$cpu_user"
export DB_ACTIVE="$db_active"
export DB_CONNECTIONS="$db_connections"
export EVICTED_KEYS="${evicted_keys:-0}"
export KEYSPACE_HITS="${keyspace_hits:-0}"
export KEYSPACE_MISSES="${keyspace_misses:-0}"
export LISTEN_DROPS="$listen_drops"
export LISTEN_OVERFLOWS="$listen_overflows"
export LOAD_1M="$load_1m"
export MEMORY_AVAILABLE_KB="$memory_available_kb"
export NGINX_ERRORS="${nginx_errors:-0}"
export NGINX_RESTARTS="${nginx_restarts:-0}"
export NGINX_STATE="$(service_state nginx.service)"
export POSTGRES_STATE="$(service_state postgresql.service)"
export RADAR_ERRORS="${radar_errors:-0}"
export RADAR_RESTARTS="${radar_restarts:-0}"
export RADAR_STATE="$(service_state radar-bds.service)"
export REDIS_RESTARTS="${redis_restarts:-0}"
export REDIS_STATE="$(service_state redis-server.service)"
export REJECTED_CONNECTIONS="${rejected_connections:-0}"
export SWAP_IN="$swap_in"
export SWAP_OUT="$swap_out"
export TCP_ESTABLISHED="$tcp_established"
export TCP_TOTAL="$tcp_total"
export USED_MEMORY="${used_memory:-0}"

python3 - <<'PY'
import json
import os


def integer(name):
    return int(os.environ[name])


def decimal(name):
    return float(os.environ[name])


sample = {
    "captured_at": os.environ["CAPTURED_AT"],
    "services": {
        "nginx": os.environ["NGINX_STATE"],
        "radar": os.environ["RADAR_STATE"],
        "redis": os.environ["REDIS_STATE"],
        "postgresql": os.environ["POSTGRES_STATE"],
    },
    "host": {
        "cpu_percent": integer("CPU_PERCENT"),
        "cpu_user": integer("CPU_USER"),
        "cpu_system": integer("CPU_SYSTEM"),
        "load_1m": decimal("LOAD_1M"),
        "memory_available_kb": integer("MEMORY_AVAILABLE_KB"),
        "swap_in": integer("SWAP_IN"),
        "swap_out": integer("SWAP_OUT"),
    },
    "tcp": {
        "total": integer("TCP_TOTAL"),
        "established": integer("TCP_ESTABLISHED"),
        "ListenOverflows": integer("LISTEN_OVERFLOWS"),
        "ListenDrops": integer("LISTEN_DROPS"),
    },
    "redis": {
        "used_memory": integer("USED_MEMORY"),
        "evicted_keys": integer("EVICTED_KEYS"),
        "rejected_connections": integer("REJECTED_CONNECTIONS"),
        "keyspace_hits": integer("KEYSPACE_HITS"),
        "keyspace_misses": integer("KEYSPACE_MISSES"),
    },
    "postgresql": {
        "connections": integer("DB_CONNECTIONS"),
        "active": integer("DB_ACTIVE"),
    },
    "restarts": {
        "nginx": integer("NGINX_RESTARTS"),
        "radar": integer("RADAR_RESTARTS"),
        "redis": integer("REDIS_RESTARTS"),
    },
    "recent_errors": {
        "nginx": integer("NGINX_ERRORS"),
        "radar": integer("RADAR_ERRORS"),
    },
}
print(json.dumps(sample, separators=(",", ":"), sort_keys=True))
PY
