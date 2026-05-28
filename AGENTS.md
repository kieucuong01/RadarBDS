# Radar BDS - Agent Quick Context

Use this file as the first read for Codex, Claude Code, Antigravity, or any new AI session. It is intentionally compact. Read deeper docs only when the task touches that area.

## Read Order

1. `AGENTS.md` - this quick context.
2. `docs/agent_playbook.md` - workflow rules and common traps.
3. `docs/architecture.md` - module boundaries and current data flow.
4. `docs/daily_crawl_flow.md` - daily crawl pipeline, signal threshold, VIP notification, JSON config, city filter.
5. `docs/dev_commands.md` - exact Windows commands for checks.

Read only when relevant:

- `docs/rbac.md` - Guest/Free/VIP/Admin masking, auth, lead capture, rate limits.
- `docs/telegram_watchlist.md` - VIP watchlists, Telegram bot binding, zrok webhook, digest format.

Avoid broad reads of `.claude/worktrees/`, `_legacy/`, `data/`, `logs/`, `reports/`, `scratch/`, `browser_recordings/`, and `artifacts/` unless the task explicitly requires them.

## Project Summary

Radar BDS is a PostgreSQL + Flask dashboard for Bình Dương real-estate signals.

Pipeline:

```text
crawler/* -> raw_listings -> cleansing/normalizer.py
          -> listings -> cleansing/dedup.py
          -> cleansing/legal_verification.py -> legal_verifications
          -> analytics/valuation.py -> valuation_results
          -> Flask dashboard / VIP Telegram push / CLI reports
```

Supported focus areas:

- Thủ Dầu Một wards.
- Bến Cát wards and Mỹ Phước sub-zones.
- Sources: Facebook, Guland, BatDongSan.

## Canonical Runtime State

- Canonical DB: PostgreSQL via `DATABASE_URL`.
- Current local dev target: portable PostgreSQL 17 in `tools/postgresql-17.10/`
  with data in `.local/postgres-data`, started by `scripts/local_postgres.ps1`.
  `.env` should point `DATABASE_URL` to `postgresql://postgres@127.0.0.1:5432/radar_bds`.
- Remote Supabase project for sync/backup: `ozdjzfiqcjnlfuihqqjy` (`kieucuong02`,
  region `ap-southeast-2`). The password lives only in local `.env`; never
  print or commit it.
- Legacy SQLite import source: `data/radar_bds.db`; use only for `scripts/migrate_sqlite_to_postgres.py`.
- Runtime images: `data/images/`.
- Card thumbnails: `data/images/thumbs/*.webp`.
- Runtime data is ignored by git. Do not commit DB files, images, reports, or logs.
- If app behavior differs from code, check which DB is loaded:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"
echo $env:DATABASE_URL
```

## Core Entry Points

- `radar.py`: CLI router.
- `app.py`: Flask app setup plus current route implementations; route registration lives in `routes/*` blueprints.
- `routes/`: public/auth/market/admin blueprint modules. Current blueprint handlers delegate to `app.py` implementations to keep this refactor behavior-neutral.
- `services/market_data.py`: dashboard/listing read models and API shaping.
- `services/image_assets.py`: image URL normalization and thumbnail resolution.
- `auth/core.py`: session, tier, rate-limit, VIP expiry, audit.
- `alerts/telegram.py`, `cli/notify.py`: VIP Telegram formatting and watchlist push.
- `cleansing/reprocess.py`: normalize, dedup, valuation orchestration.
- `cleansing/legal_image_classifier.py`, `cleansing/legal_verification.py`: later-phase so hong/so do image evidence helpers. OCR and image-based trust are disabled by default for now.
- `cleansing/dedup.py`: duplicate and price-drop policy.
- `db/connection.py`, `db/schema.py`, `db/listings.py`: DB path, schema, writes.
- `config/proximity.py`: ward/sub-ward proximity boost for `signal_score` only; does not change fair value/MOS.
- `config/database_sqlite.py`: compatibility facade; new code should prefer `db.*`.
- `cli/review.py`: `review-queue` (JSON memo, chưa review) / `review-save` (ghi `ai_deal_review`).
- `services/investment_memo.py`: `load_investment_memo()` — memo nguồn cho pre-review.

## Admin AI Training Panel

Route: `/admin/control-room` → tab "AI Training".

API endpoint: `GET /admin/api/ai-training/items` — params: `limit`, `offset`, `ward`, `city`, `mos_min`, `sort` (default/newest/cheapest/mos/score), `queue` (`main`/`recheck`/`source_qc`/`needs_valuation`/`legal_qc`). Trả JSON: `{items, pending, total, offset, has_more, wards, ward_cities, queue, queue_label}`.

Front-end files:
- `templates/admin_control_room.html` — markup; `#trainingGrid`, `#trnSentinel`, filter bar.
- `static/js/admin.js` — `loadTrainingItems`, `trainingCard`, `saveTraining`, infinite scroll.
- `static/css/admin.css` — `.training-grid`, `.view-list`, sidebar collapsed, card styles.

Current cache versions: `admin.css?v=admin-v8-crawl-ops`, `admin.js?v=admin-v20-crawl-ops` (bump khi đổi admin CSS/JS/html).

Card display:
- Listing card shows title, road/type, area, asking price, asking `Giá/m²`, and description.
- Description payload stays full; UI clamps to 3 lines and shows `Xem thêm` when longer.
- Valuation box shows Fair Value as both total `tỷ` and `tr/m²`.
- Queue `needs_valuation` ("Cần phân loại valuation") giữ các nhãn cũ/ambiguous kiểu `all_correct + bad_data` để admin phân loại valuation lại.
- Khi extraction đúng, UI không default valuation về `cheap_real`; admin phải chọn `cheap_real|fair|overpriced|fake_price|cannot_price` trước khi lưu.
- Valuation verdicts are separate from extraction: `cheap_real | fair | overpriced | fake_price | cannot_price`.
- Queue `Guland QC` shows Guland listings that were valuated but suppressed from `is_signal` because source quality flags require manual check.
- Queue `Legal QC` shows signal listings without detected so hong/so do images, or with human `bad_data/wrong_road|wrong_area|wrong_ward` notes.

Legal trust tiers:
- `candidate_signal`: cheap by model only.
- `has_legal_doc`: reserved for the later document-image/OCR extraction phase; disabled by default for now.
- OCR/parsing of certificate text is disabled for now.
- `has_so` defaults to true. Only explicit no-so wording like "vi bằng", "giấy tay", "chưa có sổ", or "đang làm sổ" should flip it false; `has_legal_doc_image` is not active in current signal/UI logic.

**Anti-bias — KHÔNG BAO GIỜ vi phạm:**
- Verdict Claude ghi `ai_deal_review` (append-only). KHÔNG ghi `ai_training_feedback`.
- `ai_training_feedback` là ground-truth nhãn người, KHÔNG contaminate bằng verdict AI.
- `review_hidden` chỉ admin bấm; Claude KHÔNG tự flip.
- Logic định giá CHỈ học từ nhãn người. Claude chỉ cố vấn.
- `reprocess_valuation()` vẫn loại mọi `review_hidden` khỏi training model, nhưng valuate lại hidden latest `bad_data` để đưa vào queue `Recheck sau fix` nếu còn `is_signal=1`.
- Hard hide: `fake_price`, `sold`, `spam`, `bad`. Soft recheck hide: `bad_data` với `wrong_*`. Valuation non-deal labels `fair`, `overpriced`, `cannot_price` vẫn ẩn khỏi main queue.
- Guland is hybrid, not deleted: crawl/display stays on, but `source_quality_flags` remove suspect Guland rows from the valuation baseline. Flags currently include old/up posts (`posted_at` → `crawled_at` age ≥ 14 days), extreme Guland price/m², suspicious bait, duplicate-like Guland listing clusters (`guland_cluster_flood`), and direct human bad/fake/cannot-price labels.
- Guland signals require a stronger gate than Facebook: normal source threshold plus extra MOS or a high signal score. Source-quality-suppressed Guland rows get `valuation_results.source_quality_recheck=1` instead of VIP/main signal promotion.

Infinite scroll: `#trnSentinel` + `IntersectionObserver` (`rootMargin:400px`) → `loadTrainingItems(true)`. Guard `_trnLoading` chống double-fetch. Badge: `pending/total`.

Chip delegation: event listener delegate trên `#trainingGrid` (1 lần, không re-bind khi append).

## Current Product Rules

Dedup and price drop:

- Same URL/source_id: same listing; track price changes with `price_history`.
- Guland/BatDongSan: source-id only for duplicate/lot identity. Do not use cross-URL heuristics for lot history or price drop.
- Facebook: heuristic repost matching is allowed, but must pass strong guards for property type, thổ cư, location, area/dimensions, and phone.
- `only_drops=1` may show duplicate reposts if `price_dropped=1`.
- Suspicious drops over 40% should be `suspicious_bait`, not normal price-drop signal.

Extractor ward rules:

- `default_area` is city/profile context, not a ward fallback. If a Facebook Bến Cát profile has no clear ward, keep `area="Bến Cát"`, `ward=None`; never default it to Tân An.
- If no city/ward/location is clear, keep `area="Unknown"`, `ward=None` so valuation does not learn from a guessed segment.
- Review-driven Bến Cát patterns: `khu L` / road codes like `DL12`, `NL5`, `DH3A` → Mỹ Phước 3; `ĐH/Đại học Việt Đức` → Thới Hòa; `Chà Vi` → parent Mỹ Phước.
- `Long Nguyên` is outside the current focus area and should normalize to `area="Other"`, `ward=None`.

Dashboard/API:

- `/api/dashboard` is lightweight summary only. It must not return all signals, descriptions, or image arrays.
- `/api/dashboard` uses a short in-process cache keyed by filters. Guest dashboard rate limiting is also in-memory to avoid a DB write on every summary refresh.
- `/api/signals` is paginated card data. Default limit is 30. It returns `primary_img` thumbnail when available.
- Source policy is Facebook-first: Guest/Free/VIP are forced to `source=facebook`; Admin alone sees the source filter and defaults to Facebook unless selecting another source for QC/research. Valuation baseline also defaults to Facebook-only.
- `services/market_data.py` read models should use the shared read connection scope, not fresh `connect()+close()` calls. Supabase remote latency makes extra round-trips visible.
- Keep `/api/signals` page queries compact: use one query with window count and primary-thumbnail selection instead of separate count/list/image queries.
- `/api/listing/<id>` is full modal/detail data, including description and full image list.
- `/api/history/<id>` returns same-listing price history and lot history/comps payload used by modal.
- Non-admin APIs must not expose original listing URLs or phone numbers. Use `redact_for_tier()` or explicit tier redaction.
- Guest/Free/VIP can see listing content, but non-admin users still never receive original URL/phone.
- `/api/market-indicators` is VIP gated.
- Filtering UX is `signals-first`: update `/api/signals` immediately, then refresh `/api/dashboard` in background.
- Do not block signal rendering behind dashboard/insights fetches.
- In command-bar flow, `mos_min` and `only_drops` controls are outside `#filterForm`; query assembly must append them explicitly.

VIP watchlist/Telegram:

- Free users can save watchlists; only active VIP users receive push.
- Users share one Telegram bot but each user maps to a private `telegram_chat_id`.
- `cli/notify.py::push_new_listings_to_vip(since)` sends one digest per user, filtered by that user's active watchlists.
- For local webhook testing use `zrok.exe share public http://127.0.0.1:5000 --headless`; see `docs/telegram_watchlist.md`.

Images/performance:

- Cards must use thumbnails from `data/images/thumbs/`.
- Modal/detail may use original images.
- `download_images()` creates thumbnails for new downloads.
- Backfill thumbnails with `python scripts/generate_thumbnails.py --signals 300` or full backfill without `--signals`.

Cleanup:

- `radar.py db-cleanup` is dry-run by default. Applied cleanup deletes listings missing/zero `price_ty` or `area_m2` because they cannot be valued, and deletes their source raw rows to prevent full reprocess from recreating them.
- Keep human feedback/audit rows unless an explicit retention policy says otherwise.

## Common Commands

Use UTF-8 mode on Windows:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"
& $py -X utf8 radar.py inspect
& $py -X utf8 app.py
& $py -X utf8 radar.py reprocess
& $py -X utf8 scripts\generate_thumbnails.py --signals 300
```

Targeted checks:

```powershell
& $py -X utf8 -m py_compile app.py services\market_data.py services\image_assets.py cleansing\download_images.py
node --check static\js\main.js
& $py -X utf8 -m pytest tests\test_dedup.py tests\test_price_history.py tests\test_lot_history.py tests\test_drop_filter.py
```

## Verification Defaults

- Backend/API change: run `py_compile` for touched Python files and the relevant pytest file.
- Frontend JS change: run `node --check static/js/auth.js` plus the touched `static/js/main/*.js` files, and smoke test `http://127.0.0.1:5000`.
- Admin UI change: also run `node --check static/js/admin.js` + `pytest tests/test_admin_control_room.py tests/test_ai_deal_review.py -q`.
- Auth/watchlist JS change: also run `node --check static/js/auth.js`.
- Telegram/notification change: run `py_compile alerts/telegram.py cli/notify.py`; if testing live send, use a known linked test user and avoid leaking tokens.
- Dashboard/API performance change: check payload sizes for `/api/dashboard`, `/api/signals?page=1&limit=30`, and `/api/listing/<id>`.
- Filter performance change: verify no duplicate requests per interaction and no duplicate cards across signal pages.
- Dedup/price-drop change: run targeted dedup/history/drop tests, then recompute only if explicitly needed.

## Agent Discipline

- Make surgical changes; do not refactor adjacent code for aesthetics.
- Do not revert user changes or runtime data unless explicitly requested.
- Prefer repo patterns and existing service boundaries.
- Keep docs concise; move long historical notes to `SUMMARY_HISTORY.md`.
- When changing behavior, update this file only if future agents need to know it.
