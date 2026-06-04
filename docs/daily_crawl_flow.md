# Daily Crawl & Signal Flow

Reference cho agent / dev mới: cách `radar.py crawl-daily` chạy end-to-end, signal được sinh ra như thế nào, VIP notification lấy gì, và config có thể chỉnh ở đâu mà không phải sửa code.

Đọc kèm `AGENTS.md` (data flow tổng quát) và `.claude/rules/valuation.md` (công thức fair value chi tiết).

---

## 1. Entry point

```
python radar.py crawl-daily
  └─ cli/crawlers.py::cmd_crawl(mode="incremental")
       ├─ capture crawl_start_ts                       # mốc "tin mới của run này"
       ├─ Facebook primary phase (profile daily_limit via Apify)
       │    ├─ run_full_reprocess()   → normalize → dedup → valuation
       │    ├─ download_images(limit=500) + broker image cleanup
       │    ├─ verify_signals_with_groq()  → LLM verify signal mới + re-valuate (xem 2a)
       │    ├─ notification:
       │    │     push_new_listings_to_vip(crawl_start_ts) # per-user VIP watchlists only
       │    └─ prewarm /api/dashboard
       ├─ export_raw()           → backup JSON
       └─ ops health check:
             _maybe_send_ops_alert(crawl_start_ts)    # crawl_runs error / zero-fetched → ops Telegram
```

Facebook là nguồn chính nên `radar-bds-crawl.timer` chỉ chạy daily Facebook + reprocess/push/cache. Guland là nguồn phụ, chạy bằng timer riêng `radar-bds-guland-crawl.timer` lúc 22:30:

```
radar.py crawl-daily --source guland --no-alert --no-groq
```

Timer Guland dùng cùng `/run/radar-bds/crawl.lock`, nên nếu job chính còn chạy thì job phụ không đè lên. Guland có reprocess riêng khi có record mới, nhưng không gửi VIP push.

> ⚠️ **BDS/BatDongSan có thể chậm hoặc bị Cloudflare/Turnstile**. Nếu nguồn này còn bật, nó không được nằm trước Facebook trong daily pipeline.

Pipeline lõi sau crawl giữ nguyên: `raw_listings → listings → valuation_results`. Phần thay đổi nằm ở **input config** (đầu pipeline) và **VIP notification** (cuối pipeline).

---

## 2. Signal definition

Co 2 lop signal:

- `valuation_results.is_signal = 1`: model-cheap/MOS candidate, dung cho audit va admin QC.
- "Actionable signal": latest valuation + `is_signal=1` + qua quality gate trong `services.signal_quality.actionable_signal_sql()`, dung cho dashboard user/VIP, review queue, va VIP push.

Dieu kien MOS model:

```
mos_pct = (fair_ppm2 - actual_ppm2) / fair_ppm2
is_signal = (mos_pct ≥ SIGNAL_MOS_THRESHOLD)
```

| Hằng số | File | Giá trị hiện tại |
|---|---|---|
| `SIGNAL_MOS_THRESHOLD` | `config/settings.py` | **0.10** (= 10%) |

Cách tính fair_ppm2 (per-ward weighted ridge + road tier + size discount) xem `.claude/rules/valuation.md`. Facebook is the primary baseline; if a canonical segment has fewer than 35 Facebook samples, strict-pass Guland rows may supplement training with weight 0.4. Regression valuation caps `road_tier=3` at max 80% of the same-listing tier-2 counterfactual before downstream adjustments. Không hardcode threshold ở chỗ khác — `analytics/valuation.py::SegmentModel.mos_threshold` đọc từ settings.

Quality flags can keep the valuation row but suppress user/VIP promotion. Fatal gates currently include parser/data risk such as `parsed_discount_as_price`, `down_payment_as_price`, `too_low_absolute_price`, `large_lot_model_risk`, `area_dimension_conflict`, `source_category_conflict`, `multi_lot_listing`, `test_artifact`, `low_segment_confidence`, source bad-extraction labels, and Guland quality flags such as `guland_weak_signal` / `guland_user_facing_risk`.

Signal now has a separate trust tier:

- `candidate_signal`: cheap by valuation, not legally verified yet.
- `has_legal_doc`: has a detected so hong/so do image.
- OCR parsing is disabled for now; having a detected so hong/so do image is the active legal trust boost.

VIP and score sorting prioritize higher trust tiers, but only actionable signals are promoted to user-facing queues. Hard legal conflicts, duplicate reposts, and quality flags keep a valuation audit row but are not promoted as normal signals.

**Sanity target sau reprocess:** model signals can stay broad for QC; actionable signals should be much cleaner. Verify with latest valuation, not raw historical joins:

```powershell
& $py -X utf8 -c "
from db.connection import get_conn
from services.signal_quality import LATEST_VALUATION_CTE, actionable_signal_sql
cond = actionable_signal_sql('v')
with get_conn() as c:
    row = c.execute(f'''
        WITH {LATEST_VALUATION_CTE}
        SELECT COUNT(*) AS n_all,
               SUM(CASE WHEN COALESCE(v.is_signal,0)=1 THEN 1 ELSE 0 END) AS model_signals,
               SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS actionable_signals
          FROM latest_valuation v
    ''').fetchone()
print(dict(row))
"
```

---

## 2a. LLM verify signals (Groq) — tự động trong crawl-daily

Sau `run_full_reprocess()` + `download_images()`, **chỉ trong `mode="incremental"`** (`crawl-daily`), `cmd_crawl` gọi `cleansing/reprocess.py::verify_signals_with_groq()`.

```python
from cleansing.reprocess import verify_signals_with_groq
verify_signals_with_groq()   # bọc try/except → lỗi Groq KHÔNG vỡ pipeline
```

- Chỉ verify tin **đã thành signal & `llm_verified=0`** (`WHERE v.is_signal=1 AND l.llm_verified=0`, order by `signal_score DESC`).
- Re-check price/area/property_type/road_tier/road_type/has_so/ward → giết false-signal, tự `reprocess_valuation()` sau khi enrich.
- `road_tier` từ LLM là **authoritative**: khi `llm_verified=1`, regex reprocess KHÔNG ghi đè (CASE order `db/listings.py`).
- Groq free-tier có **daily token cap** → 429 handle nội bộ (retry 1 lần `GROQ_RETRY_WAIT`s → break, vẫn mark `llm_verified=1` để khỏi retry vô hạn). Quota cạn → bước này dừng êm, crawl/push vẫn chạy bình thường.
- **`crawl-all` (full) KHÔNG chạy** bước này (tránh đốt budget khi reprocess toàn bộ).
- Backlog ~841 signal tồn drain dần qua các phiên daily (~2–3 ngày sạch, sau đó chỉ signal mới).

### 2a.1 Disable

```powershell
& $py -X utf8 radar.py crawl-daily --no-groq
```

Manual chạy độc lập (không qua crawl): `python radar.py reprocess --groq-signals [--ward X]`.

> `road_width_m` đã **functional-removed** khỏi code (valuation / Groq + Gemini prompt / upsert) — cột DB để dormant, optional cleanup migration sau. `--groq-frontage` chỉ fill `frontage_m` (hiển thị), KHÔNG liên quan road_tier.

---

## 3. VIP notification only

Mục đích: mỗi run crawl chỉ bắn notification cho user VIP còn hạn, theo watchlist riêng của từng user. Không còn admin/general Telegram alert và không còn dùng `TELEGRAM_CHAT_ID` để broadcast listing.

`cli/crawlers.py` gọi:

```python
from cli.notify import push_new_listings_to_vip
push_new_listings_to_vip(since=crawl_start_ts)
```

Luồng này:

- query latest actionable signal mới theo `first_seen_at >= since`;
- bỏ tin sold, blacklisted, review hidden;
- bỏ duplicate repost, valuation rows có `source_quality_recheck=1` hoặc fatal quality flags;
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

`N` = tổng latest actionable signal đang active trừ số deal đã in trong message.

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
python radar.py schedule-setup                # daily 21:00 (defaults)
python radar.py schedule-setup --time 21:00   # 9h tối
python radar.py schedule-setup --time 04:15   # đổi giờ
python radar.py schedule-setup --every 2      # cách ngày
python radar.py schedule-setup --remove       # gỡ task
```

Task tên `RadarBDS_DailyCrawl`. Chạy `cmd /c "cd /d <repo> && python -X utf8 radar.py crawl-daily"`. Verify: `schtasks /query /tn RadarBDS_DailyCrawl`.

## 3c. Production systemd observability

On Ubuntu production, `radar.py crawl-daily` tees stdout/stderr to
`logs/crawl-daily.log` from repo root. This file is the first place to inspect
when `radar-bds-crawl.service` shows `failed`, especially if the deploy user
cannot read `journalctl`.

The Admin Control Room -> Facebook Crawl ops panel reads both
`radar-bds-crawl.timer` and `radar-bds-crawl.service`. If the last systemd run
failed, it shows a red daily-crawl alert with the service result, exit code,
and the `logs/crawl-daily.log` hint.

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
- Admin có thể chỉnh danh sách này tại `/admin/control-room` → tab **Facebook Crawl**. Tab này lưu lại `active`, `daily_limit`, `range_days` vào cùng file JSON.
- Cũng trong tab **Facebook Crawl**, admin quản lý **Apify Tokens**. Token được lưu local tại `data/apify_tokens.json` (gitignored), UI chỉ hiển thị mask. Mỗi token có `monthly_quota`, `used_this_month`, `remaining`; crawler tự chọn token còn đủ quota cho request hiện tại và cộng usage theo số post Apify trả về. Khi qua tháng mới, usage tự reset theo month key.
- `daily_limit` được ưu tiên hơn `tier` khi load profile. `active=false` sẽ bị bỏ qua trong daily crawl.
- Crawl thủ công trong admin chạy dạng job nền: `first` = full crawl theo số bài, `daily` = incremental 72h, `range` = full fetch rồi lọc bài có `date_raw` trong N ngày gần nhất. Nếu bật tải ảnh, job reprocess Facebook và download ảnh cho các listing vừa xử lý.
- `broker_name` được lưu vào `raw_json` của listing, không thành column riêng.
- Key cấp 1 = `default_area` của profile → dùng cho city filter (mục 5).

Loader: `crawler/facebook_apify.py::load_profiles()`. CLI `crawl-facebook --mode full` ép `per_profile = max(tier, MAX_POSTS_FULL)`.

---

Neu Apify tra monthly/quota/payment limit, crawler danh token do `used_this_month=monthly_quota`, tu tat `active=false`, ghi `last_error`, roi thu token tiep theo trong pool.

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
| Crawl entry + notification wiring | `cli/crawlers.py::cmd_crawl`, `_facebook_crawl_to_raw` | Capture `crawl_start_ts`, gọi city filter, gọi `verify_signals_with_groq()` |
| LLM verify signals | `cleansing/reprocess.py::verify_signals_with_groq`, `cleansing/groq_enricher.py` | Chỉ incremental; opt-out `--no-groq` |
| Guland targets | `data/guland_sources.json`, `crawler/guland_pw.py` | Chỉ sửa JSON khi mở rộng ward |
| BDS targets | `data/batdongsan_sources.json`, `crawler/batdongsan_pw.py` | Cross-product slug auto-build |
| FB profiles | `data/facebook_profiles.json`, `crawler/facebook_apify.py` | tier=int, broker_name |
| City filter | `config/area_profiles.py` | `OTHER_CITY_KEYWORDS`, `CITY_OWN_KEYWORDS`, `post_mentions_other_city` |

---

## 7. Quick verify sau khi đổi gì đó

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

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
from db.connection import get_conn
with get_conn() as c:
    print('signals:', c.execute('SELECT COUNT(*) FROM valuation_results WHERE is_signal=1').fetchone()[0])
    print('min mos:', c.execute('SELECT MIN(mos_pct) FROM valuation_results WHERE is_signal=1').fetchone()[0])
"
```

---

## 7a. Claude pre-review — TÁCH RIÊNG, CỐ Ý không gắn crawl-daily

Skill `review-deal-signals` + lệnh `review-queue` / `review-save` (ghi bảng
RIÊNG `ai_deal_review`, CỐ VẤN) **không** nằm trong pipeline crawl-daily. Chạy
**thủ công** trong chat khi cần — quyết định có chủ đích để kiểm soát chi phí
và tránh confirmation-loop. Logic định giá CHỈ học từ nhãn người
(`ai_training_feedback`); verdict Claude không bao giờ trộn vào đó.

## 8. Không làm

- ❌ Đừng đưa `hồ chí minh / tp hcm / sài gòn` vào `OTHER_CITY_KEYWORDS` — BD đã sáp nhập HCM, sẽ skip nhầm tin chính chủ.
- ❌ Đừng thêm lại admin/general Telegram alert — listing notification chỉ đi qua VIP watchlist push.
- ❌ Đừng hardcode ward/slug trong crawler nữa — sửa JSON.
- ❌ Đừng tune `SIGNAL_MOS_THRESHOLD` thấp hơn 0.10 mà không verify signal rate vẫn hợp lý.
- ❌ Đừng skip dedup repost Facebook — repost FB cần lưu để track price history (anti-bloat đã bị reject).
- ❌ Đừng gắn `review-queue/review-save` (Claude pre-review) vào crawl-daily — cố ý tách (xem 7a).
