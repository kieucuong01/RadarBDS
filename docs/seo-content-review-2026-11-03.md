# SEO content consolidation — 2026-11-03

Reviewed the 219 URLs advertised by the production sitemap. Per-URL decisions
are in [the inventory](seo-content-inventory-2026-11-03.csv), including two new
guides. This is an intent/content review: no Radar BDS Search Console export or
analytics performance dataset was available. No traffic or keyword-volume
claims are made.

## Consolidate three duplicate answers

| Retired `/tin-tuc/` slug | Destination slug | Reason |
| --- | --- | --- |
| `gia-dat-phu-tan-thu-dau-mot-cap-nhat-thang-7-2026` | `gia-dat-phu-tan-hien-bao-nhieu` | Same ward price question; destination has the newer snapshot. |
| `gia-dat-dinh-hoa-thu-dau-mot-cap-nhat-thang-7-2026` | `gia-dat-dinh-hoa-hien-bao-nhieu` | Same question; moved the newer 15 October snapshot into the stable destination URL. |
| `tan-an-hay-tuong-binh-hiep-nen-xem-khu-nao-truoc` | `tan-an-vs-tuong-binh-hiep-loc-dat-nen-hay-nha-dat-truoc` | Same pair and separate land/house comparison; retained the newer, more complete analysis. |

Old URLs and their `/kien-thuc/` and `/bao-cao/` aliases return a single 301,
retaining query attribution. Removed articles no longer appear in the registry,
sitemap or archives. Related links use retained destinations. Unknown slugs
remain 404. Existing social posts are not edited or republished.

Corrected the invalid displayed date `05/13/2026` in Phú Tân to `05/10/2026`,
matching its recorded 5 October revision and 22 September–5 October window.
No new price observations or market statistics were generated.

## Improve period context; add two practical guides

79 retained non-news articles with data tables now distinguish dated snapshots
from live prices and link to current-scope data or valuation. Editorial dates
are not proof of a fresh market query. Existing data and observation periods
remain unchanged.

- `/tin-tuc/cach-tra-cuu-quy-hoach-theo-so-to-so-thua-toa-do`: area, tờ/thửa,
  coordinates, layers, source limits and missing results.
- `/tin-tuc/cach-san-deal-bds-kiem-tra-tin-duoi-gia`: filters, asking price/MOS,
  price history, Maps, valuation and independent verification.

Both guides use existing tools/templates, link from the news portal and to each
other. The planning hub links to its guide. Its next action is the planning
tool; it does not ask visitors for a property lead.

## Retain useful archives and differentiated tools

Keep 70 dated monthly report pages plus their hub and existing PDFs: each
period is a distinct historical observation. Production has October report
definitions beyond the local baseline; preserve them during deployment.
Keep 12 `/gia-dat/` pages with their existing sample/indexability gates: they
describe asking prices for land, whereas ward articles may compare houses and
explain historical data. Keep valuation and official land prices separate.
Keep supported city/ward landings, source-backed planning guides and hubs.

Do not publish more pairwise ward articles merely by swapping names or budgets.
Check for an existing canonical answer, unique evidence and a user task first.
Refresh/consolidate that answer when intent is the same. Do not promise
unsupported nationwide listing or parcel coverage. Lack of traffic evidence
is not a reason to delete a useful existing page.

After recrawling, compare 28/90-day Search Console clicks, impressions, query
overlap and landing-page conversions, allowing for seasonality. Additional
consolidation needs a relevant destination and must preserve unique evidence.
Do not redirect unrelated articles home or delete dated archives to appear fresh.

Google references:
[helpful content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content),
[permanent redirects](https://developers.google.com/search/docs/crawling-indexing/301-redirects),
[canonical consolidation](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls).

## Verification

Focused tests cover every retired alias, direct destinations, query retention,
unknown 404s, sitemap/registry links, preserved newer data and guide rendering.
Release requires exact-commit Quality gates, bounded preservation of unrelated
VPS files, then public redirect/HTML/canonical/schema/sitemap checks and
representative report availability. These checks do not establish traffic gain.
