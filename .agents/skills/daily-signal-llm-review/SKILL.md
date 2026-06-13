---
name: daily-signal-llm-review
description: Use when running the daily Radar BDS LLM workflow for newly crawled signal deals, including extraction QC and advisory investment memos for new actionable signals.
---

# Daily Signal LLM Review

This is the daily orchestration skill. It keeps two LLM tasks in one operator flow, but separates their decisions:

1. Extraction QC: is the system reading the listing fields correctly?
2. Advisory memo: if the fields are reliable, what should an investor do with this deal?

Do extraction QC first. A memo built on wrong price, area, ward, road, property type, or tho cu is not a valid memo.

## Read First

1. `AGENTS.md`
2. `docs/README.md`
3. `.agents/skills/signal-extraction-llm-qc/SKILL.md`
4. `.agents/skills/update-investment-memos/SKILL.md`
5. `docs/investment_memo_workflow.md`

## Guardrails

- Do not call external LLM APIs from crawl, reprocess, QC, or memo writing.
- Do not write Codex/Claude conclusions to `ai_training_feedback`.
- Advisory memo rows go only to `ai_deal_review`, append-only.
- Do not save confident advisory memos for listings with unresolved blocking extraction mismatches.
- Ambiguous extraction cases should go to admin extraction QC instead of forcing parser changes.
- `ward` remains the old canonical valuation ward. Treat new post-merger ward
  names as context for reverse-mapping only; do not overwrite a correct old ward
  with broad new names like `Bình Dương`, `Chánh Hiệp`, `Phú Lợi`, or `Phú An`.
  Example: `TĐC Phú Chánh` maps to old `Phú Tân`, and `Tân Định cũ nay Hòa Lợi`
  stays `Tân Định`.
- Treat KDC/TĐC names as landmarks unless the text also states a stronger old
  ward. Current alias memory: `KDC Hiệp Thành 1/2/3` and `KDC K8 Hiệp Thành`
  map to old `Hiệp Thành`; `TĐC Phú Chánh` maps to old `Phú Tân`. If a listing
  says old `Phú Mỹ` and merely mentions nearby `KDC Hiệp Thành 3`, keep
  `ward=Phú Mỹ`.

## Daily Flow

1. Export only the new production review queue to local. Do not sync the full production DB for this daily workflow:

```powershell
.\scripts\export_prod_signal_llm_review_queue.ps1
```

2. Or export an exact production window:

```powershell
.\scripts\export_prod_signal_llm_review_queue.ps1 -Since "2026-06-14T00:00:00+07:00"
```

3. Read the generated `.local/llm-review/raw/signal-llm-qc-*.jsonl` sequentially in
small batches. For every listing, compare the stored fields against the
title/description by your own LLM reading, then save one structured JSONL result
line with `listing_id`, `status`, `llm_extract`, and `reason`:

- price and price per m2
- area, frontage, depth
- ward
- road type, road tier, road name
- property type
- tho cu

4. Apply only confident extraction overrides back to production, then refresh valuation for only the touched listing IDs:

```powershell
.\scripts\apply_prod_signal_llm_review_results.ps1 -InputPath .local\llm-review\structured\signal-llm-qc-results-YYYYMMDD.jsonl -Revalue
```

5. Route each listing:

- `clean`: no blocking extraction mismatch; eligible for advisory memo.
- `override_fixed`: manual/explicit LLM parse was saved with `db.listings.save_llm_extraction_override(...)`, production valuation refresh passed, and the listing fields now match the read text; eligible for advisory memo.
- `blocked`: price, area, ward, road, type, or tho cu is unresolved; skip normal memo and send to admin extraction QC.
- `ambiguous`: text is not enough to decide; send to admin extraction QC and use `needs_map_check` if a memo is later written.

Use explicit LLM extraction overrides only when the LLM read is a deliberate workflow output. If no override is saved, Python extraction remains canonical. Do not expand the daily workflow into parser/normalizer fixes; log repeated parser bugs separately for non-daily maintenance.

6. Write/update advisory memos only for `clean` or `override_fixed` listings. Use `update-investment-memos` standards:

- Read listing, valuation, price history, lot/repost context, legal/source flags.
- Write Vietnamese investor-grade memo, not a template.
- Save append-only to `ai_deal_review` with a fresh model marker.
- Mark `needs_map_check=1` when conclusion depends on exact road, coordinates, zoning, legal status, or location reality.

7. Commit the production review state only after findings and memo decisions are saved:

```powershell
.\scripts\export_prod_signal_llm_review_queue.ps1 -Since "<same Since value printed by the reviewed queue>" -CommitState
```

## Report Back

Report in Vietnamese:

- signals read manually
- extraction mismatches by field
- listings skipped from memo because extraction was blocked
- memo rows written or updated
- override/revalue evidence
- remaining admin-review items

## Design Rule

One daily workflow, two separate gates. Extraction QC protects data correctness; advisory memo uses only data that passed or was repaired.
