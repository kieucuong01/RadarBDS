# Thiết kế tra cứu thửa đất có đất ở và đất nông nghiệp

Ngày: 2026-07-28

## 1. Mục tiêu

Nâng cấp bộ tính trên `/bang-gia-dat-tphcm` để một thửa có đồng thời đất ở và
đất nông nghiệp được tính trong cùng một luồng:

- phần đất ở tiếp tục dùng đúng tuyến đường, vị trí phi nông nghiệp và phân dải
  chiều sâu đã triển khai;
- phần đất nông nghiệp dùng vùng I-IV, vị trí 1-3 và loại đất theo Điều 3,
  Điều 5 Nghị quyết 87/2025/NQ-HĐND;
- kết quả tách riêng giá trị đất ở, giá trị đất nông nghiệp và tổng giá trị;
- mọi giả định, giá sàn và trường hợp không đủ dữ liệu phải được giải thích.

Công cụ chỉ tính giá theo bảng Nhà nước, không xác nhận mục đích sử dụng trên
giấy chứng nhận và không phải giá giao dịch thị trường.

## 2. Nguồn pháp lý

Nguồn quyết định là bản chính thức Nghị quyết 87/2025/NQ-HĐND ngày
26/12/2025, có hiệu lực từ 01/01/2026:

- Điều 3: bốn khu vực và ba vị trí đất nông nghiệp;
- Điều 5 khoản 1-2: bảng giá cây hàng năm và cây lâu năm;
- Điều 5 khoản 3-6: rừng, thủy sản, chăn nuôi tập trung và đất làm muối;
- Điều 5 khoản 8: đất nông nghiệp trong khu dân cư, trong địa giới hành chính
  phường hoặc cùng thửa có nhà ở;
- Điều 7 khoản 1: đất nông nghiệp khác phải theo loại đất liền kề hoặc loại đất
  trước khi chuyển mục đích.

Bản dự thảo do người dùng cung cấp chỉ dùng để đối chiếu bối cảnh. Khi khác
với bản chính thức, bản chính thức được ưu tiên.

## 3. Phạm vi loại đất

Các loại được tự động tính:

| Mã API | Nhãn | Quy tắc |
|---|---|---|
| `perennial` | Đất trồng cây lâu năm | Bảng 2 Điều 5 |
| `annual` | Đất trồng lúa/cây hàng năm | Bảng 1 Điều 5 |
| `aquaculture` | Đất nuôi trồng thủy sản | Bằng đất cây hàng năm |
| `production_forest` | Đất rừng sản xuất | Bằng đất cây hàng năm |
| `protected_special_forest` | Đất rừng phòng hộ/đặc dụng | 80% đất rừng sản xuất |
| `concentrated_livestock` | Đất chăn nuôi tập trung | 150% đất cây lâu năm, không vượt đất ở cùng vị trí |
| `salt` | Đất làm muối | 80% đất cây hàng năm |

`other_agricultural` được hiển thị để người dùng nhận diện hồ sơ nhưng không tự
tính. API trả `manual_review_required=true`, giá và tổng bằng `null`, kèm lý do
cần biết loại đất nông nghiệp liền kề hoặc loại đất trước khi chuyển mục đích.

Đất trong Khu Nông nghiệp Công nghệ cao giá 320.000 đồng/m² không tự động áp
dụng trong đợt này vì dữ liệu tuyến đường không đủ xác nhận thửa có thực sự
thuộc Khu Nông nghiệp Công nghệ cao. Không được suy diễn từ dòng
`KHU CÔNG NGHỆ CAO` của bảng đất phi nông nghiệp.

## 4. Vùng và vị trí đất nông nghiệp

### 4.1. Vùng I-IV

Backend sở hữu một bảng ánh xạ tĩnh, đầy đủ theo khoản 1 Điều 3. Client chỉ gửi
`row_key`; không được gửi hoặc ghi đè vùng.

Tên khu vực được chuẩn hóa không dấu, khoảng trắng và chữ hoa/thường trước khi
đối chiếu. `XÃ PHÚ BÌNH MỸ` trong phụ lục tuyến đường được coi là bí danh của
`XÃ BÌNH MỸ` tại Điều 3 và thuộc vùng III. Mọi khu vực không có trong ánh xạ
phải trả lỗi theo field `agricultural.zone`, không được đoán theo phụ lục hay
đơn giá tuyến đường.

### 4.2. Vị trí 1-3

Vị trí nông nghiệp độc lập với vị trí mặt tiền/hẻm của đất ở:

- vị trí 1: phần trong 0-200m tiếp giáp đường có tên, hoặc thửa không tiếp giáp
  nhưng cùng người sử dụng với thửa tiếp giáp;
- vị trí 2: thửa không tiếp giáp trong phạm vi 400m, hoặc phần sau vị trí 1 từ
  trên 200m đến 400m;
- vị trí 3: phần còn lại.

Đất làm muối dùng mô tả riêng tại điểm b khoản 2 Điều 3; UI thay helper text
theo loại đất. Người dùng chọn vị trí 1-3, backend chỉ nhận số nguyên trong
allowlist. Không tái sử dụng chiều rộng hẻm, hẻm đất hay hệ số khoảng cách của
đất phi nông nghiệp.

## 5. Bảng giá và công thức

Đơn giá gốc dưới đây là 1.000 đồng/m²:

| Vùng | Cây hàng năm VT1 | VT2 | VT3 | Cây lâu năm VT1 | VT2 | VT3 |
|---|---:|---:|---:|---:|---:|---:|
| I | 1.200 | 960 | 770 | 1.440 | 1.150 | 920 |
| II | 1.000 | 800 | 640 | 1.200 | 960 | 770 |
| III | 700 | 560 | 450 | 840 | 670 | 540 |
| IV | 480 | 380 | 300 | 580 | 460 | 370 |

Giá thường:

```text
production_forest = annual
protected_special_forest = annual × 0.80
aquaculture = annual
concentrated_livestock = min(perennial × 1.50, residential_same_position)
salt = annual × 0.80
agricultural_total = agricultural_area × agricultural_unit_price
```

Giá đất ở dùng làm trần cho chăn nuôi là giá vị trí trên chính tuyến đã chọn:
VT1 bằng giá đất ở vị trí 1, VT2 bằng 50% VT1, VT3 bằng 40% VT1. Không nhân
thêm hệ số hẻm đất, khoảng cách hoặc phân dải chiều sâu vào mức trần này.
Response phải nêu rõ công thức và việc có áp trần hay không.

### 5.1. Khoản 8 Điều 5

Điều kiện đặc biệt được bật khi:

- khu vực của dòng giá bắt đầu bằng `PHƯỜNG` — backend tự bật vì nằm trong địa
  giới hành chính phường; hoặc
- với xã/đặc khu, người dùng xác nhận `trong khu dân cư`; hoặc
- người dùng xác nhận `cùng thửa có nhà ở`.

Điều kiện này chỉ thay công thức cho `perennial`, `annual` và `aquaculture`:

```text
special_perennial_vt1 = residential_position_1 × 10%
special_perennial_vt2 = special_perennial_vt1 × 80%
special_perennial_vt3 = special_perennial_vt2 × 80%
special_annual_or_aquaculture = special_perennial_same_position × 80%
final_unit_price = max(special_unit_price, normal_table_unit_price)
```

Rừng, chăn nuôi tập trung và đất làm muối tiếp tục dùng công thức thường vì
khoản 8 không nêu các loại này. Response có `pricing_mode`, giá bảng thường,
giá theo khoản 8, `floor_applied` và diễn giải bằng tiếng Việt.

## 6. Hình thể phần đất ở trong thửa hỗn hợp

Mặc định công cụ giả định phần đất ở là một dải nằm gần lối tiếp giáp nhất:

```text
residential_frontage = parcel_frontage
residential_depth = residential_area / parcel_frontage
```

Nhờ đó diện tích hình học mặc định đúng bằng diện tích đất ở. Trong mục
`Chi tiết phần đất ở`, người dùng có thể nhập ngang và chiều sâu riêng theo sơ
đồ địa chính. Nếu `ngang riêng × sâu riêng` lệch trên 10% so với diện tích đất
ở, vẫn tính theo diện tích pháp lý nhưng hiện cảnh báo hình thể như luồng hiện
tại.

Không tự suy diễn phần đất ở nằm trước nếu người dùng đã bật chi tiết riêng.

## 7. UI/UX

Trong `Thông tin thửa đất`, thêm lựa chọn `Thửa có nhiều loại đất`. Khi bật:

1. `Diện tích toàn thửa`;
2. `Diện tích đất ở`;
3. `Diện tích đất nông nghiệp`;
4. `Loại đất nông nghiệp`;
5. `Vị trí đất nông nghiệp` với helper text pháp lý;
6. với xã/đặc khu, hai checkbox `Trong khu dân cư` và `Cùng thửa có nhà ở`;
7. `<details>` `Chi tiết phần đất ở` để ghi đè ngang/sâu mặc định.

Tổng hai phần phải khớp diện tích toàn thửa trong sai số 0,01m². Lỗi đặt ngay
dưới field và focus vào field đầu tiên. Khi tắt mixed mode, form và response
cũ không đổi.

Kết quả mixed mode:

- thẻ `Phần đất ở`: diện tích, đơn giá bình quân, giá trị và phân dải;
- thẻ `Phần đất nông nghiệp`: vùng, vị trí, loại đất, đơn giá, giá trị, công
  thức và giá sàn;
- thẻ nhấn mạnh `Tổng giá trị theo bảng Nhà nước`;
- cảnh báo giả định phần đất ở nằm phía trước và mọi trường hợp cần đối chiếu.

Mọi input/select/button cao ít nhất 44px, font input mobile 16px, không cuộn
ngang tại 375/390px. Vùng kết quả dùng `aria-live`, loading vô hiệu hóa submit,
và chuyển focus/scroll đến kết quả trên mobile. Không dùng màu làm tín hiệu duy
nhất.

## 8. API

Endpoint giữ nguyên: `POST /api/tphcm-land-prices/calculate`.

Request mixed mode:

```json
{
  "row_key": "stable-key",
  "parcel_mode": "mixed",
  "land_area_m2": 500,
  "frontage_m": 10,
  "depth_m": 50,
  "residential_area_m2": 100,
  "agricultural_area_m2": 400,
  "residential_geometry": {
    "use_custom": false,
    "frontage_m": null,
    "depth_m": null
  },
  "location": {
    "mode": "standard",
    "access": "frontage"
  },
  "agricultural": {
    "land_type": "perennial",
    "position": 1,
    "in_residential_area": false,
    "same_parcel_has_house": false
  }
}
```

Backend bỏ qua mọi `zone`, `base_price`, `residential_base_price` hoặc giá do
client tự thêm. `parcel_mode` chỉ nhận `single` hoặc `mixed`; thiếu field trong
mixed mode trả 400 với `field_errors`.

Response bổ sung:

```json
{
  "parcel_mode": "mixed",
  "mixed_use": {
    "total_area_m2": 500,
    "residential": {
      "area_m2": 100,
      "assumption": "front_strip",
      "average_unit_price": 687200000,
      "total_value": 68720000000,
      "bands": []
    },
    "agricultural": {
      "area_m2": 400,
      "land_type": "perennial",
      "zone": 1,
      "position": 1,
      "pricing_mode": "article_5_8",
      "normal_unit_price": 1440000,
      "special_unit_price": 68720000,
      "unit_price": 68720000,
      "floor_applied": false,
      "total_value": 27488000000,
      "formula": []
    },
    "total_value": 96208000000
  }
}
```

Với `other_agricultural`, `mixed_use.total_value` là `null` để tránh hiển thị
một tổng thiếu thành phần.

## 9. An toàn và analytics

Trust boundary là JSON công khai từ trình duyệt. Backend phải:

- xác thực object lồng nhau, enum, số hữu hạn, giới hạn kích thước và tổng diện
  tích;
- tra dòng giá và vùng trên server;
- không đưa input vào SQL, shell hoặc HTML;
- trả lỗi tiếng Việt ổn định, không lộ stack trace;
- giữ render browser bằng escaping/text content.

Analytics không chứa đường, phường/xã, diện tích, kích thước, `row_key` hoặc
giá trị tính toán. Bổ sung:

- `land_price_mixed_mode_toggle` với `enabled`;
- các event calculator hiện tại thêm `parcel_mode`;
- success gửi `agricultural_type`, `agricultural_zone`,
  `agricultural_position`, `pricing_mode` vì đây là enum không định danh.

## 10. Kiểm thử và tiêu chí hoàn thành

- ánh xạ đại diện và đầy đủ vùng I-IV, gồm bí danh `XÃ PHÚ BÌNH MỸ`;
- đúng bảng annual/perennial ở mọi vùng, vị trí;
- đúng công thức rừng, thủy sản, chăn nuôi, muối và trần đất ở;
- đúng khoản 8 cho phường và xác nhận tại xã; giá không dưới bảng thường;
- `other_agricultural` không tạo tổng giả;
- split lệch trên 0,01m² bị từ chối;
- forged zone/base price không tác động kết quả;
- single mode không hồi quy;
- form mixed mode accessible, progressive disclosure và không tràn mobile;
- browser smoke desktop/mobile, API smoke và analytics không có dữ liệu nhạy
  cảm;
- push, deploy và xác minh trực tiếp trên production.

## 11. Ngoài phạm vi

- tự đọc giấy chứng nhận hoặc bản đồ địa chính;
- tự chia nhiều hơn hai nhóm đất;
- tự chia phần đất nông nghiệp thành nhiều vị trí 1/2/3 trong cùng một lần tính;
- xác định đất liền kề cho `other_agricultural`;
- tự xác nhận Khu Nông nghiệp Công nghệ cao;
- PDF report, lưu lịch sử hoặc thay đổi schema DB.
