#!/usr/bin/env bash
set -euo pipefail
cd /opt/radar-bds/current
if [ "$(id -u)" != "0" ]; then
  echo "Run with sudo: installs crawl result hooks and the image backlog timer." >&2
  exit 1
fi
for source in facebook guland; do
  unit=radar-bds-crawl.service
  if [ "$source" = guland ]; then unit=radar-bds-guland-crawl.service; fi
  install -d -m 0755 "/etc/systemd/system/$unit.d"
  printf '[Service]\nExecStopPost=/opt/radar-bds/.venv/bin/python -X utf8 -m services.crawl_workflow %s\n' "$source" > "/etc/systemd/system/$unit.d/workflow.conf"
done
install -m 0644 deployment/ubuntu24/radar-bds-image-backfill.service /etc/systemd/system/
install -m 0644 deployment/ubuntu24/radar-bds-image-backfill.timer /etc/systemd/system/
systemd-analyze verify radar-bds-crawl.service radar-bds-guland-crawl.service radar-bds-image-backfill.service radar-bds-image-backfill.timer
systemctl daemon-reload
systemctl enable --now radar-bds-image-backfill.timer
systemctl list-timers radar-bds-crawl.timer radar-bds-guland-crawl.timer radar-bds-image-backfill.timer --no-pager
