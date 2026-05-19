---
paths:
  - "analytics/**"
---

# Valuation & Analytics

## Công thức Fair Value

```
Segment = ward × property_type × tx_type  (per-ward models)
Fallback = parent_ward → SELECTED_REGION (3-tier: sub-ward → parent → region)

1. Outlier removal:  loại listings ngoài ±2σ của segment
2. Regression:       weighted ridge regression (weight decay 90 ngày)
3. Size discount:    multiplier = (median_area / area_m2) ^ alpha
                     clamp: [0.65, 1.40]
                     alpha: dat_nen=0.60, nha_dat=0.50, nha_tro=0.40
4. Road tier:        × ROAD_TIER_MULTIPLIER[tier]
                     tier-0 → encode as tier-3 trong regression
5. ~~Floor~~:        ĐÃ BỎ — không còn max(result, median × 0.70)

mos_pct  = (fair_ppm2 - actual_ppm2) / fair_ppm2
is_signal = mos_pct ≥ MOS_THRESHOLD (theo confidence level)
```

> ⚠️ **2026-05-18:** regression chỉ dùng `road_tier` (qua multiplier). `road_width_m`
> + `frontage_m` đã loại khỏi feature matrix từ lâu (xem `valuation.py:149`).
> `road_width_m` nay functional-removed khỏi `Listing` dataclass + pipeline.
> `road_tier` LLM-authoritative khi `llm_verified=1` (sticky, regex không ghi đè).

## Road Tier Multipliers (dat_nen & nha_dat only)

| Tier | Mô tả | Multiplier |
|------|--------|-----------|
| 0 | Không rõ → **xử lý như tier 3** | **0.50×** |
| 1 | Đường lớn có tên | **2.00×** |
| 2 | Đường DX / nhựa baseline | 1.00× |
| 3 | Hẻm ≥ 5m | 0.50× |
| 4 | Hẻm 3–5m | 0.45× |
| 5 | Hẻm < 3m | 0.40× |

## Signal Score (0–100) — chỉ tính khi is_signal = True

| Yếu tố | Điểm tối đa |
|--------|------------|
| MOS contribution (`mos_pct × 0.5`, cap 40) | 0–40 |
| Area 50–200 m² (thanh khoản tốt) | +10 |
| Giá < 3 tỷ (tầm tay nhà đầu tư nhỏ) | +10 |
| `is_hot` = True (bán gấp, cắt lỗ...) | +10 |
| Frontage ≥ 4m | +10 |
| `price_dropped` = True | +10 |

**Phân loại:** ≥ 70 = HIGH · 50–69 = WATCH · < 50 = LOW

## Segments & Confidence

`high` n≥45 · `medium` n≥15 · `low` n<15 (median fallback). MIN_SAMPLES=15, OUTLIER_SIGMA=2.0.

## Chạy valuation

```bash
python radar.py reprocess --valuation-only   # chạy lại toàn bộ
python radar.py lifecycle --velocity          # segment hotness
python radar.py lifecycle --sweep-hours 48   # mark probably_sold
```
