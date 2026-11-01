# Phân khu tham khảo ngoài TP.HCM mới

Ngày kiểm: 2026-11-01. Hiện có **416 nguồn phân khu tham khảo ở48 tỉnh cũ ngoài HCM/BD/BRVT**
đã đăng ký local, chưa push/deploy. Người dùng chọn dùng Guland cho phần mở rộng, theo quy
trình đã lấy QH2030. GIS TP.HCM/Bình Dương/BRVT hiện có giữ nguyên.

## Đợt ghép đồ án theo huyện — trạng thái hiện tại

Theo yêu cầu người dùng, mở rộng từ huyện mặc định sang **671 huyện cũ của60 tỉnh**.
Chọn mã huyện cũ từ options công khai, đối chiếu mã/tên với navigation; không nhầm
xã mới đang được nguồn trộn trong cùng bộ chọn. Không lọc riêng xã: danh mục huyện
trả các đồ án phường/xã thuộc huyện. Không khẳng định đã rà độc lập mọi trang xã.

Quan sát request thật của nút QH khác:
`/map-service/layers?district_id=...&ward_id=&province_id=...&path=...&type=&lat=&lng=`.
Đọc438 hồ sơ có tên phân khu, lấy metadata bằng `/map-service/detail-layer?id=...`:
template, source link, tâm, max_zoom. Các responses được mở bằng browser thông thường;
terminal trả403 thì không vượt challenge, không dùng cookie/tài khoản/token.

422 template khác nhau; bỏ trùng26 nguồn cũ, bản lấy ý kiến và bản QHGT.406 template
mới lấy mẫu hữu hạn,395 có ảnh đủ dùng ở zoom15+;11 chưa dùng được giữ ngoài registry.
Rà tên hồ sơ lần cuối loại thêm5 bản lấy ý kiến viết tắt `(lyk)`, còn390 nguồn mới được dùng.
Tổng **416 nguồn /48 tỉnh**, chung một nút QH Phân khu, không cần tick từng đồ án.
Tỉnh chỉ được đánh dấu có dữ liệu khi có ít nhất một nguồn, không nghĩa phủ kín tỉnh.

Khung tải là bao pixel alpha ở ảnh tổng quan, cộng vùng pixel đã thấy ở zoom13+;
244 nguồn đang dùng đo được lại ở zoom11,143 giữ bao zoom8, ba nguồn tổng quan không đủ dùng
giữ khung huyện. Các bao này là chỉ mục tải, không phải ranh phê duyệt. Đối chiếu
tỉnh cũ bằng geometry địa giới local và bbox ven biển; tên tỉnh mới trong hồ sơ
không tự quyết định coverage cũ. Ví dụ đồ án Mekong trả ở Cần Thơ nhưng tâm bản vẽ
nằm Hậu Giang cũ được đưa vào Hậu Giang. Audit lưu cả catalogue scopes và reassignment.

12 tỉnh chưa có nguồn đạt kiểm tra: **Bạc Liêu, Bến Tre, Cao Bằng, Gia Lai, Hà Giang,
Hà Tĩnh, Hòa Bình, Lai Châu, Ninh Bình, Phú Thọ, Tuyên Quang, Đồng Tháp**. Đây không
phải kết luận không có phân khu; có thể còn hồ sơ chưa lộ trong danh mục huyện.

## Lượt rà ban đầu — lịch sử

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

Rà tiếp mục **QH khác của43 tỉnh**, thu387 tên hồ sơ và mở17 trang đồ án có
nhãn phân khu.262 mẫu tile bổ sung (tổng580) xác minh thêm10 nguồn có ảnh đọc được
ở zoom15+: **Bắc Kạn, Cần Thơ, Hà Nam, Hưng Yên, Nghệ An, Quảng Ngãi, Sơn La,
Thanh Hóa, Vĩnh Long, Yên Bái**. Nhiều nguồn chỉ phủ đô thị hoặc một khu công nghiệp;
đây không phải khẳng định phủ kín26 tỉnh.

Bảy ứng viên Kon Tum, Lào Cai, Long An, Sóc Trăng, Trà Vinh, Vĩnh Phúc và Điện Biên
chưa đăng ký: các mẫu zoom gần trả403 hoặc chưa có ảnh đủ rõ tại vị trí kiểm.
Không vượt403, không phóng đại ảnh tổng quan zoom8/10 thành nguồn đọc được.
Cà Mau có nhãn trộn phân khu/chi tiết/nông thôn mới nên chưa nhận làm phân khu.
Còn34 tỉnh ngoài phạm vi GIS HCM chưa có nguồn mới đạt bước kiểm này, gồm Kiên Giang.
Danh mục tại landing page thường phụ thuộc huyện mặc định; vẫn có thể còn đồ án
ở huyện khác. Không coi việc rà43 danh mục này là đã rà hết từng huyện toàn quốc.

## File và cơ chế

- `config/planning_partition_reference.json`:416 catalogue entries, exact template,
  province IDs cũ, bounds điều hướng, native/display zoom đã kiểm.
- `config/planning_partition_reference_audit.json`:63 trạng thái controls,43 danh mục
  ban đầu,580 mẫu ban đầu; `district_survey` giữ671 huyện,438 record được định danh,
  exclusions/skips/reassignments. `provinces[].schemes[]` giữ metadata và6795 mẫu,
  trong đó6710 mẫu thuộc390 nguồn mới được dùng; năm draft LYK giữ metadata với status
  loại trừ. Không chứa ảnh, cookie hay dữ liệu người dùng; audit không gửi client.
- `PARTITION_SOURCE_RULES` trong `config/planning_regions.py`: exact descriptors
  gồm cả source_url, coverage_provinces, area_id. Context template đưa chúng vào
  `RADAR_PARTITION_SOURCE_RULES`, client chỉ cho partition reference đã đăng ký.
- `services/planning_live.py` append lớp mới. Catalogue hiện613 entries, cap1024.
  Tăng cap chỉ cho số lượng hồ sơ; từng reference vẫn đối chiếu exact source rules,
  không nới host hoặc cho phép template tùy ý. Metadata mới gzip khoảng47KB trước
  khi cộng rules và các nhóm khác; không tải ảnh trong bước đọc metadata.
- Source picker tự chuyển sang reference khi tỉnh đó không có GIS khả dụng,
  và quay về GIS khi về HCM. Bản vẽ/PDF cũ vẫn giữ; nhãn source trung tính.
  Không ghi tên/link provider ở UI lớp phân khu mới theo yêu cầu người dùng;
  provenance vẫn nằm trong config/audit, không gắn nhãn “GIS chính thức”.
- Layer chỉ mount theo viewport/bounds và zoom đủ gần, không preload toàn tỉnh.
  Tile256/512 source dùng đúng XYZ world cell256 như nguồn. URLs source khác
  nhau giữ cache identity khác nhau. Bản đồ nền/listing/ranh không đổi nguồn.
- `planning_native_tiles.js:createReference` dùng lại pool4 tile dùng chung của native
  GIS. Chỉ phân khu tham khảo dùng loader mới; xếp hàng trước gán image.src, timeout15s
  bắt đầu khi thực sự tải; unload/remove hủy cả ảnh đang tải và việc còn xếp hàng.
  Override `_abortLoading` hủy cả queued/active ở zoom cũ trước khi gọi Leaflet,
  vì queued img chưa có src không phát `tileabort`. Timeout dùng ảnh trống với
  fragment riêng để Leaflet không bỏ qua `done(error)` vì trùng sentinel của nó.
  Giữ browser HTTP cache, không proxy mới, không bake opacity vào ảnh. Tile256/512
  hợp lệ; không thêm canvas composite giữa các hồ sơ chưa xác minh thứ tự pháp lý.
- zIndex dùng theme band1024 để hàng trăm sheet phân khu vẫn dưới chi tiết/chung;
  thứ tự sheet trong cùng theme cố định theo registry, không suy ngày phê duyệt mới nhất.
- Nguồn Bình Phước/Bình Thuận/Đắk Nông cần zoom15+, Huế14+; chọn vùng tự nâng
  tới mức có ảnh. Khi người dùng zoom xa, dừng requests và hiện gợi ý zoom gần.
- Đồ án riêng có `focus_bounds` quanh vị trí đã có ảnh, chỉ dùng để điều hướng;
  không dùng khung ảnh đang thấy để cắt độ phủ thực tế của nguồn. Nút xem vùng và
  chọn toàn tỉnh khi đang bật phân khu đưa tới vị trí này; chọn huyện cụ thể giữ huyện.
  `focus_bounds` cũng nằm trong exact source rules, client từ chối descriptor bị đổi.
  Zoom floor chỉ lấy nguồn của theme đang chọn: bật thêm2030/địa giới không kéo
  mức zoom của phân khu Bình Phước xuống dưới15. Runtime test tái hiện12→15.
- Không có geometry quy hoạch vector mới; không bổ sung tra giao thửa ở các tỉnh
  chỉ có raster. Không làm tiếp ranh thửa các tỉnh còn thiếu.

## Kiểm chứng và giới hạn

Registry tests đối chiếu exact descriptors, positive samples, coverage và zoom.
JS tests từ chối template/host/theme/province bị đổi, giữ source selection cũ khi
còn dùng được. Kiểm thực browser local tại Hà Nội và Bình Phước/Đồng Xoài thấy
pixel phân khu, opacity50%, toggle+zoom; mobile390px có ảnh và dock gọn.
Đợt đồ án bổ sung kiểm browser Cần Thơ: chọn tỉnh tự tới ảnh, toggle+zoom14,
18 tile đã load, desktop và mobile390x844 có ảnh.134 JS tests, overlay/native
runtime và29 Python tests đạt; hai test dùng terminal browser bị treo đã dừng,
thay bằng kiểm rendered-browser qua CUA. Chưa kiểm render riêng cả26 nguồn.

Đợt ghép huyện:135 JS tests,30 Python tests và runtime overlay/native đạt. Test
Long An kéo giữa hai đồ án xa gỡ sheet cũ/giữ sheet mới, tắt/bật đúng; test hàng đợi
hai layer chia4 ảnh active, hủy queued/unload/remove và không gọi callback muộn;
  zoom abort giải phóng slot ngay, zoom mới không chờ15s; timeout thực sự settle.
test350 phân khu giữ dưới lớp chi tiết. Kiểm browser bản trước tối ưu cuối thấy ảnh
Long An và Vinh, nhưng Vinh tải quá nhiều sheet chồng nhau. Đã thu bao tải và thêm
pool4 như trên; **chưa kiểm rendered-browser sau tối ưu cuối vì Work settings tắt
browser giữa lượt**. Không báo phần đó đạt hay claim kết quả chịu tải1000 user.

Ảnh mẫu dương tính và label control không thay thế đối chiếu quyết định/đồ án
gốc. Không coi416 nguồn này là hoàn thành phân khu toàn quốc. Các tỉnh còn thiếu
cần tiếp tục rà đồ án cấp huyện/xã trong kho bản đồ; không lấy QHC/SDĐ2030 lấp
vào lớp phân khu. Không clone archive ảnh hay crawl tile toàn quốc.

Rollback: bỏ các entries reference cần tắt khỏi config rồi restart web workers;
không xóa nguồn GIS HCM hoặc layers2030. Metadata public có TTL60s; thay descriptor
phải bump asset version tương ứng. Tắt từng entry không đổi parcel snapshot.
