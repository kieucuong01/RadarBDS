# Browser-use Social Ops for Radar BDS

This document explains the safe setup for using `browser-use` as a Radar BDS social-ops assistant.

Use cases:

1. Assist posting Radar BDS content to selected BĐS Facebook groups.
2. Discover reputable brokers to invite into the Radar BDS ecosystem.
3. Fallback listing collection from approved broker profiles/pages if Apify is limited.
4. Monitor social trends and feed ideas into `/tin-tuc` SEO/social content.

## Current local install on VPS

`browser-use` is installed outside the production app venv so it cannot break `radar-bds.service`.

| Item | Path / value |
|---|---|
| Browser-use venv | `/home/hermesops/radar-browser-use/.venv` |
| CLI | `/home/hermesops/radar-browser-use/.venv/bin/browser-use` |
| Version installed | `browser-use==0.13.6` |
| Chrome profile | `/home/hermesops/.browser-profiles/radar-social/chrome-profile` |
| CDP URL | `http://127.0.0.1:9224` |
| Start script | `/home/hermesops/radar-browser-use/start-radar-social-browser.sh` |
| Runtime logs | `/home/hermesops/radar-browser-use/logs/` |

Start the dedicated browser worker:

```bash
/home/hermesops/radar-browser-use/start-radar-social-browser.sh
```

In Hermes, this should be started as a long-running background process. Smoke-test it with:

```bash
BU_CDP_URL=http://127.0.0.1:9224 \
  /home/hermesops/radar-browser-use/.venv/bin/browser-use <<'PY'
new_tab('https://example.com')
wait_for_load()
print(page_info())
PY
```

Expected result includes:

```text
url: https://example.com/
title: Example Domain
```


## Optimized social-care workflow

For the queue-first daily operating model, use `docs/social-care-workflow.md`.

Core scripts:

| Purpose | Script |
|---|---|
| Create deterministic social queue JSON from `/tin-tuc` | `scripts/radar_social_queue.py` |
| Dry-run/prepare/publish Page post with browser-use | `scripts/browser_use_page_post.py` |
| Cron-safe latest article auto-post wrapper | `scripts/radar_social_auto_post.py` |

Recommended flow:

```bash
cd /opt/radar-bds/current
python3 scripts/radar_social_queue.py --slug latest --mode review
python3 scripts/browser_use_page_post.py --queue /opt/radar-bds/var/social_queue/<file>.json --mode dry-run
# Manual publish if needed:
python3 scripts/browser_use_page_post.py --queue /opt/radar-bds/var/social_queue/<file>.json --mode publish --yes

# Current approved auto-post wrapper:
python3 scripts/radar_social_auto_post.py
```

Do not use repeated manual accessibility-tree inspection for normal Page posting; it wastes tokens. Use the queue + script path instead.

## What browser-use should and should not do

| Area | Allowed | Not allowed by default |
|---|---|---|
| Group marketing | Draft/schedule/assist posts to whitelisted groups | Spam many groups or repeat identical templates |
| Broker discovery | Read public profiles/pages/groups and score candidates | Add brokers automatically as trusted without review |
| Listing fallback | Collect posts from approved broker sources slowly | Mass scrape Facebook broadly or bypass platform protections |
| Trend monitoring | Summarize public social trends and content ideas | Collect private data or attempt to bypass access controls |
| Page operations | Prepare draft, verify preview, screenshot | Store password or auto-handle 2FA/captcha/checkpoints |

## Safe Facebook login policy

Do **not** store Facebook password, 2FA secret, recovery codes, or cookies in Git, chat, logs, memory, or env files.

Recommended account setup:

1. Create/use a dedicated Facebook account for Radar BDS operations, not anh Cường's primary personal account.
2. Add that account to the Radar BDS Page with the minimum needed role/task, normally content creation only.
3. Enable 2FA on that account.
4. Login manually once in the dedicated Chrome profile.
5. Keep automation in draft/review mode until it has proven safe.

## Login steps for anh Cường

### Option A — safest for Facebook account health

Run browser-use on a local computer/laptop with a normal residential IP and a dedicated Chrome profile. This reduces checkpoint risk compared with a datacenter VPS IP.

1. Install `browser-use` locally in a separate venv.
2. Launch Chrome with a separate profile and remote debugging.
3. Login to Facebook manually.
4. Grant the account only the Page/group permissions needed.
5. Use browser-use for draft/review tasks, not high-volume posting.

### Option B — VPS profile, only after explicit approval

Use this when anh accepts higher checkpoint risk from a datacenter IP. The VPS already has:

```text
/home/hermesops/.browser-profiles/radar-social/chrome-profile
```

Recommended safe process:

1. Start the dedicated browser worker.
2. Open an interactive viewing method (temporary VNC/noVNC/Chrome remote workflow) to that profile.
3. Anh logs in manually.
4. If Facebook asks for 2FA/checkpoint/captcha, anh handles it manually.
5. The agent must stop after login and report status; it must not save secrets.
6. After login, use only whitelisted, low-frequency tasks.

If Facebook presents a checkpoint/captcha during automation, stop immediately and notify anh. Do not try to bypass it.

## Group posting workflow

Use a queue, not ad-hoc prompts.

```text
Daily SEO article
  -> social_queue JSON
  -> browser-use opens whitelisted group
  -> verifies group name/URL
  -> fills post text + link
  -> screenshot preview
  -> stops for review or schedules if pre-approved
  -> writes run log
```

Suggested files for future implementation:

```text
data/social_targets/groups.json
data/social_queue/YYYY-MM-DD-topic.json
data/browser_use_runs/YYYY-MM-DD-run.json
```

Group target shape:

```json
{
  "name": "Nhà đất Bình Dương ...",
  "url": "https://www.facebook.com/groups/...",
  "allowed_frequency": "2/week",
  "allow_link": true,
  "requires_review": true,
  "notes": "Prefer data posts, no direct selling tone"
}
```

## Broker discovery workflow

Browser-use can collect public broker candidates and score them for review.

Score candidate brokers by:

| Signal | Why it matters |
|---|---|
| Public posts are frequent but not spammy | Active but less likely low-quality spam |
| Posts include price, area, ward, images | Data quality useful for Radar |
| Focus area is consistent | Easier to map to Radar wards |
| Comments are not mostly complaints | Trust quality |
| Phone/Zalo/contact is public | Possible partner/contact path |
| Listings are not mostly duplicate/bait | Lower ingestion noise |

Human review is required before a broker becomes `approved`.

## Broker-specific listing fallback

Use only approved broker sources and low rate limits.

Suggested limits:

```text
10–30 approved brokers/day
3–10 newest posts/source
random pauses
stop on checkpoint/captcha
```

Pipeline:

```text
approved broker source
  -> browser-use reads public posts
  -> extract raw post text/images/link
  -> save raw staging record
  -> existing Radar dedup/normalization/review pipeline
  -> only then create/update listings
```

Never treat browser-use scraped posts as trusted listings without the normal Radar quality gates.

## Trend monitoring workflow

Run weekly/daily read-only monitoring for public groups/pages:

- high-frequency wards/areas mentioned
- repeated buyer questions
- price-drop/cut-loss language
- KCN/Mỹ Phước/Bến Cát narratives
- posts with strong engagement
- content angles for `/tin-tuc`

Output:

```text
Top trends
Evidence URLs
Suggested SEO/social topics
Risks/claims that need source verification
```

## Production guardrails

- Keep browser-use venv separate from `/opt/radar-bds/.venv`.
- Do not commit browser profile, screenshots containing private account data, cookies, or run logs with PII.
- Start in read-only/draft-only mode.
- Default group posting requires human review.
- No captcha/checkpoint bypass.
- No high-volume group posting.
- No private data collection.
- Use Meta Pages API for official Page publishing when possible; browser-use is for UI workflows and social intelligence.

## Verification checklist before enabling real Facebook tasks

- [ ] Browser worker starts and CDP endpoint is reachable.
- [ ] Smoke test opens a public site successfully.
- [ ] Dedicated Chrome profile has correct permissions (`chmod 700`).
- [ ] Anh has approved the Facebook account/profile approach.
- [ ] Group target allowlist exists.
- [ ] Posting mode is `draft` or `review`, not `publish`.
- [ ] Logs and screenshots are stored outside Git and scrubbed before sharing.
