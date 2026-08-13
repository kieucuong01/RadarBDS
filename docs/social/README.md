# Radar BDS Social Automation Map

This file is the first stop for `@rb` Facebook social tasks. Goal: avoid rediscovering scripts/config and avoid over-engineering.

## Quick rule split

| Surface | Acting identity | Cadence | Content rule |
|---|---|---:|---|
| Facebook Page Care | Radar BDS | Mon-Fri 18:40, max 1 verified post/day | Publish one Radar BDS article with varied caption style, verified native visual, then a Radar BDS self-comment link. Link preview, avatar, logo, or draft is not a successful visual post. |
| Facebook group post | Radar BDS | Tue/Fri 19:30, capped by code | Must show Radar BDS value: data, tracked listings, signals, price/m², ward filters, comparisons. No generic BĐS knowledge posts. |
| Comment seeding | Tiny Sudo | 10:30 / 15:30 / 20:30 daily, capped by code | Contextual/flexible. Can use educational content if it answers the post. No spam/trùng post/author/topic. |

Always restore/check identity to **Radar BDS** after any Tiny Sudo action.

## Cron jobs

| Job | Schedule | Script wrapper |
|---|---:|---|
| `@rb Facebook Page Care — 5 posts/week` | `40 18 * * 1-5` | `~/.hermes/profiles/portfolio-ops/scripts/rb_page_care_autopost.sh` |
| `@rb controlled Facebook group auto-post` | `30 19 * * 2,5` | `~/.hermes/profiles/portfolio-ops/scripts/radar_group_auto_post_cron.sh` |
| `@rb Facebook comment seeding 3/day` | `30 10,15,20 * * *` | `~/.hermes/profiles/portfolio-ops/scripts/radar_public_post_comment_scheduler.sh` |

All three are script-only cron jobs (`no_agent=True`). Empty stdout means silent skip.

## Repo files

| Purpose | Path |
|---|---|
| Page Care scheduler | `scripts/radar_social_auto_post.py` |
| Page Care browser executor | `scripts/browser_use_page_post.py` |
| Page Care state | `/opt/radar-bds/var/social_queue/posted_slugs.json` |
| Group post scheduler | `scripts/radar_group_auto_post.py` |
| Group post browser executor | `scripts/browser_use_group_post.py` |
| Group post targets | `config/social_group_targets.json` |
| Group post state | `/opt/radar-bds/var/social_queue/group-autopost/state.json` |
| Comment seeding scheduler | `scripts/radar_group_comment_seed.py` |
| Comment browser executor | `scripts/browser_use_group_comment.py` |
| Comment targets/pages/groups | `config/social_group_comment_targets.json` |
| Comment state | `/opt/radar-bds/var/social_queue/public-post-comment/state.json` |
| Browser supervisor | `radar-social-browser.service` (systemd, user `hermesops`, `Restart=always`) |
| Browser health wrapper | `~/.hermes/profiles/portfolio-ops/scripts/ensure_radar_social_browser.sh` |

## Reliability and truth gates

- The authenticated Chrome profile is launched only by `radar-social-browser.service` as `hermesops`. Repo Python running as `radar` connects to CDP `127.0.0.1:9224` and fails clearly if it is unavailable; it must not spawn the browser.
- Page Care is successful only when `verified_text=true`, `verified_visual=true`, `verified_comment=true`, the post has a real Facebook permalink, the self-comment contains a Radar BDS link, and the native image has a `/photo` or `/photo.php` permalink.
- Page Care daily cap reads both current flat proof fields and legacy/production evidence nested under `browser_result`. A recovery rerun must return `already posted today` without changing `posted_slugs.json`.
- Page uploads and group uploads require `img[src^="blob:"]` in the same caption composer. Generic `<img>` elements are avatars/link previews and do not count. Poll for up to 20 seconds instead of using a fixed sleep.
- Never press blanket `Escape` after typing Page hashtags: current Facebook UI may close the composer into an unpublished inline draft.
- Group `pending admin approval` is a successful submission state, not a public publish. Checkpoint/captcha/login/identity/CDP/permission/traceback failures must exit nonzero, not `SKIP`.

## Current known targets

### Group posts

- `reviewbatdongsanaz` / REVIEW BẤT ĐỘNG SẢN
  - enabled
  - max 2 posts/week
  - min gap 72h
  - pilot permalink worked: `https://www.facebook.com/groups/2458568224213476/permalink/36879677055009153/`

### Comment seeding groups/pages

- `bdsbd247` — accepted a rendered Radar link comment on 2026-07-26.
- `reviewbatdongsanaz` — BĐS review group; contextual comments OK.
- `CoVanTaichinhVietnam` — finance group; comment only on genuinely BĐS/land-related posts.
- `24hbinhduong.vn` — public Page, not group; comment source only.

## Minimum action workflows

### Add a new seeding/comment target

1. Resolve share URL in browser.
2. Classify: group vs page vs post.
3. Add only the right allowlist:
   - group/page comment source → `config/social_group_comment_targets.json`
   - group post target → `config/social_group_targets.json`
4. `python3 -m json.tool <config>`.
5. If no code changed, do not run broad tests.

### Try a real group post

1. Dry-run/queue only if needed.
2. Run prepare first.
3. Inspect screenshot: correct group, caption + image same composer, Post enabled, no warning.
4. Publish once only.
5. Verify permalink or explicit pending evidence.
6. Record/report status briefly.

### Try a real comment

1. Candidate must pass relevance, enabled ward/link, broker exclusion, cooldown.
2. Publish once only.
3. Verify rendered comment permalink with `comment_id`/`reply_comment_id`.
4. Restore/check Radar BDS identity.

## 80/20 test policy

| Change | Check |
|---|---|
| JSON config only | `python3 -m json.tool` |
| Page Care logic | targeted `test_radar_social_auto_post.py` + `test_browser_use_page_post.py` |
| Group/comment logic | targeted `test_radar_group_comment_seed.py` + `test_radar_group_auto_post.py` |
| Cron schedule | `cronjob list` after update |
| Page recovery rerun | production-shaped daily-cap test → wrapper safe no-op → unchanged state checksum/count → cron output `already posted today` |
| Live Facebook action | screenshot + permalink/native-photo/status + identity restore |

Do not run broad test suites for docs/config-only changes.

## Stop conditions

Abort and report instead of retrying blindly on:

- checkpoint/captcha/account restriction
- identity mismatch that cannot be restored
- composer ambiguity/stale dialog
- Facebook `Declined`, `Posting...` stuck, or missing permalink evidence
- group rule warning about link/sales spam
- browser scan timeout after one narrow retry
