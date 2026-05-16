---
paths:
  - "requirements.txt"
  - ".env"
  - ".env.example"
  - "crawl_all.bat"
---

# Setup môi trường

## Dependencies thực tế

> ⚠️ `requirements.txt` OUTDATED — chứa `psycopg2`, `selenium` (legacy, không dùng).

```bash
pip install playwright numpy requests python-dotenv
playwright install chromium
```

## .env (tạo từ .env.example)

```env
# Telegram VIP watchlist push
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_BOT_USERNAME=your_bot_username

# Optional overrides
CRAWLER_THREADS=8
ALERT_PRICE_DROP_PCT=20
```

## Windows Task Scheduler

```bash
python radar.py schedule-setup               # 7:00 sáng mặc định
python radar.py schedule-setup --time 06:30
python radar.py schedule-setup --remove
```

## Lần đầu cài đặt

```bash
pip install playwright numpy requests python-dotenv
playwright install chromium
cp .env.example .env
# Điền TELEGRAM_BOT_TOKEN và TELEGRAM_BOT_USERNAME vào .env
python radar.py import-raw-backup            # load data từ backup
python radar.py query --stats                # verify
```
