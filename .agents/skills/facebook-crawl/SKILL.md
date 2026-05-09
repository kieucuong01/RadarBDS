---
name: facebook-crawl
description: Crawl bài đăng BĐS từ trang cá nhân Facebook môi giới bằng Chrome MCP — điều khiển Chrome đang mở, không cần login riêng. Lấy tất cả bài BĐS (filter theo từ khóa), area filter để normalizer xử lý. Chạy khi user muốn cào data Facebook mới.
allowed-tools: Bash(python *), mcp__Claude_in_Chrome__navigate, mcp__Claude_in_Chrome__get_page_text, mcp__Claude_in_Chrome__read_page, mcp__Claude_in_Chrome__javascript_tool, mcp__Claude_in_Chrome__find, mcp__Claude_in_Chrome__tabs_context_mcp, mcp__Claude_in_Chrome__browser_batch
---

# Facebook Crawl — Cào bài đăng BĐS từ môi giới

Crawl timeline Facebook của từng môi giới trong `data/facebook_profiles.json`.
Sử dụng Chrome đang mở (user đã login Facebook sẵn).

## Chuẩn bị

```bash
python -X utf8 -c "import json; profiles = json.load(open('data/facebook_profiles.json', encoding='utf-8')); [print(p) for p in profiles]"
```

Lấy tab ID:
```
mcp__Claude_in_Chrome__tabs_context_mcp (createIfEmpty: true)
```

Mode:
- **Full** (lần đầu): tối đa **30 bài BĐS hợp lệ**, scroll tối đa 100 bài tổng
- **Incremental** (hàng ngày): bài trong **24 giờ gần nhất**, scroll tối đa 100 bài tổng

---

## Bước 1 — Crawl từng profile

### 1a. Navigate đến tab Bài viết
```
mcp__Claude_in_Chrome__navigate: "{profile_url}?sk=posts"
```

Chờ 2 giây để page load.

### 1b. Scroll + click Xem thêm + lấy text (lặp lại)

**Scroll xuống:**
```javascript
// javascript_tool
window.scrollBy(0, 3000);
document.querySelectorAll('[role="article"]').length;
```

**Click tất cả "Xem thêm" để expand text:**
```javascript
// javascript_tool
const btns = Array.from(document.querySelectorAll('div[role="button"]'))
  .filter(b => b.innerText.trim() === 'Xem thêm');
btns.forEach(b => b.click());
btns.length + ' buttons clicked';
```

**Lấy URL các post từ timestamp links (ĐÃ KIỂM CHỨNG HOẠT ĐỘNG):**
```javascript
// javascript_tool — trả về pathname, không bị block
const tsLinks = Array.from(document.querySelectorAll('a')).filter(a => {
  const t = a.innerText.trim();
  return /^\d+\s*(phút|giờ|ngày|tuần|tháng|năm)/i.test(t) ||
         /^(hôm nay|hôm qua|vừa)/i.test(t);
}).map(a => ({ text: a.innerText.trim(), path: a.pathname }));
JSON.stringify(tsLinks);
```
→ Kết quả dạng: `[{text:"2 giờ", path:"/nhadatkhanhmy/posts/pfbid0ip..."}]`
→ URL đầy đủ: `https://www.facebook.com` + path

**Lấy toàn bộ text:**
```
mcp__Claude_in_Chrome__get_page_text
```

### 1c. Parse posts từ text

Mỗi post block trong get_page_text bắt đầu bằng "Duy Khánh Bds" (tên profile) + timestamp + nội dung + "Thích Bình luận Chia sẻ".

**Filter BĐS keywords** (bỏ qua nếu không có ít nhất 1):
`đất, nhà, m², tỷ, triệu/m, rao, sổ, thổ cư, chính chủ, nền`

**Filter thời gian** (incremental): dừng khi gặp post > 24 giờ

**Extract:**
- `url`: `https://www.facebook.com` + path từ timestamp JS
- `post_id`: phần sau `/posts/` trong path
- `text`: nội dung bài (loại bỏ "Thích Bình luận Chia sẻ" và comments)
- `date_raw`: text timestamp ("2 giờ", "hôm qua"...)
- `seller_name`: tên profile (vd: "Duy Khánh Bds")
- `profile_url`: URL profile gốc
- `imgs`: `[]` (CDN token hết hạn nhanh)

### 1d. Lặp scroll cho đến khi đủ bài hoặc hết trang

Lặp lại bước 1b tối đa đến khi:
- Full mode: có 30 bài BĐS hợp lệ **hoặc** đã scroll qua 100 bài tổng
- Incremental: gặp bài > 24 giờ **hoặc** đã scroll qua 100 bài

---

## Bước 2 — Lưu kết quả

```python
import json, pathlib
posts = [...]  # list thu thập được
pathlib.Path("data/fb_import_temp.json").write_text(
    json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8"
)
```

---

## Bước 3 — Import vào DB

```bash
python -X utf8 radar.py import-facebook-json data/fb_import_temp.json
```

---

## Bước 4 — Báo cáo

```
Facebook crawl xong:
  Profiles : N
  Bài mới  : X imported | Y skipped (đã có) | Z không liên quan BĐS
  Signals  : (nếu reprocess chạy) → bao nhiêu signals mới
```

---

## Lưu ý kỹ thuật (ĐÃ KIỂM TRA)

| Kỹ thuật | Kết quả |
|----------|---------|
| `document.querySelectorAll('a[href]').map(a=>a.href)` | ❌ BỊ BLOCK (cookie/query string) |
| `a.pathname` (không có query string) | ✅ HOẠT ĐỘNG |
| Timestamp link → pathname → pfbid URL | ✅ HOẠT ĐỘNG |
| `mcp__Claude_in_Chrome__computer` click trên facebook.com | ❌ CẦN PERMISSION |
| `javascript_tool` click `div[role="button"]` | ✅ HOẠT ĐỘNG |
| `get_page_text` lấy nội dung posts | ✅ HOẠT ĐỘNG |
| `document.querySelectorAll('[role="article"]').length` | ✅ đếm được articles |

## Nếu Chrome chưa mở / Facebook chưa login

→ Báo user: "Vui lòng mở Chrome, đăng nhập Facebook, rồi thử lại."
