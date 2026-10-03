# Radar BDS Page — News Workflow (reviewed, fail-closed)

Status: **wired into the weekday 18:40 Page Care cron.** The LLM editor runs the
CLI commands below and stamps its own caption/source/visual review before
publish. The module itself never publishes without that review stamp.

Owner module: `scripts/rb_page_news_workflow.py`
Tests: `tests/test_rb_page_news_workflow.py` (run with `/opt/radar-bds/.venv/bin/python -m pytest`)

This module **reuses**, never reimplements:
- `scripts/radar_social_auto_post.py` → `load_state()`, `save_state()`,
  `posted_today()`, `create_queue(slug, preview=True)`, `upgrade_queue_image()`,
  `publish(queue_path)`, `editorial_candidates(posted)`.
- `scripts/radar_social_queue.py` schema `radar_social_queue.v1` (browser-compatible).
- The legacy no-agent Page-care path (`radar_social_auto_post.main`) is **unchanged**.

---

## Lane recommendation (no forced quota)

`recommended_lane(posted)` inspects real posted history:

- Historical entries with **no `lane`** are labeled `radar` (never inferred as news).
- Counts the last **10 real posts**; recommends `news` when fewer than **3** are news.
- **Never** recommends `news` when the most recent post was already news (no 2 consecutive).
- No quota is forced — after 3 news in 10, it recommends `radar` until the window opens again.

## Reader destination safety

- The publisher rejects Radar homepage-root links as reader CTAs; a root URL with `?tab=` / `&ward=` is not a stable filtered destination.
- Use one matching article or verified feature route. If internal filter parameters are removed and the URL collapses to `/`, fall back to the relevant article instead.
- Facebook landing links use `utm_source=facebook`, `utm_medium=social`, `utm_campaign=rb_content_v2`, and `utm_content=<slug>`.

## CLI

All commands run from the repo with `PY=/opt/radar-bds/.venv/bin/python`.

### `plan` — read-only planning (no browser, no images, no publishing)

```bash
$PY scripts/rb_page_news_workflow.py plan --report /path/to/report.json
```
Prints: `recommended_lane:`, `already_today: true|false`, the eligible source
candidates (id · publisher · published_at · score · title), and
`editorial_candidates: slug-a, slug-b` from the existing Radar queue engine.

### `prepare-news` — build a review queue + Gemini image upgrade

```bash
$PY scripts/rb_page_news_workflow.py prepare-news \
    --report /path/to/report.json \
    --draft  /path/to/draft.json \
    --out-dir /opt/radar-bds/var/social_preview/news
```
Validates the report + draft, writes a `radar_social_queue.v1` item with
`target.mode="review"`, then calls the existing `upgrade_queue_image` (Gemini is
real by default; tests mock only external generation). Prints the queue path.

### `prepare-radar` — normal Radar review queue

```bash
$PY scripts/rb_page_news_workflow.py prepare-radar --slug latest
```
Delegates to the existing `create_queue(slug, preview=True)`.

### `approve` — human/LLM review stamp

```bash
$PY scripts/rb_page_news_workflow.py approve --queue <queue.json> \
    --note "Caption/source checked; visual is a conceptual illustration, not a map or progress photo."
```
Stores a `review` stamp whose `stamp_hash` binds the **whole caption, headline,
source block, evidence, self-comment AND the actual image sha256**. This is an
acknowledgment of review, **not** automated visual understanding. If any of
those change afterward, the stamp no longer validates.

### `publish` — fail-closed publish (reuses existing publisher)

```bash
$PY scripts/rb_page_news_workflow.py publish --queue <queue.json>
```
Under an `fcntl` exclusive lock: validates the review stamp (refuses missing or
changed content/image), same-day dedupe against state, lead-source freshness
(≤24 h fetched, ≤7 d published), and an HTTP/canonical check on the lead source
URL — **before** any side effect. Then it calls the existing `publish()` and
persists the standard history fields plus `lane`, `news_source_urls`,
`news_topic_key`, `editorial_pillar`, `editorial_topic`. History is never reset
and the same queue is never published twice.

On an **ambiguous** publish failure it writes a `*.in-flight.json` marker with
`status: requires_reconciliation` and exits non-zero, refusing automatic retry
(a human must reconcile first).

---

## SOURCE REPORT CONTRACT (owned by the source worker)

`scripts/rb_page_news_discovery.py` produces `rb_page_news_discovery.v1`:

```json
{
  "schema": "rb_page_news_discovery.v1",
  "generated_at": "2026-09-12T10:00:00+07:00",
  "candidates": [{
    "id": "str", "url": "https://...", "publisher": "str", "title": "str",
    "published_at": "ISO-tz", "fetched_at": "ISO-tz", "text": "clean article body",
    "content_sha256": "sha256(text)", "is_primary": false, "eligible": true,
    "classification": "news_candidate", "trend_evidence": [], "location": "str",
    "topic_key": "str", "score": 8.5, "requires_primary": false, "rejection_reasons": []
  }],
  "errors": []
}
```

`validate_source_report` requires `content_sha256 == sha256(text)` (forged hash
rejected) and non-empty ids. `published_at` may be a full timezone-aware ISO
timestamp **or an honest date-only `YYYY-MM-DD`**; the module never manufactures
a time for a date-only source. Timezone-aware `generated_at`/`fetched_at` values
are normalized to **+07** rather than requiring a literal `+07` offset, so `Z`
discovery output is accepted.

Two classifications are supported:

| classification | allowed hosts | `published_at` | `fetched_at` freshness |
|---|---|---|---|
| `news_candidate` | trusted news domains / official `*.gov.vn` (`is_primary`) | required (date-only ok) | ≤ **24 h** |
| `product_reference` | `https://radarbds.vn/...` **only** | optional (`null` or date-only) | ≤ **7 d** |

The **selected lead** (`selected_ids[0]`) must always be a real
`news_candidate`, so a Radar product page can never be the news lead; a
`product_reference` may only support non-news claims (e.g. buyer-tip claims
quoting a Radar guide). `source.requires_primary` metadata is passed through to
`news.sources[…].requires_primary` unchanged.

### Trusted source domains
`cafeland.vn`, `vnexpress.net`, `tuoitre.vn`, `baochinhphu.vn`, plus `*.gov.vn`
(**primary only** — `.gov.vn` must also carry `is_primary: true`). HTTPS only.

## DRAFT JSON (`rb_page_news_draft.v1`)

```json
{
  "schema": "rb_page_news_draft.v1",
  "selected_ids": ["n1"],
  "headline": "short approved headline (<=90 chars)",
  "caption": "reader-facing text with news attribution + date",
  "reader_benefit": "what the buyer gets from reading",
  "radar_url": "https://radarbds.vn/tin-tuc/<existing-slug>",
  "visual_mode": "photoreal | infographic",
  "claims": [
    {"source_id": "n1", "quote": "exact excerpt present in source.text",
     "kind": "news|policy|infrastructure|financing", "claim": "paraphrase"}
  ],
  "event_status": "e.g. đang lấy ý kiến, chưa khởi công",
  "known_unknowns": ["..."]
}
```

Validation (`validate_report_and_draft`):
- **Freshness:** lead source `published_at` ≤ **7 d**; all candidates `fetched_at` ≤ 24 h.
- **Attribution mandatory:** caption must name the publisher and carry the source
  date (`YYYY-MM-DD`, `DD/MM/YYYY`, or `DD-MM-YYYY`).
- **No jargon/hype/guaranteed ROI:** rejects `trung vị`, `MOS`, `snapshot`,
  `ROI`, "cam kết sinh lời", "chắc chắn lời", "sốt nóng", etc.
- **Primary needed for material claims:** material kinds (`policy`,
  `infrastructure`, `financing`, `law`, `legal`, `planning`) **always** require a
  genuine official primary source (`.gov.vn`/`baochinhphu.vn`, `is_primary:
  true`) whose quote supports the claim — regardless of the declared `kind`, so a
  `kind: "buyer_tip"` label cannot evade it.
- Ordinary buyer-comparison wording is **not** material: comparing "cùng loại
  đường, cùng tình trạng đất ở", or using `đường`, `cầu`, `pháp lý`, `vay` as
  due-diligence topics does **not** demand a government primary source.
  `MATERIAL_RE` only matches real official assertions (`phê duyệt`, `khởi công`,
  `luật/nghị định/thông tư/quy định … có hiệu lực|ban hành|áp dụng`, `có hiệu
  lực`, `lãi suất <số>`, or a `cao tốc|metro|vành đai|cầu|đường` token within 50
  chars of `phê duyệt|khởi công|mở rộng|nâng cấp`).
- **Quote integrity:** each quote must be present verbatim in the cited
  `source.text` and the `source_id` must be among `selected_ids` (missing quote
  or quote-not-in-source rejected).
- **Trend claims need evidence:** any trend wording (`xu hướng`, `tăng`, `giảm`,
  `sốt`, …) without non-empty `trend_evidence` is rejected.
- **radar_url safety:** must be `https://radarbds.vn/tin-tuc/...` and match a
  real configured article path (invented paths and unrelated external URLs rejected).

## Queue output contract (`radar_social_queue.v1`)

- `target`: `platform=facebook`, `surface=page`, `page_url=...radarbdsvn...`,
  `mode="review"`, `requires_review=true`.
- `content.message` == the reviewed caption; `content.caption` mirrors it.
- `content.self_comment` includes the **exact original source URLs** plus a
  relevant **radarbds.vn UTM** link (`utm_source=facebook&utm_medium=pinned_comment&utm_campaign=rb_news`).
- `source.slug` = `news-<id>-<YYYY-MM-DD>`; `source.article_date` = lead date;
  `source.news_source_urls`, `source.news_topic_key` present.
- `content.editorial.pillar` / `editorial.metadata.pillar` = `news_explainer`;
  `lane` = `"news"`; `news.event_fingerprint` = sha256(topic + source URLs)[:16].
- `news.evidence` = claims with `source_id`, `quote`, `kind`; `news.sources` =
  per-source evidence (url, publisher, dates, sha256, is_primary, requires_primary).

## Image prompt safety

`content.visual_prompt` starts with "Conceptual AI illustration only" and
explicitly states it must **not** depict actual project progress, construction
status, real cadastral/legal map boundaries, route alignments, or false maps.
It forces a short approved headline. The existing Gemini stage
(`rb_gemini_page_image`) reads `source.title`/`content.message` for this.

## Verification

```bash
/opt/radar-bds/.venv/bin/python -m pytest tests/test_rb_page_news_workflow.py -q
# 13 passed
```
No existing file is modified by this module; `no_agent` legacy path is untouched.
