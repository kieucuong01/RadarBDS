---
name: update-investment-memos
description: Update/rewrite/backfill Radar BDS advisory investment memos for signal deals. Use when the user says "update memo", "rewrite memo", "cập nhật memo", "viết memo cho signal", or asks Codex to review signal deals and save memos to production.
---

# Update Investment Memos

Use this skill for Radar BDS advisory memo work. The user expects Codex to read system data and write investor-grade memos, not generate formulaic text.

## Read First

1. `AGENTS.md`
2. `docs/investment_memo_workflow.md`
3. `docs/operations.md` if touching production

## Non-Negotiables

- Write advisory rows only to `ai_deal_review`.
- Never write agent verdicts/memos to `ai_training_feedback`.
- Do not call Groq or any external LLM API.
- Use append-only writes; latest valid row wins by `created_at DESC, id DESC`.
- Mark map/legal/location-dependent deals with `needs_map_check=1`.
- User-facing memo must be Vietnamese-only. Avoid: `Invest memo`, `Verdict`, `MOS`, `stress test`, `comps`, `market approach`, `income approach`, `unknown`.

## Data To Read Per Signal

Read the actual deal context before writing:

- `listings`: title, description, ward, price, area, frontage/depth, road, residential land, legal/source hints.
- latest `valuation_results`: actual price/m2, fair price/m2, margin, signal score, segment, sample count, trust/source/legal flags.
- `price_history`: price drops or noisy price history.
- same-lot/repost history: duplicate/repost evidence and prior prices.

## Memo Quality Bar

Each memo must answer:

- Should the investor prioritize, watch, bargain hard, suspect bait price, or skip?
- What is the system comparing this deal against?
- Is the reference price credible or weak?
- Where can money be made: cheap entry, location, frontage, road, liquidity, income, holding, subdivision, negotiation leverage?
- What can make the investor lose money?
- What price/action should the investor take now?

Recommended structure:

```markdown
# Ghi chú cố vấn

## Kết luận
## Định giá chuẩn tắc
## Luận điểm đầu tư
## Mức giá hành động
## Rủi ro làm mất tiền
## Cách xử lý
```

## Production Workflow

When the user asks to update production memos:

1. Query current actionable signals using latest valuation plus `services.signal_quality.actionable_signal_sql()` and `actionable_listing_sql()`.
2. Write a new model marker for the run, for example `codex-data-appraisal-memo-v5`.
3. Insert rows into `ai_deal_review` with `actor='codex'`, verdict, confidence, reasoning, red flags JSON, `memo_markdown`, and `needs_map_check`.
4. Verify latest valid memo coverage equals actionable signal count.
5. Verify no mojibake and no banned English terms.
6. Verify `ai_training_feedback` was not touched.

## Current Baseline

As of 2026-06-06, production had `274/274` actionable signals covered by latest advisory memos:

- `254` latest memos from `codex-data-appraisal-memo-v4`
- `20` clean manual memos from `codex-data-appraisal-memo-v2`

Older append-only rows may exist; always check latest valid row, not total historical rows.
