# Radar Ask Clickable Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Radar Ask source cards open safe, useful destinations without exposing private listing data.

**Architecture:** A deterministic backend resolver converts trusted evidence metadata into a human title and safe URL. The HTTP serializer also uses the resolver for older stored cards that predate `href`, then passes only the sanitized URL. The existing frontend renderer and `safeHref()` remain the final browser-side guard.

**Tech Stack:** Python 3.12, Flask, Pydantic, vanilla JavaScript, Node test runner.

## Global Constraints

- DeepSeek must never choose or emit source URLs.
- Only same-origin paths and HTTPS official URLs may be returned.
- Guest/Free/VIP must not receive original listing URLs or phone numbers.
- No schema migration or reprocess is allowed for this fix.

---

### Task 1: Resolve safe source-card destinations

**Files:**
- Create: `services/radar_ask/source_links.py`
- Modify: `services/radar_ask/validator.py`
- Test: `tests/test_radar_ask_validation.py`

**Interfaces:**
- Consumes: `EvidenceItem.source_kind`, `source_ref`, and `provenance`.
- Produces: `SourceCard` with deterministic `title` and `href`.

- [ ] Write failing table-driven tests for listing, ward-market, official HTTPS, and unsafe/non-official URL cases.
- [ ] Run the focused Python tests and confirm failure because cards have `href=None`.
- [ ] Implement the minimal resolver and rerun focused tests.

### Task 2: Preserve safe href in the HTTP contract

**Files:**
- Modify: `services/radar_ask/service.py`
- Test: `tests/test_radar_ask_api.py`

**Interfaces:**
- Consumes: validated `AnswerEnvelope.source_cards`.
- Produces: browser payload containing `href` but not `source_ref`.

- [ ] Write a failing serialization/API assertion for `href` and private `source_ref` omission.
- [ ] Run the focused test and confirm the missing `href` failure.
- [ ] Add `href` to the sanitized payload, reconstruct deterministic links for older cards, and rerun focused tests.

### Task 3: Render and release clickable cards

**Files:**
- Modify: `tests/js/radar_ask.test.cjs`
- Verify: `static/js/radar_ask.js`

**Interfaces:**
- Consumes: `source_cards[].href`.
- Produces: `<a target="_blank" rel="noopener noreferrer">` inside the source card.

- [ ] Write a failing DOM assertion that the completed-answer fixture renders the expected source anchor.
- [ ] Confirm the existing renderer passes once the fixture contains `href`; change renderer only if the test exposes a real gap.
- [ ] Run focused Python and JavaScript suites, syntax checks, and `git diff --check`.
- [ ] Commit, push `main`, deploy, then verify production SHA, services, live Admin DOM anchor, and destination HTTP 200.
