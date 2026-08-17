# Apify Quota-Aware Facebook Batching Design

**Date:** 2026-08-17
**Status:** Approved for specification; implementation pending written-spec review

## Context

The daily Facebook crawler groups every due broker profile with the same
`daily_limit` into one Apify actor run. The run's estimated demand is:

```text
required_posts = daily_limit * number_of_profiles_in_group
```

One actor run uses one Apify token. The local token pool currently requires one
token's tracked remaining quota to cover the entire estimate before the actor is
called.

On 2026-08-17 production had 33 due profiles and 660 total tracked posts across
active tokens. The `daily_limit=10` group contained 27 profiles and therefore
required 270 posts. No individual token had 270 remaining, although the largest
had 214 and the aggregate pool was sufficient. The token pool rejected the
batch before calling Apify. The preceding 30-post actor run had succeeded, but
the exception prevented `crawl_all()` from returning, so none of those posts
were imported. The recorded Facebook crawl run ended with `status=error`,
`n_fetched=0`, and `n_new=0`. The same failure occurred on 2026-08-16.

The local quota is a planning counter, not live Apify billing truth. It is
configured per token and decremented by the number of returned dataset items.
Apify can therefore report a different balance from the application's tracked
remaining value.

## Goals

1. Use aggregate token-pool capacity by splitting a large profile group into
   token-sized actor runs.
2. Preserve each profile's configured `daily_limit` whenever a token can cover
   at least one complete profile.
3. Rotate to another token when Apify confirms that the current account has
   exhausted its usage or billing quota.
4. Import successfully fetched posts even when later profiles cannot run.
5. Record expected pool exhaustion as a partial crawl rather than losing the
   successful portion or presenting it as a fully successful run.
6. Continue to later profile groups when the current group cannot be fully
   served.

## Non-goals

- Query or reconcile live Apify billing balances in this change.
- Change broker cadence, `daily_limit`, relevance filtering, normalization,
  deduplication, valuation, notification, or image processing.
- Retry transient failures indefinitely.
- Re-enable tokens automatically after Apify confirms quota exhaustion.
- Split one profile across several tokens. Re-running the same profile on a
  second token would normally fetch the same newest posts rather than extend
  the first result set.

## Chosen Approach

Use quota-aware sub-batches while keeping the current grouping by
`daily_limit`.

For each same-limit profile group:

1. Keep a queue of profiles not yet attempted.
2. Acquire an active token that can cover at least one whole profile at the
   group's `daily_limit`.
3. Compute the sub-batch size as:

   ```text
   min(remaining_profiles, floor(token_remaining / daily_limit))
   ```

4. Call the actor with only those profile URLs and the unchanged per-profile
   `resultsLimit`.
5. Record returned item usage and remove the attempted profiles from the queue
   after a successful actor run.
6. Re-acquire from the pool and continue until the group is complete or no
   active token can cover one complete profile.
7. If that group cannot continue, record the unattempted profiles as a partial
   condition and move on to the next group. A smaller-limit group may still fit
   the remaining quota and must not be blocked.

This keeps actor calls bounded: it uses one run per quota-sized profile chunk,
not one run per broker. It also avoids launching an actor request that the local
planner already knows cannot fit a token.

## Token State Transitions

### Successful actor run

- Add the number of returned dataset items to `used_this_month`.
- Update `last_used_at`.
- Keep the token active while tracked quota remains.
- If recorded usage reaches the configured monthly quota, clamp usage to the
  quota, set remaining to zero, and deactivate the token.

### Confirmed Apify quota or billing exhaustion

When Apify returns a recognized hard exhaustion message, including monthly
usage limit, hard usage limit, remaining-usage exceedance, or equivalent billing
quota rejection:

- Set `used_this_month = monthly_quota`.
- Set derived `remaining = 0`.
- Set `active = false`.
- Update `last_used_at`.
- Preserve a bounded form of the provider error in `last_error`.
- Leave every profile from the failed actor run uncompleted, re-acquire the next
  eligible token, and recompute the sub-batch size from that token's remaining
  quota. The next token is not assumed to fit the failed token's original
  sub-batch.

This transition applies only to a confirmed account quota/billing exhaustion.
Network errors, timeouts, actor implementation errors, and temporary platform
failures must not zero the account quota. Authentication failures may exclude a
token for the current crawl and retain the error, but this design does not
reclassify them as quota exhaustion.

### Local pool cannot cover one profile

Do not throw away accumulated posts. Record a bounded partial diagnostic with
the group limit and count of unattempted profiles, then continue to any later
group whose lower limit may fit.

## Partial-Result Contract

`FacebookApifyCrawler` will retain its list-of-posts return contract to avoid an
unnecessary broad interface change. It will also expose a per-run report created
fresh at the start of `crawl_all()`. The report contains only operational
metadata:

- whether the crawl was partial;
- bounded error or exhaustion messages;
- completed and unattempted profile counts;
- successful actor-run count.

The CLI caller will import the returned posts normally, then use the report to:

- add an error count/diagnostic to crawl stats;
- finish `crawl_runs` with `status=partial` when at least one expected profile
  was not completed;
- keep `status=done` only when no partial condition occurred;
- continue the existing reprocess, image, notification, and cache steps when
  new records were imported.

Unexpected non-quota exceptions still propagate and mark the run `error`.
Provider quota exhaustion becomes partial only after all eligible tokens for the
pending work have been tried or the remaining local capacity cannot cover one
profile.

## Ordering and Fairness

This change preserves the existing profile-group and profile ordering. It does
not introduce a new business-priority model. Profiles already fetched in a
successful sub-batch are never repeated within the same daily crawl. Profiles
left unattempted remain eligible on their next scheduled day.

## Logging and Operations

Logs must show enough information to reconstruct allocation without exposing
tokens:

```text
[facebook-apify] Sub-batch limit=10/profile | profiles=21 | expected_max=210 | token=key ticivi
[facebook-apify] Token key X exhausted by provider; remaining=0; rotating
[facebook-apify] Partial group limit=10 | completed=24 | unattempted=3
```

Only the configured token label may be printed. Raw token values and unmasked
credentials remain prohibited.

Admin token-pool output continues to use masked secrets and should immediately
show a provider-exhausted account as inactive with zero remaining quota and the
bounded last error.

## Testing Strategy

Implementation will follow test-driven development. Required regression tests:

1. A 27-profile, limit-10 group is split across several tokens when no single
   token can cover 270 but aggregate capacity can.
2. Each actor run receives no more profiles than the selected token's tracked
   capacity permits.
3. A provider quota-exceed error sets that token to inactive, clamps remaining
   quota to zero, and re-plans the same unprocessed profiles against another
   token without marking them completed.
4. A transient non-quota error does not zero or deactivate the token.
5. Posts fetched by earlier sub-batches are returned and imported when a later
   group cannot be completed.
6. A partial crawl writes `crawl_runs.status=partial` with non-zero fetched/new
   counts rather than `error` with zeros.
7. An exhausted large-limit group does not prevent a later smaller-limit group
   from running.
8. Existing per-profile result clamping, incremental age filtering, token
   masking, and normal successful crawl behavior remain unchanged.

Focused verification will include at least:

```powershell
pytest tests/test_apify_token_pool.py tests/test_daily_crawl_limits.py -q
python -m py_compile crawler/apify_token_pool.py crawler/facebook_apify.py cli/crawlers.py
```

## Rollout and Recovery

After local tests pass, release follows the normal commit, push, deploy chain.
Production verification must separately confirm:

1. deployed SHA;
2. timer/service health;
3. masked token-pool state;
4. a Facebook crawl log showing more than one quota-aware sub-batch/token when
   necessary;
5. a `crawl_runs` row whose counts match imported data;
6. HTTP smoke for the dashboard/signals APIs after postprocessing.

The first production rerun is an explicit operational action, not part of the
code deployment itself. If it becomes partial, already imported data remains
valid and the run report identifies unattempted profiles for the next scheduled
or manually approved retry.
