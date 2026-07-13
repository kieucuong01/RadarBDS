# Weekly Marketing Review

- date: 2026-07-06
- mode: reviewed
- one_week_priority: Xac minh va sua public SEO tracking end-to-end de `seo_landing_viewed` va `cta_clicked` ghi vao `user_audit_log` tren production.
- why_8020: Cum public SEO da vuot ngưong "qua it page" va daily publisher van ship deu, nen nut that luc nay la khong co su that do luong cho public funnel.
- evidence:
  - Inventory public SEO: 5 bai `/kien-thuc`, 4 page nen trong `config/seo_pages.py`, 26 location slugs trong `config/seo_locations.py`.
  - Daily publisher dang ship: `.agents/seo-publish-history.md` va `.agents/loops/daily-seo-publisher.log` cho thay 5 bai da publish tu 2026-07-02 den 2026-07-05.
  - CTA/canonical/sitemap/watchlist bridge da co trong repo: `templates/seo_article.html`, `templates/seo_landing.html`, `tests/test_public_seo.py`.
  - Event 30 ngay gan day trong `user_audit_log`: `vip_cta_click=12`, `lead_vip_click=2`, `watchlist_create=1`; khong co dong nao cho `seo_landing_viewed`, `report_viewed`, `cta_clicked`, `telegram_linked`.
- next_week_focus: Kiem tra production event path tu public SEO page -> `/api/track` -> `user_audit_log`; chi sau khi co truth nay moi quyet dinh tiep tuc uu tien publish them hay toi uu CTA.
