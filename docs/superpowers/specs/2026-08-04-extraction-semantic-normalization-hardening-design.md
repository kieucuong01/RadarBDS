# Extraction Semantic Normalization Hardening Design

**Date:** 2026-08-04

**Status:** Approved by the user through the extraction audit and the follow-up instruction `ok sửa đi`.

**Scope:** Deterministic parsing and normalization of asking price, land area, residential area, lot dimensions, multi-lot offers, property type, ward context, road name/type/width, extraction provenance, and the read-only extraction audit.

## 1. Problem

The existing integrity layer already enforces the important arithmetic rules: declared total area beats rectangular multiplication, regular geometry only becomes severe above 40%, and irregular or multi-side geometry only becomes severe above 60%. The remaining production errors are semantic:

- compact asking prices such as `950TR` can be missed while deposits, down-payments, loans, or discounts can be selected as asking price evidence;
- road widths such as 6m or 8m can become land-area evidence in a secondary parser pass;
- a correct later residential-area parse can be overwritten by an earlier parse that used the wrong total area;
- three-value broker shorthand such as `4,1 x 25 x 50m thổ cư` is not carried consistently through the full normalization path;
- some multi-lot posts contain two area/residential-area groups but no numbered `Lô 1` / `Lô 2` labels and escape suppression;
- nearby or potential-use phrases such as `gần KCN` can classify a house as `kho_xuong`;
- generic prose can be accepted as a road name, while the stop word `phuong` truncates the real street `Nguyễn Tri Phương`;
- derived dimensions are stored in the same fields as source-stated dimensions without durable provenance;
- the deterministic audit ignores strong text evidence whenever the stored field is null and does not inspect frontage, depth, road type, or road width.

## 2. Chosen Approach

Use one deterministic evidence pass and carry its provenance through normalization and persistence.

This is preferred over isolated regex patches because the observed residential-area failures originate from the same text being parsed with different temporary total areas. It is preferred over external LLM enrichment because scheduled extraction must remain deterministic and the project explicitly forbids external LLM calls in crawl or reprocess.

The bounded alternative of patching only the known phrases is rejected because it would leave the duplicated parse/overwrite path and the audit blind spots intact. A broader schema redesign with synthetic per-lot child listings is also rejected; multi-lot posts remain intact and fail closed.

## 3. Measurement and Price Contract

`parse_facebook_post()` remains the single text extraction entry point used by `normalize_record()`. The normalizer supplies the final reconciled total area to residential-area extraction exactly once. A provisional `tho_cu_m2` must not overwrite a later value derived with the final canonical `area_m2`.

Evidence precedence is:

1. explicitly declared total area;
2. valid structured source area;
3. exactly one valid frontage/depth pair for a regular, non-multi-lot post;
4. no manufactured area when evidence is ambiguous.

The existing 40% regular and 60% irregular severe thresholds remain unchanged. Routine skewed-lot differences are accepted.

Compact million prices are accepted only when a price token is present and the amount is at least 100 million, for example `giá chỉ 950TR`. Amounts in clauses describing `đưa trước`, `thanh toán`, `trả trước`, `cọc`, `hỗ trợ vay`, `vay`, `giảm`, or interior value are removed before asking-price selection. Exact `giảm ... còn ...` patterns continue to return the remaining asking price.

## 4. Multi-lot and Property Context

Multi-lot detection gains two bounded forms:

- two or more distinct area groups plus a per-lot/per-nền price marker;
- two or more area/residential-area offer groups joined by `và`, bullets, or separators, with `/lô`, `mỗi lô`, or equivalent sale context.

Rental-room inventories remain excluded. Detected posts receive the existing `multi_lot_listing` suppressing flag and are not split.

Warehouse/factory classification requires asset evidence such as `bán xưởng`, `cho thuê xưởng`, `kho đang cho thuê`, `nhà kho`, or a warehouse/factory source category. `gần KCN`, `khu công nghiệp`, `thích hợp làm xưởng`, and other proximity/potential-use clauses are removed before classification. Explicit existing-house evidence continues to produce `nha_dat`.

## 5. Road and Ward Context

Road names must come from a road marker, a recognized road code, or an existing named-road vocabulary. Generic descriptions such as `đường siêu phẩm cực rẻ`, `mát mẻ`, or `trước đất rộng` are rejected.

The road-name cleaner must not treat `phuong` as a stop token inside `Nguyễn Tri Phương`. Administrative `phường` text is excluded by its surrounding location syntax instead of truncating all occurrences of the word.

Road width and road type are extracted from the same visible text used by normalization. Proximity clauses such as `cách đường nhựa` remain non-asset context.

The audit reuses `resolve_post_merger_location()` and canonical old-ward rules. A broad new ward is context only; an explicit old ward wins. Ambiguous source/text conflicts remain admin-review items rather than automatic corrections.

## 6. Measurement Provenance

Add `listings.measurement_provenance` as a JSON string with stable per-field values:

```json
{
  "area_m2": "declared_text",
  "frontage_m": "source_text",
  "depth_m": "derived_area_frontage",
  "tho_cu_m2": "source_text"
}
```

Allowed values are `source_structured`, `declared_text`, `source_text`, `derived_area_frontage`, `derived_standard_lot`, and `unknown`. Existing columns remain compatible. Reprocess overwrites deterministic provenance, just as it overwrites deterministic extraction flags.

`db.listings` must preserve provenance when it derives a missing depth or area. Explicit LLM/admin overrides remain separate and may mark the overridden field as `admin_override`; no AI result is written to `ai_training_feedback`.

## 7. Audit Contract

`audit_listing_extraction()` reports strong expected evidence even when the stored value is null. It covers:

- `price_ty`, `area_m2`, `ward`, and `property_type`;
- `frontage_m`, `depth_m`, `tho_cu_m2`;
- `road_name`, `road_type`, `road_tier`, and `road_width_m`.

Area comparison uses the shared declared-area and severe-geometry policy, not an independent 5% rectangular rule. Derived dimension provenance is reported as context, not treated as source-exact evidence.

## 8. Data Preservation and Rollout

- Do not modify or delete `raw_listings`, price history, dedup history, images, user data, `ai_deal_review`, or `ai_training_feedback`.
- Do not add external LLM calls to crawl, normalization, or reprocess.
- Do not change valuation formulas, MOS thresholds, source visibility, RBAC, or public redaction.
- After tests pass, run a non-mutating integrity report, deploy code/schema changes, run one controlled full production reprocess, refresh/compare signal and listing read models, and verify APIs and service/timer health.
- Only confident deterministic changes are applied automatically. Conflicting structured/text ward cases remain in admin review.

## 9. Verification

Every behavior change starts with a failing regression based on the audited production phrases. Focused gates cover parser functions, full `normalize_record()` output, PostgreSQL persistence/migration, extraction audit output, dedup/price history, valuation suppression, and read-model parity. The final production gate requires zero price/area/unit-price invariant violations and zero signal/listing parity differences after the controlled reprocess.
