# Daily Crawl & Signal Flow

Reference cho agent / dev mới: cách `radar.py crawl-daily` chạy end-to-end, signal được sinh ra như thế nào, VIP notification lấy gì, và config có thể chỉnh ở đâu mà không phải sửa code.

Đọc kèm `AGENTS.md`, `docs/README.md`, `docs/product_rules.md`, và `.claude/rules/valuation.md` (công thức fair value chi tiết).

---

## 1. Entry point

```
python radar.py crawl-daily
  └─ cli/crawlers.py::cmd_crawl(mode="incremental")
       ├─ capture crawl_start_ts                       # mốc "tin mới của run này"
       ├─ Facebook primary phase (profile daily_limit via Apify)
       │    ├─ run_full_reprocess()   → normalize → dedup → valuation
       │    ├─ download_images(limit=500) + broker image cleanup
       │    ├─ notification:
       │    │     push_new_listings_to_vip(crawl_start_ts) # per-user VIP watchlists only
       │    └─ prewarm /api/dashboard
       ├─ export_raw()           → backup JSON
       └─ ops health check:
             _maybe_send_ops_alert(crawl_start_ts)    # crawl_runs error / zero-fetched → ops Telegram
```

Facebook là nguồn chính nên `radar-bds-crawl.timer` chỉ chạy daily Facebook + reprocess/push/cache. Guland là nguồn phụ, chạy bằng timer riêng `radar-bds-guland-crawl.timer` lúc 22:30:

```
radar.py crawl-daily --source guland --no-alert
```

Timer Guland dùng cùng `/run/radar-bds/crawl.lock`, nên nếu job chính còn chạy thì job phụ không đè lên. Guland có reprocess riêng khi có record mới, nhưng không gửi VIP push.

Card Guland còn thu liên kết công khai `Chỉ đường`. Python chỉ lưu tọa độ khi
URL Google Maps, thứ tự lat/lng, bounds dịch vụ và canonical ward đều hợp lệ.
Tọa độ hợp lệ được resolver ưu tiên thành marker `exact`; tọa độ thiếu hoặc sai
không làm mất tin và vẫn giữ fallback road/landmark/ward hiện có. Luồng này
không thêm external LLM hay paid geocoding.

Backfill một lần cho các tin Guland cũ là lệnh vận hành riêng
`guland-coordinate-backfill`, mặc định dry-run và không nằm trong daily crawl.

Nếu deploy user chưa có quyền cài systemd unit mới, `scripts/deploy_production.ps1` sẽ cài fallback crontab cho Guland lúc 23:15:

```
15 23 * * * cd /opt/radar-bds/current && /usr/bin/flock -n /run/lock/radar-bds-guland-crawl.lock /opt/radar-bds/.venv/bin/python -X utf8 radar.py crawl-daily --source guland --no-alert >> /opt/radar-bds/current/logs/guland-crawl.log 2>&1
```

BatDongSan là nguồn legacy/disabled. Không đưa BatDongSan vào daily pipeline nếu chưa có quyết định sản phẩm mới.

Pipeline lõi sau crawl giữ nguyên: `raw_listings → listings → valuation_results`. Phần thay đổi nằm ở **input config** (đầu pipeline) và **VIP notification** (cuối pipeline).

Sau khi gỡ LLM verification, daily crawl không còn bước gọi API ngoài để sửa
`property_type`, `road_tier`, giá, diện tích, pháp lý hoặc phường. Những field
này đến từ parser/normalizer/feature extractor, dedup và valuation.

---

## 1a. Workflow kỹ thuật end-to-end theo code hiện tại

Phần này là trace nhanh cho dev/AI agent khi cần debug vì sao một tin đã crawl
về nhưng chưa hiện signal, hoặc vì sao signal chưa bắn Telegram.

### Bước 0 — lịch production gọi CLI

- Production timer chính: `radar-bds-crawl.timer`.
- Command chính: `python -X utf8 radar.py crawl-daily`.
- `radar.py` route vào `cli/crawlers.py::cmd_crawl_daily()`, rồi vào
  `cli/crawlers.py::_cmd_crawl(args, mode="incremental")`.
- Ngay đầu `_cmd_crawl()`, hệ thống lấy `crawl_start_ts` bằng SQL
  `SELECT datetime('now')`. Mốc này rất quan trọng: VIP/admin Telegram chỉ xét
  listing mới có `first_seen_at/crawled_at/posted_at >= crawl_start_ts`.

Khi debug production, log đầu tiên cần đọc là `logs/crawl-daily.log`.

### Bước 1 — crawl Facebook primary vào `raw_listings`

Luồng daily mặc định không chạy mọi crawler theo vòng lặp cũ. Với
`mode="incremental"` và không truyền `--source`, `_cmd_crawl()` chuyển sang
`_cmd_crawl_daily_facebook_first()`.

Trong `_cmd_crawl_daily_facebook_first()`:

1. Gọi `_facebook_crawl_to_raw(mode="incremental")`.
2. Crawler đọc profile từ bảng PostgreSQL `facebook_crawl_profiles`.
3. Facebook/Apify crawl bài theo profile và daily limit.
4. Tin hợp lệ được import vào bảng `raw_listings`.
5. Các bài không phải BĐS, ngoài khu vực, thiếu dữ liệu cơ bản hoặc trùng raw
   sẽ bị bỏ qua trước khi vào reprocess.

Output log thường có dạng:

```text
[facebook] crawled=139 | imported=121 | skipped=0 | refreshed_img=4 | irrelevant=13 | out_of_area=1
```

Ở bước này tin mới **chưa phải signal**. Nó mới là raw JSON đã lưu.

### Bước 2 — postprocess batch sau crawl

Nếu `fb_new > 0`, `_cmd_crawl_daily_facebook_first()` gọi
`_postprocess_crawl_batch(...)`.

Trong postprocess:

1. Gọi `cleansing/reprocess.py::run_full_reprocess()`.
2. In stats `Listings` và `Valuation`.
3. Gọi `cleansing.download_images.download_images(limit=500)`.
4. Gọi `_clean_broker_images_after_download(...)` để xóa ảnh môi giới/ảnh mặt
   người không phù hợp.

Ảnh mới không còn dùng tên chỉ theo `(listing_id, img_order)`. Downloader dùng
thêm `listing_images.id` và fingerprint của asset để hai revision ảnh Facebook
không ghi đè cùng object S3. Với URL Facebook chỉ đổi query chữ ký CDN, gallery
giữ file đã tải; khi path asset thật đổi, slot hiện hành được reset để tải lại.
Downloader chỉ đánh dấu ready sau khi body giải mã được và, ở chế độ S3, cả
original lẫn thumbnail đều upload thành công.

Nếu `fb_new = 0`, hệ thống không reprocess toàn bộ; nó chỉ tải backlog ảnh,
ops health check, prewarm dashboard rồi dừng.

### Bước 3 — `raw_listings` → `listings`

`run_full_reprocess()` chạy trong advisory lock `reprocess`, nên tránh hai job
reprocess đè nhau.

Bước đầu trong file `cleansing/reprocess.py`:

```text
run_full_reprocess()
  -> _run_full_reprocess()
     -> reprocess_listings()
```

`reprocess_listings()` làm các việc chính:

- Đọc raw bằng `db.raw_listings.get_raw_for_reprocess(...)`.
- Parse `raw_json`.
- Chuẩn hóa bằng `cleansing.normalizer.normalize_record(raw_data)`.
- Bỏ record không có URL hoặc bị trùng URL trong cùng batch.
- Bỏ record có phone nằm trong `broker_blacklist`.
- Ghi/upsert vào `listings` bằng `db.listings.upsert_listing(...)`.
- Ghi ảnh vào `listing_images` nếu record có `img_urls`.
- Backfill `content_hash` để phục vụ chống repost/spam alert.

Sau bước này, một raw có thể vẫn không thành listing nếu parser không đủ dữ
liệu, URL thiếu, phone blacklist, hoặc trùng trong batch.

`raw_listings` luôn là snapshot mới nhất. Mỗi trạng thái khác biệt của cùng
source URL được append vào `raw_listing_revisions`; observation giống hệt liền
trước không sinh thêm revision. Các cập nhật ảnh, chi tiết Guland, tọa độ,
repair và image cleanup đều đi qua repository này.

Với Guland, detail crawl còn lấy bằng chứng người đăng chỉ trong component
profile/contact của tin. Member ID, profile URL hoặc số điện thoại đúng scope
được chuẩn hóa thành HMAC bằng `GULAND_PUBLISHER_KEY_SECRET`; hotline/footer
toàn trang chỉ là diagnostic và không được dùng làm danh tính. Reprocess liên
kết listing với `source_publishers`, ghi observation theo ngày và phân loại
`low_manual`, `high_activity`, `automated_repost` hoặc fail-open `unknown`.
Ngày bump/repost nguồn được lưu thành raw revision
`guland_source_bump`; lần đầu bổ sung ngày card còn thiếu chỉ là
`guland_card_date_baseline`, không bị tính nhầm thành bump. So sánh dùng ngày
nguồn tuyệt đối `source_post_date`, nên diễn tiến tự nhiên kiểu “1 ngày trước”
thành “2 ngày trước” không bị tính là repost. Không thao tác nào đổi
`first_seen_at` hay ngày card nếu giá không đổi.

Normalizer đối soát measurement theo một policy dùng chung:

- diện tích tổng được công bố thắng `ngang × dài`;
- lô thường chỉ là xung đột nặng khi sai số lớn hơn 40%; lô xéo/nở hậu/nhiều
  cạnh chỉ bị chặn khi sai số lớn hơn 60%;
- chỉ suy diện tích thiếu từ đúng một cặp kích thước hợp lệ của lô thường;
- `price_per_m2` luôn được tính lại từ `price_ty × 1000 / area_m2`;
- mâu thuẫn chưa giải quyết được lưu ở `listings.extraction_quality_flags`;
- bài bán nhiều lô vẫn được giữ nguyên nhưng bị loại khỏi training và signal
  actionable, không tự tách thành các listing con.

### Bước 4 — hoàn tất trạng thái listing trước valuation

Sau `reprocess_listings()`, `_run_full_reprocess()` chạy đúng thứ tự:

```text
content_hash -> dedup -> first_seen -> price drops -> lifecycle
             -> weekly/monthly/daily trends -> valuation
```

Valuation vì vậy luôn đọc trạng thái dedup, giảm giá và lifecycle mới nhất;
không còn định giá trước rồi mới cập nhật các prerequisite này.

### Bước 5 — `listings` → main/shadow valuation nguyên tử

Trong `reprocess_valuation()`:

1. Lấy tập train và tập cần định giá, bỏ sold/blacklist/review hidden.
2. Chuyển row thành `analytics.valuation.Listing`; row lỗi làm cả run fail rõ
   `listing_id`, không bị bỏ qua im lặng.
3. Fit và tính xong cả main `road_tier_hierarchical_v1` lẫn shadow
   `median_road_tier_v1` trong bộ nhớ.
4. Trong đúng một PostgreSQL transaction: tạo hai model run, thay main/shadow
   rows của target, reset/cập nhật outlier và gắn `model_run_id` cùng
   `crawl_run_id`.

Nếu bất kỳ main/shadow insert nào lỗi, transaction rollback và snapshot cũ
cùng outlier state vẫn nguyên vẹn. Không xóa `valuation_model_runs` lịch sử và
không tự promote shadow thành main.

`valuation_results.is_signal=1` chỉ có nghĩa là model thấy tin rẻ hơn fair
value theo MOS threshold. Đây là **model signal**, chưa chắc được hiện lên UI
hoặc bắn Telegram.

### Bước 6 — map và public publication

Map backfill rồi `publish_public_data()` chỉ chạy sau khi transaction valuation
thành công. Exception valuation phải propagate; tuyệt đối không refresh public
read model/cache từ một snapshot dở dang.

### Bước 7 — định nghĩa signal được hiện cho user

User-facing signal dùng helper chung trong `services/signal_quality.py`:

```text
LATEST_VALUATION_CTE
actionable_signal_sql("v")
actionable_listing_sql("l")
```

`LATEST_VALUATION_CTE` lấy snapshot mới nhất theo từng `listing_id`:

```sql
SELECT DISTINCT ON (vr.listing_id) vr.*
FROM valuation_results vr
ORDER BY vr.listing_id, vr.computed_at DESC, vr.id DESC
```

`actionable_signal_sql("v")` yêu cầu:

- `v.is_signal = 1`;
- không có hard-block quality flags:
  `too_low_absolute_price`, `missing_area_evidence`,
  `area_dimension_conflict`, `price_area_inconsistent`,
  `unreprocessable_source_payload`, `ambiguous_price_text`,
  `source_category_conflict`, `multi_lot_listing`,
  `extreme_guland_ppm2`, `suspicious_bait`,
  `review_bad_extraction`, `review_bad_valuation`.

`source_quality_recheck` là metadata QC, không tự chặn signal. Các cờ
`low_road_confidence`, `low_segment_confidence`, `approximate_price_text`,
`old_guland_post`, cùng hai cờ cũ `guland_weak_signal` /
`guland_user_facing_risk` và `guland_cluster_flood` là warning-only nếu còn tồn
tại trong dữ liệu lịch sử.

Sau quality gate, feed và Maps áp dụng policy người đăng Guland chung:
`low_manual` trước `unknown`; `high_activity` và `automated_repost` bị ẩn với
Guest/Free/VIP. Admin mặc định cũng ẩn nhưng có thể bỏ chọn
“Ẩn người đăng dày/repost”. Policy này không thay đổi valuation, quality flags,
dedup hay lot history; Guland vẫn nhận diện lô theo source ID.

`actionable_listing_sql("l")` thường yêu cầu listing:

- chưa sold: `probably_sold=0`;
- không blacklist: `is_blacklisted=0`;
- không review hidden;
- không duplicate, trừ một số flow price-drop có rule riêng.

Vì vậy số lượng thường giảm theo phễu:

```text
raw_listings/imported
  -> listings đã normalize/upsert
  -> valuation_results.is_signal = 1
  -> latest actionable signal
  -> signal qua filter UI/watchlist
  -> signal thật sự được gửi Telegram sau anti-spam
```

### Bước 8 — `/api/signals` hiển thị card signal

Route public nằm ở `routes/market_api.py`:

```text
GET /api/signals
  -> app.api_signals()
     -> services.market_data.load_signals(...)
```

`load_signals()`:

- build filter từ query params: source, ward, property type, area, price,
  keyword, MOS, sort, page, limit;
- với guest: bỏ filter `mos_min` và `only_drops`, nhưng vẫn redacted dữ liệu
  nhạy cảm;
- dùng `LATEST_VALUATION_CTE` + `actionable_signal_sql("v")`;
- join `listings`;
- chọn ảnh thumbnail ưu tiên ảnh pháp lý/ảnh local qua `listing_images`;
- sort theo `newest`, score, MOS, price... tùy request;
- phân trang: default `limit=30`, cap `limit=100`;
- format card bằng `_format_signal_row(...)`;
- gọi `redact_for_tier(...)` để che phone/source URL cho guest/free/VIP.

`/api/dashboard` không phải feed signal đầy đủ. Nó là summary nhẹ. Khi debug
card đang hiển thị, ưu tiên kiểm `/api/signals` hoặc `load_signals()`.

### Bước 9 — frontend render signal

Frontend gọi `/api/signals` để lấy card paginated. Những field đã được backend
format sẵn gồm giá rao, định giá/fair value, MOS, ward, area, road tier, thổ cư,
trust/legal badge và thumbnail.

Nếu thấy UI chỉ hiện ít signal hơn số `valuation_results.is_signal`, đó thường
không phải bug UI. Trước hết kiểm:

1. Có phải đang nhìn latest valuation không.
2. Có qua `actionable_signal_sql()` không.
3. Có bị filter UI như ward/source/price/area/keyword không.
4. Có bị guest truncation/fresh lock/redaction không.
5. Có phải duplicate/sold/blacklist/review hidden không.

### Bước 10 — Telegram VIP/admin push

Sau postprocess, `_cmd_crawl_daily_facebook_first()` gọi:

```text
_push_vip_notifications(no_alert, crawl_start_ts)
  -> cli.notify.push_new_listings_to_vip(since=crawl_start_ts)
```

Lưu ý: trong Facebook-first flow hiện tại có thể gọi VIP push một lần ngay sau
postprocess batch, rồi gọi lại ở cuối run sau `export_raw()`. Đây không được
gửi trùng nếu `notification_log` đã ghi thành công, vì anti-spam kiểm theo
`user_id + listing_id + channel`.

Trong `push_new_listings_to_vip()`:

1. `_fetch_new_signals(conn, since)` lấy tối đa 500 listing mới:
   - dùng latest valuation;
   - phải qua `actionable_signal_sql("v")`;
   - phải qua `actionable_listing_sql("l")`;
   - `first_seen_at/crawled_at/posted_at >= since`;
   - sort ưu tiên `has_legal_doc`, `trust_score`, rồi thời gian mới.
2. `_fetch_active_vip_users_with_watchlists(conn)` lấy user đủ điều kiện:
   - `u.tier='admin'`; hoặc
   - `u.tier='vip'` và chưa hết hạn;
   - `u.is_banned=0`;
   - có `user_watchlists.active=1`.
3. Với từng watchlist, `_listing_matches(listing, watchlist)` lọc theo ward,
   property type, MOS min, khoảng giá, khoảng diện tích.
4. `_should_skip_notify(...)` đọc `notification_log` để tránh gửi lại, trừ khi
   giá thay đổi đủ lớn theo `SIGNAL_REALERT_THRESHOLD_PCT`.
5. Gom match theo user, dedupe listing nếu nhiều watchlist cùng match.
6. Nếu user/watchlist bật Telegram và có `users.telegram_chat_id`, gọi
   `alerts.telegram.send_watchlist_digest(...)`.
7. Nếu gửi thành công, `_log_notify(...)` ghi `notification_log` cho từng
   listing đã gửi.
8. Cập nhật `user_watchlists.last_notified_at`.

Telegram listing notification là per-user/per-watchlist. Không dùng
`TELEGRAM_CHAT_ID` global để broadcast listing. Admin muốn nhận cũng phải có
Telegram linked và active watchlist match.

### Bước 11 — ops alert và cache warm

Sau VIP push, crawl gọi:

- `_maybe_send_ops_alert(crawl_start_ts, crawler_exceptions)`:
  đọc `crawl_runs` từ lúc bắt đầu run, bỏ qua `reprocess:*`, gửi ops alert nếu
  crawler lỗi hoặc fetched = 0.
- `_prewarm_dashboard_cache()`:
  gọi trước một số endpoint dashboard/signals để cache nóng sau crawl.

Ops alert là kênh hạ tầng, tách khỏi listing notification. Nó không chứng minh
VIP push lỗi hay thành công; muốn kiểm VIP push thì xem log `VIP push: ...` và
bảng `notification_log`.

### Checklist debug nhanh

Nếu tin đã crawl nhưng không thấy trên UI:

1. Kiểm `raw_listings` có record không.
2. Kiểm `listings.raw_id/source_id/url` đã upsert chưa.
3. Kiểm `valuation_results` latest có row không.
4. Kiểm `is_signal`, `mos_pct`, `source_quality_flags`,
   `source_quality_recheck`.
5. Chạy điều kiện `actionable_signal_sql("v")`.
6. Kiểm listing flags: `probably_sold`, `is_blacklisted`, `review_hidden`,
   `possibly_duplicate`.
7. Kiểm filter `/api/signals`: ward/source/property/price/area/keyword/page.

Nếu signal hiện UI nhưng không bắn Telegram:

1. Kiểm signal có mới hơn `crawl_start_ts` không.
2. Kiểm user là admin hoặc VIP còn hạn, không banned.
3. Kiểm `users.telegram_chat_id` có giá trị.
4. Kiểm `user_watchlists.active=1` và filter watchlist có match không.
5. Kiểm `notify_telegram` ở cả user và watchlist.
6. Kiểm `notification_log` đã gửi trước đó chưa.
7. Kiểm `TELEGRAM_BOT_TOKEN`, webhook và log của
   `alerts.telegram.send_watchlist_digest(...)`.

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

Quality flags can keep the valuation row but suppress user/VIP promotion. Only
the explicit hard-block flags listed above suppress a model signal. Guland and
Facebook use the same model-signal/MOS threshold; source-specific strength
flags do not suppress Guland cards. `source_quality_recheck` and warning-only
flags remain available for QC badges and admin review.

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

## 2a. LLM verification removed

Daily crawl no longer calls external LLM verification after reprocess and image
download. Signal fields used for valuation now come from the deterministic
parser, normalizer, dedup, and valuation pipeline
only.

Current CLI shape:

```powershell
& $py -X utf8 radar.py reprocess --full
& $py -X utf8 radar.py crawl-daily
& $py -X utf8 radar.py crawl-daily --source guland --no-alert
```

Removed CLI/API surface:

- no legacy external-LLM opt-out/enrichment/verification flags;
- no legacy external-LLM extraction test command;
- no automatic chat/verification API call during crawl.

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
⚠️ ZERO FETCHED facebook: fetched=0 new=0
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

### 4.2 Legacy BatDongSan

BatDongSan is disabled for the current product. Existing code paths may remain for historical import/delete cleanup, but agents should not schedule BatDongSan, add it to daily crawl, or treat it as an active signal source unless the user explicitly changes the source policy.

### 4.3 Facebook profiles — PostgreSQL `facebook_crawl_profiles`

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
- Admin có thể chỉnh danh sách này tại `/admin/control-room` → tab **Facebook Crawl**. Tab này lưu lại `active`, `daily_limit`, `range_days`, `crawl_every_days`, `broker_name`, `city` và `url` vào bảng `facebook_crawl_profiles`.
- Cũng trong tab **Facebook Crawl**, admin quản lý **Apify Tokens**. Token được lưu local tại `data/apify_tokens.json` (gitignored), UI chỉ hiển thị mask. Mỗi token có `monthly_quota`, `used_this_month`, `remaining`; crawler tự chọn token còn đủ quota cho request hiện tại và cộng usage theo số post Apify trả về. Khi qua tháng mới, usage tự reset theo month key.
- `daily_limit` được ưu tiên hơn `tier` khi load profile. `active=false` sẽ bị bỏ qua trong daily crawl.
- Crawl thủ công trong admin chạy dạng job nền: `first` = full crawl theo số bài, `daily` = incremental 72h, `range` = full fetch rồi lọc bài có `date_raw` trong N ngày gần nhất. Nếu bật tải ảnh, job reprocess Facebook và download ảnh cho các listing vừa xử lý.
- `broker_name` được lưu vào `raw_json` của listing, không thành column riêng.
- `city` của profile → dùng làm `default_area` cho city filter (mục 5).

Loader: `crawler/facebook_apify.py::load_profiles()`. Runtime mặc định không đọc `data/facebook_profiles.json`; path JSON chỉ còn dùng khi test/import fixture explicit. CLI `crawl-facebook --mode full` ép `per_profile = max(tier, MAX_POSTS_FULL)`.

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

### 5.4 Post-merger location resolver

City filter and location normalization are separate layers:

1. City filter only decides whether to keep or skip a Facebook post before insert into `raw_listings`.
2. `cleansing.normalizer.normalize_record()` decides `area` and canonical `ward` after raw insert.
3. `config/location_aliases.py` resolves post-merger broker text into two concepts:
   - `new_ward`: administrative ward after merger, used as context only.
   - `ward`: old/canonical micro-market segment used by dedup, valuation, filters, and signals.

Never map from broad new ward alone. Examples:

| Broker text | `new_ward` context | Canonical `ward` |
|---|---:|---:|
| `KP.Phú Mỹ P.Bình Dương TP HCM` | `Bình Dương` | `Phú Mỹ` |
| `KP Hòa Phú 2, P.Bình Dương TP HCM` | `Bình Dương` | `Hòa Phú` |
| `KP Phú Tân 1, P.Bình Dương` | `Bình Dương` | `Phú Tân` |
| `KP Phú Bưng/Phú Trung/Chánh Long, P.Bình Dương` | `Bình Dương` | `Phú Chánh` |
| `P.Bình Dương TP HCM` | `Bình Dương` | `None` |
| `KP2 Tân Định cũ nay thuộc phường Hòa Lợi TPHCM` | `Hòa Lợi` | `Tân Định` |
| `KP3 Hòa Lợi TPHCM` | `Hòa Lợi` | `Hòa Lợi` |
| `DX071/DX072 phường Chánh Hiệp TPHCM` | `Chánh Hiệp` | `Định Hòa`, only if no stronger old ward evidence exists |
| `Chánh Hiệp TPHCM` | `Chánh Hiệp` | `None` |

This keeps the valuation baseline stable: old ward/sub-ward segments remain the training and MOS units. New ward names can be displayed or stored later if a schema field such as `location_evidence` or `new_ward` is added, but v1 keeps them transient inside the normalizer.

### 5.5 Đối soát lịch sử Guland

Đây là tác vụ bảo trì có giới hạn, không nằm trước Facebook trong daily crawl.
Mặc định chỉ đọc và kiểm tra live:

```powershell
& $py -X utf8 radar.py guland-reconcile --limit 100
```

Chỉ chạy `--apply` trên production sau khi người dùng duyệt rõ số liệu dry-run:

```powershell
& $py -X utf8 radar.py guland-reconcile --limit 100 --apply
```

Apply chỉ cập nhật lifecycle có bằng chứng nguồn, giá thay đổi đã xác nhận và
targeted reprocess cho các raw row tương ứng. Hai lần xác nhận nguồn báo gỡ mới
ẩn tin; lỗi mạng/Cloudflare được giữ ở trạng thái `unreachable`.

---

## 6. Files chạm khi thay đổi flow này

| Concern | File | Ghi chú |
|---|---|---|
| MOS threshold | `config/settings.py`, `analytics/valuation.py` | Sửa số → reprocess lại |
| Dashboard URL trong Telegram | `config/settings.py::DASHBOARD_BASE_URL` | Override bằng env |
| VIP push query | `cli/notify.py` | `_fetch_new_signals`, `_fetch_active_vip_users_with_watchlists` |
| Telegram digest format | `alerts/telegram.py` | `send_watchlist_digest`, `send_message_to` |
| Crawl entry + notification wiring | `cli/crawlers.py::cmd_crawl`, `_facebook_crawl_to_raw` | Capture `crawl_start_ts`, gọi city filter, reprocess, tải ảnh, push VIP |
| Deterministic signal fields | `cleansing/reprocess.py`, `cleansing/normalizer.py`, `cleansing/feature_extractor.py` | Không còn bước verify bằng LLM ngoài sau crawl |
| Post-merger location aliases | `config/location_aliases.py`, `scripts/audit_post_merger_locations.py` | Phường mới là context; chỉ KP/phường cũ/landmark đủ mạnh mới gán `ward` |
| Guland targets | `data/guland_sources.json`, `crawler/guland_pw.py` | Chỉ sửa JSON khi mở rộng ward |
| Legacy BatDongSan cleanup | `cli/data_import.py` | Disabled for daily crawl; keep only import/delete helpers for historical cleanup unless policy changes |
| FB profiles | `facebook_crawl_profiles`, `db/facebook_profiles.py`, `crawler/facebook_apify.py` | tier/daily_limit=int, broker_name, city, active, crawl cadence |
| City filter | `config/area_profiles.py` | `OTHER_CITY_KEYWORDS`, `CITY_OWN_KEYWORDS`, `post_mentions_other_city` |

---

## 7. Quick verify sau khi đổi gì đó

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"

# 1. settings & threshold
& $py -X utf8 -c "from config.settings import SIGNAL_MOS_THRESHOLD, DASHBOARD_BASE_URL; print(SIGNAL_MOS_THRESHOLD, DASHBOARD_BASE_URL)"

# 2. crawl config load
& $py -X utf8 -c "from crawler.guland_pw import GulandCrawler; g=GulandCrawler(); print(len(g.TARGET_URLS), g.crawl_for_days)"
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

# 5. removed external LLM verification flags should stay absent
& $py -X utf8 radar.py reprocess --help
& $py -X utf8 radar.py crawl-daily --help
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
- ❌ Đừng thêm lại external LLM verify/enrich vào crawl/reprocess nếu chưa có quyết định sản phẩm mới.
- ❌ Đừng gắn `review-queue/review-save` (Claude pre-review) vào crawl-daily — cố ý tách (xem 7a).
