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

Radar BDS is a local SQLite + Flask dashboard for Bình Dương real-estate signals.

Pipeline:

```text
crawler/* -> raw_listings -> cleansing/normalizer.py
          -> listings -> cleansing/dedup.py
          -> analytics/valuation.py -> valuation_results
          -> Flask dashboard / VIP Telegram push / CLI reports
```

Supported focus areas:

- Thủ Dầu Một wards.
- Bến Cát wards and Mỹ Phước sub-zones.
- Sources: Facebook, Guland, BatDongSan.

## Canonical Runtime State

- Canonical DB: `data/radar_bds.db`.
- Override: `RADAR_DB_PATH`; relative values resolve from repo root.
- Runtime images: `data/images/`.
- Card thumbnails: `data/images/thumbs/*.webp`.
- Runtime data is ignored by git. Do not commit DB files, images, reports, or logs.
- If app behavior differs from code, check which DB is loaded:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python39\python.exe"
& $py -X utf8 -c "import db.connection as c; print(c.DB_PATH)"
```

## Core Entry Points

- `radar.py`: CLI router.
- `app.py`: Flask routes only; keep route handlers thin.
- `services/market_data.py`: dashboard/listing read models and API shaping.
- `services/image_assets.py`: image URL normalization and thumbnail resolution.
- `auth/core.py`: session, tier, rate-limit, VIP expiry, audit.
- `alerts/telegram.py`, `cli/notify.py`: VIP Telegram formatting and watchlist push.
- `cleansing/reprocess.py`: normalize, dedup, valuation orchestration.
- `cleansing/dedup.py`: duplicate and price-drop policy.
- `db/connection.py`, `db/schema.py`, `db/listings.py`: DB path, schema, writes.
- `config/database_sqlite.py`: compatibility facade; new code should prefer `db.*`.
- `cli/review.py`: `review-queue` (JSON memo, chưa review) / `review-save` (ghi `ai_deal_review`).
- `services/investment_memo.py`: `load_investment_memo()` — memo nguồn cho pre-review.

## Admin AI Training Panel

Route: `/admin/control-room` → tab "AI Training".

API endpoint: `GET /admin/api/ai-training/items` — params: `limit`, `offset`, `ward`, `city`, `mos_min`, `sort` (default/newest/cheapest/mos/score), `queue` (`main`/`recheck`/`source_qc`). Trả JSON: `{items, pending, total, offset, has_more, wards, ward_cities, queue, queue_label}`.

Front-end files:
- `templates/admin_control_room.html` — markup; `#trainingGrid`, `#trnSentinel`, filter bar.
- `static/js/admin.js` — `loadTrainingItems`, `trainingCard`, `saveTraining`, infinite scroll.
- `static/css/admin.css` — `.training-grid`, `.view-list`, sidebar collapsed, card styles.

Current cache versions: `admin.css?v=admin-v5-training-ppm2`, `admin.js?v=admin-v16-source-quality` (bump khi đổi admin CSS/JS/html).

Card display:
- Listing card shows title, road/type, area, asking price, asking `Giá/m²`, and description.
- Description payload stays full; UI clamps to 3 lines and shows `Xem thêm` when longer.
- Valuation box shows Fair Value as both total `tỷ` and `tr/m²`.
- Valuation verdicts are separate from extraction: `cheap_real | fair | overpriced | fake_price | cannot_price`.
- Queue `Guland QC` shows Guland listings that were valuated but suppressed from `is_signal` because source quality flags require manual check.

**Anti-bias — KHÔNG BAO GIỜ vi phạm:**
- Verdict Claude ghi `ai_deal_review` (append-only). KHÔNG ghi `ai_training_feedback`.
- `ai_training_feedback` là ground-truth nhãn người, KHÔNG contaminate bằng verdict AI.
- `review_hidden` chỉ admin bấm; Claude KHÔNG tự flip.
- Logic định giá CHỈ học từ nhãn người. Claude chỉ cố vấn.
- `reprocess_valuation()` vẫn loại mọi `review_hidden` khỏi training model, nhưng valuate lại hidden latest `bad_data` để đưa vào queue `Recheck sau fix` nếu còn `is_signal=1`.
- Hard hide: `fake_price`, `sold`, `spam`, `bad`. Soft recheck hide: `bad_data` với `wrong_*`. Valuation non-deal labels `fair`, `overpriced`, `cannot_price` vẫn ẩn khỏi main queue.
- Guland is hybrid, not deleted: crawl/display stays on, but `source_quality_flags` remove suspect Guland rows from the valuation baseline. Flags currently include old reposts, extreme Guland price/m², suspicious bait, and direct human bad/fake/cannot-price labels.
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

Dashboard/API:

- `/api/dashboard` is lightweight summary only. It must not return all signals, descriptions, or image arrays.
- `/api/signals` is paginated card data. Default limit is 30. It returns `primary_img` thumbnail when available.
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
- Frontend JS change: run `node --check static/js/main.js` and smoke test `http://127.0.0.1:5000`.
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
