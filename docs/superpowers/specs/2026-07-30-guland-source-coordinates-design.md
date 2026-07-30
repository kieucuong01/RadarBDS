# Thiết kế tọa độ nguồn cho tin Guland

Ngày: 2026-07-30

Trạng thái: Đã duyệt thiết kế trong hội thoại, chờ review spec

Phạm vi: Crawler Guland, `raw_listings.raw_json`, backfill vị trí và `listing_map_locations`

## 1. Bối cảnh

`raw_listings` hiện không có cột riêng cho latitude/longitude. Toàn bộ field
do parser nguồn trả về được lưu trong `raw_json`. Crawler Guland hiện đọc card,
trang chi tiết, giá, diện tích, nội dung, địa chỉ, ảnh và thông tin liên hệ,
nhưng chưa đọc liên kết `Chỉ đường` chứa tọa độ.

Hệ thống Maps đã có bảng dẫn xuất `listing_map_locations` với `lat`, `lng` và
`location_precision`. Resolver cũng đã hỗ trợ `source_lat`/`source_lng` và sẽ
gắn precision `exact` khi tọa độ nguồn hợp lệ. Tuy nhiên
`db.listing_map_locations.iter_location_candidates()` hiện luôn truyền hai
field này bằng `NULL`, nên tất cả điểm Guland hiện tại chỉ có thể được suy ra
theo đường, địa danh hoặc phường.

Snapshot audit production ngày 2026-07-30:

- 6.144 raw Guland, không raw nào có key tọa độ;
- 6.167 listing Guland;
- 6.040 listing có điểm Maps;
- 0 điểm `exact`, 1.228 điểm `road`, 4.812 điểm `ward`.

Các con số trên chỉ mô tả snapshot lúc thiết kế, không phải invariant triển
khai.

## 2. Mục tiêu

1. Tin Guland mới có liên kết tọa độ công khai phải lưu được tọa độ nguồn.
2. Tọa độ nguồn hợp lệ phải được Maps ưu tiên với precision `exact`.
3. Backfill chỉ áp dụng cho tin Guland còn đủ điều kiện xuất hiện trên Maps.
4. Tin không có tọa độ hoặc tọa độ không hợp lệ vẫn giữ fallback road/landmark/
   ward hiện tại.
5. Dữ liệu phải có provenance, có thể tái tạo sau reprocess và có dry-run trước
   khi ghi production.
6. Quy trình phải idempotent và không chạy lại valuation/dedup không cần thiết.

## 3. Không nằm trong phạm vi

- Không lấy tọa độ từ Facebook.
- Không geocode địa chỉ hoặc gọi Google Maps API trả phí.
- Không tự sửa, đảo hoặc đoán latitude/longitude sai.
- Không ghi tọa độ suy diễn vào các cột chuẩn của `listings`.
- Không thay đổi source policy, quyền xem Guland hoặc quy tắc redaction.
- Không reprocess toàn bộ production, không thay đổi valuation và không gửi VIP
  notification trong lượt backfill.
- Không backfill tin Guland đã bán, bị blacklist, bị ẩn hoặc là duplicate không
  được Maps hiển thị.

## 4. Các phương án đã cân nhắc

### 4.1. Lưu trong `raw_json`, dẫn xuất sang `listing_map_locations`

Đây là phương án được chọn.

Ưu điểm:

- phù hợp vai trò `raw_json` là nơi chứa toàn bộ field parser nguồn;
- không cần migration schema;
- giữ được provenance từ liên kết `Chỉ đường`;
- tận dụng resolver và bảng Maps hiện có;
- có thể tái tạo điểm exact sau reprocess.

Nhược điểm:

- backfill phải merge JSON cẩn thận;
- truy vấn candidate phải join `raw_listings` và đọc JSON.

### 4.2. Thêm cột tọa độ vào `raw_listings`

Ưu điểm là query và constraint đơn giản hơn. Nhược điểm là migration bảng raw,
làm schema nguồn chung phụ thuộc vào field riêng của Guland và không cần thiết
cho access pattern hiện tại. Phương án này bị loại.

### 4.3. Ghi thẳng vào `listing_map_locations`

Phương án này ít code nhất nhưng mất provenance và không bảo đảm tái tạo sau
reprocess. Phương án này bị loại.

## 5. Mô hình dữ liệu

Khi tọa độ hợp lệ, `raw_json` Guland được bổ sung:

```json
{
  "source_lat": 11.0280996,
  "source_lng": 106.6206725,
  "source_coordinate_url": "https://www.google.com/maps/...",
  "source_coordinate_provider": "guland_directions",
  "source_coordinate_captured_at": "2026-07-30T12:34:56+07:00"
}
```

Quy ước:

- `source_lat` và `source_lng` chỉ tồn tại khi candidate đã vượt toàn bộ
  validation gate;
- `source_coordinate_url` là URL công khai đã bỏ fragment, tham số tài khoản
  hoặc dữ liệu không cần thiết;
- `source_coordinate_provider` cố định là `guland_directions`;
- `source_coordinate_captured_at` dùng ISO-8601 có timezone;
- `source_coordinate_captured_at` chỉ đổi khi URL hoặc cặp tọa độ thực sự đổi;
  rerun với cùng candidate phải giữ timestamp cũ;
- merge giữ nguyên tất cả field raw cũ.

Nếu card có liên kết nhưng candidate không hợp lệ, không ghi `source_lat` hoặc
`source_lng`. Lý do bị từ chối chỉ đi vào thống kê/log backfill; listing tiếp
tục sử dụng fallback Maps hiện có.

`listing_map_locations` không cần đổi schema. Điểm hợp lệ được ghi với:

- `location_precision='exact'`;
- `location_key='exact:<listing_id>'`;
- `location_label='Vị trí chính xác từ tin rao'`;
- `source='guland'`;
- `accuracy_radius_m=0`;
- signature bao gồm resolver version và tọa độ nguồn.

## 6. Thành phần và ranh giới trách nhiệm

### 6.1. Card extractor

JavaScript chạy trong trang Guland chỉ làm hai việc:

1. tìm anchor `Chỉ đường`/Google Maps nằm trong đúng card;
2. trả nguyên `source_coordinate_url` cùng card data hiện có.

JavaScript không parse, sửa hoặc validate tọa độ. Logic tin cậy nằm ở Python để
có thể unit test độc lập.

### 6.2. Coordinate parser/validator

Một helper Python thuần nhận:

- URL tọa độ;
- canonical ward của listing;
- registry/boundary hiện hành.

Helper trả về một trong hai dạng:

- candidate hợp lệ gồm `lat`, `lng` và URL đã sanitize;
- kết quả từ chối có reason code.

Reason code tối thiểu:

- `missing_coordinate_url`;
- `missing_coordinate_pair`;
- `invalid_number`;
- `invalid_lat_lng_order`;
- `outside_service_bounds`;
- `missing_canonical_ward`;
- `outside_canonical_ward`;
- `source_identity_mismatch`.

Helper không truy cập DB và không tự ghi file.

### 6.3. Raw coordinate merge

Repository helper nhận `raw_id` và candidate hợp lệ, đọc JSON hiện hành, merge
năm field tọa độ và chỉ update khi giá trị thực sự thay đổi.

Update phải nằm trong transaction theo batch. Giá trị cũ khác candidate mới chỉ
được thay khi URL/post ID vẫn khớp và candidate mới vượt toàn bộ validation.
Đây là repair bổ sung field nguồn bị bỏ sót, không được xóa hoặc thay các field
raw khác. Raw JSON lỗi parse phải làm candidate đó bị từ chối và được đếm lỗi,
không được làm hỏng toàn bộ batch.

### 6.4. Map candidate loader

`iter_location_candidates()` join `listings.raw_id` với `raw_listings.id`, đọc
`source_lat/source_lng` từ raw JSON và đưa hai giá trị này vào mapping của
resolver.

Loader không tự gắn `exact`; `resolve_listing_location()` tiếp tục là nơi quyết
định precision và signature.

### 6.5. Backfill command

CLI riêng:

```powershell
python radar.py guland-coordinate-backfill --dry-run
python radar.py guland-coordinate-backfill --apply
```

Dry-run là mặc định an toàn; `--apply` mới được phép ghi DB.

## 7. Luồng tin Guland mới

```text
Trang danh sách Guland
  -> card extractor lấy URL tin + URL Chỉ đường
  -> Python parse và validate tọa độ
  -> _build_record thêm field tọa độ hợp lệ
  -> BaseCrawler lưu toàn bộ record vào raw_listings.raw_json
  -> normalize/upsert listings như hiện tại
  -> incremental map-location backfill đọc tọa độ từ raw
  -> resolver ghi listing_map_locations precision=exact
  -> Maps ưu tiên marker exact
```

Card không có tọa độ hoặc candidate bị từ chối vẫn đi qua toàn bộ luồng crawl
hiện tại, không bị skip khỏi `raw_listings`, `listings`, valuation hoặc Maps.

## 8. Phạm vi và luồng backfill tin cũ

### 8.1. Tập target

Tập target lấy từ production DB bằng cùng common visibility gate của Maps:

```sql
l.source = 'guland'
AND COALESCE(l.probably_sold, 0) = 0
AND COALESCE(l.is_blacklisted, 0) = 0
AND COALESCE(l.review_hidden, 0) = 0
AND COALESCE(l.possibly_duplicate, 0) = 0
```

Mỗi target gồm `listing_id`, `raw_id`, canonical URL, `source_id/post_id` và
canonical ward. Không xuất description, số điện thoại hoặc ảnh vào artifact
backfill.

### 8.2. Thu candidate

Backfill scroll các trang danh sách Guland đã cấu hình và dừng khi:

- đã tìm được toàn bộ target; hoặc
- Guland không còn trả thêm card.

Backfill không fetch từng detail page. Card được khớp bằng canonical URL; post
ID là bằng chứng phụ để từ chối mismatch, không được dùng fuzzy title matching.

### 8.3. Apply

Khi `--apply`:

1. merge tọa độ hợp lệ vào raw theo batch;
2. thu đúng `listing_id` có raw thay đổi;
3. gọi `backfill_listing_locations(listing_ids=changed_ids)`;
4. clear Maps cache qua cơ chế hiện có;
5. không gọi valuation, dedup, image download hoặc notification.

Chạy lại cùng input phải cho `raw_updated=0` và không tạo thay đổi Maps mới.

Trước transaction apply đầu tiên, command tạo rollback manifest production-local
tại `.local/guland-coordinate-backfill/<run-id>-before.jsonl`. Manifest chỉ chứa
`raw_id`, `listing_id` và năm field tọa độ trước apply; không chứa title,
description, phone, ảnh hoặc URL gốc của tin. Nếu phải rollback, command khôi
phục đúng năm field này và chạy lại map-location backfill cho các listing ID của
run; các field raw khác không bị ghi đè.

## 9. Validation gate

Candidate chỉ được coi hợp lệ khi đồng thời:

1. URL sau normalize đúng mẫu công khai
   `https://www.google.com/maps/search/?api=1&query=<lat>,<lng>`;
2. query chứa đúng một cặp số theo thứ tự latitude,longitude;
3. latitude nằm trong `[-90, 90]`, longitude trong `[-180, 180]`;
4. tọa độ nằm trong `LISTING_MAP_BOUNDS`;
5. listing có canonical ward được hỗ trợ;
6. điểm nằm trong polygon canonical ward hoặc compatibility zone đã khai báo;
7. card URL khớp canonical Guland URL và post ID không xung đột.

Không có phép sửa heuristic. Ví dụ `110.99336,106.655...` phải bị từ chối,
không được đổi thành `10.99336,106.655...`.

## 10. Báo cáo và xử lý lỗi

Dry-run in một JSON object trên stdout có các counter:

```text
eligible
cards_scanned
matched
coordinate_links
valid
invalid
outside_ward
missing
would_update
would_upgrade_to_exact
```

Apply thêm:

```text
raw_updated
map_exact_updated
map_unchanged
errors
```

Mỗi lỗi chỉ ghi `listing_id`, reason code và tọa độ/URL đã sanitize. Không ghi
description, phone, ảnh hoặc credential.

Lỗi một card không làm hỏng batch. Lỗi DB transaction làm rollback batch đó và
trả exit code khác 0. Nếu crawl Guland bị block, CAPTCHA hoặc yêu cầu login,
command dừng mà không apply phần candidate chưa xác minh.
Thông báo tiến độ đi qua logger/stderr để stdout luôn là JSON có thể parse.

## 11. Kiểm thử

### 11.1. Unit tests

- parse `query=lat,lng` bình thường và URL-encoded;
- thiếu URL hoặc thiếu một tọa độ;
- giá trị không phải số;
- latitude sai như `110.99336`;
- tọa độ ngoài service bounds;
- tọa độ ngoài canonical ward;
- không tự đảo lat/lng;
- canonical URL/post ID mismatch;
- sanitize URL không giữ query/fragment ngoài allowlist;
- raw merge giữ nguyên toàn bộ field cũ;
- raw merge idempotent.
- rerun cùng candidate không đổi `source_coordinate_captured_at`;
- raw JSON lỗi parse bị từ chối mà không làm hỏng batch;
- rollback manifest không chứa field nhạy cảm.

### 11.2. Repository/integration tests

- target query chỉ lấy listing qua visibility gate của Maps;
- crawler mới lưu tọa độ hợp lệ vào raw;
- card không có tọa độ vẫn được crawl như trước;
- candidate loader đọc đúng tọa độ từ raw;
- resolver nâng listing từ road/ward lên exact;
- invalid coordinate giữ nguyên fallback;
- incremental map backfill chỉ nhận changed IDs;
- CLI dry-run không ghi DB;
- CLI apply chạy lại không phát sinh thay đổi.

### 11.3. Production gates

1. Chạy dry-run production và kiểm tra tổng counter.
2. Xem mẫu candidate valid/invalid đã sanitize.
3. Chỉ apply khi không có mức giảm bất thường về mapped coverage.
4. Sau apply, kiểm tra số `exact` Guland tăng đúng bằng số candidate hợp lệ.
5. Kiểm tra `/api/map-listings` và listing detail API không lỗi.
6. Kiểm tra trình duyệt bằng tài khoản admin, chọn nguồn Guland ở cả Maps
   `Săn Deal` và `Tin rao`.
7. Xác nhận marker exact nằm tại tọa độ nguồn và listing thiếu tọa độ vẫn dùng
   fallback cũ.

## 12. Rollout

Release code theo staging hẹp, chạy focused tests và deploy bình thường. Sau
deploy:

1. chạy production dry-run;
2. lưu counter trước apply;
3. chạy production apply;
4. kiểm tra DB precision counts;
5. smoke API;
6. browser verify hai tab Maps;
7. nếu apply thất bại, không xóa điểm fallback hiện có và không chạy full
   reprocess để “sửa” dữ liệu; dùng rollback manifest của đúng run nếu cần hoàn
   tác các field tọa độ đã ghi.

Backfill là thao tác một lần cho tập active hiện tại. Daily Guland crawl tiếp
tục tự bổ sung tọa độ cho tin mới.

## 13. Tiêu chí hoàn thành

- Tin Guland mới có tọa độ hợp lệ được lưu trong raw và hiện `exact` trên Maps.
- Chỉ listing đủ điều kiện Maps được backfill.
- Không có listing nào bị mất Maps chỉ vì thiếu hoặc sai tọa độ.
- Invalid coordinates không trở thành marker exact.
- Backfill không chạm valuation, dedup, notification hoặc source policy.
- Dry-run không ghi dữ liệu.
- Apply chạy lại là no-op.
- Focused tests, production DB check, API smoke và browser verification đều đạt.
