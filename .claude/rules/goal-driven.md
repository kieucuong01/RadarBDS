# Goal-Driven Execution

Khi sửa logic quan trọng, **định nghĩa tiêu chí kiểm tra cụ thể trước khi code**, rồi verify sau khi xong.

## Áp dụng khi nào

Bất cứ khi nào thay đổi các module sau:
- `analytics/valuation.py` — định giá, signal, outlier
- `cleansing/feature_extractor.py` — road_tier, property_type, price parse
- `cleansing/reprocess.py` — pipeline enrichment
- `config/database_sqlite.py` — upsert logic

## Quy trình

**1. Trước khi code** — nêu rõ tiêu chí thành công:
> "road_tier > 0 cho ít nhất 60% listings sau khi Groq chạy xong"
> "is_signal = 1 cho < 30% listings (quá nhiều = threshold sai)"
> "upsert không reset road_tier đã được LLM set"

**2. Sau khi code** — verify bằng câu SQL hoặc script ngắn:
```bash
python -X utf8 -c "
import sqlite3
conn = sqlite3.connect(r'C:/Users/ASUS/radar_bds.db')
# Paste kiểm tra cụ thể ở đây
"
```

**3. Nếu chưa đạt** — loop lại cho đến khi tiêu chí pass, không báo xong sớm.

## Ví dụ tiêu chí cho từng module

| Module | Tiêu chí kiểm tra |
|--------|-------------------|
| road_tier extraction | `SELECT road_tier, count(*) FROM listings GROUP BY road_tier` → tier=0 < 40% |
| Valuation signals | `SELECT count(*) FROM valuation_results WHERE is_signal=1` → 10–30% total |
| Groq enrichment | `SELECT count(*) FROM listings WHERE llm_verified=1` tăng sau mỗi run |
| upsert_listing | road_tier không bị reset về 0 sau reprocess trên listing đã verified |
