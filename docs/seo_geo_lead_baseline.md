# SEO/GEO Lead-First Baseline

Radar BDS serves Vietnamese buyers and investors researching Bình Dương. The
primary measure is a qualified lead after a useful filtered-dashboard handoff;
organic traffic and AI mentions are leading indicators, not a substitute for
lead evidence.

## Two-week baseline

1. Export the Search Console Performance table for the 20 queries below and
   canonical landing pages. Keep clicks, impressions, CTR, and average position
   separate from product events.
2. Check the same queries manually in Google Search, ChatGPT, Gemini,
   Perplexity, and Copilot. Record whether Radar BDS is cited, the cited URL,
   and the competing source; do not treat a non-citation as a ranking failure.
3. Review `/admin/tang-truong` for `organic`, `ai`, and `social` page views,
   campaign CTA clicks, filtered dashboard handoffs, lead-submit events, and
   directly attributed lead rows. These are event counts, never deduplicated
   people.
4. Run `scripts/verify_traffic_visibility.py` with the optional GSC CSV before
   interpreting a content result. A network or authentication failure stays
   `unknown`.

## Fixed Vietnamese query watchlist

### Giá theo phường

- giá đất Định Hòa
- giá đất Phú Tân
- giá đất Phú Mỹ
- giá đất Hiệp Thành
- giá đất Tân An
- giá đất Thủ Dầu Một

### So sánh và ngân sách

- Phú Mỹ hay Hiệp Thành nên xem khu nào
- Phú Tân hay Phú Mỹ
- Định Hòa hay Hiệp Thành
- đất nền dưới 3 tỷ Thủ Dầu Một
- nhà đất Thủ Dầu Một dưới 3 tỷ
- đất nền dưới 20 triệu/m2 Thủ Dầu Một

### Cách đọc dữ liệu và quyết định

- MOS là gì bất động sản
- cách xem giá đất Bình Dương
- giá rao khác giá giao dịch
- cách tính giá đất m2
- định giá nhà đất Bình Dương
- tin đất giá rẻ có đáng tin không
- cách kiểm tra tin đất trước khi đi xem
- Radar BDS

## Operating rules

- A new `/tin-tuc` article must score at least 75/100 under the existing daily
  publisher gate and must not duplicate reader intent.
- Use production data or a clearly evergreen explainer. Every factual price or
  count must name its source, scope, and date; do not invent testimonials,
  legal certainty, transaction prices, or investment outcomes.
- Each article connects to one relevant report, one location page, a filtered
  Signals CTA, one method/tool page when useful, and two to three related
  articles. Do not add links merely to inflate internal-link counts.
- Maintain the existing `robots.txt`, sitemap, JSON-LD, `llms.txt`, and agent
  discovery documents. Do not add speculative AI files, buy mentions, or use
  fake reviews as GEO tactics.
- Expand Bến Cát or Mỹ Phước only when production coverage supports a
  meaningful local comparison; a renamed Thủ Dầu Một page is not publishable.

## Monthly review output

Report these fields without claiming causation:

| Measure | Evidence | Decision it informs |
|---|---|---|
| Query and landing-page visibility | GSC export + live visibility check | Refresh, title/description test, or retain |
| AI citation share | 20-query manual sheet | Improve source/data structure or keep monitoring |
| Filtered dashboard CTA events | Admin growth `dashboard_handoffs` | Which content handoffs are useful |
| Lead submit events and lead rows | Admin growth direct attribution | Which landing/campaign deserves more effort |

Do not combine these measures into a conversion rate unless the denominator and
attribution rule are explicit for the same period.
