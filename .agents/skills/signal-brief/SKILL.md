---
name: signal-brief
description: Xem nhanh top deals đầu tư tốt nhất hiện tại — không crawl mới, chỉ review signals đang có trong DB. Dùng khi muốn ra quyết định đầu tư mà không cần chờ crawl.
allowed-tools: Bash(python radar.py *)
---

# Signal Brief — Top deals đáng đầu tư

Chạy tuần tự, báo cáo ngắn gọn.

## Bước 1 — Lấy danh sách signals

```bash
python radar.py query --signals --limit 20
```

## Bước 2 — Deal brief chi tiết top 5

```bash
python radar.py deal-brief --top 5
```

## Bước 3 — Trình bày cho user

Trình bày từng deal theo format:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#N  [Tiêu đề rút gọn]
    Giá rao : X tỷ  (Y tr/m²)
    Fair    : Z tr/m²  →  MOS: N%  |  Score: S/100
    📍 [Phường] · Tier [X] · [Diện tích] m²
    🔗 [URL]
    ✅ Điểm cộng : [lý do — is_hot, price_dropped, frontage, giá <3 tỷ...]
    ⚠️  Rủi ro   : [nếu có — ward NULL, has_so=0, tier thấp...]
```

Kết thúc bằng nhận xét tổng: deals nào đáng xuống xem thực tế nhất và lý do.
