# Daily Crawl & Signal Flow

Reference cho agent / dev mới: cách `radar.py crawl-daily` chạy end-to-end, signal được sinh ra như thế nào, VIP notification lấy gì, và config có thể chỉnh ở đâu mà không phải sửa code.

Đọc kèm `AGENTS.md` (data flow tổng quát) và `.claude/rules/valuation.md` (công thức fair value chi tiết).

---

## 1. Entry point

```
python radar.py crawl-daily
  └─ cli/crawlers.py::cmd_crawl(mode="incremental")
       ├─ capture crawl_start_ts                       # mốc "tin mới của run này"
       ├─ Guland crawl       (crawler/guland_pw.py)
       ├─ BatDongSan crawl   (crawler/batdongsan_pw.py)   ⚠️ Cloudflare blocked — 0 records
       ├─ Facebook crawl     (crawler/facebook_apify.py via Apify)
       ├─ run_full_reprocess()   → normalize → dedup → valuation
       ├─ download_images()      → tải ảnh + tạo thumbnail
       ├─ export_raw()           → backup JSON
       ├─ notification:
       │     push_new_listings_to_vip(crawl_start_ts) # per-user VIP watchlists only
       └─ ops health check:
             _maybe_send_ops_alert(crawl_start_ts)    # crawl_runs error / zero-fetched → ops Telegram
```

> ⚠️ **BDS hiện không lấy được data** (Cloudflare Turnstile, 2026-05). Daily run chỉ có Guland + Facebook. Xem `.claude/rules/crawler.md` mục BatDongSan để biết điều kiện resume.

Pipeline lõi sau crawl giữ nguyên: `raw_listings → listings → valuation_results`. Phần thay đổi nằm ở **input config** (đầu pipeline) và **VIP notification** (cuối pipeline).

---

## 2. Signal definition

Một listing là **signal** khi `valuation_results.is_signal = 1`. Điều kiện:

```
mos_pct = (fair_ppm2 - actual_ppm2) / fair_ppm2
is_signal = (mos_pct ≥ SIGNAL_MOS_THRESHOLD)
```

| Hằng số | File | Giá trị hiện tại |
|---|---|---|
| `SIGNAL_MOS_THRESHOLD` | `config/settings.py` | **0.25** (= 25%) |

Cách tính fair_ppm2 (per-ward weighted ridge + road tier + size discount) xem `.claude/rules/valuation.md`. Không hardcode threshold ở chỗ khác — `analytics/valuation.py::SegmentModel.mos_threshold` đọc từ settings.

**Sanity target sau reprocess:** signals chiếm 10–30% tổng listing đã valuated. Verify:

```powershell
& $py -X utf8 -c "
import sqlite3
c = sqlite3.connect('data/radar_bds.db')
n_sig = c.execute('SELECT COUNT(*) FROM valuation_results WHERE is_signal=1').fetchone()[0]
n_all = c.execute('SELECT COUNT(*) FROM valuation_results').fetchone()[0]
print(f'{n_sig}/{n_all} = {n_sig/n_all:.1%}')
"
```

---

## 3. VIP notification only

Mục đích: mỗi run crawl chỉ bắn notification cho user VIP còn hạn, theo watchlist riêng của từng user. Không còn admin/general Telegram alert và không còn dùng `TELEGRAM_CHAT_ID` để broadcast listing.

`cli/crawlers.py` gọi:

```python
from cli.notify import push_new_listings_to_vip
push_new_listings_to_vip(since=crawl_start_ts)
```

Luồng này:

- query signal mới theo `first_seen_at >= since`;
- bỏ tin sold, blacklisted, review hidden;
- lọc theo từng `user_watchlists` của VIP còn hạn;
- gửi riêng vào `users.telegram_chat_id`;
- không đưa original source URL vào Telegram;
- format là một digest/tin, title từng deal link về `/listing/<id>`;
- footer dẫn về `DASHBOARD_BASE_URL`.

Chi tiết bot binding, zrok webhook, local sync fallback và message format nằm ở `docs/telegram_watchlist.md`.

Footer của chunk cuối:

```
📊 Còn lại <b>N</b> tin ngộp đang active — <a href="...">xem thêm tại Dashboard</a>
```

`N` = tổng `valuation_results.is_signal=1` đang active trừ số deal đã in trong message.

### 3.1 Disable notification

```powershell
& $py -X utf8 radar.py crawl-daily --no-alert
```

---

## 3a. Ops alert (crawl health)

Một kênh **tách rời** khỏi VIP push, chỉ dành cho infra/operator. Sau mỗi `crawl-daily`, `cli/crawlers.py::_maybe_send_ops_alert()`:

- query `crawl_runs` từ `crawl_start_ts` (bỏ qua row `reprocess:*`);
- gọi `alerts.ops.summarize_crawl_health()` — flag unhealthy nếu có source `status='error'` hoặc `n_fetched=0`;
- cộng thêm exception bắt ngoài crawler loop (rare);
- nếu unhealthy → `alerts.ops.send_ops_alert(msg)` gửi Telegram đến `OPS_ALERT_CHAT_ID`.

`OPS_ALERT_CHAT_ID` đặt trong `.env`. Không set → silent no-op (dev không bị spam).

```env
OPS_ALERT_CHAT_ID=123456789
```

Message format (HTML):
```
⚙️ [Radar BDS OPS]
Crawl health summary:
❌ ERROR guland: fetched=0 new=0
   ↳ Playwright TimeoutError: page.goto exceeded 30000ms
⚠️ ZERO FETCHED batdongsan: fetched=0 new=0
```

Module: `alerts/ops.py` — tách hẳn khỏi `alerts/telegram.py` để boundary giữa listing-channel (per-user VIP) và ops-channel (admin) luôn rõ ràng. Không gửi data listing qua kênh này.

---

## 3b. Windows Task Scheduler

```powershell
python radar.py schedule-setup                # daily 10:15 (defaults)
python radar.py schedule-setup --time 04:15   # đổi giờ
python radar.py schedule-setup --every 2      # cách ngày
python radar.py schedule-setup --remove       # gỡ task
```

Task tên `RadarBDS_DailyCrawl`. Chạy `cmd /c "cd /d <repo> && python -X utf8 radar.py crawl-daily"`. Verify: `schtasks /query /tn RadarBDS_DailyCrawl`.

---

## 4. Crawl targets — JSON config

Trước đây ward/URL/profile hardcode trong từng crawler. Giờ tách ra `data/*.json` để mở rộng địa bàn không cần sửa code.

### 4.1 Guland — `data/guland_sources.json`

```json
{
  "city": "Thủ Dầu Một",
  "crawl_for_days": 7,
  "wards": [
    {"name": "Tân An", "slug": "phuong-tan-an-thanh-pho-thu-dau-mot-binh-duong"},
    ...
  ]
}
```

Loader: `crawler/guland_pw.py::__init__` → `_load_sources_config()`. Nếu file lỗi/thiếu, fallback về `_FALLBACK_WARDS` trong code (giữ backup để không gãy CI).

`crawl_for_days` chi phối `is_old()` — listing có `date_raw` cũ hơn N ngày → stop load-more cho phường đó.

### 4.2 BatDongSan — `data/batdongsan_sources.json`

```json
{
  "city": "Thủ Dầu Một",
  "crawl_for_days": 7,
  "categories": ["ban-dat", "ban-nha"],
  "wards": [
    {"name": "Tân An", "slug": "tan-an"},
    ...
  ]
}
```

`SEARCH_SLUGS` build từ `urls` của mỗi ward (default 4 URL/ward × 13 ward = 52). Loader: `crawler/batdongsan_pw.py::_load_bds_config()` (module level). **Thực tế hiện tại:** chỉ slug đầu tiên may mắn qua Cloudflare; phần còn lại trả 0 cards và lưu HTML+PNG debug vào `logs/bds_no_cards/`.

### 4.3 Facebook profiles — `data/facebook_profiles.json`

```json
{
  "Thủ Dầu Một": [
    {"url": "https://www.facebook.com/nhadatkhanhmy",
     "broker_name": "Khánh My",
     "tier": 30}
  ],
  "Bến Cát": [
    {"url": "https://www.facebook.com/khuyen.vu.86",
     "broker_name": "Khuyên Vũ",
     "tier": 10}
  ]
}
```

- `tier` = số post fetch mỗi lần (int). Backward-compat: nếu vẫn còn string `"high"/"medium"/"low"` → convert qua `_TIER_STR_MAP` = `{high:40, medium:20, low:10}` + log warning.
- `broker_name` được lưu vào `raw_json` của listing, không thành column riêng.
- Key cấp 1 = `default_area` của profile → dùng cho city filter (mục 5).

Loader: `crawler/facebook_apify.py::load_profiles()`. CLI `crawl-facebook --mode full` ép `per_profile = max(tier, MAX_POSTS_FULL)`.

---

## 5. City filter cho Facebook posts

**Mục đích:** broker thường đăng nhiều khu vực trên cùng profile. Skip những post nói RÕ về địa bàn khác.

### 5.1 Logic

`config/area_profiles.py::post_mentions_other_city(text, profile_city) → bool`:

- `text` rỗng (post ảnh thuần) → `False` (insert).
- `profile_city` rỗng → `False`.
- Lowercase text, check từng keyword trong `OTHER_CITY_KEYWORDS` không thuộc `CITY_OWN_KEYWORDS[profile_city]`.
- Match bất kỳ keyword → `True` → skip.

Gọi từ `cli/crawlers.py::_facebook_crawl_to_raw` ngay trước khi insert raw. Có counter `out_of_area` in ra CLI stats.

### 5.2 Quy ước keyword (2026-05)

⚠️ **Bình Dương đã sáp nhập vào TP HCM.** Broker có thể ghi địa chỉ mới "TP HCM / Sài Gòn / TPHCM" cho tin TDM hoặc Bến Cát → **KHÔNG** đưa các keyword này vào skip list.

`OTHER_CITY_KEYWORDS` hiện tại chỉ chứa:
- Các huyện/khu thuộc BD cũ ngoài địa bàn (nếu profile là TDM): `tân uyên`, `dĩ an`, `thuận an`, `bến cát`, `bàu bàng`, `phú giáo`, `dầu tiếng`.
- Các tỉnh/TP thực sự khác: `hà nội`, `đà nẵng`, `đồng nai`, `biên hòa`, `long an`, `tây ninh`, `vũng tàu`, `cần thơ`, `bình phước`, `đồng xoài`.
- `thủ dầu một`, `tdm` (để profile `Bến Cát` skip tin TDM).

`CITY_OWN_KEYWORDS` map từ `profile_city` → keyword của chính nó (để không tự skip mình).

### 5.3 Test cases (sanity)

| Text | profile_city | Expected |
|---|---|---|
| `"Bán đất TP HCM phường Tân An"` | TDM | keep |
| `"Đất Sài Gòn Phú Mỹ"` | TDM | keep |
| `"Đất Phú Mỹ"` (chỉ ward) | TDM | keep |
| `"Đất Dĩ An giá rẻ"` | TDM | **skip** |
| `"Đất Tân Uyên"` | TDM | **skip** |
| `"Đất Hà Nội"` | TDM | **skip** |
| post không text | TDM | keep |

---

## 6. Files chạm khi thay đổi flow này

| Concern | File | Ghi chú |
|---|---|---|
| MOS threshold | `config/settings.py`, `analytics/valuation.py` | Sửa số → reprocess lại |
| Dashboard URL trong Telegram | `config/settings.py::DASHBOARD_BASE_URL` | Override bằng env |
| VIP push query | `cli/notify.py` | `_fetch_new_signals`, `_fetch_active_vip_users_with_watchlists` |
| Telegram digest format | `alerts/telegram.py` | `send_watchlist_digest`, `send_message_to` |
| Crawl entry + notification wiring | `cli/crawlers.py::cmd_crawl`, `_facebook_crawl_to_raw` | Capture `crawl_start_ts`, gọi city filter |
| Guland targets | `data/guland_sources.json`, `crawler/guland_pw.py` | Chỉ sửa JSON khi mở rộng ward |
| BDS targets | `data/batdongsan_sources.json`, `crawler/batdongsan_pw.py` | Cross-product slug auto-build |
| FB profiles | `data/facebook_profiles.json`, `crawler/facebook_apify.py` | tier=int, broker_name |
| City filter | `config/area_profiles.py` | `OTHER_CITY_KEYWORDS`, `CITY_OWN_KEYWORDS`, `post_mentions_other_city` |

---

## 7. Quick verify sau khi đổi gì đó

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"

# 1. settings & threshold
& $py -X utf8 -c "from config.settings import SIGNAL_MOS_THRESHOLD, DASHBOARD_BASE_URL; print(SIGNAL_MOS_THRESHOLD, DASHBOARD_BASE_URL)"

# 2. crawl config load
& $py -X utf8 -c "from crawler.guland_pw import GulandCrawler; g=GulandCrawler(); print(len(g.TARGET_URLS), g.crawl_for_days)"
& $py -X utf8 -c "from crawler.batdongsan_pw import BatDongSanCrawler, SEARCH_SLUGS; print(len(SEARCH_SLUGS))"
& $py -X utf8 -c "from crawler.facebook_apify import load_profiles; ps=load_profiles(); print([(p['url'], p['tier'], p.get('broker_name')) for p in ps])"

# 3. city filter
& $py -X utf8 -c "from config.area_profiles import post_mentions_other_city as f; print(f('Bán đất Dĩ An','Thủ Dầu Một'), f('Đất TP HCM phường Tân An','Thủ Dầu Một'))"
# → True False

# 4. signal rate
& $py -X utf8 -c "
import sqlite3
c = sqlite3.connect('data/radar_bds.db')
print('signals:', c.execute('SELECT COUNT(*) FROM valuation_results WHERE is_signal=1').fetchone()[0])
print('min mos:', c.execute('SELECT MIN(mos_pct) FROM valuation_results WHERE is_signal=1').fetchone()[0])
"
```

---

## 8. Không làm

- ❌ Đừng đưa `hồ chí minh / tp hcm / sài gòn` vào `OTHER_CITY_KEYWORDS` — BD đã sáp nhập HCM, sẽ skip nhầm tin chính chủ.
- ❌ Đừng thêm lại admin/general Telegram alert — listing notification chỉ đi qua VIP watchlist push.
- ❌ Đừng hardcode ward/slug trong crawler nữa — sửa JSON.
- ❌ Đừng tune `SIGNAL_MOS_THRESHOLD` < 0.25 mà không verify signal rate vẫn ≤ 30%.
- ❌ Đừng skip dedup repost Facebook — repost FB cần lưu để track price history (anti-bloat đã bị reject).
