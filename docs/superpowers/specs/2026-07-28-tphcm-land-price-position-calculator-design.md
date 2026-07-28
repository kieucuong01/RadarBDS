# Thiết kế bộ tính giá đất TP.HCM theo vị trí và hình thể thửa

Ngày: 2026-07-28

## 1. Mục tiêu

Nâng cấp `/bang-gia-dat-tphcm` từ công cụ chỉ tra đơn giá vị trí 1 theo tuyến
đường thành công cụ có thể:

- xác định vị trí phổ biến của đất phi nông nghiệp;
- áp dụng hệ số hẻm, mặt hẻm và khoảng cách từ đường có tên;
- phân bổ đơn giá theo chiều ngang, chiều sâu của thửa;
- trả đơn giá bình quân và tổng giá trị thửa cho đất ở, thương mại dịch vụ và
  sản xuất kinh doanh phi nông nghiệp;
- giải thích được từng hệ số, không trình bày kết quả như giá thị trường hay kết
  luận pháp lý chính thức.

Phạm vi này không thay thế bản đồ địa chính, đo đạc thực địa hoặc xác nhận của
cơ quan nhà nước.

## 2. Nguồn quy tắc

Nguồn áp dụng là bản chính thức Nghị quyết 87/2025/NQ-HĐND ngày 26/12/2025, có
hiệu lực từ 01/01/2026. File người dùng cung cấp là bản dự thảo ngày 02/12/2025;
file này được dùng để hiểu bối cảnh nhưng không phải nguồn quyết định khi có
khác biệt với bản chính thức.

Các phần dùng để triển khai:

- Điều 4, khoản 2: phân loại bốn vị trí đất phi nông nghiệp.
- Điều 6: hệ số vị trí cho đất ở, thương mại dịch vụ và sản xuất kinh doanh phi
  nông nghiệp.
- Phụ lục I, mục 1-5: cách xác định mặt tiền, chiều rộng nhỏ nhất của hẻm,
  khoảng cách đi bộ và hẻm đất.
- Phụ lục I, mục 6.1: hình thể thửa và phân dải theo tỷ lệ chiều dài/chiều rộng.
- Phụ lục I, mục 6.2-6.12: các trường hợp đặc biệt.

## 3. Phạm vi tính tự động

### 3.1. Trường hợp thông dụng

Vị trí được xác định như sau:

| Điều kiện tiếp giáp | Vị trí | Hệ số so với vị trí 1 |
|---|---:|---:|
| Có ít nhất một mặt giáp đường có tên trong bảng giá | 1 | 1,00 |
| Hẻm có chiều rộng nhỏ nhất từ 5m trở lên | 2 | 0,50 |
| Hẻm có chiều rộng nhỏ nhất từ 3m đến dưới 5m | 3 | 0,40 |
| Hẻm dưới 3m hoặc trường hợp còn lại | 4 | 0,32 |

Quy tắc bổ sung:

- Chiều rộng hẻm là chiều rộng nhỏ nhất của toàn tuyến hẻm phải đi qua.
- Hẻm đất áp dụng thêm hệ số 0,80 so với hẻm trải đá, nhựa, bê tông hoặc xi
  măng.
- Đất không mặt tiền có khoảng cách đi bộ từ mép trong đường có tên đến thửa
  đất từ 100m trở lên áp dụng thêm hệ số 0,90.
- Khoảng cách hẻm được hiểu là khoảng cách di chuyển, không phải đường thẳng.

### 3.2. Phân dải chiều sâu

Với đất ở, lấy `R` là chiều ngang và `D` là chiều dài:

| Dải chiều sâu | Hệ số dải |
|---|---:|
| Từ mặt tiếp giáp đến `5R` | 1,00 |
| Trên `5R` đến `8R` | 0,80 |
| Trên `8R` | 0,70 |

Với đất thương mại dịch vụ và sản xuất kinh doanh phi nông nghiệp:

| Dải chiều sâu | Hệ số dải |
|---|---:|
| Từ mặt tiếp giáp đến `2R` | 1,00 |
| Trên `2R` đến `4R` | 0,60 |
| Trên `4R` | 0,40 |

Diện tích pháp lý do người dùng nhập là diện tích dùng để tính tổng. Tỷ trọng
các dải được suy ra từ chiều ngang và chiều dài như một thửa gần hình chữ nhật,
sau đó áp vào diện tích pháp lý. Nếu diện tích pháp lý lệch quá 10% so với
`ngang × dài`, kết quả vẫn được tính nhưng phải có cảnh báo hình thể.

### 3.3. Chi tiết nâng cao

Hai trường hợp có thể tính tự động:

- `Hai mặt tiền trở lên`: người dùng phải chọn tuyến có đơn giá cao nhất; hệ số
  vị trí đặc biệt là 1,10.
- `Nhóm hệ số 70%`: dạ cầu, dưới chân cầu vượt, hành lang điện cao thế, đường
  nhánh dẫn lên cầu vượt, bị ngăn cách bởi kênh/rạch theo Phụ lục I; hệ số vị
  trí đặc biệt là 0,70.

Hai lựa chọn này là chế độ thay thế cách tính vị trí/hẻm thông thường, không
được nhân chồng với nhau.

Các trường hợp sau chỉ hiện hướng dẫn, không tự khẳng định đơn giá:

- thửa chữ L, chữ T, đa giác hoặc có phần khuất sau từ 15m²;
- không có đường/hẻm dẫn vào hoặc phải đi bằng thuyền, ghe, bờ đất;
- địa chỉ thuộc một phường/xã nhưng lối ra thuộc phường/xã giáp ranh;
- hẻm có nhiều lối ra các tuyến đường khác nhau mà chưa xác định được tuyến áp
  dụng;
- trường hợp cần giá sàn đất nông nghiệp nhưng bộ dữ liệu hiện tại không chứa
  đủ bảng giá nông nghiệp.

## 4. Công thức

### 4.1. Hệ số vị trí

Trong chế độ thông dụng:

```text
location_factor =
    position_factor
    × alley_surface_factor
    × distance_factor
```

Trong chế độ đặc biệt:

```text
location_factor = 1.10  # từ hai mặt tiền trở lên
location_factor = 0.70  # nhóm trường hợp 70%
```

### 4.2. Diện tích và đơn giá bình quân

Với mỗi loại đất:

```text
band_area_i = legal_area × band_depth_i / total_depth
band_unit_price_i = base_position_1_price × location_factor × band_factor_i
average_unit_price = Σ(band_area_i × band_unit_price_i) / legal_area
total_value = Σ(band_area_i × band_unit_price_i)
```

Giá nguồn đang lưu theo đơn vị 1.000 đồng/m². Backend phải giữ phép tính bằng
Decimal hoặc số nguyên nghìn đồng, chỉ chuyển sang triệu/m² và tỷ đồng khi định
dạng đầu ra.

## 5. Giao diện

Luồng hiện tại vẫn bắt đầu bằng tìm phường/xã và tuyến đường. Mỗi dòng kết quả
có nút `Tính theo vị trí`. Chỉ một dòng được chọn tại một thời điểm.

Sau khi chọn, một panel `Tính giá thửa đất` xuất hiện dưới bảng/card kết quả:

1. Thông tin thửa:
   - diện tích trên giấy tờ (m²);
   - ngang tiếp giáp đường/hẻm (m);
   - chiều dài thửa (m).
2. Vị trí phổ biến:
   - mặt tiền đường;
   - trong hẻm.
3. Nếu chọn hẻm:
   - chiều rộng nhỏ nhất của tuyến hẻm;
   - mặt hẻm: bê tông/nhựa/đá/xi măng hoặc hẻm đất;
   - khoảng cách đi bộ từ đường có tên đến thửa.
4. `Chi tiết nâng cao`:
   - hai mặt tiền trở lên;
   - nhóm trường hợp hệ số 70%;
   - các trường hợp cần đối chiếu thủ công.

Kết quả gồm:

- vị trí được xác định và hệ số tổng;
- bảng từng dải chiều sâu, diện tích, hệ số và đơn giá;
- ba thẻ tổng hợp cho đất ở, thương mại dịch vụ và SXKD phi nông nghiệp;
- đơn giá vị trí 1, đơn giá bình quân và tổng giá trị;
- cảnh báo hình thể hoặc ngoại lệ;
- liên kết đến Nghị quyết chính thức.

Mobile hiển thị các dải dưới dạng card. Desktop dùng bảng nhưng không bắt buộc
cuộn ngang. Tất cả input có label, lỗi gắn đúng trường, vùng kết quả dùng
`aria-live`.

## 6. API và ranh giới dữ liệu

### 6.1. Khóa dòng giá

Mỗi dòng bảng giá có `row_key` ổn định, được tạo từ các trường nhận diện:

```text
area, street, from, to,
residential, commerce_service, production_business
```

`GET /api/tphcm-land-prices` trả thêm `row_key`.

### 6.2. Endpoint tính toán

`POST /api/tphcm-land-prices/calculate`

Request:

```json
{
  "row_key": "stable-key",
  "land_area_m2": 100,
  "frontage_m": 5,
  "depth_m": 20,
  "location": {
    "mode": "standard",
    "access": "alley",
    "alley_min_width_m": 4,
    "alley_surface": "paved",
    "distance_to_named_road_m": 120
  }
}
```

`location.mode` nhận một trong:

- `standard`;
- `multiple_frontages`;
- `special_seventy_percent`.

Backend tự tìm dòng giá theo `row_key`. Client không được gửi hoặc ghi đè giá
vị trí 1.

Response:

```json
{
  "ok": true,
  "row": {
    "row_key": "stable-key",
    "area": "PHƯỜNG ...",
    "street": "..."
  },
  "position": {
    "label": "Vị trí 3",
    "factor": 0.288,
    "breakdown": []
  },
  "geometry": {
    "legal_area_m2": 100,
    "rectangular_area_m2": 100,
    "mismatch_warning": false
  },
  "values": {
    "residential": {
      "base_unit_price": 10000000,
      "average_unit_price": 2880000,
      "total_value": 288000000,
      "bands": []
    }
  },
  "warnings": [],
  "source_url": "https://congbao.hochiminhcity.gov.vn/..."
}
```

### 6.3. Validation

- Diện tích, ngang và dài phải lớn hơn 0 và nằm trong giới hạn chống input bất
  thường.
- Hẻm bắt buộc có chiều rộng, mặt hẻm và khoảng cách.
- `multiple_frontages` chỉ dùng khi người dùng xác nhận đã chọn tuyến có giá cao
  nhất.
- Các mode đặc biệt không nhận thêm hệ số tùy ý.
- `row_key` không tồn tại trả 404; input sai trả 400 với lỗi theo trường.
- Endpoint không yêu cầu đăng nhập và không trả dữ liệu liên hệ.

## 7. Analytics

Ghi các event không chứa địa chỉ, kích thước hoặc giá trị thửa:

- `land_price_calculator_open`;
- `land_price_calculator_start`;
- `land_price_calculator_success`;
- `land_price_calculator_error`;
- `land_price_calculator_advanced_open`.

Chỉ gửi loại vị trí, có/không cảnh báo và nhóm kết quả; không gửi giá trị input.

## 8. Kiểm thử

### Logic

- Ranh giới hẻm: dưới 3m, đúng 3m, dưới 5m và đúng 5m.
- Hẻm đất nhân 0,80; hẻm lát không giảm.
- Khoảng cách 99,99m không giảm; 100m giảm 10%.
- Hai mặt tiền cho hệ số 1,10 và không nhân thêm hệ số hẻm.
- Nhóm đặc biệt cho hệ số 0,70 và không nhân thêm hệ số hẻm.
- Đất ở được chia đúng các dải `5R`, `8R`.
- Thương mại và SXKD được chia đúng các dải `2R`, `4R`.
- Tổng diện tích các dải bằng diện tích pháp lý.
- Đơn giá bình quân và tổng giá trị khớp tổng từng dải.
- Chênh diện tích trên 10% bật cảnh báo.

### API

- `row_key` ổn định và không trùng cho dữ liệu hiện hành.
- Client không thể thay đổi giá vị trí 1.
- Validation trả lỗi đúng field.
- Response giữ đơn vị, nguồn và breakdown đầy đủ.
- Guest dùng được endpoint.

### UI

- Chọn một dòng mở đúng panel và không nhầm đoạn đường.
- Field hẻm chỉ xuất hiện khi cần.
- Empty/loading/error/result không chồng nhau.
- Kết quả desktop và mobile không tràn ngang.
- Điều hướng bàn phím, focus sau tính toán và `aria-live` hoạt động.
- Analytics không chứa từ khóa, địa chỉ, diện tích, ngang hoặc dài.

## 9. Ngoài phạm vi

- Bản đồ thửa, geocoding hoặc tự đo chiều rộng hẻm.
- OCR giấy chứng nhận hoặc hồ sơ địa chính.
- Tự xác định hình chữ L/T/đa giác.
- Giá đất nông nghiệp và giá sàn tương ứng.
- Lưu lịch sử tính toán, PDF report hoặc tài khoản hóa kết quả.
- Kết luận pháp lý hoặc giá giao dịch thị trường.

## 10. Tiêu chí hoàn thành

- Công thức bám Nghị quyết 87/2025/NQ-HĐND và Phụ lục I.
- Kết quả có thể truy ngược từng hệ số và từng dải diện tích.
- Không nhận giá gốc từ client.
- Bộ test logic/API/UI liên quan xanh.
- Browser smoke đạt trên desktop 1280px và mobile 375/390px.
- Production trả đúng source, hệ số, tổng giá và không có lỗi console.
