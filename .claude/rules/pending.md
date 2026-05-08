# Pending & Backlog (2026-05-07)

## Backlog tính năng (theo thứ tự ưu tiên)

1. **has_so extraction fix** — hiện tất cả `has_so=0` dù title ghi "sổ đỏ/sổ hồng"
   - Sau khi fix: `has_so=False → fair_value × 0.75` (discount 25%)
2. **Tầng 3a — Quy hoạch checker** — WebGIS Bình Dương (`qhbinhduong.vn`)
   - Parse tọa độ từ URL → query loại đất (ODT/SKC/CLN)
   - CLN không chuyển được → loại khỏi signal
3. **Tầng 3b — Proximity scoring** — khoảng cách tới KCN Vsip 3, QL13, TDM center, trường/BV
   - Score 1–5, cộng vào Signal Score
4. **Schedule tự động** — `python radar.py schedule-setup` (Task Scheduler 7:00 sáng)
5. **Telegram alert** — config `.env` TELEGRAM_TOKEN + CHAT_ID

## Giới hạn đã biết

| Vấn đề | Trạng thái |
|--------|-----------|
| `has_so` luôn = 0 | Extraction chưa đủ; discount 25% chưa áp dụng |
| `road_tier=0` còn cao | Groq commands đã implement; chạy `--groq-frontage` để cải thiện |
| Facebook image URLs | CDN expire → auto download ngay sau crawl (đã fix) |
| BDS crawl chậm | 8s/slug × 26 slugs ≈ 40–60 phút; không thể song song (Cloudflare) |
| Apify credits | Free tier $5/tháng gần hết — dùng `--mode incremental` cho daily |
| Không có proxy | Guland OK (batch same-origin); BDS risk bị block |
| Mở rộng địa bàn | Thuận An, Dĩ An chưa có data |

## Đã làm gần đây

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
