---
paths:
  - "crawler/**"
  - "crawl_all.bat"
---

# Crawler

## Nguồn dữ liệu

| Source | File | Trạng thái |
|--------|------|-----------|
| Guland.vn | `guland_pw.py` | ✅ Hoạt động |
| BatDongSan.com.vn | `batdongsan_pw.py` | ✅ Hoạt động |
| Facebook | `facebook_apify.py` | ✅ Hoạt động (Apify API) |
| Nhatot | `nhatot_pw.py` | ❌ Stub (NotImplementedError) |
| Muaban | `muaban_pw.py` | ❌ Stub (NotImplementedError) |
| Facebook Playwright | `facebook_pw.py` | ❌ Deprecated — thay bằng Apify |

## BaseCrawler (base_crawler.py)

Playwright stealth — tránh bot detection:
- Spoof user agent (rotate 4 browsers: Chrome, Firefox)
- `navigator.webdriver = undefined`
- Disable devtools, automation markers
- `_launch(playwright, headless=True)` → Chromium context

## Guland crawler (guland_pw.py)

**2-phase architecture:**

**Phase 1 — Load all listings:**
```
Click #btn-load-more → loop đến btn.offsetParent === null
```

**Phase 2 — Batch fetch details:**
```
page.evaluate(JS_BATCH_DETAIL, urls)
→ 10 concurrent fetch() same-origin từ Guland context (bypass CORS)
```

- Incremental mode: dừng khi URL đã tồn tại trong DB từ lần crawl trước
- URL format: `guland.vn/post/slug-ID` — dashboard tự thêm `/post/` nếu thiếu
- Extract: price_raw, area_raw, pm2_raw, date_raw, description, address, legal_raw, road_type_raw, contact_phone, imgs
- Mở rộng địa bàn: chỉ cần thêm URL vào `TARGET_URLS`

## BatDongSan crawler (batdongsan_pw.py)

- Pagination: navigate `/p1`, `/p2`, ... → selector `.js__card` → `a.href`
- `SLUG_DELAY_S = 8` — delay giữa các detail page (tránh Cloudflare)
- `PAGE_DELAY_S = 3` — delay giữa listing pages
- Cloudflare detect: kiểm tra `page.title()` — bị block nếu title là Cloudflare page
- Bottleneck: ~500 records × 8s ≈ 67 phút — không thể song song
- **SEARCH_SLUGS**: 26 slugs — 13 phường TDM × 2 loại hình (`ban-dat-*` + `ban-nha-*`)
  - Format: `ban-{dat|nha}-phuong-{ward-slug}_1`
  - Ward slugs: tan-an, tuong-binh-hiep, hiep-an, chanh-my, phu-my, phu-tan, chanh-nghia, dinh-hoa, phu-tho, phu-hoa, phu-cuong, hiep-thanh, phu-loi

## Facebook crawler (facebook_apify.py)

Dùng Apify actor `apify/facebook-posts-scraper` — không cần browser, không cần cookies.

- **Token:** `APIFY_TOKEN` trong `.env`
- **Full mode:** `resultsLimit = 100 × n_profiles` (lần đầu cào)
- **Incremental mode:** fetch 30 posts/profile → filter chỉ giữ bài trong 24h
- **_adapt():** map Apify fields → `{url, post_id, text, date_raw, seller_name, profile_url, imgs}`
  - `timestamp` (Unix int) → ISO string
  - `media[].photo_image.uri` → imgs[] (full size); fallback `thumbnail`
  - `_apify_raw` key lưu raw Apify item vào DB (không mất data gốc)
- **Profiles:** `data/facebook_profiles.json` — 2 profiles: nhadatkhanhmy, hang.pk.90

> ⚠️ Apify free tier $5/tháng ≈ 2,500 posts. Full crawl ≈ $0.40. Dùng incremental cho daily.

## Auto image download

Sau mỗi lần crawl (crawl-all, crawl-daily, crawl-facebook), image URLs tự động được download về local.  
Không cần chạy thủ công `download-images` nữa.  
Guland CDN token hết hạn sau vài giờ — nên crawl + download trong cùng session.

## Chạy crawl

```bash
# Full crawl (Windows)
crawl_all.bat                               # cài playwright + crawl-all
python radar.py crawl-all                   # tất cả nguồn
python radar.py crawl-all --source guland   # chỉ Guland
python radar.py crawl-all --visible         # debug: hiện browser
python radar.py crawl-all --no-reprocess    # bỏ qua reprocess (cũng bỏ qua download images)

# Incremental
python radar.py crawl-daily                 # incremental + Telegram
python radar.py crawl-daily --no-alert

# Facebook (Apify)
python radar.py crawl-facebook              # full (100 posts/profile)
python radar.py crawl-facebook --mode incremental  # chỉ bài 24h qua

# Re-fetch thiếu price/area
python radar.py repair-missing --source guland --limit 10
python radar.py repair-missing --source guland

# Cài Playwright (1 lần)
pip install playwright && playwright install chromium
```
