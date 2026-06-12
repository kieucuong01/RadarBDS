---
name: signal-extraction-llm-qc
description: Use when reviewing Radar BDS signal listings for extraction mistakes in price, area, ward, road, property type, frontage/depth, or tho cu, especially daily Codex/LLM quality checks after crawl or production-to-local sync.
---

# Signal Extraction LLM QC

Use this skill to review new actionable signal listings by manual Codex/LLM reading. The script only prepares the queue; correctness comes from the agent reading each listing text sequentially.

## Guardrails

- Read `AGENTS.md`, `docs/README.md`, and `docs/dev_commands.md` first.
- Do not add external LLM calls into crawl, reprocess, or production ingestion.
- Do not write Claude/Codex conclusions to `ai_training_feedback`.
- Keep human/admin labels separate; extraction QC findings can be local reports or admin data-quality review items.
- Do not mark the review done until every exported listing has been read by the agent.

## Daily Workflow

1. Sync fresh production data to local if needed:

```powershell
.\scripts\sync_prod_to_local.ps1
```

2. Export new actionable signals to a markdown queue:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 scripts\export_signal_llm_review_queue.py --days 1
```

Use `--since "2026-06-12T00:00:00+07:00"` for an exact window, or `--limit N` for a smaller pass.

3. Open the generated `.local/llm-review/daily/signal-llm-qc-*.md`. For each listing, read title and description yourself, then compare:

- `price_ty`
- `area_m2`
- `ward`
- `road_type`, `road_tier`, `road_name`
- `property_type`
- `tho_cu_m2`
- `frontage_m`, `depth_m`

4. Append findings to `.local/llm-review/manual_findings.md` with this shape:

```markdown
## YYYY-MM-DD LLM QC

| listing_id | fields | manual_expected | why_system_was_wrong | action |
|---|---|---|---|---|
| 123 | road_name | DB12 | Parser ignored explicit road code after location phrase. | parser_fix |
```

5. Run deterministic support audit after manual review:

```powershell
& $py -X utf8 scripts\audit_signal_extraction.py
```

Treat this as supporting evidence only. It cannot replace the manual LLM reading.

6. If the manual LLM read produced structured facts that are clearly correct for
   an existing listing, save them as an explicit extraction override. This is the
   only LLM parse path that may override Python extraction; it must be manual or
   explicit workflow output, not automatic crawl enrichment.

```powershell
& $py -X utf8 -c "from db.listings import save_llm_extraction_override; save_llm_extraction_override(123, {'price_ty': None, 'area_m2': 120, 'ward': 'Hòa Lợi'}, actor='codex', model='manual-llm', note='manual signal QC parse')"
& $py -X utf8 radar.py reprocess --full
```

Supported override fields: `price_ty`, `price_per_m2`, `area_m2`, `ward`,
`property_type`, `frontage_m`, `depth_m`, `road_name`, `road_type`,
`road_tier`, `tho_cu_m2`, `tho_cu_ratio`, `has_so`. Use JSON/null semantics:
`price_ty: None` means the LLM determined the asking price is unknown and should
clear a stale Python/source value. If no explicit override is saved, the normal
Python extractor remains canonical.

7. If there is a repeated, clear extraction pattern, use test-first fixes:

- Add focused regression cases in `tests/test_feature_extractor.py`, `tests/test_price_history.py`, or `tests/test_extraction_audit.py`.
- Patch the smallest relevant code path, usually `cleansing/feature_extractor.py`, `cleansing/normalizer.py`, `db/listings.py`, or `services/extraction_audit.py`.
- Reprocess only affected rows when possible, then rerun the audit.

8. Mark the queue reviewed only after the findings/report are saved:

```powershell
& $py -X utf8 scripts\export_signal_llm_review_queue.py --since "<same Since value printed by the reviewed queue>" --commit-state
```

## Admin Review

Extraction mismatches should be visible to admin through the data-quality queue:

```text
/admin/api/data-quality/items?queue=extraction_qc
```

Use admin review for ambiguous listings, isolated one-offs, or cases where a parser change could damage currently-correct rows.

## With Advisory Memos

For the full daily flow, use `daily-signal-llm-review`. This QC skill should run before advisory memo writing. If a listing has unresolved blocking extraction mismatches in price, area, ward, road, property type, frontage/depth, or tho cu, do not save a confident investment memo from stale extracted data.

## Completion Report

Report these numbers to the user:

- signal listings read manually
- mismatched listings and field counts
- fixes shipped with test names
- remaining admin-review items
- before/after audit counts

## Common Mistakes

- Calling the rule audit "LLM review"; it is not.
- Advancing the review state before saving manual findings.
- Fixing a one-off ambiguous listing without a regression test and counterexamples.
- Writing Codex judgments into human training-label tables.
