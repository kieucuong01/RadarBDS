---
name: signal-extraction-llm-qc
description: Use when reviewing Radar BDS signal listings for extraction mistakes in price, area, ward, road, property type, frontage/depth, or tho cu, especially daily Codex/LLM quality checks on newly crawled production signals.
---

# Signal Extraction LLM QC

Use this skill to review new actionable signal listings by manual Codex/LLM reading. The script only prepares the queue; correctness comes from the agent reading each listing text sequentially.

## Guardrails

- Read `AGENTS.md`, `docs/README.md`, and `docs/dev_commands.md` first.
- Do not add external LLM calls into crawl, reprocess, or production ingestion.
- Do not write Claude/Codex conclusions to `ai_training_feedback`.
- Keep human/admin labels separate; extraction QC findings can be local reports or admin data-quality review items.
- Do not mark the review done until every exported listing has been read by the agent.
- `ward` is the canonical old valuation ward used by the system. New post-merger ward names are context only: use them to infer the old ward, but do not write a broad new ward unless the system explicitly migrates to new wards.
- Treat KDC/TDC names as landmarks unless the text also states a stronger old ward.

## Daily Workflow

1. Export only the new production review queue to local. Do not sync the full production DB for this daily QC workflow:

```powershell
.\scripts\export_prod_signal_llm_review_queue.ps1
```

2. Or export an exact production window:

```powershell
.\scripts\export_prod_signal_llm_review_queue.ps1 -Since "2026-06-14T00:00:00+07:00"
```

3. Read the generated `.local/llm-review/raw/signal-llm-qc-*.jsonl` in small batches. Each raw line contains `listing_id`, `stored_extraction`, `listing_text`, `raw_facts`, and valuation context. For each listing, read title and description yourself, then write a structured result line:

```json
{
  "listing_id": 123,
  "status": "ok",
  "llm_extract": {
    "price_ty": 1.3,
    "area_m2": 120,
    "ward": "Hòa Lợi",
    "road_type": "duong_nhua",
    "road_tier": 2,
    "road_name": null,
    "property_type": "dat_nen",
    "tho_cu_m2": 60,
    "frontage_m": 5,
    "depth_m": 24
  },
  "reason": "Stored extraction matches listing text."
}
```

Use `status="override"` only when the LLM read is confident. Use `status="admin_review"` when the text is ambiguous or needs map checking. Save all result lines to a JSONL file such as `.local/llm-review/structured/signal-llm-qc-results-YYYYMMDD.jsonl`.

Review fields:

- `price_ty`
- `area_m2`
- `ward`
- `road_type`, `road_tier`, `road_name`
- `property_type`
- `tho_cu_m2`
- `frontage_m`, `depth_m`

4. Apply only confident overrides back to production, then refresh valuation only for the touched listing IDs:

```powershell
.\scripts\apply_prod_signal_llm_review_results.ps1 -InputPath .local\llm-review\structured\signal-llm-qc-results-YYYYMMDD.jsonl -Revalue
```

5. Run deterministic support audit only as supporting evidence when needed:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 scripts\audit_signal_extraction.py
```

Treat this as supporting evidence only. It cannot replace the manual LLM reading.

6. Supported override fields: `price_ty`, `price_per_m2`, `area_m2`, `ward`, `property_type`, `frontage_m`, `depth_m`, `road_name`, `road_type`, `road_tier`, `tho_cu_m2`, `tho_cu_ratio`, `has_so`. Use JSON/null semantics: `price_ty: null` means the LLM determined the asking price is unknown and should clear a stale Python/source value. If no explicit override is saved, the normal Python extractor remains canonical.

7. Do not expand the daily QC workflow into parser/normalizer fixes. If a repeated parser bug becomes obvious, log it separately for non-daily maintenance instead of fixing it inside the daily run.

8. Mark the production queue reviewed only after the structured result/report is saved:

```powershell
.\scripts\export_prod_signal_llm_review_queue.ps1 -Since "<same Since value printed by the reviewed queue>" -CommitState
```

## Admin Review

Extraction mismatches should be visible to admin through the data-quality queue:

```text
/admin/api/data-quality/items?queue=extraction_qc
```

Use admin review for ambiguous listings and isolated one-offs. Do not turn the daily run into parser maintenance.

## With Advisory Memos

For the full daily flow, use `daily-signal-llm-review`. This QC skill should run before advisory memo writing. If a listing has unresolved blocking extraction mismatches in price, area, ward, road, property type, frontage/depth, or tho cu, do not save a confident investment memo from stale extracted data.

## Completion Report

Report these numbers to the user:

- signal listings read manually
- mismatched listings and field counts
- overrides applied
- remaining admin-review items
- before/after audit counts

## Common Mistakes

- Calling the rule audit "LLM review"; it is not.
- Advancing the review state before saving manual findings.
- Turning the daily run into parser maintenance work.
- Writing Codex judgments into human training-label tables.
