#!/usr/bin/env bash
set -euo pipefail

BACKUP_ROOT=/var/backups/radar-bds-performance
EXPECTED_ROOT=/opt/radar-bds/current
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd -P)
BACKUP_DIR=""

require_root() {
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    printf 'error: run as root\n' >&2
    exit 2
  fi
}

require_install_sources() {
  local path
  if [ ! -d "$EXPECTED_ROOT" ] || [ "$REPO_ROOT" != "$EXPECTED_ROOT" ]; then
    printf 'error: installer must run from %s (resolved %s)\n' "$EXPECTED_ROOT" "$REPO_ROOT" >&2
    exit 3
  fi
  for path in \
    deployment/ubuntu24/redis-radar-bds.conf \
    deployment/ubuntu24/nginx-radar-bds-cache.conf \
    deployment/ubuntu24/nginx-radar-public-cache.inc \
    deployment/ubuntu24/nginx-radar-bds.conf \
    deployment/ubuntu24/60-radar-bds-connections.conf \
    deployment/ubuntu24/radar-bds.service; do
    if [ ! -f "$REPO_ROOT/$path" ]; then
      printf 'error: missing source %s\n' "$path" >&2
      exit 4
    fi
  done
}

unit_state() {
  local unit=$1 enabled active
  enabled=$(systemctl is-enabled "$unit" 2>/dev/null || true)
  active=$(systemctl is-active "$unit" 2>/dev/null || true)
  printf '%s|%s|%s\n' "$unit" "${enabled:-not-found}" "${active:-inactive}"
}

backup_path() {
  local path=$1 target="$BACKUP_DIR/files$1"
  if [ -e "$path" ] || [ -L "$path" ]; then
    mkdir -p -- "$(dirname -- "$target")"
    cp -a -- "$path" "$target"
    printf 'present|%s\n' "$path" >> "$BACKUP_DIR/files.manifest"
  else
    printf 'absent|%s\n' "$path" >> "$BACKUP_DIR/files.manifest"
  fi
}

create_backup() {
  local stamp live_site path
  stamp=$(date -u +%Y%m%d-%H%M%S)
  BACKUP_DIR="$BACKUP_ROOT/$stamp"
  if [ -e "$BACKUP_DIR" ]; then
    printf 'error: backup already exists: %s\n' "$BACKUP_DIR" >&2
    exit 5
  fi
  install -d -m 0700 "$BACKUP_DIR/files"
  : > "$BACKUP_DIR/files.manifest"
  chmod 0600 "$BACKUP_DIR/files.manifest"

  live_site=$(readlink -f /etc/nginx/sites-enabled/radar-bds.conf)
  case "$live_site" in
    /etc/nginx/sites-available/*) ;;
    *) printf 'error: unexpected live site path: %s\n' "$live_site" >&2; exit 6 ;;
  esac
  printf '%s\n' "$live_site" > "$BACKUP_DIR/live-site-path"

  for path in \
    /etc/nginx/nginx.conf \
    "$live_site" \
    /etc/nginx/conf.d/radar-bds-cache.conf \
    /etc/nginx/snippets/radar-bds-public-cache.inc \
    /etc/redis/redis.conf \
    /etc/redis/radar-bds.conf \
    /etc/systemd/system/radar-bds.service \
    /etc/sysctl.d/60-radar-bds-connections.conf; do
    backup_path "$path"
  done

  {
    unit_state nginx
    unit_state redis-server
    unit_state radar-bds.service
  } > "$BACKUP_DIR/services.state"
  nginx -T > "$BACKUP_DIR/nginx-before.txt" 2>&1
  sysctl net.core.somaxconn net.ipv4.tcp_max_syn_backlog > "$BACKUP_DIR/sysctl-before.txt"
  printf 'net.core.somaxconn=%s\n' "$(sysctl -n net.core.somaxconn)" > "$BACKUP_DIR/sysctl-values"
  printf 'net.ipv4.tcp_max_syn_backlog=%s\n' "$(sysctl -n net.ipv4.tcp_max_syn_backlog)" >> "$BACKUP_DIR/sysctl-values"
  systemctl cat radar-bds.service > "$BACKUP_DIR/radar-service-before.txt"
  chmod 0700 "$BACKUP_DIR" "$BACKUP_DIR/files"
  find "$BACKUP_DIR" -maxdepth 1 -type f -exec chmod 0600 {} +
  printf 'PERFORMANCE_BACKUP_DIR=%s\n' "$BACKUP_DIR"
}

install_redis_package() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  if dpkg-query -W -f='${Status}' redis-server 2>/dev/null | grep -Fq 'install ok installed'; then
    if [ ! -f /etc/redis/redis.conf ]; then
      apt-get install --reinstall -y redis-server
    fi
  else
    apt-get install -y redis-server
  fi
  systemctl stop redis-server 2>/dev/null || true
}

install_redis_profile() {
  install -D -m 0644 "$REPO_ROOT/deployment/ubuntu24/redis-radar-bds.conf" /etc/redis/radar-bds.conf
  if ! grep -Fqx 'include /etc/redis/radar-bds.conf' /etc/redis/redis.conf; then
    printf '\ninclude /etc/redis/radar-bds.conf\n' >> /etc/redis/redis.conf
  fi
  if [ "$(grep -Fxc 'include /etc/redis/radar-bds.conf' /etc/redis/redis.conf)" -ne 1 ]; then
    printf 'error: Redis profile include is not unique\n' >&2
    return 1
  fi
}

install_nginx_files() {
  local live_site
  live_site=$(cat "$BACKUP_DIR/live-site-path")
  install -d -m 0755 /etc/nginx/snippets
  install -d -o www-data -g www-data -m 0750 /var/cache/nginx/radar-bds
  install -m 0644 "$REPO_ROOT/deployment/ubuntu24/nginx-radar-bds-cache.conf" /etc/nginx/conf.d/radar-bds-cache.conf
  install -m 0644 "$REPO_ROOT/deployment/ubuntu24/nginx-radar-public-cache.inc" /etc/nginx/snippets/radar-bds-public-cache.inc
  install -m 0644 "$REPO_ROOT/deployment/ubuntu24/nginx-radar-bds.conf" "$live_site"
}

install_nginx_events() {
  python3 - /etc/nginx/nginx.conf <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
matches = list(re.finditer(r"(?ms)^events\s*\{.*?^\}", text))
if len(matches) != 1:
    raise SystemExit("expected exactly one Nginx events block")
match = matches[0]
block = match.group(0)
installed = re.search(r"(?m)^\s*worker_connections\s+4096\s*;", block) and re.search(
    r"(?m)^\s*multi_accept\s+on\s*;", block
)
if installed:
    raise SystemExit(0)
if len(re.findall(r"(?m)^\s*worker_connections\s+768\s*;", block)) != 1:
    raise SystemExit("worker_connections is not the reviewed 768 baseline")
if re.search(r"(?m)^\s*multi_accept\s+(?!on\s*;)\w+\s*;", block):
    raise SystemExit("multi_accept has an unexpected active value")
block = re.sub(
    r"(?m)^([ \t]*)worker_connections\s+768\s*;",
    r"\g<1>worker_connections 4096;",
    block,
    count=1,
)
if re.search(r"(?m)^\s*#\s*multi_accept\s+on\s*;", block):
    block = re.sub(
        r"(?m)^([ \t]*)#\s*multi_accept\s+on\s*;",
        r"\g<1>multi_accept on;",
        block,
        count=1,
    )
elif not re.search(r"(?m)^\s*multi_accept\s+on\s*;", block):
    block = re.sub(
        r"(?m)^([ \t]*worker_connections\s+4096\s*;)$",
        r"\1\n\tmulti_accept on;",
        block,
        count=1,
    )
path.write_text(text[: match.start()] + block + text[match.end() :], encoding="utf-8")
PY
}

validate_before_activation() {
  redis-server --test-memory 2
  redis-server /etc/redis/redis.conf --test-memory 2
  nginx -t
  systemd-analyze verify /etc/systemd/system/radar-bds.service
}

restore_unit_state() {
  local unit=$1 enabled=$2 active=$3
  if [ "$enabled" = "enabled" ]; then
    systemctl enable "$unit" >/dev/null 2>&1 || true
  else
    systemctl disable "$unit" >/dev/null 2>&1 || true
  fi
  if [ "$active" = "active" ]; then
    systemctl start "$unit"
  else
    systemctl stop "$unit" >/dev/null 2>&1 || true
  fi
}

resolve_backup_dir() {
  local requested=$1 resolved
  if [ -L "$requested" ]; then
    printf 'error: backup path may not be a symlink\n' >&2
    return 1
  fi
  resolved=$(realpath -e -- "$requested")
  case "$resolved" in
    "$BACKUP_ROOT"/*) ;;
    *) printf 'error: backup is outside %s\n' "$BACKUP_ROOT" >&2; return 1 ;;
  esac
  if [ ! -f "$resolved/files.manifest" ] || [ ! -f "$resolved/services.state" ]; then
    printf 'error: incomplete backup manifest\n' >&2
    return 1
  fi
  printf '%s\n' "$resolved"
}

rollback_mode() {
  local requested=$1 resolved state path source unit enabled active
  resolved=$(resolve_backup_dir "$requested")

  while IFS='|' read -r state path; do
    case "$state" in
      present)
        source="$resolved/files$path"
        if [ ! -e "$source" ] && [ ! -L "$source" ]; then
          printf 'error: missing backed-up file %s\n' "$source" >&2
          return 1
        fi
        mkdir -p -- "$(dirname -- "$path")"
        rm -f -- "$path"
        cp -a -- "$source" "$path"
        ;;
      absent)
        rm -f -- "$path"
        ;;
      *) printf 'error: invalid manifest state %s\n' "$state" >&2; return 1 ;;
    esac
  done < "$resolved/files.manifest"

  nginx -t
  systemctl daemon-reload
  sysctl --system
  while IFS= read -r state; do
    [ -n "$state" ] && sysctl -w "$state" >/dev/null
  done < "$resolved/sysctl-values"
  systemctl restart radar-bds.service
  systemctl reload nginx

  while IFS='|' read -r unit enabled active; do
    restore_unit_state "$unit" "$enabled" "$active"
  done < "$resolved/services.state"
  printf 'rollback_complete=%s\n' "$resolved"
}

install_failed() {
  local status=$?
  trap - ERR
  printf 'install_failed backup=%s; restoring\n' "$BACKUP_DIR" >&2
  if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    rollback_mode "$BACKUP_DIR" || printf 'automatic_rollback_failed backup=%s\n' "$BACKUP_DIR" >&2
  fi
  exit "$status"
}

install_mode() {
  require_install_sources
  create_backup
  trap install_failed ERR

  install_redis_package
  install_redis_profile
  install_nginx_files
  install_nginx_events
  install -m 0644 "$REPO_ROOT/deployment/ubuntu24/60-radar-bds-connections.conf" /etc/sysctl.d/60-radar-bds-connections.conf
  install -m 0644 "$REPO_ROOT/deployment/ubuntu24/radar-bds.service" /etc/systemd/system/radar-bds.service

  validate_before_activation
  sysctl --system
  systemctl daemon-reload
  systemctl enable --now redis-server
  systemctl restart radar-bds.service
  systemctl reload nginx

  [ "$(redis-cli -h 127.0.0.1 -p 6379 PING)" = "PONG" ]
  [ "$(systemctl is-active redis-server)" = "active" ]
  [ "$(systemctl is-active radar-bds.service)" = "active" ]
  [ "$(systemctl is-active nginx)" = "active" ]
  trap - ERR
  printf 'install_complete backup=%s\n' "$BACKUP_DIR"
}

usage() {
  printf 'usage: %s install | rollback %s/YYYYMMDD-HHMMSS\n' "$0" "$BACKUP_ROOT" >&2
  exit 64
}

require_root
[ "$#" -ge 1 ] || usage
case "$1" in
  install)
    [ "$#" -eq 1 ] || usage
    install_mode
    ;;
  rollback)
    [ "$#" -eq 2 ] || usage
    rollback_mode "$2"
    ;;
  *) usage ;;
esac
