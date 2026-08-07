# Listing Map Registry Automation

Runbook này dùng cho việc tự bổ sung đường và địa danh còn thiếu trên màn hình
Maps bằng dữ liệu miễn phí. Quy trình chạy ngoài request/crawl: OpenStreetMap
là nền registry, còn Google Maps trong browser chỉ cung cấp bằng chứng gợi ý.
Không dùng Google API trả phí và không ghi dữ liệu browser vào các cột chuẩn
của `listings`.

Quy trình không cần người dùng duyệt từng ứng viên. Ứng viên chỉ được nhận khi
vượt toàn bộ hard gate và `confidence >= 0.90`; mọi trường hợp còn lại tự động
được cách ly và tiếp tục dùng fallback landmark/phường hiện có.

## 1. Xuất queue trực tiếp từ production

```powershell
$ssh = "$env:USERPROFILE\.ssh\radar_bds_deploy_rsa"
New-Item -ItemType Directory -Path .local\listing-map-evidence -Force
ssh -i $ssh deploy@103.90.226.230 "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py map-location-research-queue --limit 50 --candidate-type all" |
  Set-Content -Encoding utf8 .local\listing-map-evidence\production-queue.json
```

Không tạo queue từ DB local khi mục tiêu là production. File
`production-queue.json` là snapshot duy nhất browser runner được dùng cho
batch đó. Ghi lại tổng listing bị ảnh hưởng và số candidate; không đưa mô tả
tin, số điện thoại hoặc URL gốc của tin vào bằng chứng.

Queue tự loại các chuỗi giống nội dung rao bán như giá, diện tích, số tầng và
phòng ngủ. Trường `filtered_candidates` cho biết số ứng viên nhiễu đã bị loại.
Auto-entry quá 180 ngày được đưa lại vào đầu queue với
`status=recheck_due`; nếu lookup tạm thời thất bại thì entry đang hoạt động
không bị tự xóa hoặc tự di chuyển.

## 2. Thu bằng chứng bằng browser

Mở từng `search_url` trong queue bằng browser. Chỉ ghi các trường công khai:

- candidate key/type, city, ward, canonical và aliases từ queue;
- `landmark_scope` nguyên vẹn từ queue khi road candidate được scope theo
  TĐC/KDC;
- query;
- tiêu đề, địa chỉ và loại của kết quả được chọn;
- URL Google Maps công khai có tọa độ, đã bỏ query string, fragment và thông
  tin tài khoản;
- `unique_result`;
- thời điểm kiểm tra ISO-8601.

Lưu batch tối đa 50 items tại
`.local/listing-map-evidence/<date>-<batch>.json`. Không đọc hoặc lưu cookie,
history, tài khoản đăng nhập hay browser storage. Không giải CAPTCHA, không
bypass login và không crawl khối lượng lớn.

`unique_result=true` chỉ khi có đúng một kết quả được chọn, tiêu đề khớp chính
xác canonical hoặc alias đầy đủ, loại kết quả phù hợp, tọa độ nằm trong ward
hoặc compatibility zone đã khai báo rõ. Danh sách kết quả doanh nghiệp, kết quả
tự chọn nhầm, tên gần giống hoặc chỉ có tâm vùng đều phải để
`unique_result=false`.

## 3. Dry-run và tự áp dụng kết quả đạt chuẩn

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -X utf8 radar.py map-location-ingest-evidence `
  --input .local\listing-map-evidence\batch.json

& $py -X utf8 radar.py map-location-ingest-evidence `
  --input .local\listing-map-evidence\batch.json `
  --apply
```

Dry-run phải báo đúng `attempted`, `accepted` và `quarantined`. Lệnh `--apply`
chỉ ghi các item accepted vào
`config/listing_map_location_auto_overrides.json` bằng replace nguyên tử.
Manual override luôn thắng và không thể bị auto override ghi đè.

## 4. Build registry hai lần

```powershell
& $py -X utf8 scripts\build_listing_location_registry.py `
  --osm-json .local\listing-map\osm-binh-duong-20260807-v4.json `
  --sources config\listing_map_location_sources.json `
  --overrides config\listing_map_location_overrides.json `
  --auto-overrides config\listing_map_location_auto_overrides.json `
  --boundary config\map_products\thu_dau_mot_legacy_boundaries.geojson `
  --boundary config\map_products\ben_cat_legacy_boundaries.geojson `
  --boundary config\map_products\thuan_an_legacy_boundaries.geojson `
  --boundary config\map_products\di_an_legacy_boundaries.geojson `
  --output-dir static\maps\listing-locations
```

Chạy lệnh hai lần và so SHA-256 của bốn file JSON trong output. Tất cả hash
phải giống nhau. Kiểm tra manifest có đúng resolver version,
`auto_override_count`, hash manual/auto override, ward/road/landmark count.

## 5. Kiểm thử tập trung

```powershell
& $py -X utf8 -m pytest `
  tests\test_listing_map_context.py `
  tests\test_listing_location_resolver.py `
  tests\test_listing_location_registry.py `
  tests\test_listing_location_backfill.py `
  tests\test_listing_location_coverage.py `
  tests\test_listing_map_service.py `
  tests\test_listing_map_api.py `
  tests\test_listing_map_js.py `
  tests\test_listing_map_ui.py `
  tests\test_listing_location_auto_registry.py `
  tests\test_listing_location_auto_registry_cli.py `
  tests\test_listing_map_automation_docs.py -q
node --check static\js\main\listing_map.js
git diff --check
```

## 6. Dry-run backfill

Local khi DB sẵn sàng:

```powershell
& $py -X utf8 radar.py map-locations --full --dry-run
```

Nếu local DB không khả dụng, không dùng credential đoán hoặc bỏ qua bằng cách
ghi DB khác. Chỉ tiếp tục release khi code/artifact tests xanh; sau deploy phải
chạy dry-run bằng production DB trước khi apply.

## 7. Commit, push và deploy

Stage đúng các file Maps đã kiểm chứng; tuyệt đối không stage `.local/`.

```powershell
git diff --cached --name-only
git commit -m "feat: update automatic map registry"
git push origin main
.\scripts\deploy_production.ps1
```

## 8. Backfill production

```powershell
ssh -i $ssh deploy@103.90.226.230 "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --full --dry-run"
ssh -i $ssh deploy@103.90.226.230 "set -a; . /etc/radar-bds/radar.env; set +a; cd /opt/radar-bds/current && /opt/radar-bds/.venv/bin/python -X utf8 radar.py map-locations --full"
```

So sánh dry-run và apply: số scanned phải hợp lý; tổng precision không vượt
scanned; không có ward/mapped count giảm bất thường; resolver version phải là
version vừa deploy.

## 9. API và browser smoke

```powershell
Invoke-RestMethod "https://radarbds.vn/api/map-listings?mode=signals"
Invoke-RestMethod "https://radarbds.vn/api/map-listings?mode=all&complete=1"
```

Trong browser, kiểm tra cả tab Săn Deal và Tin Rao:

1. nút `Xem trên Maps` vẫn fixed ở bottom center;
2. tin gần/sát/cách/1 sẹc đường đã resolve dùng chung marker của đường;
3. không có GIS block và không có vòng tròn `Gần đúng`;
4. chọn marker mở modal ngay trên Maps;
5. đóng modal giữ nguyên URL, tab, viewport, filter và trạng thái Maps;
6. tin chỉ nêu landmark accepted nằm tại landmark, không rơi về tâm phường.

## Stop gates

Dừng candidate hoặc cả batch tại cổng tương ứng:

- gặp CAPTCHA, yêu cầu login hoặc browser block;
- trang không có đủ title, address, type, public URL và tọa độ;
- kết quả không duy nhất, title/type/ward không khớp hoặc confidence dưới
  `0.90`;
- conflict với manual override;
- bằng chứng/hash bị thay đổi hoặc candidate key bị retarget;
- hai lần build có hash khác nhau;
- bất kỳ focused test nào fail;
- invariant backfill fail hoặc mapped/ward count giảm bất thường;
- deploy, API hoặc production browser smoke fail.

Stop gate phải ghi nhận/quarantine ứng viên và không tự đoán tọa độ. Quy trình
không hỏi người dùng phê duyệt ứng viên bị dừng; chỉ báo cáo blocker nếu toàn bộ
release không thể tiếp tục an toàn.
