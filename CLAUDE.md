# 🧠 ANDREJ KARPATHY SKILLS (CRITICAL GUIDELINES)

You are operating under Andrej Karpathy's recommended skills for LLM coding agents. Adhere to these principles:

### 1. Think Before Coding
- **Don't assume.** If the user's request is ambiguous, state your assumptions explicitly. If uncertain, STOP and ASK rather than guess.
- **Present tradeoffs.** If there are multiple ways to solve a problem, present them and let the user decide.
- **Push back.** If a simpler approach exists or the user is asking for something overcomplicated, say so.
- **Manage confusion.** If you don't understand something, name what's unclear and ask for clarification.

### 2. Simplicity First
- **Minimum code.** Write only the code necessary to solve the exact problem. Nothing speculative.
- **No overengineering.** No features beyond what was asked. No abstractions for single-use code. No "flexibility" or "configurability" that wasn't requested.
- **Simplify.** If 200 lines could be 50, rewrite it.

### 3. Surgical Changes
- **Touch only what you must.** Clean up only your own mess.
- **Don't touch adjacent code.** Do not "improve" adjacent code, comments, or formatting unless explicitly requested.
- **Match existing style.** Even if you'd do it differently, follow the surrounding code style.
- **Don't delete dead code unless asked.** If you notice unrelated dead code, mention it — don't delete it.
- **Clean up your orphans.** Remove imports/variables/functions that YOUR changes made unused.

### 4. Goal-Driven Execution
- **Define success criteria.** For multi-step tasks, state a brief plan and loop until verified.

---

# RADAR BDS — AI Agent Context

> **Mục đích file này**: Cung cấp context đầy đủ cho AI Agent để làm việc ngay, không hỏi lại những gì đã biết.

---

## 1. DỰ ÁN LÀ GÌ?

Công cụ **định giá tự động bất động sản** tại Bình Dương (Thủ Dầu Một & Bến Cát).  
Luồng: **Crawl Facebook/Guland/BDS** → **Regex parse** → **LLM enrich (Groq/Gemini)** → **Ridge Regression định giá** → **Dashboard HTML**.

**Khu vực hỗ trợ**:
- **Thủ Dầu Một (TDM)**: 13 phường.
- **Bến Cát**: Phú An, An Tây, An Điền, Mỹ Phước (1-4 sub-zones), Thới Hòa, Tân Định, Hòa Lợi, Chánh Phú Hòa.

**Database**: SQLite tại `C:\Users\ASUS\radar_bds.db`. 
**Kiến trúc**: Hỗ trợ xử lý tịnh tiến (Incremental) cho tập dữ liệu lớn (>500k records).

---

## 2. CÁC LỆNH QUAN TRỌNG

```bash
# Cào dữ liệu & Automation
python radar.py crawl-daily              # Chạy full pipeline: Crawl (BDS/Guland/FB) -> Reprocess -> Telegram Alert
python radar.py schedule-setup --every 3 # Cài Windows Task Scheduler chạy crawl-daily mỗi 3 ngày
python radar.py crawl-facebook --mode incremental --limit 30 # Cào tin FB 3 ngày qua (10 tin/ngày/môi giới)

# Xử lý dữ liệu
python radar.py reprocess                # Chạy Tịnh Tiến (Incremental) - CHỈ xử lý tin mới (Mặc định cực nhanh)
python radar.py reprocess --full         # Chạy Toàn Bộ (Full) - Dùng khi sửa logic normalize/valuation
python radar.py reprocess --groq         # Regex + Groq batch enrich
python radar.py inspect                 # Snapshot nhanh tình trạng DB (Agent nên chạy đầu session)

# Debug/Manual/Testing
python app.py                           # Flask Dashboard (DYNAMIC)
python tests/sanity_test.py             # MANDATORY: Run after any backend/API changes
python alerts/telegram.py               # Test gửi tin nhắn Telegram manually
```

---

## 3. CẤU TRÚC MODULE

| Module | Chức năng chính |
|--------|----------------|
| `radar.py` | CLI router (argparse) |
| `app.py` + `services/market_data.py` | Flask dashboard |
| `cli/crawlers.py` | crawl-all, crawl-daily, crawl-facebook, repair-missing |
| `cli/system.py` | reprocess, lifecycle, schedule, download-images |
| `cli/queries.py` | inspect, stats, deal-brief, top50-cheap |
| `analytics/valuation.py` | ValuationEngine: per-ward ridge regression, signals |
| `analytics/lifecycle.py` | sweep delisted, segment velocity |
| `cleansing/reprocess.py` | pipeline: normalize → dedup → valuation → groq |
| `cleansing/feature_extractor.py` | road_tier, property_type, frontage, legal |
| `cleansing/groq_enricher.py` | Groq Llama 3.3 70B, batch 20/call |
| `crawler/guland_pw.py` | Guland Playwright (13 wards, MAX_CLICKS=50) |
| `crawler/batdongsan_pw.py` | BatDongSan (26 slugs, 8s delay) |
| `crawler/facebook_apify.py` | Facebook via Apify API |
| `config/area_profiles.py` | Config-driven area rules: street patterns, standard lots, sub-wards |
| `config/database_sqlite.py` | get_conn(), init_schema(), upsert_listing() |
| `alerts/telegram.py` | Telegram consolidated alert |

---

## 4. SCHEMA DATABASE (BẢNG CHÍNH: `listings`)

| Cột quan trọng | Ý nghĩa |
|---|---|
| `ward` | Tên phường (13 TDM + Bến Cát incl. Mỹ Phước 1-4 sub-zones); `"unknown"` nếu chưa xác định |
| `road_type` | `hem_xe_may / hem_ba_gac / hem_xe_hoi / duong_nhua / mat_tien_kinh_doanh` |
| `road_tier` | 1=mặt tiền lớn, 2=đường nhựa, 3=hẻm xe hơi, 4=hẻm xe máy |
| `road_width_m` | Chiều rộng đường (mét) |
| `price_ty` | Giá (tỷ VNĐ) |
| `price_per_m2` | Giá/m² (triệu/m²) |
| `area_m2` | Diện tích (m²) |
| `llm_verified` | 0=chưa qua LLM, 1=đã xử lý (dù có kết quả hay không) |
| `llm_notes` | JSON string kết quả LLM |
| `is_signal` | (trong `valuation_results`) 1=Deal hời/ngợp theo AI |
| `outlier_direction` | `'low'` = đáng ngờ rẻ, `'high'` = ngờ đắt |

---

## 5. LOGIC ĐỊNH GIÁ (ValuationEngine)

- **Per-ward models**: Mỗi phường có SegmentModel riêng. Fallback 3 tầng: sub-ward → parent ward → `SELECTED_REGION`.
- **Fit strategy**: Chỉ lấy **30.000 records gần nhất** để huấn luyện mô hình nhằm tối ưu RAM và bám sát giá thị trường.
- **Tier-0 = Tier-3**: `road_tier=0` định giá như tier-3 hẻm xe hơi (×0.50).
- **Signal**: Tin rẻ hơn Fair Value đáng kể → `is_signal = 1`.
- **Fit threshold**: Cần tối thiểu 15 listing/segment để dùng Regression.

---

## 6. HYBRID LLM PIPELINE

```text
raw text (Facebook/Guland)
    ↓ Regex (normalizer.py) — nhanh, miễn phí
listings có ward/road_type
    ↓ nếu ward='unknown' OR road_tier=0 → Groq Batch Enrich (groq_enricher.py)
    ↓ Groq: Llama 3.3 70B, batch 20/call, 2s delay, retry 65s nếu 429
listings đầy đủ
    ↓ ValuationEngine.fit() + evaluate_all()
valuation_results
    ↓ gửi Telegram Alert (alerts/telegram.py)
    ↓ 1. Alert signal mới ngay lập tức
    ↓ 2. Consolidated Alert 3 ngày (tổng hợp deal hời nhất)
Dashboard
```

**Keys cần có trong `.env`**:
```env
APIFY_TOKEN=...         # Crawl Facebook
GEMINI_API_KEY=...      # Gemini (backup)
GROQ_API_KEY=...        # Groq (ưu tiên)
```

---

## 7. TRẠNG THÁI HIỆN TẠI & VIỆC CẦN LÀM

### Số liệu DB (Cập nhật 2026-05-07 — sau Guland re-crawl)

| Bảng | Số lượng | Ghi chú |
|------|----------|---------|
| raw_listings | 6,336 | Guland + Facebook (BatDongSan đang crawl lại) |
| listings active | 6,335 | 1 skipped |
| Valuated | 5,787 | 663 signals (~11.5%), 204 outliers |
| Dedup | 577 flagged | 300 groups, 5,758 unique lots |

**Nhanh kiểm tra**: `python radar.py inspect`

- **Tối ưu Dedup**: Thuật toán Bucketing xử lý 6000+ tin trong < 1 phút.
- **UI/UX (Dynamic Dashboard)**: 
    - Real-time filtering by Ward, Property Type, MOS (Ngợp), and Source.
    - Advanced Sorting: Newest, Price/m2, Total Price, Best Opportunity.
    - Dynamic Analytics: Trend Charts (Period-based), Heatmap (Ward comparison).
    - Performance: Centralized `applyFilters()` and `load_data()` with SQL optimizations.
- **Valuation refactor (07/05)**:
    - Per-ward models thay SELECTED_REGION → định giá theo đúng thị trường từng phường
    - Tier-0 → tier-3 (×0.50) thay vì neutral (×1.00)
    - Bỏ floor check (FAIR_FLOOR_RATIO × median)
- **Crawler refactor (07/05)**:
    - BatDongSan: 4 slugs → 26 slugs (13 phường × ban-dat + ban-nha)
    - Guland: re-crawl full với ảnh, 5,083 records mới
    - Auto download images sau mỗi lần crawl (không cần chạy thủ công)
- **Groq pipeline (07/05)**:
    - `enrich_frontage_with_groq()`: fill frontage_m + road_width_m bị thiếu
    - `verify_signals_with_groq()`: verify + re-valuate top signals
    - Lệnh: `python radar.py reprocess --groq-frontage [--ward Tân An]`
    - Lệnh: `python radar.py reprocess --groq-signals [--ward Tân An]`

### ⚠️ Vấn đề tồn tại

| Vấn đề | Trạng thái |
|--------|-----------|
| `has_so` luôn = 0 | Extraction chưa đủ; discount 25% valuation chưa áp dụng |
| Facebook image URLs | CDN token hết hạn sau vài giờ → download ngay sau crawl để dùng local |
| `road_tier=0` còn cao | Groq commands đã implement — chạy `--groq-frontage` để cải thiện |

### 🔲 TODO tiếp theo (theo thứ tự ưu tiên)
1. **has_so extraction fix** — `has_so=False → fair_value × 0.75` (discount 25%)
2. **Sanity Testing** — Always run `python tests/sanity_test.py` before finalizing edits.
3. **Token Efficiency** — Use `python radar.py inspect` to get context instead of reading large DB logs.

---

- **13 phường TDM**: Tân An, Tương Bình Hiệp, Hiệp An, Chánh Mỹ, Phú Mỹ, Phú Tân, Chánh Nghĩa, Định Hòa, Phú Thọ, Phú Hòa, Phú Cường, Hiệp Thành, Phú Lợi.

---

*Cập nhật: 09/05/2026 — Dashboard UX: Compact Sidebar, MOS Slider, Tab Hạ Tầng nâng cấp*

### 🚀 TIẾN ĐỘ & FIXES (Phiên 08/05/2026)

#### 1. Hệ thống Bộ lọc & Sắp xếp (Frontend/Backend Sync)
- **Fix Lọc Loại hình**: Chuyển toàn bộ trigger sang `applyFilters()` để thu thập đầy đủ trạng thái checkbox trước khi fetch.
- **Tối ưu Slider Ngợp**: Tách biệt `oninput` (cập nhật text nhanh) và `onchange` (fetch dữ liệu khi buông tay) → Hết lỗi load 2 lần.
- **Thêm Sắp xếp (Săn Deal)**: Hỗ trợ 4 chế độ: Mới nhất, Giá/m² rẻ nhất, Giá trị rẻ nhất, Cơ hội tốt nhất (MOS).
- **Fix Trigger Phường**: Thêm `onchange` trực tiếp vào template tạo checkbox ward động trong `main.js`.

#### 2. Độ ổn định Backend (Fix 500 Errors)
- **SQL Parameter Order**: Sửa lỗi sai thứ tự `?` trong `stats_query` (where_sql vs mos_pct).
- **Rounding Safety**: Thêm `COALESCE` và kiểm tra `None` trước khi `round()` dữ liệu Heatmap/WardStats → Hết crash khi gặp phường không có dữ liệu.
- **Serialization**: Đảm bảo toàn bộ kết quả từ `load_data` được convert sang `dict()` trước khi `jsonify` (Sửa lỗi Row object không serializable).

#### 3. Quy trình AI Agent & QA
- **MANDATORY Sanity Test**: Triển khai `tests/sanity_test.py` kiểm tra API, Lọc, Sắp xếp.
- **Dashboard Rules**: Cập nhật `.claude/rules/dashboard.md` mô tả kiến trúc Dynamic Dashboard (UI -> Aggregation -> API -> Backend).
- **Testing Rules**: Thêm `.claude/rules/testing.md` bắt buộc AI phải run test trước khi hoàn tất.

### 🚀 TIẾN ĐỘ & FIXES (Phiên 09/05/2026)

#### 1. Sidebar gọn + Bộ lọc tín hiệu
- **Compact sidebar**: spacing giảm toàn bộ (padding, margin, font-size, checkbox size).
- **Collapsible sections**: mỗi filter-group có chevron toggle, Data Sources mặc định collapsed.
- **BỘ LỌC TÍN HIỆU** (section mới): gộp MOS slider + checkbox "Chỉ tin giảm giá".
- **MOS slider range 30–70**: `mos_pct` trong DB lưu theo %, tất cả signals >= 30% — range 0–50 cũ không có tác dụng.
- **Backend `mos_min`**: `get_base_filters()` parse param, `load_data()` filter `v.mos_pct >= ?` cho signals.

#### 2. Tab Hạ Tầng nâng cấp
- **Filter bar**: lọc theo diện tích (m²) và giá (tỷ) ngay trên bảng; backend `/api/listings` nhận `area_min/max`, `price_min/max`.
- **Ngày đăng column**: hiển thị ngày + số ngày trước (`posted_at` hoặc `crawled_at`).
- **Sortable headers**: click vào tiêu đề cột (Loại, Khu vực, Diện tích, Giá, Fair Value, Ngày đăng) để sort asc/desc với icon ↑↓.
- **Infinite scroll**: cuộn xuống cuối bảng tự load 50 tin tiếp theo (IntersectionObserver với `root: .table-scroll`); sentinel nằm trong `.table-scroll` để detect đúng scroll container.
