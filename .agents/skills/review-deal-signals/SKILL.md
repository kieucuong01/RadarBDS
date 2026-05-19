---
name: review-deal-signals
description: Claude pre-review signal BĐS — đọc investment memo từng deal, đánh giá rẻ thật / mồi / không rẻ, lưu verdict cố vấn vào ai_deal_review. KHÔNG thay nhãn cuối cùng của admin.
allowed-tools: Bash(python radar.py *)
---

# Review Deal Signals — Claude pre-review (CỐ VẤN)

Đây là **pre-review cố vấn**. Mục tiêu: đỡ việc cho admin bằng cách đọc trước
từng deal signal và đề xuất "rẻ thật / mồi / không rẻ / thiếu thông tin".

**Ranh giới phải nhớ và nói rõ với user:**

- Nhãn cuối cùng **VẪN do người bấm** trên màn admin review. Skill này KHÔNG
  thay nhãn đó.
- Verdict của Claude lưu vào bảng **RIÊNG** `ai_deal_review`. **KHÔNG bao giờ**
  ghi vào `ai_training_feedback` (nhãn người = ground-truth). Logic định giá
  chỉ học từ nhãn người — tránh model chấm bài chính nó.
- **Trần cứng:** Claude chỉ đọc text marketing. KHÔNG xác minh được quy hoạch,
  pháp lý thực tế, vị trí/đường thực địa. Mọi kết luận phụ thuộc các yếu tố đó
  PHẢI set `--needs-map-check` để admin tự tra Guland/bản đồ quy hoạch.

Thực hiện tuần tự, báo cáo ngắn gọn từng bước.

## Bước 1 — Lấy hàng đợi signal chưa review

```bash
python radar.py review-queue --top 5
```

(User có thể đổi `--top N` hoặc thêm `--ward <Phường>`.)

Lệnh in **JSON ra stdout**: `{count, generated_at, items:[{listing_id, title,
url, ward, price_ty, area_m2, mos_pct, signal_score, memo:{...}}]}`. Chỉ gồm
signal **chưa có** verdict Claude. Parse JSON này.

## Bước 2 — Phân tích từng deal

Với mỗi item, đọc `memo`:

- `metrics` — `actual_ppm2` vs `fair_ppm2`, `mos_pct`, `valuation_sample_size`
  (mẫu nhỏ → MOS kém tin cậy, hạ confidence).
- `comps_summary` — count / median / low / high ppm2 (so deal với comps).
- `price_context` — `suspicious_bait`, `drop_pct`, `price_dropped`, history
  (drop bất thường/quá sâu = nghi mồi/giá ảo).
- `valuation_explanation`, `valuation_signals`, `risk_warnings`,
  `verification_questions`, `missing_info` (missing nhiều → thiếu thông tin).

Lập luận: **rẻ thật** (`cheap_real`) vs **mồi/giá ảo** (`suspect`) vs **không
thực sự rẻ** (`not_cheap`) vs **thiếu thông tin để kết luận**
(`insufficient_info`).

**Bắt buộc** nêu trần cứng: nếu kết luận phụ thuộc quy hoạch/pháp lý/vị trí/
đường thực tế → phải `--needs-map-check`. Trình bày lập luận cho user, **user
chỉnh được verdict/confidence/red-flags trước khi lưu**.

## Bước 3 — Lưu verdict (sau khi user đồng ý)

```bash
python radar.py review-save --id <listing_id> --verdict <cheap_real|suspect|not_cheap|insufficient_info> --confidence <0..1> --reasoning "<lập luận tiếng Việt>" --red-flags "cờ 1;cờ 2" --needs-map-check
```

`--red-flags` và `--needs-map-check` là tùy chọn. Append-only: mỗi lần lưu là
một bản ghi mới (không ghi đè).

## Bước 4 — Tóm tắt

Trình bày bảng tóm tắt:

```
#<id> <title rút gọn>
   Giá: X tỷ · MOS N% · Score S
   🤖 Verdict: <verdict> (conf C)
   🚩 Red flags: ...
   🗺️ needs_map_check: có/không
   💬 <1 dòng lý do>
```

**Nhắc rõ user:**
- Đây chỉ là gợi ý cố vấn — **nhãn cuối vẫn bấm trên màn admin review**.
- Mọi deal `needs_map_check=có`: admin **tự mở Guland / bản đồ quy hoạch** xác
  minh vị trí, pháp lý, quy hoạch trước khi chốt.
