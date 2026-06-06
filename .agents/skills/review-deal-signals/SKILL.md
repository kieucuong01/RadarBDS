---
name: review-deal-signals
description: Claude pre-review signal BĐS — đọc bối cảnh từng deal, viết ghi chú cố vấn gọn và có giá trị, lưu kết luận vào ai_deal_review. KHÔNG thay nhãn cuối cùng của admin.
allowed-tools: Bash(python radar.py *)
---

# Review Deal Signals — Claude pre-review (CỐ VẤN)

Nếu nhiệm vụ là cập nhật/rewrite/backfill memo đầu tư cho signal deals, đọc thêm
`docs/investment_memo_workflow.md` trước khi viết hoặc lưu memo. Chuẩn mới là
memo cố vấn dựa trên dữ liệu và định giá chuẩn tắc, không dùng Groq/API ngoài,
không ghi vào `ai_training_feedback`, và tránh toàn bộ thuật ngữ tiếng Anh trong
phần người dùng đọc.

Đây là **pre-review cố vấn**. Mục tiêu: đọc từng deal signal như một nhà cố vấn
đầu tư BĐS, tự đưa nhận định "rẻ thật / mồi / không rẻ / thiếu thông tin", rồi
lưu memo do chính agent viết sau khi đọc context. Không sinh memo bằng rule-base
hoặc script rewrite hàng loạt.

**Ranh giới phải nhớ và nói rõ với user:**

- Nhãn cuối cùng **VẪN do người bấm** trên màn admin review. Skill này KHÔNG
  thay nhãn đó.
- Kết luận của Claude lưu vào bảng **RIÊNG** `ai_deal_review`. **KHÔNG bao giờ**
  ghi vào `ai_training_feedback` (nhãn người = ground-truth). Logic định giá
  chỉ học từ nhãn người — tránh model chấm bài chính nó.
- **Trần cứng:** Claude chỉ đọc text marketing. KHÔNG xác minh được quy hoạch,
  pháp lý thực tế, vị trí/đường thực địa. Mọi kết luận phụ thuộc các yếu tố đó
  PHẢI set `--needs-map-check` để admin tự tra Guland/bản đồ quy hoạch.
- Memo hợp lệ phải là nhận định riêng cho từng lô sau khi đọc `context`.
  Các memo có `model` bắt đầu bằng `claude-code-advisory-` là bản rewrite
  rule-based cũ, không được xem là memo cố vấn hợp lệ.

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

Với mỗi item, đọc `context`:

- `metrics` — `actual_ppm2` vs `fair_ppm2`, `mos_pct`, `valuation_sample_size`
  (mẫu nhỏ → biên an toàn kém tin cậy, hạ confidence).
- `comps_summary` — count / median / low / high ppm2 (so deal với comps).
- `price_context` — `suspicious_bait`, `drop_pct`, `price_dropped`, history
  (drop bất thường/quá sâu = nghi mồi/giá ảo).
- `valuation_explanation`, `valuation_signals`, `risk_warnings`,
  `verification_questions`, `missing_info` (missing nhiều → thiếu thông tin).

Lập luận: **rẻ thật** (`cheap_real`) vs **mồi/giá ảo** (`suspect`) vs **không
thực sự rẻ** (`not_cheap`) vs **thiếu thông tin để kết luận**
(`insufficient_info`).

### Chuẩn viết ghi chú cố vấn

Viết như một nhà cố vấn đầu tư BĐS lâu năm: phải có quan điểm rõ, không ba phải,
không chỉ tóm tắt dữ liệu, không viết theo một form cố định. Mỗi memo phải thể
hiện agent đã đọc riêng lô đó: form đất, vị trí mô tả, đường, thổ cư, giá tổng,
lịch sử giảm/repost, mẫu so sánh, nguồn tin và điểm có thể làm thay đổi quyết
định. Không dùng thuật ngữ tiếng Anh trong phần người dùng đọc.

Memo không đạt nếu đọc như checklist giống nhau giữa nhiều lô. Memo đạt khi nhà
đầu tư đọc xong biết ngay: nên ưu tiên, chỉ theo dõi, cần ép giá, nghi giá mồi,
hay bỏ qua; vì sao; và điều kiện nào làm đổi kết luận.

Cấu trúc khuyến nghị:

```markdown
# Ghi chú cố vấn

## Kết luận
<2-3 câu: nên ưu tiên, theo dõi, ép giá, hay bỏ qua. Nêu ngay lý do lớn nhất.>

## Luận điểm đầu tư
- <Điểm đáng tiền nhất của tài sản: giá vào, vị trí, diện tích, dòng tiền, thanh khoản...>
- <Điểm làm giảm hấp dẫn: giá tổng, mẫu so sánh mỏng, đường, thổ cư, pháp lý...>
- <Nếu có thể mua, điều kiện mua là gì: giá mục tiêu, thông tin phải xác minh.>

## Định giá dễ hiểu
- Giá rao khoảng <x> triệu/m2; vùng so sánh hợp lý khoảng <y> triệu/m2.
- Mức rẻ chỉ đáng tin nếu vị trí, đường, pháp lý và diện tích đúng như tin đăng.
- Nếu biên an toàn mỏng, nói rõ: đây là tin cần kiểm tra thêm, không phải cơ hội mạnh.

## Trước khi đặt cọc
- <3-5 việc kiểm tra cụ thể: sổ/thổ cư, quy hoạch, đường thực tế, đúng lô, giá chốt, lịch sử đăng lại.>

## Cách xử lý
- <Nên gọi hỏi gì, đi xem gì, trả giá/neo giá thế nào, khi nào bỏ qua.>
```

Quy tắc biên tập:

- Không lặp cùng một ý ở hai mục. `Kết luận` là quyết định; các mục sau chỉ bổ
  sung căn cứ.
- Không copy nguyên tiêu đề dài nếu không cần; chỉ nhắc tài sản bằng cách tự
  nhiên như "lô 5x82 ở Tân Định".
- Không viết lời chung chung như "cần kiểm tra pháp lý" một mình; phải nói kiểm
  tra cái gì và vì sao nó ảnh hưởng đến giá.
- Không thổi phồng signal. Nếu biên an toàn dưới khoảng 15%, giá tổng cao, mẫu
  so sánh mỏng, hoặc thổ cư thấp thì nói thẳng là chưa đáng ưu tiên.
- Với nhà đầu tư, luôn có một dòng hành động: mua được khi nào, ép giá về đâu,
  hoặc bỏ qua trong điều kiện nào.

**Bắt buộc** nêu trần cứng: nếu kết luận phụ thuộc quy hoạch/pháp lý/vị trí/
đường thực tế → phải `--needs-map-check`. Trình bày lập luận cho user, **user
chỉnh được kết luận/độ tin cậy/cờ rủi ro trước khi lưu**.

## Bước 3 — Lưu verdict (sau khi user đồng ý)

```bash
python radar.py review-save --id <listing_id> --verdict <cheap_real|suspect|not_cheap|insufficient_info> --confidence <0..1> --reasoning "<lý do ngắn tiếng Việt>" --red-flags "cờ 1;cờ 2" --needs-map-check --memo-file <file.md>
```

`--red-flags` và `--needs-map-check` là tùy chọn. Append-only: mỗi lần lưu là
một bản ghi mới (không ghi đè).

## Bước 4 — Tóm tắt

Trình bày bảng tóm tắt:

```
#<id> <title rút gọn>
   Giá: X tỷ · biên an toàn N% · điểm S
   Kết luận: <verdict> (độ tin cậy C)
   Cờ rủi ro: ...
   🗺️ needs_map_check: có/không
   💬 <1 dòng lý do>
```

**Nhắc rõ user:**
- Đây chỉ là gợi ý cố vấn — **nhãn cuối vẫn bấm trên màn admin review**.
- Mọi deal `needs_map_check=có`: admin **tự mở Guland / bản đồ quy hoạch** xác
  minh vị trí, pháp lý, quy hoạch trước khi chốt.
