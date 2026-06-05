# Exact Keyword Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make keyword search precise for investors searching by road or area, using exact road/area intent instead of broad noisy terms.

**Architecture:** Keep the existing `q=` API and UI input. Implement exact intent parsing inside `services/market_data.py`, then reuse the same SQL filter for `/api/signals`, `/api/listings`, dashboard counts, and related market reads that already call `keyword_search_filter`.

**Tech Stack:** Flask, PostgreSQL-compatible SQL helpers, Python `unittest`/direct test execution, existing Radar BDS read-model helpers.

---

### Task 1: Add Exact Search Regression Tests

**Files:**
- Modify: `tests/test_source_policy.py`

- [x] **Step 1: Extend `_seed_signal` so tests can set description and ward**

Add optional `description=None` and `ward=None` parameters. Insert `description or "Source policy listing"` and `ward or self.ward` into the listing insert.

- [x] **Step 2: Add failing API tests**

Add tests that prove:
- `/api/signals?q=DX44` matches a title with `Đường ĐX 44`.
- `/api/signals?q=ĐX 44` matches a title with `DX44`.
- `/api/signals?q=khu L` matches area text with `khu L`.
- `/api/signals?q=MP3` matches `Mỹ Phước 3`.
- `/api/signals?q=duong` does not narrow the feed by generic road wording.
- `/api/listings?q=DX44` uses the same exact tokenizer.

- [x] **Step 3: Verify red**

Run the focused tests before production-code changes. Expected: at least the compact/spaced road code or generic-word behavior fails against current whitespace search.

### Task 2: Implement Exact Search Tokenizer

**Files:**
- Modify: `services/market_data.py`

- [x] **Step 1: Add tokenizer helpers near existing search helpers**

Add helpers that:
- ASCII-fold and lowercase query text.
- Detect road codes like `dx44`, `dx 44`, `dh3a`, `dl12`, `nl5`.
- Detect area terms like `khu l`, `mp3`, `my phuoc 3`.
- Remove generic words `duong`, `khu`, `gan`, `phuong`, `tp`, `thanh pho` when they are standalone.
- Return no search clauses for generic-only queries.

- [x] **Step 2: Improve SQL search target**

Keep the current accent-insensitive text expression and add a compact expression that removes spaces, hyphens, slashes, dots, and underscores so `DX44` can match `ĐX 44`.

- [x] **Step 3: Update `keyword_search_filter`**

Use phrase tokens against the normal expression and compact tokens against the compact expression. Combine each token with `AND`, preserving exact-search behavior.

- [x] **Step 4: Verify green**

Run the focused tests and confirm they pass.

### Task 3: Verify Syntax And Scope

**Files:**
- Verify: `services/market_data.py`
- Verify: `static/js/main/filters.js`

- [x] **Step 1: Run Python syntax check**

Run `python -X utf8 -m py_compile services/market_data.py app.py`.

- [x] **Step 2: Run JS syntax check**

Run `node --check static/js/main/filters.js`.

- [x] **Step 3: Inspect diff**

Confirm the search implementation touches only search-helper code and tests, while pre-existing Market/UI changes remain unowned.
