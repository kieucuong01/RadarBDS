---
paths:
  - "cleansing/**"
---

# Cleansing Pipeline

## Flow

```
raw_listings (raw_json)
    │
    ▼ normalize_record()       — idempotent, không cần DB
listings fields
    │
    ▼ flag_duplicates_in_db()
possibly_duplicate, duplicate_of_id set
```

## normalize_record(raw) — normalizer.py

Idempotent. Không đọc/write DB. Gọi feature_extractor để extract regex.

| Field | Logic |
|-------|-------|
| `ward` | `match_ward(title, desc, address, url)` — check từng source riêng (priority: title → desc → addr → url), tránh collision Phú An/Tân An |
| `price_ty` | `raw.price_ty` hoặc tính từ price_total |
| `area_m2` | Sanity check: 0.1–10,000 m² |
| `property_type` | `classify_property_type()` — cascade (xem bên dưới) |
| `road_tier` | `extract_road_tier(title, desc)` → 0–5 |
| `road_type` | `extract_road_type(text)` → nhua/be_tong/dat/unknown |
| `has_so` | `extract_legal(title+desc+legal_raw)` — ⚠️ thường = 0 |
| `is_hot` | Match HOT_SIGNALS list |
| `tx_type` | `_norm_tx_type()` → 'ban' / 'thue' |

**HOT_SIGNALS:** cắt lỗ, ngộp, bán gấp, bán nhanh, kẹt tiền, cần tiền gấp, giảm giá mạnh, giảm sốc, bán lỗ

**Ward keywords:** 13 TDM + Bến Cát (incl. Mỹ Phước 1-4 sub-zones, detected via keyword + street name patterns from `config/area_profiles.py`)

## Feature Extractor (feature_extractor.py)

### Price
```
"12,5 tỷ"    → 12.5
"2 tỷ 550"   → 2.55
"880 triệu"  → 0.88
"Thỏa thuận" → None
```

### Road Tier (0–4) — cascade priority

> ⚠️ Đã refactor 2026-05-06 — fix 5 bugs: hẻm blocking, DX gần false-positive, named roads thiếu, `\bmt\b` backspace bug

| Tier | Điều kiện | Valuation multiplier |
|------|-----------|---------------------|
| 1 | MP trunk street (NE/DE) OR Named road in **TITLE** + MT signal + không hẻm/nhánh/N/ | 2.00× |
| 2 | MP internal street (NG/DJ/NA) detected via `area_profiles.py` | 1.00× |
| 2 | DX road / nhựa / mặt tiền baseline | 1.00× |
| 3 | Bê tông/hẻm, ô tô vào | 0.50× |
| 4 | Hẻm <3m, xe máy | 0.40× |
| 0 | Không xác định → xử lý như tier 3 | 0.50× |

**Key fixes:**
- `has_hem_title` (title-only) thay vì full text — desc có thể đề cập hẻm lân cận
- DX gần/cách: chỉ downgrade tier 3 khi "gần/cách" xuất hiện TRƯỚC DX (không phải sau)
- `_MT_RE`: fix `'\bmt\b'` (backspace bug) → `r'\bmt\b'` (proper word boundary)
- N/ notation: `\b\d+\s*/` trong title → block tier 1 ("2/ Huỳnh Văn Luỹ" = hẻm số 2)
- xẹc/xẹt: cả hai variant bị chặn

**Named road whitelist:** ~42 đường TDM, xem `_NAMED_ROADS` trong `feature_extractor.py`. QL13 excluded.

### Property Type — cascade priority

> ⚠️ Đã refactor 2026-05-06 — cascade cũ gây 70% dat_vuon sai

0. Chung cư/căn hộ → `chung_cu`
0b. Nhà trọ/phòng trọ/dãy trọ/khu trọ → `nha_tro` (tách khỏi nha_dat, định giá rental yield)
1. Strong house (nhà cấp 4 mới, N căn nhà đang) → `nha_dat`
2. vuon_kw (đất vườn/CLN...) → `dat_vuon` **blocked by**: land_only_kw | house_kw | price > 8 tr/m²
3. nha_kw (nhà/biệt thự/xưởng...) → `nha_dat` (nhà luôn thắng đất)
4. Thổ cư < 5% → `dat_vuon` **blocked by**: land_only_kw
5. land_only_kw (lô đất/đất nền/mặt tiền...) → `dat_nen`
6. Đường DX → `dat_nen` (block vườn)
7. area ≥ 500m² + không nhà: `dat_vuon`, ngoại lệ → `dat_nen` nếu thổ cư ≥ 20% hoặc giá > 8 tr/m²
8. Source label hint → mapped type
9. Default → `dat_nen`

**Kết quả sau fix**: dat_vuon > 8 tr/m² giảm từ 388 → 0 (100%)

### Legal Extraction

```python
{
  has_shr:     # "SHR", "sổ hồng riêng"
  has_gcn:     # "GCN", "sổ đỏ", "giấy chứng nhận"
  has_so:      # True nếu has_shr hoặc has_gcn
  no_so:       # "chưa có sổ", "không có sổ"
  dang_lam_so: # "đang làm sổ", "đang hoàn công"
}
```

> ⚠️ has_so thường = 0 do legal_raw từ Guland sparse. Cần fix extraction trước khi áp dụng discount 25% trong valuation.

## Dedup (dedup.py)

`flag_duplicates_in_db(conn)` — union-find cross-source:
- Same `source_id` → duplicate
- Cross-source: same property_type + ward + area ±1% + price ±2% → likely duplicate
- Canonical = record có data đầy đủ nhất
- Kết quả: `possibly_duplicate=1`, `duplicate_of_id=canonical_id`
- **Không xóa** — chỉ flag để audit trail

## Reprocess

```bash
python radar.py reprocess                    # normalize + valuation tất cả
python radar.py reprocess --valuation-only   # chỉ chạy lại valuation engine
python radar.py reprocess --listings-only    # chỉ normalize, bỏ valuation
python radar.py reprocess --source guland    # chỉ 1 nguồn
python radar.py reprocess --since 2026-04-01
```

**Optimization:** batch valuation save trong 1 transaction (241 commits → 1 ≈ 200× nhanh hơn).
