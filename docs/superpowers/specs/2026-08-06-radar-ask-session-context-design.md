# Radar Ask Session Context Design

## Goal

Make each Radar Ask session understand follow-up questions as one continuous
conversation. Users should not need to repeat the ward, property type, budget,
area, goal, or listing already established in the current session.

Memory is limited to the current `session_id`. A new chat starts with no memory
from older chats.

## Product Behaviour

Examples that must work:

- User: `Đất Định Hòa thì sao?` then `Giá tầm 3 tỷ đổ lại thôi.` The second turn
  inherits Định Hòa and the prior property intent.
- User: `Ngân sách 2,5 tỷ ở Thủ Dầu Một nên xem phường nào?` then `Mấy phường
  khác thì sao?` The second turn refers to the preceding recommendation.
- User: `Tân An có lô nào khoảng 500 m2 không?` then `Rẻ hơn nữa thì sao?` The
  second turn keeps Tân An and the approximate area unless the user changes them.
- If the user explicitly says a different ward, budget, or property type, the
  new value replaces the inherited value for that turn and subsequent turns.

## Context Model

For a request with an owned `session_id`, the backend loads:

1. Up to six most recent user/assistant messages from that session.
2. A bounded structured snapshot from the most recent successful runs in that
   session: city, ward or compared wards, road, property type, budget, area
   bounds, current listing, and the previous question type.

No additional LLM call is used to build this context. The snapshot is derived
from validated server-owned route/tool arguments and persisted answers, so it
cannot invent market facts.

The context is request-scoped. It does not create a user profile, cross-session
memory, or a new database table.

## Precedence And Routing

Context values follow this precedence:

1. Values explicitly stated in the current question.
2. The current page or listing context.
3. Values inherited from the current chat session.

The session context is supplied to both routing paths:

- Deterministic fast paths use inherited typed fields only when the current
  question omits them.
- The typed DeepSeek planner receives the bounded recent turns and structured
  snapshot for ambiguous follow-ups.

The planner still chooses only allowlisted typed tools. Session text is context,
not executable instructions, SQL, URLs, or evidence. Tool outputs remain the
only source for market numbers and source cards.

## Components

### Repository

Add one owner-scoped read that returns recent messages and recent successful run
routes for a session. It must reject a session owned by another user and apply
strict row and text limits.

### Session Context Resolver

Add a small resolver that converts repository records into:

- bounded `recent_turns` for the planner and natural conversation responder;
- a structured session snapshot for typed routing inheritance.

Only allowlisted location and filter fields are copied from validated tool
arguments. Raw source URLs, phone numbers, evidence payloads, and arbitrary tool
arguments are excluded.

### Service And Orchestrator

Before starting a follow-up run, the service hydrates `AskContext` from the
owned session. The orchestrator receives an immutable request snapshot so the
same question is routed consistently even if another request later updates the
session.

### Routing

Fast routes may inherit missing city, ward, road, property type, budget, and
area constraints. Explicit values in the new question always win. A follow-up
that is still genuinely ambiguous asks one concise clarification instead of
silently guessing.

## Failure Behaviour

- If no `session_id` is supplied, the request behaves as a new chat.
- An unknown or foreign session remains `404` through the existing ownership
  boundary.
- A transient context read failure returns the existing service-unavailable
  response; it must not silently answer with the wrong session.
- Missing useful history is valid and falls back to ordinary routing.
- Deleted chats immediately lose their context.

## Cost, Privacy, And Limits

- No extra provider request is added.
- Recent turns remain capped at six and use existing field length limits.
- Structured context contains intent/filter values only, not market evidence.
- Current authentication, tier quotas, daily limits, and monthly budget stops do
  not change.

## Verification

Important tests follow the 80/20 rule:

1. Repository ownership and bounded ordering.
2. Resolver extracts only approved fields and applies latest explicit values.
3. Deterministic follow-up inherits ward plus budget/property constraints.
4. Planner receives recent turns for an ambiguous follow-up.
5. A new session does not inherit context from another session.
6. Explicit correction overrides inherited context.
7. Existing Radar Ask routing, orchestrator, API, and redaction tests remain
   green.

Production smoke will verify one real multi-turn admin session, the deployed
SHA, both Radar services, and a grounded follow-up answer. No crawl, reprocess,
or schema migration is required.

