# Radar Ask Clickable Sources Design

## Goal

Every Radar Ask source card must either open a safe, useful source or remain an explicitly non-clickable calculation reference. The production bug is that all cards are currently non-clickable because the server always sets `href=None` and the HTTP serializer removes `href`.

## Scope

- Add deterministic, server-owned links. DeepSeek never supplies URLs.
- Link Radar listing, signal, comparable, risk, and valuation evidence to the same-origin `/listing/<id>` detail page.
- Link official-document evidence only to an HTTPS `provenance.source_url` already stored in the curated corpus.
- Link ward market aggregates to the same-origin dashboard with reproducible `tab=all`, `ward`, and `date_range` filters.
- Keep unsupported/internal evidence non-clickable instead of guessing a URL.
- Keep `source_ref` private in the HTTP response. Free/VIP must not receive original listing URLs or phone numbers.
- Preserve frontend `safeHref()` validation and `rel="noopener noreferrer"`.

## Data Flow

`EvidenceItem` remains the source of truth. Answer validation builds each `SourceCard` with a human-readable title and a deterministic safe `href`. When an older persisted answer has no `href`, the HTTP serializer reconstructs only the same deterministic link types from its stored `source_ref`. The API returns the sanitized `href`, and the existing renderer turns it into an anchor. No database migration or reprocess is required.

## Link Rules

| Evidence | Link |
|---|---|
| `radar-listing:<id>...`, `radar-signal:<id>`, `radar-valuation:<id>`, `radar-lot:<lot>:listing:<id>` | `/listing/<id>` |
| `ward-market:<ward>:<days>d` | `/?tab=all&ward=<ward>&date_range=<mapped range>` |
| Official document with curated HTTPS `source_url` | Exact HTTPS source URL |
| Unsupported aggregate/calculation | No link; retain readable source label |

Day windows map to `1w`, `1m`, `3m`, `6m`, `1y`, or `all`, using the smallest dashboard range that contains the evidence window.

## Verification

- Python tests prove listing, ward-market, and official-document mappings and prove unsafe/non-official external URLs are not exposed.
- API serialization test proves `href` reaches the browser while `source_ref` does not.
- JavaScript test proves a source card with `href` renders one safe anchor.
- Production Chrome Admin proof opens a listing source and verifies the destination.
