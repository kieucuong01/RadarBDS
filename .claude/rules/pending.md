# Pending & Backlog (2026-05-18)

## Backlog tính năng (theo thứ tự ưu tiên)

1. **LLM verify signals (daily job)** — ✅ ĐÃ TỰ ĐỘNG HOÁ (2026-05-18)
   - Đã gắn `verify_signals_with_groq()` vào `crawl-daily` (incremental) sau
     reprocess+download_images, trước VIP push. `cli/crawlers.py`. Opt-out:
     `--no-groq`. 429 daily-cap handle nội bộ → không vỡ pipeline. `crawl-all`
     (full) KHÔNG chạy. Manual vẫn được: `python radar.py reprocess --groq-signals`.
   - Backlog tự rút cạn: ~841 signal chưa verify sẽ drain dần qua các phiên
     crawl-daily (Groq cap/ngày → ~2–3 ngày sạch hàng tồn, sau đó chỉ signal mới).
   - ⚠️ Đây là cách dùng LLM ĐÚNG (quyết định 2026-05-18): ngân sách Groq
     free-tier ~400–500 call/ngày → đổ vào **841 signal chưa verify**, KHÔNG
     blanket `--groq` (1408 tin road_tier=0, ~800 không text = đốt budget vô ích).
   - `verify_signals_with_groq()` re-check price/area/property_type/road_tier/
     has_so → giết false-signal + tự re-valuate. Đã sửa luôn tier cho 175
     signal đang kẹt road_tier=0 (chỗ tier ảnh hưởng định giá nhất).
   - ~2 phiên/ngày là sạch 841; sau đó queue nhỏ dần (chỉ signal mới mỗi crawl).
   - `road_tier` giờ **LLM-authoritative**: khi `llm_verified=1`, regex
     reprocess KHÔNG ghi đè (fix CASE order `db/listings.py`).
   - `road_width_m` **functional-removed** khỏi code (valuation/Groq/Gemini
     prompt/upsert) — cột DB để dormant, optional cleanup migration sau.
   - `--groq-frontage` chỉ fill `frontage_m` (hiển thị), KHÔNG liên quan road_tier.
1b. **(Phase 2, tùy hứng) blanket `--groq` road_tier=0** — chỉ cứu false-negative
   (deal ngon bị tier-0 dìm dưới ngưỡng signal). Làm SAU khi signal sạch, kèm
   tweak code bỏ tin không text (đừng đốt budget vào ~800 null).
2. **Tầng 3b — Proximity scoring** — khoảng cách tới KCN Vsip 3, QL13, TDM center, trường/BV
   - Score 1–5, cộng vào Signal Score
   - Không cần toạ độ chính xác tới thửa; ward centroid đủ

## DEFERRED (không làm cho tới khi có điều kiện)

- **Tầng 3a — Quy hoạch checker (WebGIS)** — DEFER 2026-05-17 theo quyết định user.
  - **Lý do**: dữ liệu listing là text marketing thuần, không có lat/lng, không có
    cadastral (thua_so/to_ban_do/dia_chi_thua = 0%), Guland raw không expose zoning
    field, WebGIS Bình Dương không có public API. Môi giới có lợi giấu thông tin
    quy hoạch bất lợi → text regex chỉ catch ~2% với false negative cao.
  - **Unlock khi**: (a) OCR sổ hồng pipeline có → fill cadastral fields, HOẶC
    (b) BD publish open data quy hoạch (shapefile/GeoJSON/REST), HOẶC
    (c) source mới có lat/lng per listing, HOẶC
    (d) manual coord entry cho top-N signal sau khi pool đã sạch.
  - **Workaround tạm**: dashboard có thể thêm link external "Tra quy hoạch" mở
    Guland map cho user nhìn manual (chưa làm — chờ user confirm cần).

## Giới hạn đã biết

| Vấn đề | Trạng thái |
|--------|-----------|
| `has_so` default=1 | Thiết kế đúng: 6990/6991 has_so=1, chỉ trừ khi title/desc nói ngược |
| `road_tier=0` còn cao | Groq commands đã implement; chạy `--groq-frontage` để cải thiện |
| Facebook image URLs | CDN expire → auto download ngay sau crawl (đã fix) |
| BDS crawl chậm | 8s/slug × 26 slugs ≈ 40–60 phút; không thể song song (Cloudflare) |
| Apify credits | Free tier $5/tháng gần hết — dùng `--mode incremental` cho daily |
| Không có proxy | Guland OK (batch same-origin); BDS risk bị block |
| Mở rộng địa bàn | Thuận An, Dĩ An chưa có data |
| 958 listings không valuated (14%) | Giới hạn cố hữu: tin "giá thoả thuận" (`price_ty=0.0` ở nguồn) + Facebook free-text. `repair-missing` đã chạm trần (52/52 guland re-fetch nhưng vẫn no-price). Loại khỏi valuation là đúng |

## Đã làm gần đây

**Session 2026-05-20 — Valuation cleanup: signal reliability gate + Hiệp Thành sub-ward:**
- **Part C — Signal reliability gate** (`analytics/valuation.py`):
  - Thêm hằng `MIN_RELIABLE_N_FOR_SIGNAL = 15` (semantic riêng so với
    `MIN_SAMPLES`: ngưỡng tin cậy phát signal, không phải build segment).
  - Trong `valuate()`, sau check ward unknown và trước sigma calc:
    `if m.n_samples < MIN_RELIABLE_N_FOR_SIGNAL: is_sig = False`.
  - Lý do: segment dưới ngưỡng → fair rơi về median fallback, không đủ tin cậy
    để phát signal dù MOS lớn (false-positive). `valuation_result` vẫn ghi.
  - Kết quả: weak-n signal 28/809 → 0 sau reprocess.
- **Part F — Hiệp Thành sub-ward split** (`config/area_profiles.py` +
  `cleansing/normalizer.py`):
  - Thêm `HIEP_THANH_PROFILE` với 5 street patterns: HT3/HT1/HT2 (regex
    `\bhi[eệ]p\s*th[aà]nh\s*[123]\b`) + KDC K8 (2 variants).
  - `_HT_SUBWARDS = {Hiệp Thành 1/2/3, KDC K8 Hiệp Thành}` auto-extends
    `ALL_SUBWARDS` (valuation.py 3-tier fallback dùng dict này).
  - `detect_subward_from_street(text, parent_filter=None)` — thêm
    `parent_filter` scope theo profile.parent_ward, ngăn pattern HT3 fire
    trong tin Mỹ Phước.
  - Normalizer line 419-423: gate sub-ward promotion mở rộng từ
    `ward == "Mỹ Phước"` thành `ward in ("Mỹ Phước", "Hiệp Thành")`; truyền
    `parent_filter=ward_final`.
- **Kết quả combined** (`reprocess --full` trên 6991 listings):
  - Total signal: 809 → 763 (-46, -5.7%).
  - Hiệp Thành family: 152 → 134 (HT parent 107, HT3 22, HT1 5; HT2/K8 fit
    segment nhưng 0 deal vượt threshold).
  - MOS distribution chặt hơn: HT3 avg 46% vs HT-mixed cũ 42%.
- **Tests**: `pytest -q` 93/93 pass. NE5 vẫn match Mỹ Phước 3 (regression-free).
- **Out-of-scope giữ nguyên**: `has_so` default=1 (intentional design per
  cleansing.md); bug parse `2t45` (#38764 — task riêng); magic number tuning
  (refactor session); quy hoạch checker Tầng 3a (deferred 2026-05-17); thêm
  sub-ward cho ward khác (Phú Lợi/Định Hòa cũng có thể, làm sau khi đo độ ổn
  định Hiệp Thành sub-split).

**Session 2026-05-19 — Skill `review-deal-signals` (Claude pre-review CỐ VẤN):**
- **Đã ship**: bảng RIÊNG `ai_deal_review` (`db/schema.py`, append-only,
  idempotent); CLI `review-queue` (JSON memo) / `review-save`
  (`cli/review.py`, wired `radar.py`); skill `review-deal-signals`
  (`.claude/skills/` + `.agents/skills/`); `app.py` items JOIN `ai_*` +
  endpoint `/admin/api/ai-training/disagreements` (read-only, lọc CHẶT);
  `static/js/admin.js` block gợi ý read-only; `tests/test_ai_deal_review.py`
  (5 case, anti-bias verified) + pytest.ini.
- **Anti-bias (cứng)**: verdict Claude KHÔNG bao giờ ghi `ai_training_feedback`
  / không flip `review_hidden`. Nhãn cuối VẪN người bấm trên màn admin. Logic
  định giá CHỈ học nhãn người. KHÔNG gắn crawl-daily (chạy skill thủ công).
- **Phiên pre-review #1 đã chạy** (2026-05-19): batch `--top 10` → 10 verdict
  lưu `ai_deal_review` (7 suspect · 2 not_cheap · 1 insufficient_info · 0
  cheap_real). Verify: 10 id rời hàng đợi, `ai_training_feedback`=0 &
  `review_hidden` không đổi (anti-bias OK). Hiển thị read-only ở
  `/admin/control-room` tab AI training.
- **UI AI Training mở rộng** (2026-05-19, `app.py` items endpoint +
  `templates/admin_control_room.html` + `admin.js` + `admin.css`): badge
  số lượng cần review (`pending`/`total`); filter Phường + MOS≥ + Sắp xếp
  (mặc định/mới nhất/giá thấp/MOS/score) — server nhận `ward,mos_min,sort`;
  card hiện thêm Title + Description; nút "🖼️ Ảnh (n)" mở
  lightbox gallery ngay trên card (prev/next, phím ←→/Esc). Endpoint trả
  thêm `images[]` (full ảnh resolved), `wards[]`, `pending`, `total`.
  Toggle "Lưới / Dòng" (list view 1 card/dòng, ảnh trái) — nhớ localStorage
  `trnView`, responsive < 720px tự về 1 cột.
- **UI AI Training tinh chỉnh** (2026-05-19, `static/js/admin.js` +
  `static/css/admin.css`): thêm chip trích xuất "Sai giá" (`wrong_price`) /
  "Sai diện tích" (`wrong_area`); khi trích xuất ≠ "Đúng hết" → ẩn mục
  "2. Định giá AI" (tin về nhánh học **làm sạch dữ liệu**, verdict
  `bad_data`); chỉ khi trích xuất đúng mới chấm định giá (nhánh **cải tiến
  định giá**). Card thu nhỏ font/spacing + grid auto-fill để xem nhiều hơn.
  Backend không đổi (phân nhánh dựa `extraction_verdict`).
- **UI AI Training — fix lọc phường + infinite scroll** (2026-05-19,
  `app.py` + `static/js/admin.js` + `templates/admin_control_room.html`):
  (1) `admin_api_ai_training_items` đổi thứ tự filter `if ward … elif city`
  (trước là city-precedence → phường bị bỏ qua khi đã chọn TP). (2) Badge
  `#trainingCount` luôn hiển thị `pending/total` (vd `7/901`). (3) Bỏ nút
  "Tải thêm", thay bằng `#trnSentinel` + IntersectionObserver
  (`rootMargin:400px`) tự load batch kế khi cuộn gần cuối; guard `_trnLoading`
  chống double-fetch, `_trnHasMore` theo `data.has_more`. (4) Bỏ dòng dead
  `root.innerHTML = items.map(trainingCard)` ghi đè append (vỡ phân trang);
  chip listener chuyển sang **event delegation** trên `#trainingGrid` (bind
  1 lần, card append vẫn click được). (5) Dropdown phường nay phủ **mọi**
  phường có signal (`_trnAllWards` từ `data.wards`, không chỉ CITY_MAP).
- **UI AI Training — `/m²` + full description** (2026-05-20,
  `app.py` + `static/js/admin.js` + `static/css/admin.css` +
  `templates/admin_control_room.html`): card hiển thị giá rao quy đổi `tr/m²`;
  box "2. Định giá AI" hiển thị Fair Value cả tổng `tỷ` và `tr/m²`; description
  giữ full text, clamp 3 dòng và có `Xem thêm` / `Thu gọn`. API training trả
  thêm/chuẩn hóa `price_per_m2`, fallback `actual_ppm2`. Cache bump
  `admin.css?v=admin-v5-training-ppm2`, `admin.js?v=admin-v14-training-ppm2-desc`.
  node --check + py_compile + Flask test client OK.
- **Bug phát hiện ngoài lề (chưa fix)**: listing #38764 — parser giá nuốt
  cú pháp `"2t45"` (= 2.45 tỷ) thành 0.245 tỷ (sai 10×) → tạo signal MOS ảo.
  Nghi `cleansing/normalizer.py` regex `<tỷ>t<trăm-triệu>`. Cần fix riêng,
  có thể ảnh hưởng nhiều tin khác.
- **Phase sau (chưa làm)**: dùng `/admin/api/ai-training/disagreements` làm
  input phân tích/tune logic định giá — nhưng tune CHỈ học từ nhãn người;
  bảng disagreement chỉ để con người soi chỗ Claude vs người lệch nhau.

**Session 2026-05-18 — repair-missing run + xác định trần valuation coverage:**
- `inspect`: 6991 listings, 6033 valuated (86%), 958 không valuated. road_tier=0 = 25%, LLM enriched 8%.
- User chọn hướng "Repair missing price/area". Phân bố thiếu price/area: 430 facebook + 52 guland.
- `repair-missing --source guland --limit 10` test OK 10/10 → full run 52/52 re-fetch OK (background).
- **Phát hiện**: 52 guland sau re-fetch **area được điền nhưng price vẫn NULL** — raw `price_ty=0.0`. Đây là tin "Bán đất X m²" đăng **giá thoả thuận/liên hệ**, người bán không công bố giá. Re-fetch xác nhận giá không tồn tại ở nguồn.
- **Kết luận**: `repair-missing` đã chạm trần. 958 không valuated (14%) = tin giá thoả thuận + Facebook free-text → giới hạn cố hữu của nguồn, loại khỏi valuation là đúng (không thể tính MOS khi no-price). Ghi vào bảng "Giới hạn đã biết".
- Backlog #1 (Groq frontage) vẫn chưa chạy — chờ user quyết (tốn Groq credits).

**Session 2026-05-17 (tiếp 3) — Quy hoạch checker research & defer:**
- User hỏi "Quy hoạch checker (WebGIS) nên làm như thế nào? Nghiên cứu và đề xuất."
- **Verify giả thuyết "Guland raw_json có sẵn zoning"** → **SAI**. Inspect 5 raw mới nhất: top-level keys chỉ có address/area_m2/description/imgs/legal_raw/... — không có lat/lng, không có code đất, không có cadastral.
- **Audit DB**: 0% listings có thua_so/to_ban_do/dia_chi_thua (OCR pipeline chưa có). Address chỉ tới level phường (6955/6991). Không có anchor để query bản đồ.
- **Đếm keyword zoning trong text**:
  - `legal_raw` distribution: 4930 rỗng, 524 "Có sổ hồng", 65 "Có sổ hồng, Sổ sẵn" — chỉ pháp lý sổ, không phải mã quy hoạch
  - "quy hoạch" mention: 207/6991 (~3%, free text "dính/không dính/có quy hoạch đường")
  - Mã đất chuẩn ODT/SKC/CLN/LUC/TMD/RSX: ~120 hits / 6991 (< 2%); "ONT" 5539 hits là false positive (substring URL `guland.vn/post/...`)
- **WebGIS Bình Dương official** (qhkhsdd / gisxd / quyhoachxaydung .binhduong.gov.vn): không có public API/shapefile/GeoJSON cộng đồng cho BD
- **Quyết định user**: *"Vì dữ liệu hiện tại là bài đăng tin dựa vào text thuần, nên không thể check quy hoạch bằng ứng dụng. Chỉ có thể dựa vào môi giới cung cấp toạ độ cụ thể rồi tra trên bản đồ."*
- **Tầng 3a → DEFERRED**: di chuyển khỏi backlog active, ghi 4 điều kiện unlock (OCR sổ hồng / BD open data / source mới có lat-lng / manual coord entry). Promote Tầng 3b — Proximity scoring lên #2 (không cần coord precision tới thửa)
- **Memory**: lưu `project_quy_hoach_checker_deferred.md` để session sau không retry

**Session 2026-05-17 (tiếp 2) — DB cleanup CLI:**
- **`cli/cleanup.py`** (NEW): 4 cleanup pass + `run_cleanup(apply, sold_days, raw_days, notif_days, vacuum)`
  - `listings probably_sold=1` cũ hơn `--sold-days` (default 90) → DELETE; FK cascade tự dọn `listing_images`/`price_history`/`valuation_results`
  - `raw_listings` mồ côi (không có `listings.raw_id` trỏ tới) cũ hơn `--raw-days` (default 60) → DELETE
  - `notification_log` cũ hơn `--notif-days` (default 180) → DELETE
  - File trong `data/images/` không match `listing_images.local_path` → unlink + tính `bytes_freed`
- **VACUUM** chạy trên dedicated `sqlite3.connect(..., isolation_level=None)` để bypass implicit transaction; có flag `--no-vacuum`
- **`radar.py`** + **`cli/system.py`**: subparser `db-cleanup` + wrapper `cmd_db_cleanup`. Dry-run mặc định, `--apply` mới xóa
- **`pytest.ini`**: thêm 5 file test bỏ sót (`test_admin_control_room`, `test_guest_visibility`, `test_vip_notify`, `test_db_cleanup`, `test_investment_memo`) vào `python_files`
- **Tests**: `tests/test_db_cleanup.py` +9 case (dry-run no-op, sold > N days deleted, FK cascade verified, orphan raw deleted, raw with listing kept, old notif deleted, orphan image files unlinked + bytes counted, custom threshold, idempotent re-run)
- **Full suite**: 55 → **86 pass** (test discovery mở rộng)
- **Dry-run trên DB thật**: 6991 listings/raw, 0 sold/orphan/notif → cleanup không có gì để xóa (DB sạch); CLI verified hoạt động đúng
- Backlog #2 cũ ship xong, đẩy Tầng 3a Quy hoạch checker lên #2

**Session 2026-05-17 (tiếp) — Signal alert TTL re-alert khi price drop ≥5%:**
- **`db/schema.py`**: `notification_log` CREATE bỏ `UNIQUE(user_id,listing_id,channel)`, thêm cột `notified_price_ty REAL` + index `idx_notif_user_listing(user_id,listing_id,sent_at DESC)`
- **Migration idempotent** `_migrate_notification_log()`: ALTER ADD column nếu thiếu; nếu phát hiện `sqlite_autoindex_notification_log_*` (UNIQUE cũ) → rebuild table trong BEGIN/COMMIT, copy data sang `_new`, swap tên
- **`cli/notify.py`**: thay `_already_notified` (binary check) bằng `_last_notification` + `_should_skip_notify(conn, uid, lid, current_price, threshold_pct)` → `(skip, prev_price)`. Logic: no prior=push lần đầu; prev_price NULL=legacy skip; drop_pct ≥ threshold = re-alert
- **In-memory shared dict fix**: shallow copy listing trước khi gán `_prev_notified_price_ty` để per-user flag không leak cross-user
- **`alerts/telegram.py`**: digest có header switch "TIN MỚI + TIN GIẢM TIẾP" khi có realert; mỗi item realert thêm dòng `🔔 [Tiếp tục giảm giá] Giá cũ: X tỷ → Giá mới: Y tỷ (-Z%)`
- **`config/settings.py`** + **`.env.example`**: `SIGNAL_REALERT_THRESHOLD_PCT=5.0` (env-tunable)
- **Tests**: `tests/test_vip_notify.py` +8 case mới (first push records price, same-price skip, small drop <threshold skip, ≥threshold realert, legacy NULL skip, badge text contains "Tiếp tục giảm giá", boundary 5.0% inclusive, custom threshold via patched settings); 9/9 pass, full suite 55/55
- **Backlog #2 cũ ship xong**, đẩy DB cleanup CLI lên #2

**Session 2026-05-17 — VIP-only notification + admin auth cleanup (ship WIP):**
- **`alerts/telegram.py`** (-340 dòng net): xoá toàn bộ admin/global broadcast path
  - Xoá `send_message(text)` (legacy admin chat), `_already_alerted`, `collect_fresh_signals`, `collect_hot_deals_3d`, `send_consolidated_daily_alert`
  - Chỉ giữ `send_message_to(chat_id, text)` + `send_watchlist_digest(...)` cho per-user push
- **`cli/notify.py`**: chuyển log từ `user_audit_log` → bảng mới `notification_log` (UNIQUE per user+listing+channel)
  - Filter thêm `probably_sold=0`, `is_blacklisted=0`; ưu tiên `first_seen_at`
- **`cli/crawlers.py`**: bỏ gọi broadcast, chỉ giữ `push_new_listings_to_vip`
- **`radar.py`/`cli/system.py`**: bỏ flag `--alert` ở `lifecycle`; help text "Telegram alert" → "VIP notification"
- **`app.py`**: tách `_basic_admin_authorized()`/`_admin_request_authorized()`; api_listings không còn fresh-lock cho non-admin
- **`db/schema.py`**: bỏ CREATE `alert_logs` (legacy giữ trong DB cũ, schema mới không tạo lại)
- **Tests mới**: `test_vip_notify.py`, `test_guest_visibility.py`, `test_admin_control_room.py`; 53/53 pass
- **Backlog #5 cũ (TELEGRAM_TOKEN + CHAT_ID admin alert)**: xoá khỏi roadmap

**Session 2026-05-09 — Dashboard UX overhaul:**
- **Compact sidebar**: spacing toàn bộ giảm, collapsible sections (chevron toggle), Data Sources mặc định collapsed.
- **BỘ LỌC TÍN HIỆU**: section mới gộp MOS slider (range 30–70) + checkbox "Chỉ tin giảm giá".
  - MOS range 30–70 vì `mos_pct` trong DB là % (30–95%), range cũ 0–50 không lọc được gì.
  - Backend `get_base_filters()` + `load_data()` nhận `mos_min`, filter `v.mos_pct >= ?`.
- **Tab Hạ Tầng**:
  - Filter bar: lọc diện tích + giá ngay trên bảng (`/api/listings` nhận `area_min/max`, `price_min/max`).
  - Cột Ngày đăng: `posted_at` hoặc fallback `crawled_at`, hiển thị ngày + "X ngày trước".
  - Sortable headers: click tiêu đề → sort asc/desc với icon ↑↓; sort_by/sort_dir qua URL param.
  - Infinite scroll: IntersectionObserver với `root: .table-scroll` (scroll container thực). Sentinel nằm trong `.table-scroll`. Cuộn gần cuối tự fetch 50 tin tiếp, append vào bảng.
- **`scripts/find_reposted.py`** (NEW): query ad-hoc tìm tin môi giới đăng lại với giảm giá (dùng `price_history` + `possibly_duplicate`).

**Session 2026-05-07 (tiếp 3) — Mỹ Phước optimization:**
- **`config/area_profiles.py`** (NEW): Config-driven area profiles — extensible pattern for per-area rules
  - Street patterns (regex → sub_ward/road_width/tier), standard lots, sub-wards mapping
  - Public API: `detect_subward_from_street()`, `infer_standard_lot()`, `ALL_SUBWARDS`
- **`nha_tro` property type**: Tách 207 nhà trọ khỏi `nha_dat` — định giá rental yield riêng
- **MP1-4 sub-ward detection**: keyword + street name → MP3=305, MP1=22, MP4=14, MP2=4
- **Mid-level fallback**: sub-ward → parent ward aggregate → SELECTED_REGION (3-tier)
- **Standard lot inference**: 150m²→5x30, 100m²→5x20, 80m²→4x20 (Mỹ Phước grid lots)
- **Road tier for MP streets**: NE/DE→tier 1 (trunk 16-25m), NG/DJ/NA→tier 2 (internal 8m)
- **Kết quả**: MP road tier-2=219 (61%), tier-0=59 (16%); TDM không ảnh hưởng
- **Files**: `config/area_profiles.py`, `cleansing/feature_extractor.py`, `cleansing/normalizer.py`, `analytics/valuation.py`, `services/market_data.py`

**Session 2026-05-07 (tiếp 2) — Housekeeping:**
- **`_legacy/` cleanup**: 8 file không dùng chuyển vào `_legacy/`:
  - `crawler/facebook_pw.py` (deprecated → Apify), `crawler/nhatot_pw.py`, `crawler/muaban_pw.py` (stubs)
  - `run_all_crawlers.py` (thay bằng `radar.py crawl-all`)
  - `scripts/build_app.py`, `scripts/repair_*.py` (không wire vào CLI)
  - `tests/scratch.py` (debug code)
- **Image orphan cleanup**: 702 file ảnh cũ (trước re-crawl) đã xóa, giải phóng ~116.5 MB
  - `data/images/`: còn 3,715 file (~900 MB) — tất cả đang active trong DB

**Session 2026-05-07 (tiếp) — Valuation + Crawler overhaul:**
- **Valuation per-ward** (`analytics/valuation.py`): mỗi phường SegmentModel riêng, fallback SELECTED_REGION
- **Tier-0 = Tier-3**: `ROAD_TIER_MULTIPLIER[0] = 0.50`, encode as tier-3 trong regression
- **Bỏ floor check**: `FAIR_FLOOR_RATIO` không còn dùng — fair value thuần từ regression
- **Groq pipeline** (`cleansing/reprocess.py`): `enrich_frontage_with_groq()` + `verify_signals_with_groq()`
  - CLI: `python radar.py reprocess --groq-frontage [--ward X]` / `--groq-signals [--ward X]`
- **BatDongSan 26 slugs** (`crawler/batdongsan_pw.py`): 4 → 26 (13 phường × ban-dat + ban-nha)
- **Guland re-crawl**: xóa 5,244 listings không có ảnh → re-crawl → 5,083 records mới có ảnh
- **Auto image download** (`cli/crawlers.py`): `download_images()` gọi tự động sau mỗi crawl (bỏ limit=1000)
- **DB sau reprocess**: 6,335 listings | 5,787 valuated | 663 signals (11.5%) | 204 outliers

**Session 2026-05-06/07 — Feature Extractor refactor (cleansing/feature_extractor.py):**
- `extract_road_tier()`: fix 5 bugs:
  - `_MT_RE`: `'\bmt\b'` backspace bug → `r'\bmt\b'` raw string
  - `has_hem` → `has_hem_title` (title-only) cho tier 2 blocking — desc có thể nhắc hẻm lân cận
  - N/ notation: `\b\d+\s*/` trong title → block tier 1 ("2/ Huỳnh Văn Luỹ" = hẻm số 2)
  - xẹc/xẹt: cả 2 variant thêm vào `_NHANH_XEET_RE`
  - DX gần/cách: position-aware — chỉ downgrade tier 3 khi "gần/cách" xuất hiện TRƯỚC DX
- `_NAMED_ROADS`: mở rộng 14 → 42 đường TDM
- Secondary desc check: named road trong desc + MT trong title + không hẻm + không DX → tier 1 (+77 listings)
- Kết quả tier 1: 330 → 689 (+109%); tier 1 có hẻm trong title: 30 → 0
- `classify_property_type()`: cascade reorder → dat_vuon > 8 tr/m²: 388 → 0 (100%)
- `match_ward()` (`cleansing/normalizer.py`): per-source priority (title→desc→addr→url) → fix Hiệp An/Tân An collision
- `cleansing.md`: cập nhật đầy đủ logic mới (road tier, property type)

**Session 2026-04-25 — Facebook Apify Crawler + Dedup:**
- `crawler/facebook_apify.py` thay Chrome MCP (Apify `apify/facebook-posts-scraper`)
- Dedup redesign: exact dims, text weight, union-find cross-source
- `radar.py inspect`: DB snapshot command
