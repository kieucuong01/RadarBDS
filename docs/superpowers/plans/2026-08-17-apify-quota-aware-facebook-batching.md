# Apify Quota-Aware Facebook Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split Facebook broker crawls into token-sized Apify actor runs, rotate accounts after confirmed quota exhaustion, and persist already fetched posts as a partial crawl when the full profile set cannot run.

**Architecture:** Keep `FacebookApifyCrawler.crawl_all()` as the single allocator and preserve its list-of-posts return type. It will choose one token at a time, size a whole-profile sub-batch from that token's tracked remaining quota, call the actor once, and expose a fresh per-run operational report; `cli/crawlers.py` will use that report when finishing `crawl_runs`.

**Tech Stack:** Python 3.12, Apify Python client, PostgreSQL repository wrappers, pytest, unittest.mock.

## Global Constraints

- Keep Facebook as the primary production source; do not alter Guland or re-enable BatDongSan.
- Preserve broker cadence, `daily_limit`, profile order, relevance filtering, normalization, deduplication, valuation, notifications, and image processing.
- Preserve the public `crawl_all()` list-of-posts return contract.
- Never split one broker profile across multiple tokens within the same daily crawl.
- A confirmed Apify quota/billing exhaustion must set `used_this_month = monthly_quota`, derived `remaining = 0`, `active = false`, update `last_used_at`, and retain a bounded `last_error`.
- Network failures, timeouts, and actor implementation failures must not zero or deactivate a token.
- A quota event that is recovered by another token is a warning, not automatically a partial crawl; `partial` means at least one due profile was not completed.
- Unexpected non-quota exceptions still propagate and finish the crawl run as `error`.
- Never log an unmasked Apify token.
- Do not modify or stage the unrelated `.playwright-cli/` worktree artifact.
- Do not push, deploy, or manually rerun production without separate user authorization.

---

## File Map

- `crawler/facebook_apify.py`: allocate quota-aware profile chunks, make one actor call with an explicitly selected token, rotate rejected tokens, and expose `last_run_report`.
- `crawler/apify_token_pool.py`: retain the existing token persistence rules; no schema change is required because `acquire_token()` already returns quota metadata and `mark_limit_exhausted()` already clamps/deactivates the token.
- `cli/crawlers.py`: import returned partial results and map the crawler report to `crawl_runs.status`, counts, and bounded diagnostics.
- `tests/test_apify_token_pool.py`: prove allocation, provider-exhaustion rotation, transient-error behavior, smaller-group continuation, per-profile clamping, and masking.
- `tests/test_daily_crawl_limits.py`: prove non-zero partial results are imported and persisted as `status=partial` while fatal write errors remain `status=error`.

---

### Task 1: Split same-limit profile groups by selected-token capacity

**Files:**
- Modify: `tests/test_apify_token_pool.py`
- Modify: `crawler/facebook_apify.py:171-316`

**Interfaces:**
- Consumes: `crawler.apify_token_pool.acquire_token(required_posts: int, exclude_ids: set[str] | None) -> dict`.
- Produces: `FacebookApifyCrawler.last_run_report: dict` with exact keys `partial`, `messages`, `completed_profiles`, `unattempted_profiles`, and `actor_runs`.
- Produces: `FacebookApifyCrawler._token_remaining(token_rec: dict) -> int`.
- Changes: `FacebookApifyCrawler._run_actor(run_input: dict, required_posts: int, token_rec: dict | None = None) -> list[dict]`.

- [ ] **Step 1: Add a failing allocation regression test**

Append this test to `tests/test_apify_token_pool.py`. It creates four limit-10 profiles while each token can cover only two complete profiles, proving the old single-270-style allocation is no longer used.

```python
def test_facebook_apify_splits_profile_group_by_token_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 25,
        "active": True,
    })
    pool.upsert_token({
        "label": "Key B",
        "token": "apify_api_BBBBBBBBBBBBB",
        "monthly_quota": 25,
        "active": True,
    })
    calls = []

    class FakeActor:
        def __init__(self, token):
            self.token = token

        def call(self, run_input):
            calls.append((self.token, run_input))
            return {
                "defaultDatasetId": self.token,
                "items": [
                    {
                        "id": f"post-{index}",
                        "text": "Ban dat Tan An",
                        "url": f"https://facebook.test/posts/{index}",
                        "timestamp": 1893456000,
                        "inputUrl": start["url"],
                    }
                    for index, start in enumerate(run_input["startUrls"], start=1)
                ],
            }

    class FakeDataset:
        def __init__(self, items):
            self.items = items

        def iterate_items(self):
            return list(self.items)

    class FakeClient:
        datasets = {}

        def __init__(self, token):
            self.token = token

        def actor(self, _actor_id):
            actor = FakeActor(self.token)
            original_call = actor.call

            def call(run_input):
                result = original_call(run_input)
                self.datasets[result["defaultDatasetId"]] = result["items"]
                return result

            actor.call = call
            return actor

        def dataset(self, dataset_id):
            return FakeDataset(self.datasets[dataset_id])

    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    crawler._client_cls = FakeClient
    crawler.actor = "apify/facebook-posts-scraper"

    posts = crawler.crawl_all(
        [
            {
                "url": f"https://facebook.com/broker-{index}",
                "tier": 10,
                "broker_name": f"Broker {index}",
                "default_area": "TDM",
            }
            for index in range(4)
        ],
        mode="incremental",
    )

    assert [len(call[1]["startUrls"]) for call in calls] == [2, 2]
    assert calls[0][0] != calls[1][0]
    assert len(posts) == 4
    assert crawler.last_run_report == {
        "partial": False,
        "messages": [],
        "completed_profiles": 4,
        "unattempted_profiles": 0,
        "actor_runs": 2,
    }
```

- [ ] **Step 2: Run the new test and confirm the old behavior fails**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_apify_token_pool.py::test_facebook_apify_splits_profile_group_by_token_capacity -q
```

Expected: FAIL because the current crawler asks `acquire_token()` to cover all 40 posts and does not expose `last_run_report`.

- [ ] **Step 3: Add the report and token-capacity helpers**

In `FacebookApifyCrawler`, initialize a fresh report at the start of every `crawl_all()` call and add the pure remaining-quota helper:

```python
    @staticmethod
    def _token_remaining(token_rec: dict) -> int:
        return max(
            0,
            int(token_rec.get("monthly_quota") or 0)
            - int(token_rec.get("used_this_month") or 0),
        )

    @staticmethod
    def _new_run_report() -> dict:
        return {
            "partial": False,
            "messages": [],
            "completed_profiles": 0,
            "unattempted_profiles": 0,
            "actor_runs": 0,
        }
```

At the beginning of `crawl_all()`:

```python
        self.last_run_report = self._new_run_report()
```

- [ ] **Step 4: Refactor `_run_actor()` to accept an explicitly selected token**

Keep the non-pool client path unchanged. For the pool path, use the passed token when present and retain the current acquire fallback for compatibility with direct callers:

```python
    def _run_actor(
        self,
        run_input: dict,
        required_posts: int,
        token_rec: Optional[dict] = None,
    ) -> list[dict]:
        if not self._use_token_pool:
            run = self._client.actor(self.actor).call(run_input=run_input)
            return list(self._client.dataset(run["defaultDatasetId"]).iterate_items())

        from crawler.apify_token_pool import (
            acquire_token,
            mark_error,
            mark_limit_exhausted,
            record_usage,
        )

        if token_rec is None:
            excluded: set[str] = set()
            last_error = None
            for _ in range(5):
                selected = acquire_token(
                    required_posts=required_posts,
                    exclude_ids=excluded,
                )
                try:
                    return self._run_actor(
                        run_input,
                        required_posts=required_posts,
                        token_rec=selected,
                    )
                except Exception as exc:
                    last_error = exc
                    message = str(exc)
                    if _is_apify_limit_error(message) or "401" in message or "Unauthorized" in message:
                        excluded.add(selected["id"])
                        continue
                    raise
            raise last_error or RuntimeError("Khong chon duoc APIFY_TOKEN kha dung.")

        selected = token_rec
        client = self._client_cls(selected["token"])
        try:
            run = client.actor(self.actor).call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            record_usage(selected["id"], len(items))
            return items
        except Exception as exc:
            message = str(exc)
            if _is_apify_limit_error(message):
                mark_limit_exhausted(selected["id"], message)
            else:
                mark_error(selected["id"], message)
            raise
```

- [ ] **Step 5: Allocate and process quota-sized sub-batches in `crawl_all()`**

For pool mode, replace the one-call-per-limit-group path with this queue. Keep the existing single call for non-pool mode. `unusable_token_ids` must be created before iterating `by_limit.items()` so a 401 token is not retried in a later group during the same crawl.

```python
        unusable_token_ids: set[str] = set()

        for per_profile, batch_profiles in by_limit.items():
            pending = list(batch_profiles)

            while pending:
                if not self._use_token_pool:
                    chunk = pending
                    token_rec = None
                else:
                    from crawler.apify_token_pool import acquire_token

                    token_rec = acquire_token(
                        required_posts=per_profile,
                        exclude_ids=unusable_token_ids,
                    )
                    if token_rec["id"] == "env":
                        chunk_size = len(pending)
                    else:
                        chunk_size = min(
                            len(pending),
                            self._token_remaining(token_rec) // per_profile,
                        )
                    chunk = pending[:chunk_size]

                expected_total = per_profile * len(chunk)
                run_input = {
                    "startUrls": [{"url": profile["url"]} for profile in chunk],
                    "resultsLimit": per_profile,
                }
                token_label = token_rec["label"] if token_rec else "APIFY_TOKEN"
                print(
                    f"[facebook-apify] Sub-batch limit={per_profile}/profile | "
                    f"profiles={len(chunk)} | expected_max={expected_total} | "
                    f"token={token_label}"
                )
                items = self._run_actor(
                    run_input,
                    required_posts=expected_total,
                    token_rec=token_rec,
                )
                limited_items = self._limit_items_per_profile(
                    items,
                    chunk,
                    per_profile,
                )
                for item, profile in limited_items:
                    post = self._adapt(item)
                    if post:
                        if profile:
                            post["default_area"] = profile.get("default_area")
                            post["broker_name"] = profile.get("broker_name")
                        adapted_all.append(post)

                pending = pending[len(chunk):]
                self.last_run_report["completed_profiles"] += len(chunk)
                self.last_run_report["actor_runs"] += 1
```

Retain the incremental 72-hour filter after all groups finish. Preserve the existing actor-overfetch clamp log for each sub-batch.

- [ ] **Step 6: Run the complete token-pool test file**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_apify_token_pool.py -q
```

Expected: all tests PASS. The optional `token_rec` path enables Task 1 allocation while the `token_rec=None` compatibility loop keeps the existing direct `_run_actor()` rotation tests green.

- [ ] **Step 7: Commit the allocation change**

```powershell
git add -- crawler/facebook_apify.py tests/test_apify_token_pool.py
git diff --cached --check
git commit -m "fix: split Facebook crawls by Apify token capacity"
```

---

### Task 2: Rotate provider-exhausted tokens and preserve partial groups

**Files:**
- Modify: `tests/test_apify_token_pool.py`
- Modify: `crawler/facebook_apify.py:196-316`

**Interfaces:**
- Consumes: Task 1's `last_run_report`, `_token_remaining()`, and explicit-token `_run_actor()`.
- Consumes: `_is_apify_limit_error(message: str) -> bool`, `mark_limit_exhausted(token_id, message)`, and `list_tokens_public()`.
- Produces: recovered quota events in `last_run_report["messages"]` without setting `partial` when all profiles complete.
- Produces: partial metadata when one or more profiles remain unattempted.

- [ ] **Step 1: Add a failing provider-exhaustion rotation test**

Add a test in which Key A can initially fit both profiles but Apify rejects it; Key B can fit only one profile per run. The assertions prove Key A becomes zero/inactive and Key B's smaller capacity causes the failed profiles to be re-planned rather than replaying the oversized chunk.

```python
def test_facebook_apify_exhausted_token_is_zeroed_and_profiles_are_replanned(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    key_a = pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 30,
        "active": True,
    })[0]["id"]
    pool.upsert_token({
        "label": "Key B",
        "token": "apify_api_BBBBBBBBBBBBB",
        "monthly_quota": 15,
        "active": True,
    })
    calls = []

    class FakeActor:
        def __init__(self, client):
            self.client = client

        def call(self, run_input):
            calls.append((self.client.token, len(run_input["startUrls"])))
            if self.client.token.endswith("AAAAAAAAAAAAA"):
                raise RuntimeError("Monthly usage hard limit exceeded")
            self.client.items = [
                {
                    "id": start["url"],
                    "text": "Ban dat Tan An",
                    "url": f"{start['url']}/posts/1",
                    "timestamp": 1893456000,
                    "inputUrl": start["url"],
                }
                for start in run_input["startUrls"]
            ]
            return {"defaultDatasetId": "dataset"}

    class FakeDataset:
        def __init__(self, client):
            self.client = client

        def iterate_items(self):
            return list(self.client.items)

    class FakeClient:
        def __init__(self, token):
            self.token = token
            self.items = []

        def actor(self, _actor_id):
            return FakeActor(self)

        def dataset(self, _dataset_id):
            return FakeDataset(self)

    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    crawler._client_cls = FakeClient
    crawler.actor = "apify/facebook-posts-scraper"
    profiles = [
        {"url": f"https://facebook.com/broker-{index}", "tier": 10}
        for index in range(2)
    ]

    posts = crawler.crawl_all(profiles, mode="incremental")
    token_a = next(item for item in pool.list_tokens_public() if item["id"] == key_a)

    assert calls == [
        ("apify_api_AAAAAAAAAAAAA", 2),
        ("apify_api_BBBBBBBBBBBBB", 1),
        ("apify_api_BBBBBBBBBBBBB", 1),
    ]
    assert len(posts) == 2
    assert token_a["used_this_month"] == token_a["monthly_quota"]
    assert token_a["remaining"] == 0
    assert token_a["active"] is False
    assert token_a["last_error"] == "Monthly usage hard limit exceeded"
    assert crawler.last_run_report["partial"] is False
    assert crawler.last_run_report["completed_profiles"] == 2
```

- [ ] **Step 2: Run the provider-exhaustion test and verify failure**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_apify_token_pool.py::test_facebook_apify_exhausted_token_is_zeroed_and_profiles_are_replanned -q
```

Expected: FAIL because Task 1's queue still propagates the quota exception instead of putting the profiles back and selecting Key B.

- [ ] **Step 3: Add quota/auth rotation around the actor call**

Wrap the Task 1 `_run_actor()` call inside the pending-profile loop. Do not remove profiles from `pending` until the actor succeeds.

```python
                try:
                    items = self._run_actor(
                        run_input,
                        required_posts=expected_total,
                        token_rec=token_rec,
                    )
                except Exception as exc:
                    message = str(exc)
                    if token_rec and _is_apify_limit_error(message):
                        unusable_token_ids.add(token_rec["id"])
                        event = f"Token {token_rec['label']} exhausted by provider; remaining=0; rotating"
                        self.last_run_report["messages"].append(event)
                        print(f"[facebook-apify] {event}")
                        continue
                    if token_rec and ("401" in message or "Unauthorized" in message):
                        unusable_token_ids.add(token_rec["id"])
                        event = f"Token {token_rec['label']} rejected authentication; rotating"
                        self.last_run_report["messages"].append(event)
                        print(f"[facebook-apify] {event}")
                        continue
                    raise
```

On the next loop iteration, `acquire_token()` selects another token and the chunk size is recalculated from that token's remaining quota.

- [ ] **Step 4: Run the provider-exhaustion test and existing limit-message tests**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_apify_token_pool.py::test_facebook_apify_exhausted_token_is_zeroed_and_profiles_are_replanned `
  tests\test_apify_token_pool.py::test_token_pool_marks_limit_error_as_exhausted_and_rotates `
  tests\test_apify_token_pool.py::test_facebook_apify_pool_treats_remaining_usage_error_as_exhausted -q
```

Expected: PASS. The new public-boundary test proves rotation/replanning, while both existing direct-call tests continue proving that monthly and remaining-usage messages clamp/deactivate the rejected token.

- [ ] **Step 5: Add a failing transient-error test**

Add `import pytest` at the top of `tests/test_apify_token_pool.py`, then append:

```python
def test_facebook_apify_transient_error_does_not_zero_token(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    token_id = pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 30,
        "active": True,
    })[0]["id"]

    class FakeActor:
        def call(self, run_input):
            raise RuntimeError("temporary network timeout")

    class FakeClient:
        def __init__(self, _token):
            pass

        def actor(self, _actor_id):
            return FakeActor()

    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    crawler._client_cls = FakeClient
    crawler.actor = "apify/facebook-posts-scraper"

    with pytest.raises(RuntimeError, match="temporary network timeout"):
        crawler.crawl_all(
            [{"url": "https://facebook.com/broker-a", "tier": 10}],
            mode="incremental",
        )

    token = next(item for item in pool.list_tokens_public() if item["id"] == token_id)
    assert token["used_this_month"] == 0
    assert token["remaining"] == 30
    assert token["active"] is True
    assert token["last_error"] == "temporary network timeout"
```

- [ ] **Step 6: Run the transient-error test**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_apify_token_pool.py::test_facebook_apify_transient_error_does_not_zero_token -q
```

Expected: PASS after Step 3 because `_run_actor()` calls `mark_error()` but the outer loop re-raises non-quota errors.

- [ ] **Step 7: Add a failing partial-group and smaller-group continuation test**

Use one token with 15 tracked posts. The first limit-10 profile succeeds and consumes 10 returned items, the second limit-10 profile cannot fit, and the later limit-5 profile must still run.

```python
def test_facebook_apify_preserves_partial_posts_and_runs_smaller_group(tmp_path, monkeypatch):
    monkeypatch.setattr(pool, "TOKEN_PATH", tmp_path / "apify_tokens.json")
    pool.upsert_token({
        "label": "Key A",
        "token": "apify_api_AAAAAAAAAAAAA",
        "monthly_quota": 15,
        "active": True,
    })
    calls = []

    class FakeActor:
        def __init__(self, client):
            self.client = client

        def call(self, run_input):
            calls.append((run_input["resultsLimit"], len(run_input["startUrls"])))
            self.client.items = []
            for start in run_input["startUrls"]:
                for index in range(run_input["resultsLimit"]):
                    self.client.items.append({
                        "id": f"{start['url']}-{index}",
                        "text": "Ban dat Tan An",
                        "url": f"{start['url']}/posts/{index}",
                        "timestamp": 1893456000,
                        "inputUrl": start["url"],
                    })
            return {"defaultDatasetId": "dataset"}

    class FakeDataset:
        def __init__(self, client):
            self.client = client

        def iterate_items(self):
            return list(self.client.items)

    class FakeClient:
        def __init__(self, _token):
            self.items = []

        def actor(self, _actor_id):
            return FakeActor(self)

        def dataset(self, _dataset_id):
            return FakeDataset(self)

    crawler = FacebookApifyCrawler.__new__(FacebookApifyCrawler)
    crawler._use_token_pool = True
    crawler._client_cls = FakeClient
    crawler.actor = "apify/facebook-posts-scraper"
    profiles = [
        {"url": "https://facebook.com/limit-10-a", "tier": 10},
        {"url": "https://facebook.com/limit-10-b", "tier": 10},
        {"url": "https://facebook.com/limit-5", "tier": 5},
    ]

    posts = crawler.crawl_all(profiles, mode="incremental")

    assert calls == [(10, 1), (5, 1)]
    assert len(posts) == 15
    assert crawler.last_run_report["partial"] is True
    assert crawler.last_run_report["completed_profiles"] == 2
    assert crawler.last_run_report["unattempted_profiles"] == 1
    assert any("limit=10" in message for message in crawler.last_run_report["messages"])
```

- [ ] **Step 8: Run the partial-group test and verify failure**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_apify_token_pool.py::test_facebook_apify_preserves_partial_posts_and_runs_smaller_group -q
```

Expected: FAIL because `acquire_token(required_posts=10)` still raises when only five tracked posts remain.

- [ ] **Step 9: Convert local capacity exhaustion into a bounded partial report**

Wrap only the `acquire_token()` call. Do not catch unrelated actor or parsing exceptions here.

```python
                    try:
                        token_rec = acquire_token(
                            required_posts=per_profile,
                            exclude_ids=unusable_token_ids,
                        )
                    except RuntimeError as exc:
                        unattempted = len(pending)
                        self.last_run_report["partial"] = True
                        self.last_run_report["unattempted_profiles"] += unattempted
                        event = f"limit={per_profile}: {unattempted} profile(s) unattempted: {exc}"
                        self.last_run_report["messages"].append(event)
                        print(f"[facebook-apify] Partial group {event}")
                        break
```

The `break` exits only the current group's `while pending` loop. The outer `for per_profile, batch_profiles in by_limit.items()` loop must continue to the smaller group.

- [ ] **Step 10: Run all token-pool crawler tests**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_apify_token_pool.py -q
```

Expected: all tests PASS, including masking, existing rotation, per-profile clamping, new quota-aware allocation, transient errors, and partial continuation.

- [ ] **Step 11: Commit provider rotation and partial preservation**

```powershell
git add -- crawler/facebook_apify.py tests/test_apify_token_pool.py
git diff --cached --check
git commit -m "fix: rotate exhausted Apify accounts safely"
```

---

### Task 3: Persist imported partial results in `crawl_runs`

**Files:**
- Modify: `tests/test_daily_crawl_limits.py:174-262`
- Modify: `cli/crawlers.py:112-266`

**Interfaces:**
- Consumes: Task 2's `FacebookApifyCrawler.last_run_report` exact keys.
- Produces: Facebook stats keys `errors: int`, `crawl_partial: bool`, and `crawl_messages: list[str]` in addition to existing counters.
- Produces: `crawl_runs.status=partial` and bounded `error_msg` only when one or more profiles were unattempted.

- [ ] **Step 1: Add a failing non-zero partial persistence test**

Add this test after `test_facebook_crawl_records_health_row`:

```python
def test_facebook_crawl_imports_partial_posts_and_records_partial_health():
    class _PartialFacebookCrawler:
        last_run_report = {
            "partial": True,
            "messages": ["limit=10: 3 profile(s) unattempted"],
            "completed_profiles": 24,
            "unattempted_profiles": 3,
            "actor_runs": 2,
        }

        def crawl_all(self, *_args, **_kwargs):
            return [{
                "url": "https://facebook.test/partial-1",
                "post_id": "partial-1",
                "text": "ban dat 100m2",
                "imgs": [],
            }]

    with mock.patch(
        "crawler.facebook_apify.FacebookApifyCrawler",
        return_value=_PartialFacebookCrawler(),
    ), mock.patch(
        "crawler.facebook_apify.load_profiles",
        return_value=[{"url": "https://facebook.test/a"}],
    ), mock.patch(
        "crawler.facebook_chrome.is_relevant",
        return_value=True,
    ), mock.patch(
        "crawler.facebook_chrome.build_record",
        return_value={
            "url": "https://facebook.test/partial-1",
            "post_id": "partial-1",
            "contact_phone": "",
            "imgs": [],
        },
    ), mock.patch(
        "config.area_profiles.post_mentions_other_city",
        return_value=False,
    ), mock.patch(
        "db.crawl_runs.start_crawl_run",
        return_value=123,
    ), mock.patch(
        "db.crawl_runs.finish_crawl_run",
    ) as finish_run, mock.patch.object(
        crawlers,
        "insert_raw_result",
        return_value=RawInsertResult("inserted", 456),
    ):
        stats = crawlers._facebook_crawl_to_raw(mode="incremental")

    assert stats["fetched"] == 1
    assert stats["inserted"] == 1
    assert stats["errors"] == 1
    assert stats["crawl_partial"] is True
    finish_run.assert_called_once_with(
        123,
        {"fetched": 1, "new": 1, "skipped": 0},
        status="partial",
        error_msg="limit=10: 3 profile(s) unattempted",
    )
```

- [ ] **Step 2: Run the partial persistence test and verify failure**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest tests\test_daily_crawl_limits.py::test_facebook_crawl_imports_partial_posts_and_records_partial_health -q
```

Expected: FAIL because the current CLI ignores `last_run_report`, omits `errors`, and finishes the row as `done`.

- [ ] **Step 3: Read and normalize the crawler report once**

Immediately after `crawl_all()` returns, normalize the report so test doubles and older callers without the attribute remain compatible:

```python
        raw_posts = crawler.crawl_all(
            profiles,
            mode=mode,
            limit_override=limit_override or None,
        )
        crawl_report = getattr(crawler, "last_run_report", {}) or {}
        crawl_partial = bool(crawl_report.get("partial"))
        crawl_messages = [
            str(message)[:240]
            for message in (crawl_report.get("messages") or [])
            if str(message).strip()
        ]
        partial_error = "; ".join(crawl_messages)[:500] or None
```

- [ ] **Step 4: Persist empty partial runs correctly**

Replace the current `if not raw_posts` branch with:

```python
    if not raw_posts:
        print("[facebook] Khong co bai nao tu Apify (kiem tra profile URL va APIFY_TOKEN).")
        stats = {
            "fetched": 0,
            "inserted": 0,
            "skipped": 0,
            "irrelevant": 0,
            "out_of_area": 0,
            "range_filtered": 0,
            "errors": 1 if crawl_partial else 0,
            "crawl_partial": crawl_partial,
            "crawl_messages": crawl_messages,
        }
        finish_crawl_run(
            run_id,
            {"fetched": 0, "new": 0},
            status="partial" if crawl_partial else "done",
            error_msg=partial_error if crawl_partial else None,
        )
        return stats
```

- [ ] **Step 5: Add report fields and status to the non-empty finish path**

Extend the existing `stats` mapping and final `finish_crawl_run()` call:

```python
    stats = {
        "fetched": len(raw_posts),
        "inserted": inserted,
        "skipped": skipped,
        "irrelevant": irrelevant,
        "inserted_raw_ids": inserted_raw_ids,
        "refreshed_images": refreshed_images,
        "refreshed_raw_ids": refreshed_raw_ids,
        "out_of_area": out_of_area,
        "range_filtered": range_filtered,
        "errors": 1 if crawl_partial else 0,
        "crawl_partial": crawl_partial,
        "crawl_messages": crawl_messages,
    }
    finish_crawl_run(
        run_id,
        {
            "fetched": stats["fetched"],
            "new": inserted + refreshed_images,
            "skipped": skipped + irrelevant + out_of_area + range_filtered,
        },
        status="partial" if crawl_partial else "done",
        error_msg=partial_error if crawl_partial else None,
    )
```

Update `test_facebook_crawl_records_health_row` to expect explicit `status="done"` and `error_msg=None`. Keep `test_facebook_crawl_propagates_raw_insert_failure` unchanged so it continues proving a database write error is fatal.

- [ ] **Step 6: Run daily-crawl health tests**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_daily_crawl_limits.py::test_facebook_crawl_records_health_row `
  tests\test_daily_crawl_limits.py::test_facebook_crawl_imports_partial_posts_and_records_partial_health `
  tests\test_daily_crawl_limits.py::test_facebook_crawl_propagates_raw_insert_failure -q
```

Expected: all three PASS; successful runs are `done`, quota-limited results are imported and `partial`, and raw insert failures remain `error`.

- [ ] **Step 7: Run the complete focused crawl test set**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_apify_token_pool.py `
  tests\test_daily_crawl_limits.py `
  tests\test_ops_alert.py -q
```

Expected: all tests PASS with no warnings or unexpected output.

- [ ] **Step 8: Commit partial health persistence**

```powershell
git add -- cli/crawlers.py tests/test_daily_crawl_limits.py
git diff --cached --check
git commit -m "fix: persist partial Facebook crawl results"
```

---

### Task 4: Verify the implementation and prepare a release handoff

**Files:**
- Verify: `crawler/apify_token_pool.py`
- Verify: `crawler/facebook_apify.py`
- Verify: `cli/crawlers.py`
- Verify: `tests/test_apify_token_pool.py`
- Verify: `tests/test_daily_crawl_limits.py`
- Verify: `tests/test_ops_alert.py`

**Interfaces:**
- Consumes: all code and tests from Tasks 1-3.
- Produces: local verification evidence and a clean, scoped commit range ready for a separately authorized push/deploy.

- [ ] **Step 1: Compile all changed Python modules**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m py_compile `
  crawler\apify_token_pool.py `
  crawler\facebook_apify.py `
  cli\crawlers.py
```

Expected: exit code 0 and no output.

- [ ] **Step 2: Run the focused regression suite once more from a clean process**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 -m pytest `
  tests\test_apify_token_pool.py `
  tests\test_daily_crawl_limits.py `
  tests\test_ops_alert.py -q
```

Expected: all tests PASS.

- [ ] **Step 3: Refresh Graphify structural evidence**

Run:

```powershell
graphify update .
```

Expected: the graph refresh completes. If the known Windows wrapper failure reports `Access is denied` or `uv trampoline failed to canonicalize script path`, record that exact tooling failure in the handoff and rely on direct source plus pytest/py_compile evidence; do not claim Graphify was refreshed.

- [ ] **Step 4: Audit the final diff and repository scope**

Run:

```powershell
git diff --check HEAD~3 HEAD
git status --short
git log -4 --oneline
```

Expected: no diff-check errors; only the three scoped implementation commits follow the already committed design/plan documents; `.playwright-cli/` remains untracked and unstaged.

- [ ] **Step 5: Report the local handoff and stop before external mutations**

Report:

```text
Local implementation complete.
- Allocation: large same-limit groups split by per-token remaining quota.
- Rotation: confirmed Apify quota exhaustion sets remaining=0 and active=false, then replans profiles on the next token.
- Partial safety: fetched posts import normally and crawl_runs records partial with non-zero counts.
- Verification: py_compile and focused pytest results.
- Git: exact commit SHAs and remaining unrelated worktree entries.
Push, deploy, and a manual production rerun still require explicit authorization.
```
