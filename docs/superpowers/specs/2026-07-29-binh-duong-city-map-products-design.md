# Thiết kế ba sản phẩm bản đồ thành phố Bình Dương cũ

Ngày: 29/07/2026
Trạng thái: Đã duyệt thiết kế tổng thể, chờ duyệt đặc tả viết trước khi lập kế hoạch triển khai

## 1. Mục tiêu

Mở rộng hệ thống `/ban-do-thu-dau-mot` thành một họ sản phẩm bản đồ dùng chung
cho ba thành phố thuộc Bình Dương cũ:

- `/ban-do-thuan-an`;
- `/ban-do-di-an`;
- `/ban-do-ben-cat`.

Mỗi trang vừa phục vụ tra cứu miễn phí và SEO, vừa bán một package riêng giá
99.000đ. Khách thanh toán VietQR qua PayOS, không cần tài khoản hoặc email, rồi
nhận link tải có hiệu lực 24 giờ gắn với mã đơn hàng.

Ba trang phải giữ chất lượng, khả năng truy cập và mức minh bạch nguồn tương
đương trang Thủ Dầu Một. Không được tạo các trang chỉ thay tên địa phương nhưng
thiếu dữ liệu riêng.

## 2. Quyết định sản phẩm đã chốt

| Trang | Đơn vị trước sắp xếp | Đơn vị hiện tại | Giá |
|---|---:|---:|---:|
| Thuận An | 10 phường | 5 phường | 99.000đ |
| Dĩ An | 7 phường | 3 phường | 99.000đ |
| Bến Cát | 7 phường và 1 xã | 6 phường | 99.000đ |

Mỗi sản phẩm gồm hai phiên bản: trước sắp xếp năm 2025 và sau sắp xếp năm
2025. Mỗi package chứa:

1. hai PDF vector hoàn thiện để in A0;
2. hai SVG có lớp/nhóm và text chỉnh sửa được;
3. hai KML chứa geometry địa lý;
4. font Be Vietnam Pro và giấy phép font;
5. hướng dẫn sử dụng;
6. giấy phép sản phẩm;
7. `MANIFEST.json` cùng checksum;
8. một ZIP bất biến dùng để giao file.

Mỗi sản phẩm có package, manifest, checksum, preview và trạng thái phát hành
riêng. Một sản phẩm chưa vượt release gate không được bán dù các sản phẩm khác
đang hoạt động.

## 3. Taxonomy hành chính

### 3.1. Thuận An

Mười phường trước sắp xếp:

- An Phú;
- An Sơn;
- An Thạnh;
- Bình Chuẩn;
- Bình Hòa;
- Bình Nhâm;
- Hưng Định;
- Lái Thiêu;
- Thuận Giao;
- Vĩnh Phú.

Năm phường hiện tại:

- An Phú;
- Bình Hòa;
- Lái Thiêu;
- Thuận An;
- Thuận Giao.

### 3.2. Dĩ An

Bảy phường trước sắp xếp:

- An Bình;
- Bình An;
- Bình Thắng;
- Dĩ An;
- Đông Hòa;
- Tân Bình;
- Tân Đông Hiệp.

Ba phường hiện tại:

- Đông Hòa;
- Dĩ An;
- Tân Đông Hiệp.

### 3.3. Bến Cát

Tám đơn vị trước sắp xếp:

- phường An Điền;
- phường An Tây;
- phường Chánh Phú Hòa;
- phường Hòa Lợi;
- phường Mỹ Phước;
- xã Phú An;
- phường Tân Định;
- phường Thới Hòa.

Sáu phường hiện tại:

- Hòa Lợi;
- Tây Nam;
- Long Nguyên;
- Bến Cát;
- Chánh Phú Hòa;
- Thới Hòa.

Danh sách Bến Cát trước sắp xếp phải giữ đúng loại đơn vị của Phú An là xã,
không đổi toàn bộ thành phường chỉ để đơn giản hóa template.

## 4. Nguồn dữ liệu và cách dựng ranh

### 4.1. Ranh hiện tại

Ranh hiện tại được lọc từ snapshot
`static/maps/binh-duong/current-36-wards.geojson`, theo đúng trường `group`.
Snapshot này đã ghim relation ID OpenStreetMap, thuộc ODbL và đang dùng trên
trang `/ban-do-binh-duong`.

Kết quả phải là:

- Thuận An: đúng 5 Polygon/MultiPolygon;
- Dĩ An: đúng 3 Polygon/MultiPolygon;
- Bến Cát: đúng 6 Polygon/MultiPolygon.

### 4.2. Ranh trước sắp xếp

Nguồn chính là snapshot Stanford Geospatial Center / GADM v2.8 đã dùng cho bản
Thủ Dầu Một. Mỗi feature nguồn phải giữ `source`, `source_url`, `source_id`,
`boundary_source`, ngày snapshot và giấy phép.

Nguồn có đủ tám ranh của Bến Cát. Thuận An có chín trong mười ranh và Dĩ An có
sáu trong bảy ranh. Hai ranh còn thiếu được dựng như sau:

- Vĩnh Phú: lấy hợp của năm ranh Thuận An hiện tại, trừ hợp chín ranh lịch sử
  có nguồn;
- An Bình: lấy hợp của ba ranh Dĩ An hiện tại, trừ hợp sáu ranh lịch sử có
  nguồn.

Sau phép trừ, pipeline phải:

- sửa geometry không hợp lệ bằng phép sửa polygon an toàn;
- loại các mảnh nhiễu dưới ngưỡng diện tích;
- giữ tất cả mảnh có ý nghĩa của cùng đơn vị;
- kiểm tra phần giao/chồng lấn với các ranh nguồn;
- kiểm tra tâm ranh nằm trong phạm vi thành phố tương ứng;
- ghi `boundary_source: derived_boundary`;
- ghi rõ công thức trong `derived_from`;
- gắn `boundary_confidence: derived_reference`;
- hiển thị cảnh báo công khai rằng đây là ranh suy luận tham khảo.

Không sao chép tọa độ từ trang thương mại hoặc nguồn không cho phép tái phân
phối. Ranh lịch sử và ranh suy luận không thay thế hồ sơ địa chính hoặc xác nhận
của cơ quan có thẩm quyền.

### 4.3. Đường, thủy hệ và tiện ích

Mỗi thành phố có bbox/source registry riêng để lấy snapshot OpenStreetMap:

- đường chính, đường nhỏ và cầu;
- sông, kênh, rạch và hồ;
- trường học, bệnh viện, chợ, cơ quan hành chính, công viên, khu công nghiệp và
  địa danh có dữ liệu;
- tên/vị trí trung tâm khu phố khi có nguồn đủ tin cậy.

Khu phố chỉ hiển thị tên/vị trí trung tâm, không vẽ hoặc khẳng định ranh giới.
Ảnh vệ tinh chỉ là nền tra cứu web từ Esri; không được đưa vào package vector.

## 5. Kiến trúc dùng chung

### 5.1. Registry trang và sản phẩm

Tạo một registry `CITY_MAP_PRODUCTS` làm nguồn cấu hình duy nhất cho bốn thành
phố. Mỗi entry tối thiểu có:

- `city_slug`, `city_name`, `path`;
- `product_slug`, version, price;
- danh sách legacy/current và loại đơn vị;
- URL GeoJSON công khai và URL static;
- preview trước/sau;
- bbox, source registry và tên file release;
- title, description, hero, answer block, FAQ và related links;
- dashboard URL/label;
- tracking prefix.

Config phải kiểm tra slug duy nhất, URL duy nhất, product slug duy nhất, count
khớp taxonomy và mọi tên current đều tồn tại trong snapshot 36 phường.

### 5.2. Route và template

Ba trang mới dùng cùng template dữ liệu hóa với trang Thủ Dầu Một. Các phần
không được hard-code tên/count của Thủ Dầu Một:

- hero và proof list;
- nhãn layer trước/sau;
- selection panel;
- danh sách đơn vị;
- purchase form và order URL;
- nội dung package;
- FAQ;
- dashboard CTA;
- liên kết GeoJSON cho AI Agent;
- tracking event/context.

Route trang, GeoJSON, checkout và order page dùng `city_slug` đã allowlist từ
registry. Không chấp nhận path tùy ý hoặc product slug do client gửi.

### 5.3. Commerce đa sản phẩm

`services/digital_products.py` đăng ký bốn `DigitalProduct` bất biến. Mỗi sản
phẩm có release file list, package filename, SHA-256 và manifest SHA-256 riêng.

Checkout xác định sản phẩm từ route server-side. Trình duyệt không được gửi
giá, version hoặc product slug để quyết định đơn.

Status và download phải lấy `order.product_slug` đã lưu, sau đó đối chiếu:

- slug/version;
- expected amount/currency;
- package checksum;
- manifest;
- protected storage path.

Không được tiếp tục dùng hằng `_PRODUCT_SLUG` Thủ Dầu Một ở download endpoint.

Retry cookie được tách theo product/path để một checkout ở Thuận An không tái sử
dụng nhầm đơn Bến Cát. Order authorization cookie vẫn giới hạn đúng
`public_id`. Webhook PayOS giữ một URL dùng chung và xử lý idempotent theo order
code.

### 5.4. Build và release

Pipeline hiện tại được tổng quát hóa theo `MapProductSpec`, không copy ba bộ
renderer. Pipeline nhận city config và tạo:

- normalized legacy/current boundaries;
- street/hydro/POI layers;
- scene trước/sau;
- PDF/SVG/KML;
- preview WebP có watermark;
- hướng dẫn và giấy phép;
- manifest/checksum;
- ZIP release.

Validator nhận expected legacy/current count từ spec thay vì hard-code `14/5`.
Nó vẫn bắt buộc:

- geometry hợp lệ;
- PDF A0 và giữ vector/font;
- SVG có text editable và group/layer;
- KML parse được và đủ placemark;
- nguồn/license đầy đủ;
- manifest khớp chính xác danh sách file;
- package checksum khớp registry;
- manual approval trước khi `can_sell=True`.

## 6. Nội dung, SEO và AI discovery

Mỗi trang phải có nội dung địa phương riêng, không chỉ thay tên:

- mô tả vai trò đô thị và phạm vi tra cứu;
- danh sách đơn vị trước/sau;
- giải thích cụ thể đơn vị hình thành từ đâu;
- ghi chú riêng về ranh suy luận nếu có;
- dashboard CTA đúng khả năng sản phẩm;
- FAQ và related links riêng.

Dashboard hiện hỗ trợ lọc tin ổn định cho Bến Cát, nên CTA Bến Cát dùng
`/?tab=signals&city=Bến Cát`. Thuận An và Dĩ An dẫn tới `/?tab=signals` với
nhãn “Xem toàn bộ tin đang bán”; không tuyên bố đã lọc theo thành phố khi backend
chưa hỗ trợ.

Mỗi trang có:

- title/meta/canonical/Open Graph riêng;
- `WebPage`, `Map`, `Product`, `Offer`, `Dataset`, `ItemList`,
  `BreadcrumbList` và `FAQPage` schema phù hợp;
- Product availability phản ánh đúng package riêng;
- đúng hai DataDownload GeoJSON;
- sitemap `lastmod`;
- `llms.txt`;
- liên kết từ `/ban-do-binh-duong`, `/quy-hoach-binh-duong`, footer và giữa bốn
  trang sản phẩm;
- tracking page view, layer selection, purchase, checkout, QR, payment,
  download và dashboard click mà không gửi token/order code.

Trang và schema không được tuyên bố ranh có giá trị pháp lý, không thêm rating
giả và không công bố sản phẩm `InStock` nếu package chưa vượt release gate.

## 7. UX và accessibility

Giữ bố cục đã kiểm chứng của Thủ Dầu Một:

- bản đồ phố/vệ tinh;
- wheel zoom, fullscreen và retry;
- selection panel nằm trên map;
- tìm có dấu/không dấu;
- chọn khu vực từ map hoặc directory;
- hash URL chia sẻ layer/khu vực;
- progressive fallback khi JavaScript hoặc Leaflet lỗi;
- control và CTA tối thiểu 44px;
- `aria-live` cho trạng thái map/search/order;
- không tràn ngang tại 375, 768, 1024 và 1440px.

Các preview có watermark, kích thước cố định và alt text đúng count/tên thành
phố. File PDF/SVG/KML gốc không nằm trong `static/`.

## 8. Kiểm thử

### 8.1. Data và build

- taxonomy lần lượt đúng `10/5`, `7/3`, `8/6`;
- mọi slug/tên/URL duy nhất;
- ranh sourced giữ provenance;
- chỉ Vĩnh Phú và An Bình mang nhãn derived;
- derived geometry hợp lệ, nằm đúng phạm vi và không chồng lấn đáng kể;
- Bến Cát giữ Phú An là xã cũ;
- renderer/validator dùng expected count từ spec;
- mỗi package đủ đúng file, parse được và checksum khớp;
- preview tồn tại, có watermark và khác nhau theo thành phố/layer.

### 8.2. Trang và SEO

- ba route trang và sáu route GeoJSON trả 200;
- canonical, H1, title/meta và schema riêng;
- ItemList count khớp và URL không trùng;
- Dataset distribution có MIME `application/geo+json`;
- không còn copy Thủ Dầu Một lọt sang trang khác;
- sitemap/`llms.txt`/internal links đủ;
- Product availability độc lập theo package.

### 8.3. Checkout và download

- mỗi route checkout tạo đúng product/price server-side;
- retry cookie không đi chéo sản phẩm;
- order page quay lại đúng product;
- status/download chọn sản phẩm từ order;
- đơn không khớp version/amount/currency bị từ chối;
- webhook hợp lệ cấp quyền tải đúng product;
- webhook sai/trùng/out-of-order an toàn;
- token và cookie authorization vẫn giữ ranh giới order;
- link tải hết hạn sau 24 giờ;
- package thiếu/sai checksum trả trạng thái không khả dụng, không giao nhầm file.

### 8.4. Browser QA

Kiểm tra cả ba trang tại 375, 768, 1024 và 1440px:

- không tràn ngang và không có console error;
- map/layer/basemap/fullscreen/search/hash hoạt động;
- count/directory/selection đúng từng thành phố;
- CTA dashboard đúng đích;
- preview và purchase copy đúng sản phẩm;
- checkout hiển thị đúng QR, số tiền, mã đơn và trạng thái;
- paid state tải đúng filename/package.

## 9. Release và vận hành

Không bật bán một sản phẩm cho đến khi:

- package v1.0 của sản phẩm đó vượt validator;
- preview đã được kiểm tra;
- protected storage production chứa ZIP/manifest đúng checksum;
- registry production khớp checksum;
- PayOS env và webhook dùng chung đang hoạt động;
- targeted tests và browser QA đạt;
- production smoke xác minh trang, GeoJSON, tạo checkout, order recovery và
  download đúng package.

Deploy có thể phát hành code/trang trước, nhưng `can_sell` phải giữ `False` cho
mọi package chưa được upload và kiểm định. Không tạo giao dịch PayOS thật trong
test tự động.

## 10. Ngoài phạm vi

- bán bundle gộp nhiều thành phố;
- giá khuyến mại hoặc coupon;
- file Adobe Illustrator `.ai`;
- bản đồ địa chính/thửa đất;
- ranh khu phố;
- ảnh vệ tinh trong package;
- CMS quản lý sản phẩm;
- hỗ trợ dashboard lọc Thuận An/Dĩ An;
- trang riêng cho từng phường;
- refund tự động.
