# Radar BDS — Broker Discovery MVP

This runbook packages the broker-discovery system for finding data-rich Facebook real-estate brokers without hardcoding target areas into code.

## Goal

Find brokers who can improve Radar BDS data density in under-covered wards/cities.

A good broker for Radar BDS means a **good public data source**, not a legal guarantee:

- Most posts include clear price, area, ward/city, and property type.
- Posts are concentrated in one city/market instead of spread across many provinces.
- Posting rhythm is steady, not only burst spam.
- Real property photos are positive; title-book/cadastral/document photos are a strong internal review signal.
- Broker is manually reviewed before being added to approved crawl/follow config.

## Config-driven target areas

Do not hardcode target wards/cities in scripts. Current targets are campaign config only:

```text
config/broker_discovery_targets.json
```

Current priority:

| City | Priority wards |
|---|---|
| Thủ Dầu Một | Hòa Phú, Phú Cường |
| Bến Cát | Mỹ Phước, Tân Định, An Điền, An Tây, Thới Hòa, Hòa Lợi, Phú An, Chánh Phú Hòa |

Future expansion should only update config/aliases, for example:

```json
{
  "city": "Dĩ An",
  "aliases": ["Di An", "Dĩ An"],
  "priority_wards": [
    {"name": "Tân Đông Hiệp", "aliases": ["Tan Dong Hiep"]}
  ]
}
```

Same pattern applies to Thuận An, Tân Uyên, or any future city/ward.

## Files

| File | Purpose |
|---|---|
| `config/broker_discovery_targets.json` | Campaign target areas + aliases |
| `scripts/radar_broker_discovery.py` | Score collected public posts and broker candidates |
| `tests/test_broker_discovery.py` | Config-driven scoring tests |
| `/opt/radar-bds/var/broker_discovery/` | Runtime outputs; not committed |

## Input format

`score` accepts either a JSON array or `{ "posts": [...] }`.

Required/minimal fields:

```json
{
  "post_url": "https://facebook.com/groups/.../posts/...",
  "author_url": "https://facebook.com/profile-or-page",
  "author_name": "Broker name",
  "group_url": "https://facebook.com/groups/...",
  "text": "Bán đất Hòa Phú 100m2 giá 2.8 tỷ...",
  "posted_at": "2026-07-21T10:00:00+07:00",
  "image_labels": ["real_property_photo", "title_book_or_document"]
}
```

`image_labels` are optional. Supported useful labels:

```text
real_property_photo
street_photo
map_screenshot
cadastral_map
title_book_or_document
stock_or_reused_image
unclear_image
```

Do not publish document/title-book images. Treat them only as an internal quality signal and manual-review trigger.

## Commands

Print group search keywords from current config:

```bash
cd /opt/radar-bds/current
scripts/radar_broker_discovery.py keywords --config config/broker_discovery_targets.json
```

Score collected posts:

```bash
scripts/radar_broker_discovery.py score \
  --config config/broker_discovery_targets.json \
  --posts /opt/radar-bds/var/broker_discovery/candidate_posts.json \
  --out /opt/radar-bds/var/broker_discovery/broker_scores.json
```

Render a Markdown review report:

```bash
scripts/radar_broker_discovery.py report \
  --scores /opt/radar-bds/var/broker_discovery/broker_scores.json \
  --out /opt/radar-bds/var/broker_discovery/broker-report.md
```

Run focused tests:

```bash
python3 -m unittest tests.test_broker_discovery -v
```

## Scoring overview

### Post quality score

| Component | Points |
|---|---:|
| Price present | 15 |
| Area present | 12 |
| Target ward/city match | 15 |
| Property type clear | 8 |
| Price/m² possible | 8 |
| Location detail: road/KDC/frontage/dimensions | 8 |
| Real property image | 8 |
| Legal/document text or image | 10 |
| Current campaign priority area | 10 |
| Phone/contact | 4 |
| Non-empty content | 2 |

Penalties:

- `inbox` without price.
- hype/compliance-risk words: `siêu phẩm`, `cơ hội vàng`, `bao lời`, `cam kết lời`, `lời chắc`, `sốt đất`, `hot nhất`, `rẻ nhất`.
- missing both price and area.

Price completeness rule from anh Cường:

- Accept prices missing only tens of millions, e.g. `1t5xx`, `1 tỷ 5xx`, `2ty150`.
- Treat prices as incomplete when hundreds of millions are missing or vague, e.g. `1 tỷ x`, `1tx`, `hơn 1 tỷ`.

### Broker score

Broker score aggregates sampled public posts by author:

```text
40% median post quality score
+ target fit ratio
+ data completeness
+ document image signal
+ cadence / weeks active
+ main city concentration
- duplicate text penalty
```

Tiers:

| Tier | Score | Action |
|---|---:|---|
| A | 85–100 | Priority manual review / outreach |
| B | 70–84 | Watchlist / review soon |
| C | 55–69 | Potential source; needs more evidence |
| D | <55 | Low priority |

Labels:

```text
target_area_specialist
data_rich_poster
document_signal_poster
high_duplicate_risk
needs_manual_review
```

## Recommended operating flow

```text
1. Map Facebook groups from generated keywords.
2. Use browser-use/manual review to collect public post metadata into candidate_posts.json.
3. Normalize author links before deep scan: /groups/<group_id>/user/<id> is only a group-member context link; open https://www.facebook.com/<username-or-id> for the broker profile/page.
4. Run score + report.
5. Deep-scan Tier A/B brokers on the plain profile/page URL, sampling about 20 recent public posts when visible; if fewer are visible, mark insufficient evidence unless quality is very clear.
6. Only after approval, add broker to data/facebook_profiles.json or future approved-source config.
```

## Browser-use guardrails

- Deep-scan profile/page via the plain Facebook profile URL (`https://www.facebook.com/<username-or-id>`). Do not use `https://www.facebook.com/groups/.../user/...` as the profile scan URL; that stays inside the group context and can distort the results.
- Read-only discovery first.
- Low rate: 3–5 groups/day, 10–20 broker profiles/day.
- Do not auto-message, comment, add friend, or join groups without approval.
- Stop on checkpoint/captcha/login wall.
- Do not collect private/access-controlled data.
- Store runtime outputs under `/opt/radar-bds/var/broker_discovery/`, not Git.

## Manual review checklist

For any broker Tier A/B or `document_signal_poster`:

1. Open about 20 latest public posts when visible; if Facebook exposes fewer, mark the sample size and be stricter before recommending.
2. Verify most posts include price + area + ward + property type.
3. Check if posts concentrate in one city/market.
4. Check cadence across multiple weeks, not a one-day burst.
5. Watch for repeated text/images across many groups.
6. Treat document/title-book images as sensitive internal evidence only.
7. Mark `approved`, `watchlist`, `manual_only`, or `ignore`.

## Outreach template after approval

```text
Chào anh/chị, em đang làm RadarBDS.vn — công cụ tổng hợp và lọc dữ liệu nhà đất Bình Dương theo phường, giá/m² và dấu hiệu giảm giá.

Em thấy anh/chị đăng khá đều ở khu vực [khu vực], bài có giá và diện tích rõ nên muốn hỏi mình có nhận cập nhật nguồn hàng thường xuyên không.

Bên em đang ưu tiên kết nối môi giới chuyên khu để hiển thị nguồn tin sạch hơn cho người mua. Nếu tiện, em xin Zalo để trao đổi nhanh ạ.
```
