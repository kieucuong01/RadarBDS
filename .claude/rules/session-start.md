# Session Start

## Checklist bắt đầu mỗi session (theo đúng thứ tự)

1. Đọc CLAUDE.md — KHÔNG đọc lại code trừ khi cần sửa file cụ thể
2. Chạy `python radar.py inspect` → xem snapshot DB đầy đủ
   - Nếu raw = 0 → `python radar.py import-raw-backup`
3. Xem `pending.md` — hỏi user muốn làm gì
4. Chỉ đọc file code khi thực sự cần thay đổi nó
5. Tóm tắt output ngắn gọn — KHÔNG paste toàn bộ log

## Quick check

```bash
python radar.py inspect              # snapshot đầy đủ (counts, quality, signals, dedup)
python radar.py import-raw-backup    # nếu raw=0
```

## Trạng thái dữ liệu (2026-05-07 — sau Guland re-crawl)

| Bảng | Số lượng | Ghi chú |
|------|----------|---------|
| raw_listings | ~6,336+ | Guland + Facebook; BatDongSan đang crawl lại (26 slugs) |
| listings active | ~6,335 | 1 skipped |
| Valuated | 5,787 | `valuation_results` |
| signals (is_signal=1) | 663 | ~11.5% — per-ward models + tier-0=tier-3 + no floor |
| outliers | 204 | |

