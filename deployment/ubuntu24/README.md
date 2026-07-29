# Radar BDS on Ubuntu 24.04 LTS

Production target: Ubuntu Server 24.04 LTS, Python 3.12, PostgreSQL, Nginx,
Gunicorn, and systemd. This deploy is intentionally native instead of Docker
so one small VPS can share CPU/RAM with Cuon Truyen during the early stage.

## 1. Base packages

```bash
sudo apt update
sudo apt install -y \
  ca-certificates curl git nginx postgresql postgresql-contrib \
  python3 python3.12-venv python3-pip libpq-dev util-linux \
  certbot python3-certbot-nginx
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
PUBLIC_BASE_URL=https://radarbds.vn
DASHBOARD_BASE_URL=https://radarbds.vn
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

### Thu Dau Mot digital map package and PayOS

Keep the validated ZIP and its exact sibling manifest outside the checkout:

```text
/var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0/
```

Install with sales disabled. The source files below are the separately
transferred, already validated release files; never copy them into `static/`:

```bash
sudo install -d -o radar -g radar -m 0750 \
  /var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0
sudo -u radar cp \
  /tmp/radarbds-thu-dau-mot-map-v1.0.zip \
  /var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0/
sudo -u radar cp \
  /tmp/MANIFEST.json \
  /var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0/
sudo chown radar:radar \
  /var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0/radarbds-thu-dau-mot-map-v1.0.zip \
  /var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0/MANIFEST.json
sudo chmod 0750 \
  /var/lib/radar-bds/products \
  /var/lib/radar-bds/products/thu-dau-mot-map-bundle \
  /var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0
sudo chmod 0640 \
  /var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0/radarbds-thu-dau-mot-map-v1.0.zip \
  /var/lib/radar-bds/products/thu-dau-mot-map-bundle/1.0/MANIFEST.json
```

Add the following keys to `/etc/radar-bds/radar.env`. Store real secrets only
in that protected file; `DIGITAL_PRODUCT_COOKIE_SECRET` must contain at least
64 characters:

```env
PAYOS_CLIENT_ID=
PAYOS_API_KEY=
PAYOS_CHECKSUM_KEY=
DIGITAL_PRODUCT_COOKIE_SECRET=
DIGITAL_PRODUCT_STORAGE_DIR=/var/lib/radar-bds/products
DIGITAL_PRODUCT_SALES_ENABLED=0
```

Require exactly one sales-flag line and verify the disabled value without
printing any other environment entry:

```bash
test "$(sudo grep -c '^DIGITAL_PRODUCT_SALES_ENABLED=' /etc/radar-bds/radar.env)" -eq 1
sudo grep -qx 'DIGITAL_PRODUCT_SALES_ENABLED=0' /etc/radar-bds/radar.env
sudo -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current; /opt/radar-bds/.venv/bin/python -X utf8 -c "from config.settings import get_digital_product_commerce_settings as load; assert not load().sales_enabled; print(\"digital_product_sales_enabled=0\")"'
```

Apply the schema and restart while sales remain disabled:

```bash
cd /opt/radar-bds/current
sudo -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; /opt/radar-bds/.venv/bin/python -X utf8 -c "from db.schema import init_schema; init_schema()"'
sudo systemctl restart radar-bds.service
curl -fsS https://radarbds.vn/ban-do-thu-dau-mot | grep -F 'Sắp mở bán'
```

In the PayOS merchant configuration, register and confirm this exact webhook:

```text
https://radarbds.vn/api/webhooks/payos/digital-products
```

Validate the protected copy through the same registry and integrity gate used
by checkout. This command deliberately keeps sales disabled:

```bash
cd /opt/radar-bds/current
sudo -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; /opt/radar-bds/.venv/bin/python -X utf8 -c "from config.settings import get_digital_product_commerce_settings; from services.digital_products import get_digital_product, snapshot_protected_package; s=get_digital_product_commerce_settings(); assert not s.sales_enabled and s.storage_dir is not None; p=get_digital_product(\"thu-dau-mot-map-bundle\"); x=snapshot_protected_package(p, s.storage_dir); print(f\"protected_package_ok size={x.size} sha256={x.sha256}\")"'
```

Only after all checks pass, atomically change the single allowlisted flag,
verify the effective application setting, restart, and perform one deliberate
99,000 VND production payment:

```bash
set -euo pipefail
test "$(sudo grep -c '^DIGITAL_PRODUCT_SALES_ENABLED=' /etc/radar-bds/radar.env)" -eq 1
sudo sed -i 's/^DIGITAL_PRODUCT_SALES_ENABLED=.*/DIGITAL_PRODUCT_SALES_ENABLED=1/' /etc/radar-bds/radar.env
sudo grep -qx 'DIGITAL_PRODUCT_SALES_ENABLED=1' /etc/radar-bds/radar.env
sudo -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current; /opt/radar-bds/.venv/bin/python -X utf8 -c "from config.settings import get_digital_product_commerce_settings as load; s=load(); assert s.sales_enabled and s.ready_for_checkout; print(\"digital_product_sales_enabled=1 ready_for_checkout=1\")"'
sudo systemctl restart radar-bds.service
sudo systemctl status radar-bds.service --no-pager
curl -fsS https://radarbds.vn/ban-do-thu-dau-mot | grep -F 'https://schema.org/InStock' >/dev/null
```

Confirm that PayOS settles the order, the order page becomes `paid`, one
protected download succeeds, and `download_expires_at` is exactly 24 hours
after `paid_at`. Use the reconciliation command when webhook delivery needs an
explicit safe check:

```bash
cd /opt/radar-bds/current
sudo -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; /opt/radar-bds/.venv/bin/python -X utf8 scripts/reconcile_digital_product_order.py --public-id <32-lowercase-hex-public-id>'
```

Run these read-only assertions for the deliberate order. They print only a
fixed success marker; they do not select a token, QR payload, payment
reference, signature, credential, or bank-transfer field:

```bash
set -euo pipefail
ORDER_PUBLIC_ID=<32-lowercase-hex-public-id>
test "${#ORDER_PUBLIC_ID}" -eq 32
case "$ORDER_PUBLIC_ID" in *[!0-9a-f]*) exit 2 ;; esac
proof="$(
  sudo -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; PGOPTIONS="-c default_transaction_read_only=on" psql "$DATABASE_URL" --no-psqlrc -X -v ON_ERROR_STOP=1 -v order_public_id="$1" -At' bash "$ORDER_PUBLIC_ID" <<'SQL'
SELECT CONCAT_WS(
    '|',
    orders.status,
    (
        SELECT COUNT(*)::text
          FROM digital_product_order_events AS events
         WHERE events.order_id = orders.id
           AND events.event_type = 'payment_verified'
    ),
    CASE
        WHEN orders.paid_at IS NOT NULL
         AND orders.download_expires_at = orders.paid_at + INTERVAL '24 hours'
        THEN '24h'
        ELSE 'invalid'
    END
)
FROM digital_product_orders AS orders
WHERE orders.public_id = :'order_public_id';
SQL
)"
test "$proof" = 'paid|1|24h'
printf '%s\n' 'paid_order_proof_ok'
unset proof ORDER_PUBLIC_ID
```

If any proof fails, immediately disable new sales with the exact checked
rollback below:

```bash
set -euo pipefail
test "$(sudo grep -c '^DIGITAL_PRODUCT_SALES_ENABLED=' /etc/radar-bds/radar.env)" -eq 1
sudo sed -i 's/^DIGITAL_PRODUCT_SALES_ENABLED=.*/DIGITAL_PRODUCT_SALES_ENABLED=0/' /etc/radar-bds/radar.env
sudo grep -qx 'DIGITAL_PRODUCT_SALES_ENABLED=0' /etc/radar-bds/radar.env
sudo systemctl restart radar-bds.service
sudo -u radar bash -lc 'set -a; source /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current; /opt/radar-bds/.venv/bin/python -X utf8 -c "from config.settings import get_digital_product_commerce_settings as load; assert not load().sales_enabled; print(\"digital_product_sales_enabled=0\")"'
curl -fsS https://radarbds.vn/ban-do-thu-dau-mot | grep -F 'Sắp mở bán' >/dev/null
```

Do not delete the paid order, its append-only event, or the protected package;
existing valid paid access must remain recoverable while new checkout is
disabled.

## 5. systemd

Install the service and crawl timer templates:

```bash
sudo cp deployment/ubuntu24/radar-bds.service /etc/systemd/system/radar-bds.service
sudo cp deployment/ubuntu24/radar-bds-crawl.service /etc/systemd/system/radar-bds-crawl.service
sudo cp deployment/ubuntu24/radar-bds-crawl.timer /etc/systemd/system/radar-bds-crawl.timer
sudo cp deployment/ubuntu24/radar-bds-guland-crawl.service /etc/systemd/system/radar-bds-guland-crawl.service
sudo cp deployment/ubuntu24/radar-bds-guland-crawl.timer /etc/systemd/system/radar-bds-guland-crawl.timer
sudo cp deployment/ubuntu24/radar-bds-public-content.service /etc/systemd/system/radar-bds-public-content.service
sudo cp deployment/ubuntu24/radar-bds-public-content.timer /etc/systemd/system/radar-bds-public-content.timer
sudo systemctl daemon-reload
sudo systemctl enable --now radar-bds.service
sudo systemctl enable --now radar-bds-crawl.timer
sudo systemctl enable --now radar-bds-guland-crawl.timer
sudo systemctl enable --now radar-bds-public-content.timer
```

Useful checks:

```bash
systemctl status radar-bds.service
systemctl list-timers radar-bds-crawl.timer
systemctl list-timers radar-bds-guland-crawl.timer
systemctl list-timers radar-bds-public-content.timer
journalctl -u radar-bds.service -n 100 --no-pager
journalctl -u radar-bds-crawl.service -n 100 --no-pager
journalctl -u radar-bds-guland-crawl.service -n 100 --no-pager
journalctl -u radar-bds-public-content.service -n 100 --no-pager
```

If the `deploy` user cannot install new systemd units, `scripts/deploy_production.ps1`
falls back to a deploy-user crontab entry for Guland at 23:15:

```bash
crontab -l | grep 'radar.py crawl-daily --source guland'
tail -n 120 /opt/radar-bds/current/logs/guland-crawl.log
```

Run one manual crawl only after the web/API smoke checks pass:

```bash
sudo systemctl start radar-bds-crawl.service
sudo systemctl start radar-bds-guland-crawl.service
sudo systemctl start radar-bds-public-content.service
```

## 6. Nginx and SSL

DNS should point both `radarbds.vn` and `www.radarbds.vn` to the VPS public
IPv4 address before issuing SSL. Install the Nginx site:

```bash
sudo cp deployment/ubuntu24/nginx-radar-bds.conf /etc/nginx/sites-available/radar-bds.conf
sudo ln -s /etc/nginx/sites-available/radar-bds.conf /etc/nginx/sites-enabled/radar-bds.conf
sudo nginx -t
sudo systemctl reload nginx
```

Use Certbot or the VPS provider's SSL flow for HTTPS. Cuon Truyen should use a
different `server_name`, port, systemd service, and database.

```bash
sudo certbot --nginx -d radarbds.vn -d www.radarbds.vn --redirect
```

## 7. Smoke checks

```bash
curl -fsS http://127.0.0.1:5000/api/dashboard >/dev/null
curl -fsS "http://127.0.0.1:5000/api/signals?page=1&limit=3" >/dev/null
curl -fsS https://radarbds.vn/api/dashboard >/dev/null
curl -fsS https://radarbds.vn/robots.txt >/dev/null
curl -fsS https://radarbds.vn/sitemap.xml >/dev/null
```

Before DNS cutover, keep the old server available until these pass on the new
VPS. Backup before every cutover:

```bash
pg_dump --format=custom "$DATABASE_URL" > /var/backups/radar-bds/radar_bds_$(date +%F).dump
tar -C /opt/radar-bds/current -czf /var/backups/radar-bds/images_$(date +%F).tgz data/images
```
