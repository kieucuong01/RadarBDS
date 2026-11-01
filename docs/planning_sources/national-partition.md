# Phân khu tham khảo ngoài TP.HCM mới

Ngày kiểm: 2026-11-01. Người dùng chọn dùng Guland cho phần mở rộng, theo quy
trình đã lấy QH2030. GIS TP.HCM/Bình Dương/BRVT hiện có giữ nguyên.

## Những gì thực sự được kiểm

Quan sát controls trên 63 landing pages tỉnh cũ bằng browser bình thường, rồi
lấy 318 mẫu tile hữu hạn, tối đa bốn tải đồng thời. Không đăng nhập, không dùng
token hoặc vượt challenge. Giữ đúng nút có nhãn QH Phân khu, không suy loại lớp
từ `data-type=layer_qhpk_2`: mã này còn được nguồn dùng cho QHC2050/QH xây dựng.
Tên folder nguồn cũng không chứng nhận loại quy hoạch hoặc tỷ lệ pháp lý.

Trong 60 tỉnh ngoài HCM/BD/BRVT: 17 landing pages có control phân khu; 16 có ảnh
mẫu dương tính để đăng ký. Kiên Giang có control nhưng các điểm kiểm chưa có ảnh;
43 landing pages còn lại chưa thấy control phân khu riêng. Đây **không** là kết
luận các tỉnh đó không có đồ án lẻ ở huyện/xã hoặc mục QH khác.

16 tỉnh đã đăng ký: Hà Nội, Bắc Giang, Bắc Ninh, Bình Phước, Bình Thuận, Hải Dương,
Hải Phòng, Khánh Hòa, Lạng Sơn, Nam Định, Quảng Ninh, Tây Ninh, Thái Bình,
Thừa Thiên Huế, Đà Nẵng, Đắk Nông. Độ phủ chỉ theo dữ liệu nguồn thực có;
không chứng nhận phủ kín tỉnh hay thống nhất1/2000. Ví dụ nguồn Tây Ninh mang
tên thành phố Tây Ninh, không đại diện toàn bộ tỉnh mới.

## File và cơ chế

- `config/planning_partition_reference.json`:16 catalogue entries, exact template,
  province IDs cũ, bounds điều hướng, native/display zoom đã kiểm.
- `config/planning_partition_reference_audit.json`:63 trạng thái controls và318
  mẫu URL/status/dimensions/pixels/hash. Không chứa ảnh, cookie hay dữ liệu người dùng.
- `PARTITION_SOURCE_RULES` trong `config/planning_regions.py`: exact descriptors
  gồm cả source_url, coverage_provinces, area_id. Context template đưa chúng vào
  `RADAR_PARTITION_SOURCE_RULES`, client chỉ cho partition reference đã đăng ký.
- `services/planning_live.py` append lớp mới. Catalogue hiện213 entries, dưới
  cap256; không nới cap hay host allowlist để nhập nguồn tùy ý.
- Source picker tự chuyển sang reference khi tỉnh đó không có GIS khả dụng,
  và quay về GIS khi về HCM. Bản vẽ/PDF cũ vẫn giữ; nhãn source trung tính.
  Không ghi tên/link provider ở UI lớp phân khu mới theo yêu cầu người dùng;
  provenance vẫn nằm trong config/audit, không gắn nhãn “GIS chính thức”.
- Layer chỉ mount theo viewport/bounds và zoom đủ gần, không preload toàn tỉnh.
  Tile256/512 source dùng đúng XYZ world cell256 như nguồn. URLs source khác
  nhau giữ cache identity khác nhau. Bản đồ nền/listing/ranh không đổi nguồn.
- Nguồn Bình Phước/Bình Thuận/Đắk Nông cần zoom15+, Huế14+; chọn vùng tự nâng
  tới mức có ảnh. Khi người dùng zoom xa, dừng requests và hiện gợi ý zoom gần.
- Không có geometry quy hoạch vector mới; không bổ sung tra giao thửa ở các tỉnh
  chỉ có raster. Không làm tiếp ranh thửa các tỉnh còn thiếu.

## Kiểm chứng và giới hạn

Registry tests đối chiếu exact descriptors, positive samples, coverage và zoom.
JS tests từ chối template/host/theme/province bị đổi, giữ source selection cũ khi
còn dùng được. Kiểm thực browser local tại Hà Nội và Bình Phước/Đồng Xoài thấy
pixel phân khu, opacity50%, toggle+zoom; mobile390px có ảnh và dock gọn.

Ảnh mẫu dương tính và label control không thay thế đối chiếu quyết định/đồ án
gốc. Không coi 16 nguồn này là hoàn thành phân khu toàn quốc. Các tỉnh còn thiếu
cần tiếp tục rà đồ án cấp huyện/xã trong kho bản đồ; không lấy QHC/SDĐ2030 lấp
vào lớp phân khu. Không clone archive ảnh hay crawl tile toàn quốc.

Rollback: bỏ các entries reference cần tắt khỏi config rồi restart web workers;
không xóa nguồn GIS HCM hoặc layers2030. Metadata public có TTL60s; thay descriptor
phải bump asset version tương ứng. Tắt từng entry không đổi parcel snapshot.
