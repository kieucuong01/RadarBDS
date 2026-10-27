# Bản thử quy hoạch Bến Cát trên Maps

Bản local ngày **27/10/2026** có bộ chọn theo **lớp bản đồ + nguồn**, mặc định
GIS. Đã đồng bộ đủ tám ảnh GIS phân khu, chụp ngày **27/10/2026**, cùng bảy
ảnh thay thế từ bản vẽ/PDF đã làm trước đây. Thêm một lớp **quy hoạch chung
đô thị 1/10.000 từ GIS**, tổng cộng 9 lớp GIS sẵn sàng.
Các bản vẽ, cấu hình căn chỉnh và ảnh gốc trước đây vẫn được giữ nguyên.
Mở Maps mặc định hiển thị toàn bộ GIS của Bến Cát và Thủ Dầu Một.
Chỉ chọn loại bản đồ, nguồn và độ hiển thị; không còn tick phường/thành phố.

**GIS phân khu đã đủ 8/8 phường.** Đường tải curl trước đây bị timeout;
Python requests tải được metadata/ảnh từ public export, không cần đăng nhập.
Không tự chuyển sang PDF khi GIS thiếu dữ liệu. Theo yêu cầu mới, lớp sử
dụng đất cấp huyện đã được gỡ khỏi catalog và giao diện; các tài liệu nghiên
cứu cũ vẫn nằm trong thư mục ignored.

| Lớp | Nguồn chọn | Dữ liệu hiện sẵn sàng |
|---|---|---|
| Phân khu 1/2.000 | GIS (mặc định) | Đủ tám phường, giữ tọa độ native EPSG:3857, bản lưu 27/10/2026 |
| Phân khu 1/2.000 | Bản vẽ / PDF | Bảy lớp đã căn chỉnh; Mỹ Phước chưa có lớp từ bản vẽ |
| Quy hoạch chung đô thị 1/10.000 | GIS (mặc định) | Một lớp toàn Bến Cát, giữ màu và tọa độ gốc, bản lưu 27/10/2026 |
| Quy hoạch chung đô thị 1/10.000 | Bản vẽ / PDF | Chưa có overlay từ bản vẽ; không thay bằng dữ liệu phân khu |

Mỗi lớp có công tắc, lựa chọn nguồn và độ hiển thị riêng. Đổi nguồn phân khu
giữ nguyên trạng thái lớp quy hoạch chung. Một lớp quy hoạch chung chỉ được
thêm một lần dù chọn nhiều phường. Chưa có lớp chi tiết 1/500.

## Quy hoạch chung đô thị GIS

- Dịch vụ chính thức: `HCM/SuDungDat_QHC_HCM/MapServer/export`, được menu
  công khai đặt dưới **Quy hoạch chung đô thị → Sử dụng đất → Nền**. Không
  dùng dịch vụ phân khu hay quy hoạch sử dụng đất cấp huyện cho lớp này.
- Hồ sơ đối chiếu: [QĐ 1573/QĐ-UBND ngày 01/07/2022](https://congbao-aloha.s3.hcm-1.cloud.cmctelecom.vn/form-attachments/QD%201573.pdf),
  Điều chỉnh tổng thể Quy hoạch chung thị xã Bến Cát đến năm 2040. Trang17,
  mục15.b liệt kê bản đồ sử dụng đất/phân khu chức năng tỷ lệ1/10.000.
- Xuất ảnh2400×2400 theo EPSG:3857; giữ nguyên RGB, WebP lossless. Chỉ
  cắt alpha bằng hợp tám mặt nạ đường bao phân khu GIS đã xác minh, lấy mẫu
  theo tọa độ native. Đây là **giới hạn vùng hiển thị**, không khẳng định là
  ranh riêng của đồ án quy hoạch chung. Tổng diện tích được so thô với23.435,4ha.
- Truy vấn đường bao QHC bị WAF từ chối; không đổi cú pháp để vượt chặn.
  Không xác nhận phiên bản raster tương ứng chính xác quyết định1573 hay
  đã cập nhật điều chỉnh cục bộ1337/2025 và1840/2025. Giao diện ghi rõ giới hạn.
- Cấu hình hash và nguồn: `config/ben_cat_gis_general.json`. Dựng lại từ
  đầu vào đã lưu: `python scripts/build_ben_cat_gis_general.py`. Đầu vào
  `export.json`, `source.png`, hồ sơ nghiên cứu và kết quả nằm trong
  `.local/planning-ben-cat/general-plan/`; cần đủ tám mặt nạ GIS phân khu.
  Builder kiểm tra SHA-256, endpoint QHC, lưới tọa độ, vùng hiển thị và độ phủ
  ảnh trước khi xuất manifest. Không dùng đường dẫn localhost do GIS trả về.

## Các lớp bản vẽ/PDF được giữ lại

| Khu vực | Nguồn ảnh | Sai lệch lớn nhất tại 3 điểm thử OSM |
|---|---|---|
| Thới Hòa | Bản vẽ công bố có đóng dấu, QĐ 2909 | 53,6 m |
| Tân Định | Bản vẽ công bố có đóng dấu, QĐ 2910 | 31,1 m |
| Hòa Lợi | Bản vẽ công bố có đóng dấu, QĐ 2911 | 24,1 m |
| Chánh Phú Hòa | Bản vẽ công bố có đóng dấu, QĐ 2912 | 10,7 m |
| Mỹ Phước | Chưa có lớp phủ từ bản vẽ/PDF; chọn nguồn GIS để xem | — |
| An Điền | Bản vẽ đơn vị tư vấn A.A.P; ô phê duyệt còn trống | 85,7 m |
| An Tây | Bản vẽ A.A.P có ghi QĐ 1451; chưa có dấu phê duyệt trên ảnh | 8,9 m |
| Phú An | Bản vẽ A.A.P có ghi QĐ 1452; chưa có dấu phê duyệt trên ảnh | 19,3 m |

Các số đo chỉ áp dụng tại điểm kiểm tra, không chứng minh độ chính xác toàn
vùng hay từng thửa. Bảy lớp căn chỉnh thủ công dùng 6 điểm khống chế và 3 điểm
kiểm tra không dùng để fit. Phía bắc Chánh Phú Hòa và một số vùng ven sông
An Tây/Phú An chưa có kiểm tra đường sá độc lập. Nguồn bản vẽ An Điền chỉ nên xem tổng quan
ở mức khoảng 100 m. Giao diện đánh dấu riêng ba lớp **Nguồn tư vấn**; không
gán trạng thái bản vẽ phê duyệt cho các ảnh này.

Các lớp GIS lấy từ [cổng GIS](https://gisxaydung.tphcm.gov.vn/tracuuttqh), bộ
hiện tại chụp ngày **27/10/2026** (Mỹ Phước từng có bản đầu ngày 26/10).
Builder cắt ảnh theo đường bao đồ án xuất từ dịch vụ
`ThongTinDoAn`, lọc số quyết định và ngày ký riêng từng phường (Mỹ Phước là
2913 ngày 28/12/2022), cùng lưới điểm ảnh với ảnh sử dụng
đất `SuDungDat_QHPK_HCM_V2`. Không tự vẽ ranh giới phường thay thế. Diện tích
mặt nạ ảnh Mỹ Phước khoảng 2.175 ha so với số tham chiếu hồ sơ 2.150,21 ha chỉ là phép
kiểm tra thô, không phải diện tích pháp lý. Chưa tải được chú giải độc lập;
liên kết “Cổng GIS và chú giải” mở nguồn gốc, không tạo chú giải giả hay số
sai lệch bằng 0. Ảnh GIS có độ phân giải thấp hơn các lớp PDF.

URL nguồn, SHA-256, điểm ảnh/tọa độ và ghi chú từng lớp nằm trong
`config/ben_cat_planning_*.json`; danh mục nằm ở
`config/ben_cat_planning_catalog.json`. Chưa xác minh đầy đủ hiệu lực hiện
tại của mọi đồ án và quyền phát hành lại ảnh dẫn xuất. Bản này chỉ dùng local.

## Mở bản thử

Chạy từ thư mục gốc của repo, với PostgreSQL local đã hoạt động:

```powershell
$py = 'C:\Users\ASUS\AppData\Local\Programs\Python\Python312\python.exe'
& $py -X utf8 scripts/run_planning_pilot.py
```

Mở `http://127.0.0.1:5055/`, chọn **Maps → Quy hoạch · Bình Dương**.
Toàn bộ GIS tự hiển thị; bật/tắt riêng Quy hoạch phân khu hoặc Quy hoạch chung
đô thị, chọn nguồn và độ hiển thị. **Xem vùng có quy hoạch** đưa bản đồ về
vùng phủ của các loại đang bật.
Kéo thanh độ hiển thị riêng của mỗi lớp để đối chiếu với
bản đồ đường phố hoặc ảnh vệ tinh. Có nút toàn màn hình và chú giải gốc.

Runner chỉ nghe loopback, chặn Host lạ/proxy, trả `private, no-store`.
`app.py` thông thường không bật pilot và không phục vụ ảnh quy hoạch local.
Thiếu/hỏng ảnh chỉ làm lớp quy hoạch không sẵn sàng, bản đồ nền vẫn mở được.

## Nguồn và cách dựng lại

- [Bài công bố của Bến Cát](https://bencat.binhduong.gov.vn/cong-khai-thong-tin/quy-hoach-phan-khu-ty-le-12000-cac-phuong-tren-dia-ban-thi-xa-ben-cat-den-nam-2040).
- [Thư mục hồ sơ Thới Hòa](https://drive.google.com/drive/folders/124MnQCo-BAyNE7M6cvK11GO_kyKLl0_Y).
- [Bản vẽ gốc](https://drive.google.com/file/d/12OJDgFVXtPZkXh2DGk5XzEeRAwbCEbiv/view),
  tên `4.BAN VE A0 FIT THOI HOA.pdf`, 101010377 bytes.
- SHA-256: `9a7c8e9e4112f706ba1ddab9fb0024a456ac0f8e0b8184089187bfe466031151`.

Lưu PDF đúng hash tại `.local/planning-ben-cat/thoi-hoa-original.pdf`.
Các thư viện dựng raster: NumPy, pypdfium2, Pillow, OpenCV, pyproj.
Chạy `python scripts/build_ben_cat_planning_pilot.py` để dựng WebP, manifest
và `alignment-audit.json`. Toàn bộ tệp nhị phân nằm trong `.local` bị Git bỏ qua.

`config/ben_cat_planning_pilot.json` ghi điểm ảnh, tọa độ OSM tham chiếu,
ID nút/đường, mặt nạ cắt ảnh và vùng chú giải. Phép affine chuyển điểm ảnh
sang EPSG:3857 trước khi tạo ảnh north-up cho Leaflet. Mặt nạ chỉ cắt vùng
hình ảnh, không phải dữ liệu ranh giới pháp lý.

## Độ chính xác và giới hạn

- 6 điểm dùng để căn chỉnh: RMSE 23,6 m.
- 3 điểm kiểm tra không dùng để fit: RMSE 37,2 m, lớn nhất 53,6 m.
- Các điểm kiểm tra vẫn dùng cùng nguồn tham chiếu OSM; không phải khảo sát
  địa chính độc lập. Chưa chứng minh sai số trên toàn vùng, nhất là phía tây.
- Ngưỡng 150 m trong builder chỉ phát hiện lệch thô, không phải chuẩn nghiệm thu.
- Chưa xác minh hiệu lực hiện tại và quyền phát hành lại dữ liệu dẫn xuất.
  Bản này dùng thử trải nghiệm theo khu vực, không xác định quy hoạch từng thửa.
- Không suy diễn quy hoạch từ marker tin rao có vị trí gần đúng.

## Kiểm chứng

Ngày 26/10/2026: kiểm thử local routes, hash ảnh, startup thiếu dữ liệu,
manifest không hợp lệ, ảnh lỗi/thử lại, hủy fetch khi đóng Maps và phản hồi
đến muộn; kiểm tra trực tiếp desktop và viewport 390×844 bằng trình duyệt.
Đã xác nhận bật/tắt, opacity 30%/65%, đổi nền vệ tinh, đóng/mở lại và chiều cao
canvas mobile 763 px. Đã sửa inline `position: relative` của Leaflet làm
canvas mobile cao 0 khi chuyển từ desktop.

HTTP thực: home/manifest 200, private/no-store, không có public-cache marker;
PDF gốc và Host lạ 404. Local hiện không có tin phù hợp bộ lọc nên chưa kiểm
chứng click marker thật; các hợp đồng Maps hiện có được kiểm tra tự động.
Tổng kết kiểm tra tập trung: 79 test đạt, 5 test UI/DB hoặc trình duyệt độc lập
không chạy trong lượt này. JS syntax và diff whitespace đều đạt.

```powershell
& $py -X utf8 -m pytest tests/test_planning_pilot.py tests/test_listing_map_js.py -q
node tests/planning_overlay_runtime.cjs
```

Chưa commit, push hay deploy. Điều kiện phát hành production trong audit cũ
vẫn còn hiệu lực; bản local này là thử nghiệm riêng theo yêu cầu người dùng.

## Chọn nhiều khu vực, 27/10/2026

Phần dưới ghi lại giai đoạn dùng độ hiển thị chung; bản hiện tại đã có lựa
chọn GIS/PDF và độ hiển thị riêng theo lớp như mô tả ở đầu tài liệu.

- Mỗi phường có ô chọn riêng. Ô thành phố chọn/bỏ toàn bộ các phường có dữ
  liệu trong nhóm; trạng thái một phần được thể hiện bằng checkbox mixed.
  Hiện chỉ có dữ liệu Bến Cát. Nhóm thành phố khác chỉ xuất hiện khi catalog
  có dữ liệu tương ứng; không giả lập thêm lớp quy hoạch cho khu vực chưa có.
- Nút đến vùng dùng hợp của các bounds đã chọn. Thanh độ hiển thị áp dụng
  cho tất cả lớp. Dropdown hồ sơ chỉ đổi phần nguồn/chú giải đang xem.
- Tải lỗi một ảnh vẫn giữ các ảnh khác; bỏ chọn/chọn lại phường đó để thử lại.
  Thứ tự lớp ổn định theo catalog, giữ bản sửa teardown trước khi xóa listener.
- Node kiểm tra chọn nhóm nhiều thành phố bằng dữ liệu giả trong test, chọn
  nhiều phường, union bounds, opacity chung, lỗi một lớp, thử lại, tắt/bật và
  dọn hook zoom. Pytest tập trung: 90 đạt, 2 test trình duyệt độc lập bỏ qua.
- Browser desktop xác nhận bật cả tám lớp, bỏ riêng hai phường còn sáu,
  opacity 40% trên cả sáu ảnh, tắt còn 0 và bật lại đúng 6; không có lỗi console.
- Mobile CSS 390×844: chọn/bỏ nhiều phường, tắt/bật rồi zoom vẫn đúng sáu
  lớp; chọn thành phố trở lại tám. Viewport đã được đặt lại sau kiểm tra.
  Review tập trung không phát hiện lỗi cần sửa; Node kiểm tra thêm phản hồi
  load/error cũ không được làm mất ảnh thay thế sau khi thử tải lại.

## GIS làm nguồn mặc định và hai lớp độc lập

Catalog có 18 bản ghi, phân biệt `theme`, `source`, `area_id`, `scope`:
`partition` và `urban_general`; `gis` và `document`. Địa chỉ thư mục ảnh
do config cố định, được resolve/kiểm tra không ra ngoài thư mục pilot.
Giới hạn catalog 64 bản ghi. Nguồn chưa sẵn sàng luôn được ghi rõ; không dùng
ảnh PDF dưới nhãn GIS, không tự đổi sang lớp phân khu để thay QHSDĐ.

Builder mới `scripts/build_ben_cat_gis_partitions.py` và
`config/ben_cat_gis_partitions.json` dùng ảnh/đường bao trên cùng lưới native.
Trước khi dựng phải xác minh tên phường, số quyết định và ngày/năm của đồ án;
lọc tiền tố số quyết định đơn lẻ chưa đủ. Bộ hiện tại khóa cả ngày ký bằng
điều kiện `NgayKy_DC`, đối chiếu số quyết định/ngày ký/phường với hồ sơ công
bố. Kiểm tra âm ngày sai trả ảnh rỗng, chứng minh máy chủ có áp dụng bộ lọc.
Public API không mở truy vấn thuộc tính: không khai rằng đã lấy được các
thuộc tính GIS bị hạn chế. Tám lớp đều có request, hash, mask và audit riêng
ở `.local/planning-ben-cat/gis-partitions/<slug>/`, giữ ngày chụp 27/10/2026.

Nguồn cấp huyện (lịch sử nghiên cứu; đã gỡ khỏi giao diện ngày27/10/2026):

- [QHSDĐ đến 2030](https://bencat-hochiminhcity.gov.vn/cong-khai-thong-tin/quy-hoach-su-dung-dat-den-nam-2030-thi-xa-ben-cat),
  QĐ 08 ngày 05/01/2022: bài công bố có bản đồ 1/25.000, nhưng liên kết PDF
  CDN hiện trả 404. Các liên kết bản đồ KHSDĐ 2025 cũng chưa tải được.
- [KHSDĐ 2023](https://bencat-hochiminhcity.gov.vn/cong-khai-thong-tin/ke-hoach-su-dung-dat-nam-2023-thi-xa-ben-cat),
  QĐ 411 ngày 22/02/2023: tải được bản vẽ lịch sử từ thư mục Drive công bố.
  PDF một trang, SHA-256 `b86d1f1c2987d03285c2422bc0a3d1f0e846dfbc8c7b48bcc9580b76f5a54c65`.
  Bản đồ ghi lưới tọa độ nhưng không có GeoPDF/CRS được xác minh; ô phê duyệt
  trên ảnh trống. Chỉ tạo preview 1800×2272 và liên kết mở nguồn, không tạo
  overlay hay coi đây là bản đồ 2030/2025 hiện hành.

URL, hash và lỗi nguồn được lưu trong các `source-manifest.json` /
`source-inspection` dưới `.local/planning-ben-cat/{gis-partitions,district-landuse}`.
Đây là bằng chứng kiểm tra ngày 27/10, không chứng minh dịch vụ luôn không có.

Kiểm thử tập trung: 98 pytest đạt, 2 test trình duyệt độc lập bỏ qua. Node
kiểm tra chuyển GIS/PDF, độ hiển thị theo lớp, lớp cấp huyện độc lập khi thiếu
phân khu, tải lỗi/thử lại, ảnh phản hồi muộn và nhãn preview lịch sử. Review
phát hiện nhãn tỷ lệ cố định và phụ thuộc khu vực vào phân khu; đã thêm test
thất bại trước sửa và xác nhận cả hai lỗi đã được sửa.
Browser bản cuối: desktop/mobile CSS 390×844 chuyển PDF (7 ảnh) sang GIS
(1 ảnh Mỹ Phước), giữ lựa chọn khu vực và độ hiển thị theo lớp; tắt/bật rồi
zoom không có lỗi console. PDF cấp huyện lịch sử chỉ mở preview, không làm
mất lớp phân khu. Đã đặt lại viewport. Chưa kiểm chứng overlay cấp huyện
thực tế vì không có nguồn sẵn sàng; tính độc lập của hai lớp dùng dữ liệu
giả trong kiểm thử Node. Lượt kiểm tra này là trước bước hoàn tất tám GIS
phân khu ghi ở phần tiếp theo; chưa deploy.

## Hoàn tất tám GIS phân khu ngày 27/10/2026

### Sửa tải nền đường phố

Trình duyệt tái hiện ba ô OSM bị `ERR_CONNECTION_REFUSED` trong vùng đang xem;
các ô khác được cache nên vẫn có hình, gây khoảng xám. HTTPS từ máy local tới
cùng ô cũng lỗi; ảnh Esri World_Street_Map tương ứng trả HTTP200. Không phải
ảnh GIS bị mất alpha hoặc lệch tọa độ.

Nền đường phố giữ OSM làm nguồn chính và chuyển toàn bộ nền sang Esri khi có
lỗi ô ảnh đang hoạt động. Chỉ chuyển một lần trong phiên Maps, bỏ qua phản hồi
OSM cũ; nếu nguồn dự phòng cũng lỗi thì báo trạng thái, không chuyển qua lại
vô hạn. Attribution đổi theo đúng nguồn, giữ các lớp quy hoạch và marker.
Ẩn thanh điều hướng dưới khi Maps mở ở mọi chiều rộng để phần credit không
bị che. Asset JS/CSS có phiên bản mới. Chưa deploy production.
Kiểm chứng: 101 test tập trung đạt, 2 test trình duyệt độc lập bỏ qua.
Desktop đổi vệ tinh/đường phố, zoom rồi quay lại: 18/18 ô nền tải được và còn
8 lớp GIS; mobile CSS 390×844: 12/12 ô tải được, 8 lớp GIS. Attribution Esri
hiển thị, không có lỗi JS; viewport đã đặt lại. Không có thay đổi dữ liệu GIS.

Đường tải public export hoạt động bằng requests với Origin/Referer của cổng
nguồn và TLS được xác minh bình thường. Đã bỏ phụ thuộc curl trong downloader,
giữ timeout, dừng khi 401/403, kiểm tra PNG/JSON và từ chối body rỗng trước khi
ghi đè tệp. Không lấy token hay đi vòng endpoint yêu cầu xác thực.

Ảnh màu và đường bao dùng cùng extent/size do máy chủ trả về. Tám đường bao
lọc theo SoQD_DC và đúng ngày ký (28/12/2022 hoặc 15/07/2022); source publication
riêng từng phường được giữ trong config và manifest. Điểm ảnh cắt chỉ đổi
extent; không kéo giãn theo khung phường từ PDF. Mặt nạ được kiểm tra kín,
không chạm mép export, một thành phần liên thông và có dữ liệu màu bên trong.
Không coi các kiểm tra này là khảo sát địa chính hoặc xác nhận hiệu lực pháp lý.

Catalog hiện có tám bản ghi phân khu/GIS overlay_ready; API local trả manifest
và ảnh HTTP200 cho cả tám. Bản vẽ/PDF trước đây và hash nguồn được giữ nguyên.
Sau này tải lại phải ghi đúng ngày chụp thực tế trong config, kiểm tra đầy đủ
bộ ảnh/ranh/metadata trước khi cập nhật trạng thái catalog.

Kiểm chứng mới: **100 pytest đạt, 2 test trình duyệt độc lập bỏ qua**. Đã thấy
test downloader thất bại trước sửa client; thêm kiểm tra body rỗng không thay
ảnh cũ và 401 không thử lại. Kiểm tra ảnh tổng hợp đủ tám phường; không có
đợt review độc lập mới vì subagent hết hạn mức, tác giả đối chiếu hash/grid,
đường bao và ảnh thực. Giới hạn nguồn cấp huyện giữ nguyên: DNS công khai xác
nhận hai portal cũ NXDOMAIN, PDF QHSDĐ2030 vẫn HTTP404, không thay bằng QHPK.

## Lịch sử: bổ sung lớp và sửa zoom ngày 26/10/2026

Phần dưới ghi lại trạng thái ngày 26/10; các trạng thái thiếu lớp đã được
thay bằng danh mục đầy đủ ngày 27/10 ở đầu tài liệu.

Người dùng xác định lỗi xảy ra sau lần tắt/bật lại. Trình duyệt tái hiện được
`Cannot read properties of null (reading 'getZoomScale')` trong Leaflet.
`overlay.off()` trước `map.removeLayer()` đã xóa cả listener `remove` nội bộ,
khiến hook zoom của lớp cũ không được gỡ. Thứ tự mới là removeLayer trước,
off sau. Test Node mô phỏng chính listener này đã thất bại trước sửa và đạt
sau sửa. Trình duyệt kiểm tra lại trên cả hai lớp và khi chuyển khu vực.

| Khu vực | Trạng thái local |
|---|---|
| Thới Hòa | Có lớp phủ, max 53,6 m tại 3 điểm kiểm tra |
| Tân Định | Có lớp phủ, max 31,1 m tại 3 điểm kiểm tra |
| Hòa Lợi | Có bản vẽ QH01 để mở xem, căn chỉnh tọa độ chưa được xác nhận |
| Chánh Phú Hòa | Có bản vẽ QH01 để mở xem, căn chỉnh tọa độ chưa được xác nhận |
| Mỹ Phước | Link hồ sơ trong bài công bố trả 404 |
| An Điền | Thư mục công bố có quyết định, thiếu bản vẽ |
| An Tây, Phú An | Link hồ sơ trong bài công bố trả 404 |

Nguồn các xã: [bài công bố An Điền, An Tây, Phú An](https://bencat-hochiminhcity.gov.vn/tin-tuc/thong-bao-ve-viec-cong-bo-cong-khai-do-an-quy-hoach-phan-khu-ty-le-12000-cac-xa-an-dien-an-tay-va-phu-an-den-nam-2040-20812).
Danh mục, quyết định, hash tài liệu tải được và trạng thái:
`config/ben_cat_planning_catalog.json`.

Tân Định có 6 điểm khống chế và 3 điểm kiểm tra OSM được đối chiếu trực tiếp
với giao lộ trên bản vẽ; RMSE fit 15,4 m, RMSE check 25,1 m. Ghép đặc trưng
ảnh với vùng chồng lấn Thới Hòa chỉ dùng gợi ý vị trí tìm giao lộ, không được
coi là kiểm tra tọa độ độc lập. Các ứng viên ghép Hòa Lợi/Chánh Phú Hòa không
đủ độ phân bố hoặc ghép nhầm cấu trúc bảng, đã bị loại khỏi lớp phủ.

Dựng lại Tân Định và các bản vẽ chưa có tọa độ:

```powershell
& $py -X utf8 scripts/build_ben_cat_planning_pilot.py --config config/ben_cat_planning_tan_dinh.json --output .local/planning-ben-cat/tan-dinh
& $py -X utf8 scripts/build_ben_cat_planning_documents.py
```

Lượt cuối: 82 test tập trung đạt, 5 test UI/DB hoặc trình duyệt độc lập không
chạy; Python/JS syntax và diff whitespace đạt. Review độc lập không có phát
hiện quan trọng. Browser kiểm tra desktop, viewport 390×844, lặp tắt/bật rồi
zoom, chuyển lớp, và mở cả hai bản vẽ nguồn. Tham chiếu OSM và các điểm kiểm
tra vẫn không phải khảo sát địa chính, không chứng minh sai số toàn vùng.

## Dựng lại các lớp bổ sung ngày 27/10/2026

Giữ nguyên các tệp nguồn khớp hash trong `.local/planning-ben-cat/<slug>/`.
Builder thủ công hỗ trợ cả PDF và PNG tư vấn ở đúng khung điểm ảnh gốc:

```powershell
foreach ($slug in @('hoa-loi', 'chanh-phu-hoa', 'an-dien', 'an-tay', 'phu-an')) {
  $configName = $slug.Replace('-', '_')
  & $py -X utf8 scripts/build_ben_cat_planning_pilot.py --config "config/ben_cat_planning_$configName.json" --output ".local/planning-ben-cat/$slug"
}
& $py -X utf8 scripts/build_ben_cat_official_gis.py --config config/ben_cat_planning_my_phuoc.json
```

Builder GIS chỉ đọc snapshot có hash, metadata lưới và URL xuất đường bao đã
lưu; không tự tải lại hoặc suy đoán tọa độ. Manifest không khai báo sai số
kiểm tra thủ công khi dùng tọa độ gốc GIS.

Kiểm tra ngày 27/10: **90 test đạt, 2 test dùng trình duyệt độc lập được bỏ
qua**; kiểm tra browser dùng CUA. Review độc lập không phát hiện lỗi cần sửa
trong dựng GIS, chú giải tùy chọn, đổi lớp và manifest của tám khu vực.
Trực tiếp desktop xác nhận từng lớp tải được, chỉ còn một ảnh phủ, chọn đúng
vùng, lặp tắt/bật và zoom không có lỗi console. Các kiểm tra ngày 26/10 ở trên
là lịch sử, không phải số đếm của lượt hiện tại.
Viewport CSS 390×844 đã kiểm tra lớp Hòa Lợi, canvas rộng 390 px/cao 764 px,
lặp tắt/bật và zoom còn đúng một ảnh phủ, không có lỗi console. Đã đặt lại
viewport về mặc định sau kiểm tra. Ảnh bằng chứng nằm trong thư mục
visualizations của task; dữ liệu và ảnh bản đồ nguồn vẫn ở `.local`.

Cache của runner được áp dụng sau hook static của app: cả catalog và JS/CSS
đều `private, no-store`, tránh dùng bản JS cũ có cache immutable. App thường
không có thay đổi đăng ký route pilot. Preview vẫn chỉ nghe 127.0.0.1:5055.


## Kiểm chứng sau đổi lớp quy hoạch chung,27/10/2026

-105 ca kiểm tra tập trung đạt; hai ca chạy trình duyệt độc lập không chạy
 vì dùng CUA cho kiểm tra UI. Node syntax và git diff --check đạt.
- Local catalog17 dòng:9 ảnh GIS và7 ảnh bản vẽ sẵn sàng; một dòng Mỹ Phước
 bản vẽ chưa có ảnh. URL ảnh quy hoạch chung200, tỷ lệ10000; ảnh cấp huyện404.
- Desktop:9 ảnh GIS tải đủ; đổi phân khu sang PDF còn7 bản vẽ+1 GIS chung;
 độ mờ chung độc lập, tắt/bật chung rồi zoom vẫn đủ9 ảnh.
- Mobile CSS390×844: canvas390×763, master tắt/bật rồi zoom tải đủ9 ảnh,
 không tràn ngang và không có lỗi console. Đã trả viewport về mặc định.
- Ảnh kiểm chứng: `ben-cat-general-plan-gis.png` trong thư mục visualization
 của task. Chỉ local5055; chưa commit/push/deploy.


Mở rộng ngày27/10/2026: bản thử dùng chung thêm Thủ Dầu Một; xem
[phạm vi, tỷ lệ và giới hạn nguồn](thu-dau-mot-local-pilot.md).
Các số9 GIS/8phường ở phần trên chỉ nói riêng Bến Cát.


Giao diện mới bỏ bộ chọn phường/thành phố và công tắc tổng. Các ghi nhận
chọn vùng trong phần lịch sử ở trên thuộc phiên bản trước thay đổi này.
