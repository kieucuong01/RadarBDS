# QH Phân khu các tỉnh còn lại — nguồn Guland

Ngày: 2026-11-01. Trạng thái: **đã triển khai local16 nguồn tại `6b5ae926`; chưa phủ đủ các tỉnh còn lại**.
Baseline: `945274fc`, `docs/maps-agent-guide.md`.

## Yêu cầu mới nhất

Người dùng đã đổi quyết định: dùng **Guland** cho lớp phân khu các tỉnh còn lại,
không tiếp tục tích hợp các GIS tỉnh trong đợt này. Giữ GIS HCM/Bình Dương/BRVT
đang có; không thay lớp hiện hữu bằng Guland nếu chưa được yêu cầu.
Bộ chọn tiếp tục dùng 63 tỉnh/thành cũ; đích mở rộng là 60 tỉnh ngoài ba địa bàn
đã có GIS HCM mới. Người dùng không muốn ghi tên/nguồn Guland trên giao diện.
Metadata/URL/evidence kỹ thuật vẫn cần giữ nội bộ; không gán source_kind chính thức
cho nguồn tham khảo hoặc giả định một URL public là quyền phát hành lại raster.

## Phương án đã chọn và phạm vi

Đã cân nhắc GIS-only, GIS-first/reference-fallback và Guland. Người dùng chọn
Guland cho phần mới. Giữ UI QH Phân khu, 50% opacity, vệ tinh, viewport loading,
bộ lọc tin rao, ranh thửa và các lớp khác như hiện tại. Không mở lại ranh thửa
các tỉnh thiếu. Không lấy SDĐ2030/QH chung thay thế phân khu để đạt số lượng tỉnh.

Chỉ publish overlay xác minh được ở nguồn. “Rà đủ 60 tỉnh” khác “phủ đầy phân khu
60 tỉnh”; có nơi chưa công bố hoặc không truy cập được. Báo riêng ready/partial,
chưa kiểm, không thấy lớp và lỗi truy cập. Không kết luận vùng trống không có
quy hoạch và không bịa tỷ lệ 1/2000 cho tất cả nguồn.

## Nguồn cần kiểm và trở ngại hiện tại

Các trang `https://guland.vn/soi-quy-hoach/<tinh-cu>` là điểm vào theo registry
2030 đã có, nhưng **chưa có actual partition template ngoài HCM được xác minh
trong lượt rà này**. Trang SEO/legend có chữ phân khu chưa chứng minh provider
đó có lớp phân khu ở tỉnh đang chọn. Captures cũ chỉ giữ control2030, không đủ
để dùng cho phân khu. HTTP trực tiếp Cần Thơ/Hà Nội trả challenge/403.

Ở bước khảo sát ban đầu công cụ browser báo `Local browser use is disabled in Work settings`; đã khắc phục và rà63 landing controls, kết quả trong `../../planning_sources/national-partition.md`.
Cần người dùng bật browser để quan sát UI/public network bình thường. Không đổi
user-agent/host/signed params để vượt challenge, không sao chép token trả phí,
không dùng đăng nhập/API key của ứng dụng khác. Nếu public UI cũng chặn, giữ
nguồn ở trạng thái không truy cập được, không thử vượt cơ chế đó.

## Thiết kế registry và catalogue

Thêm registry phân khu riêng (không dùng registry SDĐ2030 làm nguồn phân khu):
entry có ID, province coverage cũ, provider/source_kind, exact source URL và
public template, bounds/coverage windows, native/display zoom, grid/tile size,
layer type evidence, tên đồ án/tỷ lệ/quyết định nếu xác minh được, ngày kiểm,
revision và source-image/metadata digests. License/credit constraints được lưu
để dùng nguồn đúng điều kiện; không đổi branding source pixels trong task này.

`planning_regions.py`/`planning_live.py` đưa entries và exact descriptors vào
catalogue. `planning_overlay.js` cho phép reference ở theme partition chỉ khi
có descriptor đăng ký; không nới host regex toàn cục. Giữ nguồn GIS HCM nguyên
vẹn. `planning_area.js:coversProvince` dùng coverage_provinces được kiểm, không
bbox overlap để suy tỉnh mới. Không đưa URL arbitrary từ request vào gateway.

Với phân khu ở tỉnh mới, source UI chọn reference trung tính “Bản đồ phân khu”;
GIS HCM và bản vẽ cũ giữ lựa chọn hiện tại. Không cần auto GIS/reference blend.
Nếu nguồn mới có các bản chồng nhau, phải xác định provider/đồ án và thứ tự vẽ
trong registry; không suy thiếu dữ liệu từ alpha để ghép nguồn khác âm thầm.

Giữ cap catalogue256 entries. Nếu số đồ án vượt cap, registry tóm tắt theo tỉnh
và tải manifest tỉnh được chọn; không đẩy cả catalogue unbounded vào browser.
Các manifest thiếu/sai phải được loại riêng trước catalogue công khai, không
làm invalid cả lớp GIS HCM hiện đang hoạt động.

## Tải và cache

Ưu tiên tile public có sẵn. Chỉ tile đang thấy và một buffer; bật cả lớp không
tải toàn quốc/cả tỉnh. Giữ native min zoom đã kiểm; không có pyramid thấp thì
nhắc zoom gần, không fan-out hàng trăm ô. Khai báo bounds/grid/512-vs256 đúng
nguồn; không sửa tọa độ để ép ảnh trông vừa với bbox tỉnh.

Tiếp tục abort/newest-response, loading task, offscreen removal và fresh-memory
reuse. Key cache có provider ID + revision + render signature + z/x/y; không
reuse HCM key chỉ theo theme. HTTP public không gửi credentials. Không thêm
proxy raster mới khi chưa cần; nếu nguồn không cho direct public access thì
không âm thầm dùng server để né restriction. Mỗi provider có disable flag và
rollback độc lập, không tắt nguồn HCM hoặc lớp2030 đang hoạt động.

Giữ ảnh/PDF nguồn cũ đã làm. Không tạo national parcel lookup hoặc giao quy hoạch
theo thửa từ raster; card thửa/GIS lookup hiện tại giữ scope nguồn hiện có.

## Các bước bàn giao

1. Quan sát actual controls/network public và kiểm layer classification cho
   60 tỉnh còn lại; ghi mẫu kiểm hữu hạn, không tải archive cả tỉnh/toàn quốc.
2. Bổ sung registry+client support, tích hợp các provider đã đủ bằng chứng,
   bắt đầu tỉnh có source phân khu public xác minh được. Báo số tỉnh/đồ án thật
   được thêm và gaps; không coi framework/registry trống là đã hoàn thành maps.
3. Kiểm release sạch, CI, browser desktop/mobile, commit/push/deploy khi đến bước
   triển khai đã được duyệt. Giữ riêng dirty work Đồng Nai/RegionalParcels.

## Gate kiểm chứng

- Control/metadata đúng phân khu, không annual land-use,2030,chung,draft.
- HTTP/dimensions/alpha đúng, vị trí và zoom mẫu hợp lý;200 không đủ chứng minh.
- Source exact descriptors, IDs unique, coverage cũ đúng, HCM catalogue còn valid.
- Province switch chỉ bật source province hợp lệ; ngoài vùng/tỉnh chưa có source
  không hiện nút hoạt động giả. Cho bật/tắt, opacity, zoom/pan không lệch.
- Request count, byte caps, cancel, warm reuse; không layer stale sau off/on.
- Privacy: errors/lookup/original/OCR không cache public. Chỉ nguồn public
  anonymous trong đợt này; không thêm luồng credential hoặc nguồn đòi quyền mới.
- Test nhóm planning_overlay runtime, planning_area và registry mới; nếu sửa
  header/cache thì thêm privacy regressions. Không stress GIS hay Guland public
  bằng cold nationwide loads. Snapshot smoke không đại diện1000-user capacity.

Builder-check: đã review; chưa có template Guland phân khu ngoài HCM được xác
minh là blocker khảo sát, không phải lý do publish provider chưa đủ gate.

## Quyết định đã duyệt

Người dùng duyệt thiết kế **Guland cho phần phân khu mới, giữ GIS HCM hiện có,
tích hợp theo source thực đã kiểm và tải theo viewport**. Implementation plan:
`../plans/2026-11-01-national-partition.md`. Browser enable là điều kiện khảo sát source đang thiếu, không
phải lý do tự tạo URL tile hoặc báo đã làm xong.

## Phụ lục: nghiên cứu GIS đã dừng theo quyết định mới

Các endpoint dưới chỉ là evidence khảo sát cũ, **không nằm trong implementation
đợt Guland này**. Bình Phước export layerDefs có negative control1=0 cho ảnh
GIỐNG HỆT filter type20; dynamicLayers disabled. Vì vậy cached raster đó không
được publish như partition-only, dù query có type20 thật.

### Evidence tham khảo

| Nguồn công khai | Kết quả đã quan sát | Việc còn cần |
| --- | --- | --- |
| `https://gisserver.cantho.gov.vn:6443/arcgis/rest/services/_SoXayDung/QHPK_SuDungDat/MapServer` | Layer 0 tên “Quy hoạch phân khu - Sử dụng đất”, count 11.483; export anonymous ảnh 256px có nội dung tại bbox 105.74,10.01,105.81,10.08 | Native grid VN2000 custom, cần dynamic export sang 3857; kiểm các vùng khác và tình trạng đồ án |
| `https://quyhoach.haiphong.gov.vn/assets/appconfig.json` | App config trỏ `https://dataquyhoach.haiphong.gov.vn`; style `assets/styles/haiphong_qhxd.json` dùng VectorTileServer 293, source layers 1850/1851, filter `capDoQuyHoach=2` | Anonymous service còn timeout; không sao chép public app API key. Cần kiểm quyền dùng/vector adapter trước khi ready |
| `https://gis.dongnai.gov.vn/arcgis/rest/services/SuDungDat/ThongTinQuyHoachSDD_Cache/MapServer` | Layer 11 có `LoaiQuyHoach`, `MaDuAn`; `LoaiQuyHoach=20` trả 27.922 zones. `ThongTinDoAn/MapServer/0` có 11 schemes phân khu, 10 có approval flag 1. Export layer33 type20 và negative control1=0 cho ảnh giống hệt; dynamicLayers disabled | Nguồn Bình Phước cũ, không phủ Đồng Nai cũ. Raster export mixed không đủ gate phân khu; query/vector cần nghiên cứu riêng, không nằm trong task Guland mới |
| `https://quyhoach.xaydung.gov.vn/vn/loai-quy-hoach/5/48/quy-hoach-phan-khu-do-thi.aspx` | Có hồ sơ đồ án phân khu từng địa phương | PDF/JPG không tự là tile georeference; không gắn bằng bbox tỉnh |
| Guland public theo tỉnh | Có loại lớp quy hoạch trong ứng dụng; chưa có template phân khu ngoài HCM được xác minh trong lượt này | Chỉ chấp nhận template quan sát thực và bằng chứng phân khu; không suy từ trang SEO hoặc button chung |
| GIS Huế/Đà Nẵng/Long An | Một số địa chỉ nguồn lỗi DNS/HTTP/TLS trong lần rà | Không bypass TLS; không kết luận tỉnh không có phân khu chỉ vì cổng lỗi |

