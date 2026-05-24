# Radar BDS - Summary History and Handoff

This file keeps durable handoff notes for future AI sessions. For day-to-day context, read `AGENTS.md` first.

## Current Handoff - 2026-05-20

### Valuation cleanup: signal reliability gate + Hiệp Thành sub-ward split

**Mục tiêu**: tăng signal-to-noise ratio bằng (C) chặn signal khi mẫu so sánh
quá yếu và (F) audit ward Hiệp Thành (152/901 = 17% signal toàn DB, segment
quá rộng gộp nhiều khu vực khác giá).

**Code changes:**
- `analytics/valuation.py`: thêm `MIN_RELIABLE_N_FOR_SIGNAL = 15`; gate
  `is_sig = False` khi `m.n_samples < threshold` (giữa block `ward unknown`
  và `sigma` calc). `valuation_result` vẫn ghi để audit.
- `config/area_profiles.py`: thêm `HIEP_THANH_PROFILE` với 5 street patterns
  (HT3/HT1/HT2/KDC K8 ×2 variants); `_HT_SUBWARDS = {Hiệp Thành 1/2/3, KDC K8
  Hiệp Thành}`. `detect_subward_from_street()` nhận thêm `parent_filter` để
  scope detection theo ward (tránh pattern HT3 nhặt nhầm trong tin MP).
- `cleansing/normalizer.py`: gate sub-ward promotion mở rộng từ
  `ward == "Mỹ Phước"` thành `ward in ("Mỹ Phước", "Hiệp Thành")`; truyền
  `parent_filter=ward_final`.

**Kết quả goal-driven (`python -X utf8 radar.py reprocess --full`):**

| Metric                     | Baseline | After   |
|----------------------------|---------:|--------:|
| Total signal               |     809  |    763  |
| Signal `n_segment < 15`    |      28  |      0  |
| Hiệp Thành parent          |     152  |    107  |
| Hiệp Thành 3 (sub-ward)    |       — |     22  |
| Hiệp Thành 1 (sub-ward)    |       — |      5  |

Hiệp Thành 2 (10 listings) + KDC K8 (19 listings) chưa ra signal — đủ listing
fit segment riêng nhưng không deal nào vượt MOS threshold. Tổng signal họ HT:
152 → 134 (-12%); MOS distribution chặt hơn (HT3 avg 46% vs HT-mixed cũ 42%).

**Tests**: `pytest -q` → 93/93 pass (kể cả `tests/test_valuation.py`). Không
listing chuyển sang ward sai (MP NE5 vẫn match Mỹ Phước 3 OK).

### Admin AI Training panel (feature complete)

**Bảng / API:**
- `ai_deal_review` (append-only) — verdict Claude pre-review, KHÔNG dùng làm ground-truth.
- `ai_training_feedback` — nhãn người (ground-truth). Logic định giá CHỈ học từ đây.
- `/admin/api/ai-training/items` — filter `ward/city/mos_min/sort`, phân trang `limit+offset`, trả `pending`, `total`, `has_more`, `wards`, `ward_cities`.

**Front-end (admin_control_room.html + admin.js + admin.css):**
- Card 2 loại view: Grid và List (toggle nhớ `localStorage trnView`).
- List view: 2 cột bên trong (extraction+valuation | Claude pre-review).
- Badge `#trainingCount` luôn `pending/total` (e.g. `7/901`).
- Infinite scroll: `#trnSentinel` + `IntersectionObserver` rootMargin=400px, guard `_trnLoading`, state `_trnHasMore`.
- Chip event delegation trên `#trainingGrid` (1 lần bind, không double-bind khi append).
- Ward filter đúng ưu tiên (`if ward … elif city`); `_trnAllWards` từ `data.wards` phủ mọi phường signal.
- Conditional valuation: chỉ hiện "2. Định giá AI" khi extraction = `all_correct`.
- Card hiển thị giá rao quy đổi `tr/m²`; box định giá hiển thị Fair Value cả tổng `tỷ` và `tr/m²`.
- Description giữ full text trong payload/DOM, UI clamp 3 dòng và có `Xem thêm`/`Thu gọn` khi dài.
- Lightbox gallery trực tiếp từ card.
- Cache bust hiện tại: `admin.css?v=admin-v5-training-ppm2`, `admin.js?v=admin-v14-training-ppm2-desc`.

**CLI review-deal-signals:**
- `python radar.py review-queue --top N` — lấy queue JSON (chưa có verdict Claude).
- `python radar.py review-save --id <id> --verdict <...> --confidence <0..1> --reasoning "<vi>" [--red-flags "a;b"] [--needs-map-check]`.
- Phiên pre-review #1 đã chạy (2026-05-19): 10 verdict lưu, anti-bias verified.

**Sidebar admin:** 240px, collapsible (52px), toggle `body.sidebar-collapsed`, localStorage `sidebarCollapsed`.

**Còn mở:**
- Bug parser giá `"2t45"` → 0.245 tỷ (sai 10×), nghi `cleansing/normalizer.py`. Chưa fix.
- Backlog: Proximity scoring (Tầng 3b) — chưa làm.
- `ai_training_feedback` disagreements endpoint `/admin/api/ai-training/disagreements` — read-only, có thể dùng để audit/tune sau.

---

## Archived Handoff - 2026-05-10

- Canonical DB is `data/radar_bds.db`; `RADAR_DB_PATH` remains the override.
- Runtime data is ignored by git: DB files, `data/images/`, thumbnails, logs, reports, and scratch output.
- Dashboard first load was optimized:
  - `/api/dashboard` is lightweight summary only.
  - `/api/signals` is paginated card summary, default `limit=30`.
  - `/api/listing/<id>` lazy-loads full modal detail and original images.
- Signal card scroll was optimized:
  - Cards use WebP thumbnails from `data/images/thumbs/`.
  - Modal/detail still uses original images from `data/images/`.
  - `scripts/generate_thumbnails.py` backfills thumbnails.
  - `cleansing/download_images.py` creates thumbnails for new downloads.
- Current dedup policy:
  - Same URL/source_id means same listing.
  - Guland/BatDongSan cross-URL lot heuristics are disabled; source-id only.
  - Facebook repost heuristics remain, with strict property/location/thổ cư guards.
- Current doc policy:
  - `AGENTS.md` is the primary quick context for all agents.
  - `CLAUDE.md` intentionally points to `AGENTS.md` instead of duplicating content.
  - `docs/architecture.md`, `docs/dev_commands.md`, and `docs/agent_playbook.md` hold deeper context.

## Older Stable Milestones

- Refactored `app.py` toward thin Flask routes and moved dashboard read shaping into `services/market_data.py`.
- Refactored DB layer into focused modules under `db/`; `config/database_sqlite.py` remains a compatibility facade.
- Added incremental reprocess flow for daily crawls.
- Moved valuation to per-ward models with recent-record training limits.
- Added Facebook/Guland/BatDongSan crawl flows and local image download pipeline.
- Added dashboard filters, sorting, modal detail, history/comps, and all-listings tab.

## What Not To Reintroduce

- Do not document `C:\Users\ASUS\radar_bds.db` as the default DB.
- Do not make `/api/dashboard` return all signals/descriptions/images again.
- Do not use Guland/BatDongSan cross-URL heuristics for same-lot price drop.
- Do not rely on remote Facebook image URLs for dashboard cards; use local images and thumbnails.
