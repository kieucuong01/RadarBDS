# Default Signal MOS 15% Design

**Date:** 2026-08-03

**Status:** Design and written spec approved by the user; implementation pending

**Scope:** Default signal semantics and MOS filtering for the homepage Săn Deal feed, badge/counts, Maps, default alerts/reports, and existing VIP/Admin MOS controls

## 1. Problem

Radar BDS currently uses 10% in three different roles:

- `SIGNAL_MOS_THRESHOLD=0.10` marks model-cheap valuation candidates as `is_signal`;
- public request parsing defaults `mos_min` to 10;
- Guest signal feeds and Maps normalize `mos_min` back to 10.

As a result, listings with displayed MOS from 10% through 14.9% can appear in the default Săn Deal feed and contribute to its badge. The requested product rule is stricter: the default Săn Deal experience starts at MOS 15%, while VIP and Admin retain the existing ability to deliberately filter down to 10%.

## 2. Product Semantics

The implementation separates the internal candidate boundary from the user-facing default boundary.

| Context | Effective MOS minimum |
|---|---:|
| Internal valuation candidate (`is_signal`) | unchanged at 10% |
| Guest default or supplied MOS parameter | fixed at 15% |
| Free default or supplied MOS parameter | fixed at 15% |
| VIP/Admin with no MOS parameter or an invalid value | 15% |
| VIP/Admin with an explicit valid MOS filter | the selected value, including 10% |

The internal 10% candidate boundary remains necessary so VIP/Admin can retrieve the 10-14.9% range. Those rows are not part of the default signal experience, badge, Maps, or default alert/report counts.

An explicit VIP/Admin value below 10% does not manufacture new candidates. The existing `is_signal` candidate gate still limits the result set, so the practical minimum remains the internal candidate threshold.

## 3. Chosen Architecture

Introduce one shared user-facing constant, `DEFAULT_SIGNAL_MOS_MIN_PCT = 15`, separate from `SIGNAL_MOS_THRESHOLD`.

Add a small tier-aware normalization helper with this contract:

```text
effective_signal_mos_min(tier, requested_value, was_explicit)
  Guest/Free -> 15
  VIP/Admin + missing/invalid -> 15
  VIP/Admin + explicit valid value -> selected value
```

All default signal consumers must use the same normalized value rather than embedding `10` independently:

- `/api/signals` and legacy/read-model implementations;
- `/api/counts` and `/api/dashboard` signal totals;
- signals-mode Listing Maps summary and items;
- homepage initial MOS slider and query assembly;
- default Telegram signal delivery and default actionable report/card queries;
- VIP/Admin watchlists with an explicit MOS value, which retain that selected value;
- any shared signal cache/read-model key whose result depends on MOS.

Admin QC remains candidate-oriented and may continue to inspect suppressed or 10-14.9% rows. The Tin rao feed remains unchanged.

## 4. Request and UI Behavior

- The homepage MOS slider initializes at 15 instead of 10.
- Guest/Free controls remain locked. Supplying `mos_min=5`, `10`, or a higher value manually does not change their effective 15% feed.
- VIP/Admin controls remain enabled. With no URL/filter value they receive 15%; choosing 10% explicitly includes eligible 10-14.9% candidates.
- The API, badge, and signals-mode Maps use the same effective value, so they cannot disagree about the default signal count.
- Missing, empty, invalid, or non-finite values fall back safely to 15. Explicit numeric VIP/Admin values are clamped to the existing UI range of 0-70; the internal candidate gate still prevents values below the candidate boundary from creating extra rows.

## 5. Data and Cache Handling

This change does not require a valuation reprocess or database rewrite because `is_signal` remains an internal 10% candidate flag. Existing rows already contain the candidates VIP/Admin need.

The production rollout must refresh/publish the signals read model and advance its dataset/cache version after deployment. Application, Redis, Nginx, and Cloudflare responses for the default signal URLs must not retain the earlier 10% result under an equivalent cache key.

No crawler, normalization, deduplication, valuation formula, human label, `ai_deal_review`, or `ai_training_feedback` data changes are authorized.

## 6. Test Requirements

Tests must be written first and observed failing before production code changes.

Required behavior coverage:

- shared normalization returns 15 for Guest and Free regardless of a supplied lower value;
- VIP/Admin missing or invalid MOS uses 15;
- VIP/Admin explicit 10 remains 10;
- default `/api/signals` excludes a valid 10-14.9% candidate and includes a valid 15% candidate;
- VIP/Admin `mos_min=10` can retrieve both candidates;
- default counts/badges equal the signal feed total;
- default signals-mode Maps excludes 10-14.9% and matches feed semantics;
- Tin rao remains unaffected;
- frontend slider defaults to 15;
- existing quality suppression, redaction, pagination, filters, and read-model/legacy parity remain passing.

## 7. Production Verification

After rebase, push, and standard deployment:

1. confirm the deployed commit and active `radar-bds.service`;
2. refresh/publish the signal read model and confirm dataset/Redis versions advance together;
3. verify Guest and Free default `/api/signals`, `/api/counts`, dashboard badge, and Maps contain no MOS below 15%;
4. verify a VIP/Admin request with explicit `mos_min=10` can return eligible 10-14.9% candidates;
5. verify default homepage slider displays 15 and the Săn Deal badge is non-zero and matches the API total;
6. verify Tin rao, public redaction, cache headers, and Cloudflare/private bypass behavior remain correct.

## 8. Rollback

Rollback is code/cache-only and data-preserving:

1. revert the scoped default-MOS commits;
2. redeploy and republish the signals read model/cache version;
3. verify the previous default feed/count/Maps behavior;
4. do not alter PostgreSQL listing, valuation, crawler, review, or user data.
