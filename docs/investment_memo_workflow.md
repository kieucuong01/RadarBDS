# Investment Memo Workflow

Use this doc when the user asks to update, rewrite, backfill, or inspect advisory memos for signal deals.

## Product Intent

Investment memo is a data-backed advisory note for real-estate investors. It is not a rule-based template, not an API-generated opinion, and not a human training label.

The memo must read like an experienced property investor has reviewed the deal context: price, land form, location clues, road, residential land, legal/source flags, valuation sample strength, price history, lot history, and practical action price.

## Hard Rules

- Store memo/advisory verdicts only in `ai_deal_review`.
- Never write Codex/Claude/agent verdicts into `ai_training_feedback`.
- Do not call any external LLM API for memo writing.
- Do not expose phone numbers or source URLs to non-admin users.
- Keep user-facing memo Vietnamese-only: do not use `Invest memo`, `Verdict`, `MOS`, `stress test`, `comps`, `market approach`, `income approach`, or `unknown`.
- Use append-only writes. A new review row should supersede older memo rows by `created_at DESC, id DESC`.
- If a conclusion depends on map, zoning, legal status, actual road, or exact location, set `needs_map_check=1`.

## Current Memo Standard

Each memo should include these sections:

```markdown
# Ghi chú cố vấn

## Kết luận
Say clearly: prioritize, watch, bargain hard, suspect bait price, not attractive, or insufficient data.

## Định giá chuẩn tắc
Explain the market-comparison logic in plain Vietnamese:
- asking price and asking price per m2
- system reference price per m2 and total reference value
- comparison group size/strength
- why the reference is credible or weak
- whether the gap is enough to compensate for risk

## Luận điểm đầu tư
State what creates investor value for this specific lot: cheap entry, road, frontage, location, liquidity, rental use, lot size, subdivision/holding potential, price drop, or negotiation leverage.

## Mức giá hành động
Give practical anchors:
- current asking price
- price worth viewing
- price worth bidding while risk remains
- condition to walk away

## Rủi ro làm mất tiền
Name deal-specific risks, not generic warnings: legal status, residential-land ratio, zoning, road reality, wrong ward/road, thin samples, repost history, source quality, bait price, building condition, rental proof.

## Cách xử lý
List what to ask/check before deposit: title document, coordinates, zoning, frontage/depth, road width, residential land, current tenant/rent, price-change reason, and final seller price.
```

## Valuation Principles

- Market comparison is the main method for residential land and house-land signals.
- Income/dòng tiền is a secondary check only when the listing has rent, rooms, shopfront, or another clear income use.
- Replacement/cost is a secondary check only for properties with meaningful buildings.
- Highest and best use is the final sense-check: living, renting, holding, trading, subdivision, or business use.
- Thin samples, weak source flags, unclear legal status, or unverified location must lower confidence and require a bigger margin of safety.

## Production Update Workflow

For production memo updates, use the deploy SSH path and production env described in `operations.md`. Do not print secrets.

1. Get current actionable signal IDs using latest valuation plus `services.signal_quality.actionable_signal_sql()` and `actionable_listing_sql()`.
2. For each signal, read:
   - `listings`: title, description, ward, property type, price, area, frontage/depth, road, residential land, source, legal/source hints.
   - latest `valuation_results`: actual price/m2, fair price/m2, margin, score, segment, sample count, trust/source/legal flags.
   - `price_history` and same-lot/repost history.
3. Write a new `ai_deal_review` row with:
   - `actor='codex'`
   - `model` marker for the run, for example `codex-data-appraisal-memo-v5`
   - one of `cheap_real`, `suspect`, `not_cheap`, `insufficient_info`
   - `reasoning` short Vietnamese summary
   - `red_flags` JSON array
   - `memo_markdown`
   - `needs_map_check`
4. Verify:
   - actionable signal count equals latest valid memo coverage
   - latest memo has no mojibake such as `Ã`, `Â`, `�`
   - latest memo does not contain banned English terms
   - latest memo has core sections
   - `ai_training_feedback` has no Codex/Claude/agent rows

## Latest Known Production Backfill

On 2026-06-06, current actionable signals were backfilled:

- `274/274` latest signals had advisory memo coverage.
- Latest memo model distribution: `254` rows from `codex-data-appraisal-memo-v4`, `20` clean manual rows from `codex-data-appraisal-memo-v2`.
- `ai_training_feedback` was not touched.
- Older append-only rows may still exist, but latest valid memo wins.
