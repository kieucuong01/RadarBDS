# Radar BDS on Ubuntu 24.04 LTS

Production target: Ubuntu Server 24.04 LTS, Python 3.12, PostgreSQL, Nginx,
Gunicorn, and systemd. This deploy is intentionally native instead of Docker
so one small VPS can share CPU/RAM with Cuon Truyen during the early stage.

## 1. Base packages

```bash
sudo apt update
sudo apt install -y \
  ca-certificates curl git nginx postgresql postgresql-contrib \
  python3 python3.12-venv python3-pip libpq-dev util-linux
```

Set the server timezone used by logs, crawl timers, and Telegram timestamps:

```bash
sudo timedatectl set-timezone Asia/Ho_Chi_Minh
```

## 2. OS user and folders

```bash
sudo adduser --system --group --home /opt/radar-bds radar
sudo mkdir -p /opt/radar-bds/current /etc/radar-bds /var/backups/radar-bds
sudo chown -R radar:radar /opt/radar-bds
sudo chmod 750 /etc/radar-bds
```

Clone or rsync the repo into `/opt/radar-bds/current`. Runtime folders such as
`data/images/`, `logs/`, and DB dumps must not be committed to git.

## 3. Python environment

```bash
cd /opt/radar-bds/current
sudo -u radar python3 -m venv /opt/radar-bds/.venv
sudo -u radar /opt/radar-bds/.venv/bin/python -m pip install -U pip setuptools wheel
sudo -u radar /opt/radar-bds/.venv/bin/pip install -r requirements.txt
```

Install Playwright OS dependencies as root, then browser binaries as the app
user so crawl jobs can launch Chromium:

```bash
sudo /opt/radar-bds/.venv/bin/python -m playwright install-deps chromium
sudo mkdir -p /opt/radar-bds/ms-playwright
sudo chown -R radar:radar /opt/radar-bds/ms-playwright
sudo -u radar env PLAYWRIGHT_BROWSERS_PATH=/opt/radar-bds/ms-playwright \
  /opt/radar-bds/.venv/bin/python -m playwright install chromium
```

## 4. PostgreSQL

Create a separate app role. Do not paste the generated password into shell
history; store it only in `/etc/radar-bds/radar.env`.

```bash
sudo -u postgres createuser radar_app --pwprompt
sudo -u postgres createdb -O radar_app radar_bds
```

Create `/etc/radar-bds/radar.env`:

```env
DATABASE_URL=postgresql://radar_app:CHANGE_ME@127.0.0.1:5432/radar_bds
FLASK_HOST=127.0.0.1
PORT=5000
FLASK_DEBUG=0
RADAR_INSIGHTS_ENABLED=0
LEGAL_IMAGE_EVIDENCE_ENABLED=0
DASHBOARD_BASE_URL=https://radar.example.com
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
TELEGRAM_WEBHOOK_SECRET=
OPS_ALERT_CHAT_ID=
APIFY_TOKEN=
ADMIN_BASIC_USER=admin
ADMIN_BASIC_PASS=CHANGE_ME
PLAYWRIGHT_BROWSERS_PATH=/opt/radar-bds/ms-playwright
PYTHONUNBUFFERED=1
```

Lock the env file down:

```bash
sudo chown root:radar /etc/radar-bds/radar.env
sudo chmod 640 /etc/radar-bds/radar.env
```

Initialize or restore data:

```bash
sudo -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; /opt/radar-bds/.venv/bin/python -X utf8 radar.py inspect'

# Custom-format backup:
pg_restore --dbname "$DATABASE_URL" /var/backups/radar-bds/radar_bds.dump

# Plain SQL backup:
psql "$DATABASE_URL" < /var/backups/radar-bds/radar_bds.sql
```

Copy `data/images/` and `data/images/thumbs/` from the old server if this is a
migration. Missing thumbnails can be backfilled later:

```bash
sudo -u radar /opt/radar-bds/.venv/bin/python -X utf8 scripts/generate_thumbnails.py --limit 1000
```

## 5. systemd

Install the service and crawl timer templates:

```bash
sudo cp deployment/ubuntu24/radar-bds.service /etc/systemd/system/radar-bds.service
sudo cp deployment/ubuntu24/radar-bds-crawl.service /etc/systemd/system/radar-bds-crawl.service
sudo cp deployment/ubuntu24/radar-bds-crawl.timer /etc/systemd/system/radar-bds-crawl.timer
sudo systemctl daemon-reload
sudo systemctl enable --now radar-bds.service
sudo systemctl enable --now radar-bds-crawl.timer
```

Useful checks:

```bash
systemctl status radar-bds.service
systemctl list-timers radar-bds-crawl.timer
journalctl -u radar-bds.service -n 100 --no-pager
journalctl -u radar-bds-crawl.service -n 100 --no-pager
```

Run one manual crawl only after the web/API smoke checks pass:

```bash
sudo systemctl start radar-bds-crawl.service
```

## 6. Nginx and SSL

Install the Nginx site after changing `server_name` in the template:

```bash
sudo cp deployment/ubuntu24/nginx-radar-bds.conf /etc/nginx/sites-available/radar-bds.conf
sudo ln -s /etc/nginx/sites-available/radar-bds.conf /etc/nginx/sites-enabled/radar-bds.conf
sudo nginx -t
sudo systemctl reload nginx
```

Use Certbot or the VPS provider's SSL flow for HTTPS. Cuon Truyen should use a
different `server_name`, port, systemd service, and database.

## 7. Smoke checks

```bash
curl -fsS http://127.0.0.1:5000/api/dashboard >/dev/null
curl -fsS "http://127.0.0.1:5000/api/signals?page=1&limit=3" >/dev/null
curl -fsS https://radar.example.com/api/dashboard >/dev/null
```

Before DNS cutover, keep the old server available until these pass on the new
VPS. Backup before every cutover:

```bash
pg_dump --format=custom "$DATABASE_URL" > /var/backups/radar-bds/radar_bds_$(date +%F).dump
tar -C /opt/radar-bds/current -czf /var/backups/radar-bds/images_$(date +%F).tgz data/images
```
