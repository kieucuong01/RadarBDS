# Keyword Search Road And Area Design

## Goal

Upgrade keyword search so investors can reliably filter listings by a specific road or area. The selected product direction is exact search: prefer fewer, cleaner results over broad full-text matches.

## Current Behavior

The current `q=` filter normalizes accents and splits the query into up to six terms. Each term must appear somewhere in the combined listing text: title, description, ward, road type, property type, source, or URL. This works for simple phrases like `nguyen chi thanh`, but it does not understand road or area intent. It can also match noisy terms such as `duong` or `khu` instead of the meaningful road or area token.

## Requirements

- Keep the existing `q=` API contract for `/api/signals` and `/api/listings`.
- Use exact intent matching for road and area searches.
- Support Vietnamese and unaccented input.
- Support compact and spaced road codes, including `DX44`, `ĐX 44`, `DH3A`, `DL12`, and `NL5`.
- Support investor area terms such as `khu L`, `Mỹ Phước 3`, `MP3`, and ward names.
- Do not return rows only because they contain generic words such as `đường`, `duong`, `khu`, `gần`, or `gan`.
- Preserve current redaction and tier behavior.
- Keep `/api/dashboard` lightweight; search may affect counts, but must not add full listing payloads there.

## Proposed Behavior

The backend search parser will convert a user query into exact search tokens:

- Road code token: `DX44`, `ĐX 44`, `duong dx 44` all become a road-code intent for `dx44`.
- Area code token: `khu L`, `khu-l`, and `Khu L Mỹ Phước` keep `khu l` as an exact phrase.
- Mỹ Phước shorthand: `MP3`, `Mỹ Phước 3`, `my phuoc 3` normalize to the same area intent.
- Named roads: `Nguyễn Chí Thanh`, `nguyen chi thanh` stay as an exact phrase.
- Generic words are removed unless they are part of a recognized phrase.

Each recognized intent must match the normalized searchable text. This is intentionally stricter than broad search. If a query contains no meaningful token after cleanup, no keyword filter is applied.

## Data Flow

1. `static/js/main/filters.js` continues sending the input as `q=`.
2. `app.py` continues normalizing the raw query through `_request_keyword`.
3. `services/market_data.py` owns search parsing and SQL filter generation.
4. Both `/api/signals` and `/api/listings` reuse `keyword_search_filter`.

## Implementation Shape

- Add a small tokenizer in `services/market_data.py` near the existing search helpers.
- Keep `_search_text_expr` as the SQL search target, but improve the normalized target with compact alphanumeric matching for road codes.
- Replace simple whitespace terms with exact intent tokens.
- Add focused regression tests in `tests/test_source_policy.py`:
  - `q=DX44` matches title containing `Đường ĐX 44`.
  - `q=ĐX 44` matches title containing `DX44`.
  - `q=khu L` matches area text containing `khu L`.
  - `q=MP3` matches `Mỹ Phước 3`.
  - `q=duong` alone does not narrow to arbitrary road listings.
  - The same behavior applies to `/api/listings`.

## Non-Goals

- No fuzzy ranking or partial-result fallback.
- No new database columns or reprocess required.
- No new UI search modes.
- No broad search over legal verification text.

## Testing

Use TDD:

1. Add failing tests for exact road and area search.
2. Verify the new tests fail against current behavior where applicable.
3. Implement the parser and SQL filter changes.
4. Verify targeted tests pass.
5. Run syntax checks for touched Python and JS files.

## Risks

- Exact search can return fewer rows than broad search. This is accepted by the selected product direction.
- Some real listings may omit road or area terms in text and therefore not match. This is also accepted because the goal is high precision for investor road/area search.
