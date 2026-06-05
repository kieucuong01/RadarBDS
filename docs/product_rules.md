# Product And Data Rules

Use this when a task touches user-facing deal quality, dedup/history, valuation, admin training, or API payload shape.

## Signal Semantics

- `valuation_results.is_signal=1` means model-cheap/MOS candidate. It is not automatically an investable deal.
- User/VIP/main surfaces use the latest valuation plus `services.signal_quality.actionable_signal_sql()`.
- Admin QC can show suppressed rows so humans can review parser/source quality.
- `low_segment_confidence` alone should not suppress user-facing signals. Keep it in `source_quality_flags` and show a warning badge.
- Fatal quality flags that can suppress promotion include parser price mistakes, down-payment-as-price, too-low absolute price, large-lot model risk, area/dimension conflict, source category conflict, multi-lot listing, test artifact, human bad-extraction labels, and Guland quality flags.

## Source Policy

- Facebook is primary for crawl, valuation baseline, user feed, VIP push, and default admin review.
- Guland is secondary. It may supplement sparse valuation segments only when strict quality gates pass, and it should not promote itself directly unless stronger gates are satisfied.
- BatDongSan is legacy/disabled. Keep old cleanup/import helpers only when needed for historical data cleanup; do not schedule it in daily crawl.
- Guest/Free/VIP are forced to `source=facebook`. Admin may use source filters for QC/research.

## Dedup And Lot History

- Same URL/source_id is the same listing; track price changes with `price_history`.
- Facebook repost matching is allowed only with strict guards for property type, thổ cư, ward/location, area, dimensions, and phone.
- Facebook same-price reposts may support same-lot history if the lot signature is reliable.
- Guland and legacy BatDongSan use source-id identity only. Do not use cross-URL same-lot heuristics for them.
- `price_dropped=1` means a reliable drop. Suspicious drops over 40% should be treated as `suspicious_bait`, not a normal price-drop signal.
- When auditing lot-history regressions, verify both pair-level conflicts and group-level spread. A clean local audit should reach `pair_issue_counts={}` and `group_spread_flags=0`.

## Extractor Ward Rules

- `default_area` is city/profile context, not a ward fallback.
- If a Facebook Bến Cát profile has no clear ward, keep `area="Bến Cát"`, `ward=None`; never default it to Tân An.
- If no city/ward/location is clear, keep `area="Unknown"`, `ward=None` so valuation does not learn from a guessed segment.
- Bến Cát patterns from review:
  - `khu L`, `DL12`, `NL5`, `DH3A` -> Mỹ Phước 3.
  - `ĐH` / `Đại học Việt Đức` -> Thới Hòa.
  - `Chà Vi` -> parent Mỹ Phước.
- `Long Nguyên` is outside the current focus area and should normalize to `area="Other"`, `ward=None`.

## Valuation Rules

- Facebook is the primary valuation baseline.
- If a canonical segment has fewer than 35 Facebook samples, strict-pass Guland rows may supplement training with weight `0.4`.
- Strict Guland baseline rows must have no source/valuation quality flags, no old-post/extreme/bait/cluster/human-bad flags, valid ward/area/price, and known `road_tier` for `dat_vuon` or lots >= 1000 m2.
- Regression valuation caps `road_tier=3` at max 80% of the same-listing tier-2 counterfactual before downstream adjustments.
- `road_tier=0` is still encoded as tier 3.
- Proximity boosts in `config/proximity.py` affect `signal_score` only; they do not change fair value/MOS.

## Legal Trust

- `candidate_signal`: cheap by model only.
- `has_legal_doc`: reserved for detected sổ hồng/sổ đỏ document-image evidence.
- OCR/parsing certificate text is disabled for now.
- `has_so` defaults to true. Only explicit no-sổ wording such as "vi bằng", "giấy tay", "chưa có sổ", or "đang làm sổ" should flip it false.
- `has_legal_doc_image` is not active in current signal/UI logic.

## Admin AI Training

Route: `/admin/control-room`, tab "AI Training".

Endpoint: `GET /admin/api/ai-training/items` with `limit`, `offset`, `ward`, `city`, `mos_min`, and `sort`.

AI Training is valuation-only. Admin labels should only express whether the model-cheap listing is `cheap_real`, `fair`, `overpriced`, `fake_price`, or `cannot_price`. Data extraction, source quality, recheck, and legal review belong to Data Quality/pipeline work, not this screen.

Data Quality endpoint: `GET /admin/api/data-quality/items` with `queue=recheck|source_qc|legal_qc`.

Data Quality queues:

- `recheck`: hidden/bad-data rows that need recheck after fixes.
- `source_qc`: model-cheap listings suppressed from user/VIP promotion due to source or valuation quality flags.
- `legal_qc`: signal rows missing detected legal-doc image or with human wrong-data notes.

Anti-bias rules:

- Claude/AI verdicts go to `ai_deal_review` only.
- `ai_training_feedback` is human ground truth only.
- Do not let Claude flip `review_hidden`; only admin action should do that.
- Valuation learns only from human labels.
- `reprocess_valuation()` excludes `review_hidden` rows from training, but may valuate hidden latest `bad_data` rows for recheck visibility.

Admin frontend files:

- `templates/admin_control_room.html`: markup, `#trainingGrid`, `#trnSentinel`, filters.
- `static/js/admin.js`: `loadTrainingItems`, `trainingCard`, `saveTraining`, infinite scroll.
- `static/css/admin.css`: training grid, list view, sidebar/card styles.

When changing admin CSS/JS/templates, bump the admin asset cache version in the template.

## API Payload Rules

- `/api/dashboard` is lightweight summary only. No full signal list, no descriptions, no image arrays.
- `/api/signals` is paginated card data. Default limit is 30. It should return a thumbnail `primary_img` when available.
- `/api/listing/<id>` is full modal/detail data, including description and full image list.
- `/api/history/<id>` returns price history, same-lot history, and comps for the modal.
- Non-admin APIs must not expose original listing URLs or phone numbers.
- `/api/market-indicators` is VIP gated.
- Filtering UX is signals-first: update `/api/signals` immediately, then refresh `/api/dashboard` in the background.
- `mos_min` and `only_drops` controls are outside `#filterForm`; query assembly must append them explicitly.

## Images And Cleanup

- Cards must use thumbnails from `data/images/thumbs/`.
- Modal/detail may use original images.
- `download_images()` creates thumbnails for new downloads.
- Backfill thumbnails with `python scripts/generate_thumbnails.py --signals 300` or full backfill without `--signals`.
- `radar.py db-cleanup` is dry-run by default.
- Applied cleanup deletes listings missing/zero `price_ty` or `area_m2`, plus their source raw rows, because they cannot be valued.
- Keep human feedback/audit rows unless an explicit retention policy says otherwise.
- Runtime synthetic rows such as `Tin test` / `.test` URLs should be hidden as `review_hidden_reason='test_artifact'` only when explicitly requested; do not delete them by default.
