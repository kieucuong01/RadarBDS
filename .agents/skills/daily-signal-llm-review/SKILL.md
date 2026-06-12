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

## Daily Flow

1. Sync production data to local if the task needs current production signals:

```powershell
.\scripts\sync_prod_to_local.ps1
```

2. Export new actionable signals for manual LLM extraction QC:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 scripts\export_signal_llm_review_queue.py --days 1
```

3. Read the generated `.local/llm-review/daily/signal-llm-qc-*.md` sequentially. For every listing, compare the stored fields against the title/description by your own LLM reading:

- price and price per m2
- area, frontage, depth
- ward
- road type, road tier, road name
- property type
- tho cu

4. Save extraction findings to `.local/llm-review/manual_findings.md`. Then run:

```powershell
& $py -X utf8 scripts\audit_signal_extraction.py
```

5. Route each listing:

- `clean`: no blocking extraction mismatch; eligible for advisory memo.
- `fixed`: parser/data fixed and targeted reprocess passed; eligible for advisory memo.
- `blocked`: price, area, ward, road, type, or tho cu is unresolved; skip normal memo and send to admin extraction QC.
- `ambiguous`: text is not enough to decide; send to admin extraction QC and use `needs_map_check` if a memo is later written.

6. Write/update advisory memos only for `clean` or `fixed` listings. Use `update-investment-memos` standards:

- Read listing, valuation, price history, lot/repost context, legal/source flags.
- Write Vietnamese investor-grade memo, not a template.
- Save append-only to `ai_deal_review` with a fresh model marker.
- Mark `needs_map_check=1` when conclusion depends on exact road, coordinates, zoning, legal status, or location reality.

7. Commit the extraction QC state only after findings and memo decisions are saved:

```powershell
& $py -X utf8 scripts\export_signal_llm_review_queue.py --since "<same Since value printed by the reviewed queue>" --commit-state
```

## Report Back

Report in Vietnamese:

- signals read manually
- extraction mismatches by field
- listings skipped from memo because extraction was blocked
- memo rows written or updated
- tests/reprocess/audit evidence
- remaining admin-review items

## Design Rule

One daily workflow, two separate gates. Extraction QC protects data correctness; advisory memo uses only data that passed or was repaired.
