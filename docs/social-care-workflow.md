# Radar BDS — Social Care Workflow

This is the operating workflow for caring for Radar BDS social channels with low token cost and safe browser-use automation.

## Goal

Turn every Radar BDS data asset into a measurable social action:

```text
Radar data / /tin-tuc / /bao-cao
  -> social queue JSON
  -> Page/group draft or publish
  -> screenshot + run log
  -> weekly learnings feed SEO + product
```

## 80/20 operating model

| Layer | Owner | Frequency | Tooling | Notes |
|---|---|---:|---|---|
| SEO article/social atom | Hermes daily cron | Daily | `docs/daily_seo_publisher.md` | Publish/refresh `/tin-tuc`, then create social queue item |
| Facebook Page post | Browser-use worker | Daily or review mode | `scripts/browser_use_page_post.py` | Can publish if approved; otherwise prepare/screenshot |
| Group distribution | Browser-use worker + human approval | 2–5x/week | future group queue | Whitelisted groups only; no spam |
| Broker discovery | Browser-use read-only | Weekly | future broker script | Collect candidates; human review before approval |
| Trend monitoring | Browser-use read-only | Weekly | future trend script | Feed SEO/social topic choices |
| Measurement | Hermes report | Weekly | nginx/Facebook UI/GSC later | Keep to 3 actions max |

## Token budget principle

Do not ask an LLM to inspect Facebook UI repeatedly. Use scripts.

| Workflow | Expected tokens/action | Notes |
|---|---:|---|
| Manual browser-use exploration | 18k–45k | Only for first-time UI discovery |
| Scripted Page post with queue | 2.5k–8k | Normal path |
| Queue creation only | <1k | Deterministic script; no LLM needed |
| Meta API Page post | <1.5k | Future official path if token/API is configured |

## Queue-first workflow

Create a queue item from the latest `/tin-tuc` article:

```bash
cd /opt/radar-bds/current
python3 scripts/radar_social_queue.py --slug latest --mode review
```

Dry-run without writing:

```bash
python3 scripts/radar_social_queue.py --slug latest --mode review --dry-run
```

Default queue location:

```text
/opt/radar-bds/var/social_queue/
```

Queue schema summary:

```json
{
  "schema": "radar_social_queue.v1",
  "source": {"slug": "...", "url": "https://radarbds.vn/tin-tuc/..."},
  "target": {"platform": "facebook", "surface": "page", "mode": "review"},
  "content": {"message": "...", "link": "..."},
  "guards": {"stop_on_checkpoint": true, "no_group_spam": true}
}
```


## Facebook Page copy standard

Agency `social-media-strategist` audited the first auto-post template and scored it **6.5/10**: safe and data-driven, but too much like an RSS announcement. The queue script now uses Facebook-native deterministic variants instead of the old `Bài mới trên Radar BDS...` hook.

Current encoded rules in `scripts/radar_social_queue.py`:

- Use 3 rotating variants by `sha1(slug) % 3`: `data_first`, `problem_first`, `signal_first`.
- Start with local data or buyer problem, not with “Bài mới”.
- Render prices as **“giá rao trung vị”**.
- Prioritize these facts: listing count, đất nền median, nhà đất median, `tin có dấu hiệu đáng kiểm tra`.
- CTA in the status itself for data-like posts: “Vào radarbds.vn → lọc phường <ward> để xem từng tin đang rao”. Use a ward-filtered `radarbds.vn` URL first, then the article/report URL if useful.
- Append UTM: article links use `utm_source=facebook&utm_medium=organic&utm_campaign=daily_article&utm_content=<slug>`; ward-filter links use `utm_campaign=ward_filter&utm_content=<slug>-ward-filter`.
- Use max 3 hashtags, normally `#RadarBDS #BinhDuong #<WardNoAccent>`.
- Hard-block hype/compliance-risk phrases: `deal ngon`, `lời chắc`, `cam kết lợi nhuận`, `sinh lời`, `cơ hội vàng`, `rẻ nhất`, `dưới giá thị trường`, `hot nhất`, `sốt đất`.

Default data-first shape:

```text
Giá rao {phường} 14 ngày qua có {số_tin} tin Radar đang theo dõi.

• Đất nền: giá rao trung vị {giá_đất_nền}
• Nhà đất: giá rao trung vị {giá_nhà_đất}
• {số_tin} tin có dấu hiệu đáng kiểm tra

Đừng gộp 2 loại hình khi so giá.

Vào radarbds.vn → lọc phường {phường} để xem từng tin đang rao:
{ward_filter_url_utm}

Bài phân tích dữ liệu:
{article_url_utm}

#RadarBDS #BinhDuong #{PhuongKhongDau}
```

## Facebook Page posting

Dry-run a queue item:

```bash
python3 scripts/browser_use_page_post.py \
  --queue /opt/radar-bds/var/social_queue/<file>.json \
  --mode dry-run
```

Prepare a post in the composer and stop for review/screenshot:

```bash
python3 scripts/browser_use_page_post.py \
  --queue /opt/radar-bds/var/social_queue/<file>.json \
  --mode prepare
```

Publish only after explicit approval:

```bash
python3 scripts/browser_use_page_post.py \
  --queue /opt/radar-bds/var/social_queue/<file>.json \
  --mode publish --yes
```

Runtime outputs:

| Output | Path |
|---|---|
| Screenshot | `/home/hermesops/radar-browser-use/artifacts/` |
| Run log | `/opt/radar-bds/var/browser_use_runs/` |

## Auto-post mode

Anh Cường approved temporary auto-posting while the user base is still small. The cron-safe wrapper is:

```bash
/opt/radar-bds/current/scripts/radar_social_auto_post.py
```

It does all of the following without LLM/UI exploration:

1. Ensure the dedicated Radar Social Chrome/CDP worker is reachable.
2. Create a publish-mode queue item from the latest `/tin-tuc` article.
3. Publish it to the Radar BDS Facebook Page via `scripts/browser_use_page_post.py --mode publish --yes`.
4. Record `slug:article_date` in `/opt/radar-bds/var/social_queue/posted_slugs.json` to avoid duplicate reposts.

Hermes cron:

```text
@rb Daily Social Auto Post
schedule: 40 18 * * *
mode: no_agent=true
script: /opt/radar-bds/current/scripts/radar_social_auto_post.py
```

If Facebook shows checkpoint/captcha/login wall, the script fails loudly and the cron delivers the error; do not bypass it automatically.

## Daily cron behavior

The `@rb Daily SEO Publish + Social Post` cron should:

1. Publish or refresh one `/tin-tuc` asset.
2. Create a social queue item using `scripts/radar_social_queue.py`.
3. If Page publish is explicitly enabled for that day, run `scripts/browser_use_page_post.py --mode publish --yes`.
4. Otherwise include the queue file + social draft in Telegram.
5. Never open public noVNC during cron; noVNC is only for manual login/recovery.

Default mode remains **review**, not publish, unless anh asks to auto-post.

## Group posting rules

Group posting is higher risk than Page posting. Before enabling it:

- Maintain a whitelist of groups.
- Store per-group frequency limits.
- Use varied, useful data posts instead of repetitive link drops.
- Screenshot preview before post.
- Default `requires_review=true`.
- Stop on checkpoint/captcha.

Suggested target file for future implementation:

```text
/opt/radar-bds/var/social_targets/groups.json
```

## Broker discovery rules

Browser-use can read public groups/pages/profiles to produce broker candidates, but it must not automatically approve them.

Candidate scoring:

| Signal | Score use |
|---|---|
| Posts include price/area/ward/image | Data quality |
| Focus area is consistent | Useful Radar source |
| Engagement looks real | Trust signal |
| Complaint/spam comments | Negative signal |
| Contact is public | Outreach feasibility |
| Duplicate/bait pattern | Negative signal |

Human review converts `candidate` -> `approved`.

## Trend monitoring rules

Trend monitor should output:

```text
Top social trends
Evidence URLs
Suggested /tin-tuc topics
Suggested social posts
Claims requiring verification
```

Use trends to inform the 90-day SEO roadmap, not to chase every viral post.

## Safety guardrails

- Do not store Facebook password, 2FA, recovery codes, cookies, or screenshots with secrets in Git/chat/memory.
- Browser profile stays under `/home/hermesops/.browser-profiles/radar-social/chrome-profile`.
- Public noVNC links are temporary login/recovery only and must be killed after use.
- If Facebook shows checkpoint/captcha, stop and notify anh.
- Do not spam groups.
- Do not scrape private or access-controlled data.
- Do not bypass platform protections.
- Keep browser-use separate from `/opt/radar-bds/.venv`.

## Verification checklist

After a Page post action:

- [ ] Queue JSON created and references a live source URL.
- [ ] Correct Page URL was opened.
- [ ] Message text or link preview appeared in composer.
- [ ] If published, distinctive text appears on Page timeline.
- [ ] Screenshot saved.
- [ ] Run log saved.
- [ ] noVNC public port is closed if it was opened manually.
- [ ] Telegram report includes URL, queue path, screenshot path, and status.
