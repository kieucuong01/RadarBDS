---
name: daily-review
description: Workflow review BĐS hàng ngày — crawl tin mới từ Guland và BatDongSan, định giá tự động, hiện các deals rẻ hơn fair value. Dùng thay thế việc lên Guland scan tay mỗi ngày.
allowed-tools: Bash(python radar.py *)
---

# Daily Review — Scan tin BĐS mới & định giá

Thực hiện tuần tự các bước sau, báo cáo kết quả từng bước ngắn gọn.

## Bước 1 — Crawl tin mới

```bash
python radar.py crawl-daily --source guland --no-alert
python radar.py crawl-daily --source batdongsan --no-alert
```

Báo: bao nhiêu tin mới từ mỗi nguồn.

> ⚠️ **Facebook môi giới:** chưa tự động được (cần login).
> Nhắc user: **check thủ công các trang FB môi giới quen** song song khi tool đang chạy.

## Bước 2 — Định giá tự động

```bash
python radar.py reprocess
```

Báo: bao nhiêu listings được định giá, bao nhiêu signals mới phát hiện.

## Bước 3 — Backup

```bash
python radar.py export-raw
```

## Bước 4 — Hiện deals đáng chú ý

```bash
python radar.py query --signals --limit 10
python radar.py deal-brief --top 5
```

## Bước 5 — Tóm tắt cho user

Sau khi chạy xong, trình bày bảng tóm tắt các signals theo format:

```
🏠 [Tiêu đề rút gọn]
   Giá rao : X tỷ  (Y tr/m²)
   Fair    : Z tr/m²  →  MOS: N%  |  Score: S/100
   📍 [Phường] · [Đường tier X] · [Diện tích] m²
   🔗 [URL]
   ⚡ [Lý do nổi bật: is_hot / price_dropped / frontage lớn]
```

Kết thúc bằng: tổng số tin mới hôm nay, tổng signals hiện tại, và 1 nhận xét ngắn về thị trường nếu có bất thường.
