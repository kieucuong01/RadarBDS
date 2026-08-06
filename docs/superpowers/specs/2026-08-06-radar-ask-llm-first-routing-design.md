# Radar Ask LLM-First Routing Design

## Goal

Radar Ask should feel like a real BĐS consultant: understand natural Vietnamese questions first, ask a short clarification when needed, call the right database/RAG tool when data is needed, and answer directly with sources as supporting evidence.

The current regex-first router is too brittle. It catches many questions before the LLM planner can infer intent, so simple investor questions can route to the wrong tool or fail as a service error.

## Non-goals

- Do not reprocess listings, valuations, or read models.
- Do not add new crawl-time LLM enrichment.
- Do not broaden tool permissions or expose private listing URLs/phones to non-admin users.
- Do not build a new chat product; this is a focused Radar Ask routing change.

## Proposed Architecture

Radar Ask will route every new user question through the typed LLM planner first when a planner is available.

```text
User question
  -> quota/session/context
  -> LLM typed intent planner
  -> typed route validation and guardrails
  -> tool execution or natural reply
  -> direct answer + source cards
```

Deterministic routing remains, but only as a fallback and guardrail:

- fallback when the planner is unavailable or returns invalid typed JSON;
- special handling for explicit listing references like `tin #1061`;
- bounded policy enforcement through existing `finalize_planned_route()`;
- deterministic answer presenters for common data answers after tools run.

## Routing Behavior

The planner must classify these practical user intents:

- `conversation`, `help`, `off_topic`: no DB tool; answer naturally.
- `clarification`: no DB tool; ask one concise consultant-style follow-up.
- `area_market_estimate`: price level by ward/area; use `compare_areas`.
- `deal_search`: "find a decent/cheap/ok lot"; use `search_deals`.
- `price_drop_ranking`: count/rank discount signals; use `rank_price_drop_areas`.
- `budget_match`: budget-to-area fit; use `match_budget`.
- `valuation_explanation` or `listing_comparison`: explicit listing IDs; use valuation/listing tools.
- `official_price_explanation`: official land-price policy; use curated knowledge tools.

## Guardrails

- The planner output must still be a `RouteDecision`.
- Only approved tools are allowed.
- Existing max tool-call limits remain.
- Fast tool routes still use deterministic presenters when available.
- If the planner fails, deterministic fallback can answer common safe cases instead of returning service unavailable.
- If neither planner nor fallback can safely infer intent, Radar Ask asks a clarification instead of pretending data is missing.

## Cost and Latency

This adds one low-cost router-model call for most questions. It is acceptable because:

- Free/VIP/Admin daily limits already cap usage.
- The monthly warning and hard-stop budgets remain active.
- The planner uses the cheaper router model, not the smarter answer model.
- Better intent routing avoids wasted expensive answer calls and failed runs.

## Required Regression Tests

Add/update tests for these user-facing cases:

- `Xin chào` routes to conversation and does not call DB tools.
- `đất tân an giờ giá bao nhiêu` lets planner choose `compare_areas`.
- `kiếm cho tôi lô đất tại Tân An ok xíu` lets planner choose `search_deals`.
- `Tân An có lô nào 500m2 rẻ k` lets planner choose `search_deals` with an area range.
- `hiện có bao nhiêu lô giảm giá ở Tân An` lets planner choose `rank_price_drop_areas`.
- `Giải thích định giá tin #1061` and `So sánh tin #1061 với tin #52103` remain supported.
- Planner failure falls back to deterministic routing without exposing internal errors.

## Deployment Plan

1. Implement tests first for planner-first behavior.
2. Change routing/orchestration so the LLM planner is attempted before deterministic fast paths when available.
3. Preserve deterministic fallback and existing safety validation.
4. Run the focused Radar Ask test set.
5. Commit, push `main`, deploy production, then smoke production route behavior and HTTP 200.

