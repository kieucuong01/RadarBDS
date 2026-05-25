# Legacy Code Archive

Mã nguồn cũ được lưu trữ (không còn dùng trong pipeline hiện tại).

## Nội dung

| File | Lý do archive |
|------|---------------|
| `main.py` | Entry point PostgreSQL cũ — đã thay thế bằng `radar.py` (PostgreSQL runtime qua `DATABASE_URL`) |
| `crawler/base.py` | BaseCrawler phiên bản requests — đã thay bằng `base_crawler.py` (Playwright) |
| `crawler/batdongsan.py` | BDS crawler requests — thay bằng `batdongsan_pw.py` (Playwright stealth) |
| `crawler/facebook.py` | FB crawler prototype — chưa giải quyết được login, stub `facebook_pw.py` |
| `crawler/batdongsan_scraper.py` | Scraper standalone cũ — chức năng đã vào `batdongsan_pw.py` |
| `crawler/guland_scraper.py` | Scraper standalone cũ — chức năng đã vào `guland_pw.py` |

## Không xóa hẳn để làm gì

- Tham chiếu logic parse cũ khi cần debug edge case
- Giữ lại regex patterns đã calibrated
- Reference cho session migration tiếp theo

Archive date: 2026-04-24
