# Thiết kế bundle bản đồ TP Thủ Dầu Một trả phí

Ngày: 29/07/2026
Trạng thái: Đã thống nhất định hướng, chờ duyệt đặc tả trước khi lập kế hoạch triển khai

## 1. Mục tiêu

Xây dựng một sản phẩm bản đồ số do Radar BDS biên tập, bán một lần với giá
99.000đ. Khách quét VietQR PayOS, thanh toán thành công và tải ngay một bundle
gồm bản đồ TP Thủ Dầu Một trước và sau sắp xếp hành chính. Khách không cần tài
khoản, email hoặc số điện thoại.

Sản phẩm phục vụ:

- in bản đồ hành chính - đô thị ở khổ A0;
- chỉnh sửa trong Adobe Illustrator, CorelDRAW, Inkscape và phần mềm tương thích
  SVG/PDF;
- mở các lớp địa lý trong Google Earth, Google My Maps và phần mềm GIS hỗ trợ
  KML;
- tra cứu ranh phường, đường giao thông, thủy hệ, địa danh, khu phố và tiện ích.

Trang miễn phí `/ban-do-binh-duong` tiếp tục phục vụ SEO, tra cứu và dẫn người
dùng sang dashboard Radar BDS. Sản phẩm trả phí dùng URL riêng
`/ban-do-thu-dau-mot`; quyết định này chỉ mở rộng phạm vi cho sản phẩm mới, không
biến trang bản đồ Bình Dương miễn phí thành paywall.

## 2. Các quyết định đã chốt

- Giá niêm yết: 99.000đ cho toàn bộ bundle.
- Bundle gồm cả bản đồ 14 phường trước sắp xếp và 5 phường thuộc khu vực
  Thủ Dầu Một sau sắp xếp năm 2025.
- Mức chi tiết gồm đường nhỏ có dữ liệu, sông/kênh, tên khu phố và các điểm tiện
  ích.
- Khu phố chỉ hiển thị tên và vị trí trung tâm tham khảo; không vẽ hoặc khẳng
  định ranh giới khu phố.
- Quy trình sản xuất là quy trình lai: tự động xử lý dữ liệu GIS, sau đó biên tập
  và kiểm tra bản in thủ công trước khi phát hành.
- Thanh toán bằng PayOS tự động. Khách quét VietQR và trang tự mở quyền tải sau
  khi webhook xác nhận.
- Không thu email, số điện thoại, tài khoản hoặc yêu cầu đăng nhập.
- Khách có mã đơn và URL khôi phục chứa token ngẫu nhiên.
- Quyền tải hết hạn 24 giờ kể từ khi thanh toán thành công.
- Khách được in, chỉnh sửa và dùng trong dự án cá nhân/doanh nghiệp; không được
  bán lại, chia sẻ công khai hoặc phân phối lại file gốc.

## 3. Phạm vi bundle

Một bản phát hành có tên dạng
`radarbds-thu-dau-mot-map-v1.0.zip`, chứa:

1. `thu-dau-mot-truoc-2025-a0.pdf`
2. `thu-dau-mot-sau-2025-a0.pdf`
3. `thu-dau-mot-truoc-2025.svg`
4. `thu-dau-mot-sau-2025.svg`
5. `thu-dau-mot-truoc-2025.kml`
6. `thu-dau-mot-sau-2025.kml`
7. thư mục `fonts/` chứa đúng font được phép phân phối;
8. `HUONG-DAN.pdf`;
9. `GIAY-PHEP.txt`;
10. `MANIFEST.json`.

Hai PDF là bản hoàn thiện để in A0. Nội dung hình học phải là vector và font được
nhúng hợp lệ; PDF ưu tiên độ ổn định khi in. Hai SVG là bản chỉnh sửa chính, giữ
đối tượng `<text>` và các nhóm/lớp có tên. Font được đóng gói riêng để phần mềm
đồ họa không tự thay font. Hai KML chứa dữ liệu địa lý, không cố mô phỏng bố cục
in của PDF.

Không đưa ảnh vệ tinh hoặc raster nền vào bundle vì điều đó mâu thuẫn với cam
kết thuần vector. Không phát hành file `.ai` ở phiên bản đầu; SVG là định dạng
nguồn mở có thể mở bằng Illustrator và CorelDRAW.

### 3.1. Nội dung bản đồ

- ranh TP Thủ Dầu Một và các phường;
- ranh 14 phường trước sắp xếp;
- ranh 5 phường sau sắp xếp thuộc nhóm Thủ Dầu Một;
- quốc lộ, đường chính, đường nhánh và đường nhỏ có dữ liệu hợp lệ;
- cầu, sông, kênh và hồ quan trọng;
- tên và vị trí trung tâm khu phố;
- trường học, bệnh viện, chợ, cơ quan hành chính, công viên, khu công nghiệp và
  địa danh nổi bật;
- mũi tên Bắc, thước tỷ lệ, chú giải, ngày dữ liệu, nguồn và phiên bản;
- ghi chú rằng bản đồ không thay thế bản đồ địa chính, hồ sơ thửa đất, hồ sơ quy
  hoạch hoặc xác nhận của cơ quan có thẩm quyền;
- ghi chú rằng vị trí khu phố mang tính tham khảo và không thể hiện ranh giới
  khu phố.

## 4. Dữ liệu và dây chuyền bản đồ

### 4.1. Nguồn dữ liệu

Mỗi lớp dữ liệu phải có nguồn, giấy phép, ngày snapshot và checksum:

- ranh sau năm 2025: tái sử dụng phần geometry đã kiểm tra trong snapshot 36
  phường/xã hiện có của Radar BDS;
- ranh 14 phường cũ: phải lấy từ nguồn chính thức hoặc nguồn mở có giấy phép phù
  hợp và xác minh đủ 14 đơn vị; codebase hiện chưa có lớp này nên thiếu nguồn là
  điều kiện chặn phát hành;
- đường, thủy hệ và điểm tiện ích: trích xuất từ OpenStreetMap hoặc nguồn mở phù
  hợp trong phạm vi TP Thủ Dầu Một;
- tên/vị trí khu phố: danh sách biên tập riêng, mỗi điểm có tên, tọa độ, nguồn và
  mức tin cậy;
- danh sách đơn vị sau sắp xếp: đối chiếu văn bản/danh sách hành chính công bố.

Các sản phẩm có dữ liệu OpenStreetMap phải ghi
`© OpenStreetMap contributors` và URL
`https://www.openstreetmap.org/copyright` ở vị trí phù hợp trên bản đồ và trong
hướng dẫn. Không sao chép dữ liệu từ Google Maps hoặc nguồn thương mại không cho
phép tái phân phối.

### 4.2. Các mô-đun độc lập

1. **Source registry**
   Khai báo nguồn, license, snapshot, checksum và phạm vi sử dụng.

2. **Boundary builder**
   Chuẩn hóa tên/mã, kiểm tra geometry, cắt phạm vi và tạo hai bộ ranh cũ/mới.

3. **Street and hydro builder**
   Lọc, phân cấp và cắt đường/thủy hệ theo ranh thành phố.

4. **POI and neighborhood curator**
   Chuẩn hóa điểm, loại trùng, loại điểm thiếu tên hoặc ngoài phạm vi, giữ nguồn
   và mức tin cậy.

5. **Draft renderer**
   Sinh bản nháp vector có lớp, màu, label rule, chú giải và bố cục A0.

6. **Release validator**
   Kiểm tra đủ file, đủ 14/5 phường, geometry hợp lệ, font/license, PDF vector,
   SVG có text editable, KML parse được và checksum khớp.

7. **Release packager**
   Chỉ đóng ZIP sau khi bản phát hành đã được đánh dấu duyệt thủ công.

### 4.3. Kiểm tra biên tập

Trước mỗi bản phát hành phải kiểm tra thủ công:

- nhãn không đè ranh hoặc đường quan trọng;
- tên phường/khu phố không trùng hoặc rơi ra ngoài phạm vi hợp lý;
- phân cấp nét đường đọc được khi in A0;
- màu các phường liền kề dễ phân biệt;
- tất cả ký tự tiếng Việt hiển thị đúng;
- chú giải, nguồn, tỷ lệ, mũi tên Bắc và cảnh báo có mặt;
- bản in thử ở tỷ lệ thu nhỏ vẫn đọc được cấu trúc chính.

Nếu thiếu ranh, font, license, nguồn, file hoặc một kiểm tra bắt buộc thất bại,
pipeline dừng và không thay bản ZIP đang bán bằng bản chưa hoàn chỉnh.

## 5. Trang sản phẩm và trải nghiệm mua

### 5.1. URL và bố cục

Trang canonical: `/ban-do-thu-dau-mot`.

Thứ tự nội dung:

1. breadcrumb;
2. hero với tiêu đề, mô tả ngắn, giá 99.000đ và CTA
   `Mua trọn bộ bản đồ`;
3. hai ảnh preview có watermark cho bản trước/sau sắp xếp;
4. khối `Bạn nhận được gì` liệt kê PDF, SVG, KML, font và hướng dẫn;
5. khối chi tiết dữ liệu: ranh, đường nhỏ, khu phố, thủy hệ và tiện ích;
6. thông số kỹ thuật và khả năng tương thích;
7. giấy phép sử dụng và các giới hạn;
8. nguồn, phương pháp và ngày cập nhật;
9. FAQ;
10. CTA mua lặp lại;
11. CTA phụ sang dashboard lọc tin Thủ Dầu Một.

Preview web là raster có watermark và độ phân giải đủ xem nhưng không thay thế
file trả phí. Không đưa SVG/PDF nguồn vào HTML hoặc thư mục static công khai.

CTA mua là hành động chính. CTA dashboard vẫn có mặt nhưng là hành động phụ trên
trang sản phẩm này.

### 5.2. Checkout không cần tài khoản

Khi khách bấm mua:

1. server tạo đơn với `product_slug`, `product_version` và số tiền 99.000đ cố
   định phía server;
2. server gọi PayOS và nhận dữ liệu VietQR;
3. trang hiển thị QR, số tiền, mô tả chuyển khoản, mã đơn, thời hạn thanh toán
   15 phút và URL khôi phục;
4. trang poll trạng thái đơn với nhịp vừa phải và cập nhật vùng `aria-live`;
5. webhook PayOS xác nhận thanh toán;
6. QR được thay bằng trạng thái thành công, nút tải và thời điểm hết hạn;
7. tải file được ghi nhận nhưng không gửi token/mã đơn vào analytics.

Trang khôi phục đơn dùng URL dạng:

`/ban-do-thu-dau-mot/don-hang/<public_id>#token=<recovery_token>`

`public_id` không phải khóa chính tuần tự. Recovery token có entropy cao, chỉ
lưu dạng hash trong PostgreSQL và nằm trong URL fragment nên không được gửi lên
server, referrer hoặc access log. JavaScript gửi token một lần bằng request body
để đổi lấy cookie HttpOnly, Secure, SameSite=Lax giới hạn đúng order; sau đó xóa
fragment khỏi thanh địa chỉ. Mã đơn hiển thị để hỗ trợ khách hàng nhưng bản thân
mã đơn không cấp quyền tải.

### 5.3. Trạng thái và lỗi

- `pending`: hiển thị QR và trạng thái chờ trong tối đa 15 phút.
- `paid`: hiển thị nút tải và thời hạn 24 giờ.
- `expired`: QR hoặc quyền tải đã hết hạn.
- `cancelled`: không cấp quyền tải.
- `payment_review`: nhận callback nhưng số tiền/chữ ký/dữ liệu chưa hợp lệ; không
  cấp quyền tải và đưa vào đối soát.

Nếu gọi PayOS thất bại trước khi có payment link, thao tác thử lại phải
idempotent và không sinh nhiều đơn cho cùng một yêu cầu. Nếu PayOS đã tạo payment
link, trang dùng lại link của đơn thay vì tạo order code mới. Nếu webhook chậm,
polling chỉ đọc trạng thái server; một tác vụ đối soát có thể hỏi PayOS và phục
hồi đơn hợp lệ. Nếu ZIP bị thiếu sau khi khách đã trả tiền, hệ thống không trả
file lỗi, ghi cảnh báo vận hành và hiển thị đường hỗ trợ Radar BDS.

## 6. Kiến trúc thanh toán và tải file

### 6.1. Thành phần

- `services/digital_products.py`: registry sản phẩm, version, price, package
  metadata và trạng thái bán.
- `services/payos_client.py`: lớp nhỏ gọi PayOS, tạo payment link, xác minh
  webhook và đọc trạng thái.
- `services/digital_product_orders.py`: vòng đời đơn, idempotency, token và
  quyền tải.
- `routes/digital_products.py`: trang sản phẩm, API checkout/status/webhook và
  download.
- PostgreSQL: bảng đơn hàng và bảng/sổ sự kiện tối thiểu phục vụ đối soát.
- protected product storage: đường dẫn ngoài `static/` và ngoài thư mục deploy
  có thể bị ghi đè.

Codebase hiện chưa có PayOS. Tích hợp mới phải dùng biến môi trường cho client
ID, API key và checksum key; không được ghi secret vào repo, HTML hoặc log.

### 6.2. Dữ liệu đơn hàng

Bảng đơn tối thiểu lưu:

- internal id;
- public id ngẫu nhiên;
- product slug và product version bất biến theo đơn;
- expected amount;
- PayOS order code;
- status;
- recovery token hash;
- checkout/QR metadata cần thiết nhưng không chứa secret;
- created, updated, paid và download expiry timestamps;
- download count và last download timestamp;
- webhook/reconciliation status.

Không lưu email hoặc số điện thoại vì checkout không thu các trường này.

### 6.3. Quy tắc bảo mật

- Giá, mã sản phẩm và version được lấy phía server; không tin dữ liệu giá từ
  trình duyệt.
- Redirect thành công/cancel của PayOS không phải bằng chứng thanh toán.
- Webhook phải xác minh chữ ký, order code, sản phẩm và số tiền. Chỉ chấp nhận
  khi số tiền nhận được không thấp hơn expected amount.
- Webhook idempotent; gửi lại hoặc đến sai thứ tự không cấp quyền tải lần hai.
- Token khôi phục/tải không xuất hiện trong analytics, query string, access log
  hoặc application log.
- Endpoint authorize xác minh recovery token từ request body rồi cấp cookie
  HttpOnly có chữ ký, giới hạn order và thời hạn.
- ZIP không nằm ở URL public. Server kiểm tra đơn, cookie ủy quyền và hạn rồi mới
  stream file với `Content-Disposition: attachment`.
- Không khóa theo IP vì người dùng có thể đổi mạng; bảo vệ dựa trên token khó
  đoán, hạn 24 giờ và rate limit.
- Tạo đơn, poll, webhook và download đều có rate limit phù hợp.
- Secret PayOS chỉ đọc từ environment.
- Hủy/refund tự động không thuộc phiên bản đầu; trường hợp hỗ trợ xử lý thủ công
  và phải có audit trail.

## 7. SEO, schema và tracking

Trang sản phẩm có:

- title, meta description, canonical và Open Graph image riêng;
- Breadcrumb schema;
- Product schema với Offer giá 99.000 VND;
- `availability` chỉ là `InStock` khi manifest và ZIP của version đang bán đã
  qua validator;
- FAQ schema chỉ cho câu hỏi thực sự hiển thị trên trang;
- sitemap `lastmod`;
- mục tương ứng trong `llms.txt`;
- internal link từ `/ban-do-binh-duong` và `/quy-hoach-binh-duong`.

Không thêm review/rating giả, số người mua giả hoặc lời đảm bảo pháp lý. Copy
không dùng các tuyên bố tuyệt đối như “chính xác 100%” hoặc “mở trên mọi thiết
bị không bao giờ lỗi”.

Tracking tối thiểu:

- product page viewed;
- purchase CTA clicked;
- checkout created;
- QR displayed;
- payment confirmed;
- download clicked;
- secondary dashboard CTA clicked.

Analytics không nhận raw order code, recovery token, PayOS signature hoặc dữ
liệu chuyển khoản.

## 8. Kiểm thử và nghiệm thu

### 8.1. Dữ liệu và file

- đúng 14 phường cũ và 5 phường mới;
- tất cả geometry hợp lệ và nằm trong phạm vi hợp lý;
- không trùng slug/mã/tên sau chuẩn hóa;
- đường/POI ngoài phạm vi bị loại;
- khu phố có source/confidence và không có polygon;
- PDF giữ vector, khổ A0 và font nhúng;
- SVG parse được, có layer/group và text editable;
- KML parse được, có placemark/geometry đúng phiên bản;
- manifest/checksum khớp ZIP;
- license/source bắt buộc có mặt;
- validator từ chối package thiếu hoặc chưa duyệt.

### 8.2. Thanh toán

- tạo đơn luôn dùng giá 99.000đ phía server;
- không thể thay product/version/amount từ client;
- webhook chữ ký sai, order sai hoặc thiếu tiền không cấp tải;
- webhook hợp lệ cấp tải đúng một lần về trạng thái;
- webhook trùng và out-of-order vẫn idempotent;
- token sai hoặc thiếu bị từ chối;
- đơn pending/cancelled/review không tải được;
- đơn paid tải được trong 24 giờ;
- link hết hạn sau 24 giờ;
- package bị thiếu không trả response thành công giả;
- reconciliation phục hồi được đơn PayOS đã trả nhưng webhook bị bỏ sót;
- không có secret/token trong response không liên quan hoặc log test.

Test tự động dùng PayOS client giả; không tạo giao dịch thật. Trước khi bật
production phải cấu hình credential thật, webhook thật và thực hiện một lần
nghiệm thu thanh toán có chủ đích do chủ hệ thống phê duyệt.

### 8.3. Browser QA

Kiểm tra 375, 768, 1024 và 1440 px:

- không tràn ngang;
- preview trước/sau rõ ràng;
- CTA và control tối thiểu 44 px;
- QR đọc được trên desktop và có thể lưu/mở app ngân hàng trên mobile;
- trạng thái `aria-live` cập nhật đúng;
- copy mã đơn và link khôi phục hoạt động;
- reload/Back/Forward không mất khả năng khôi phục;
- paid state hiển thị nút tải và thời điểm hết hạn;
- hết hạn/hủy/lỗi có hướng dẫn rõ;
- không có console error.

### 8.4. Release gate

Không bật CTA PayOS production nếu thiếu một trong các điều kiện:

- bundle v1.0 đã qua validator và biên tập thủ công;
- protected storage đã chứa đúng ZIP/checksum;
- migration PostgreSQL đã chạy;
- PayOS credential được cấu hình;
- webhook HTTPS public được PayOS chấp nhận;
- backup/rollback cho migration và package metadata;
- targeted tests, full tests liên quan và browser QA đạt;
- production smoke xác minh product page, tạo QR, webhook, khôi phục và tải.

## 9. Ngoài phạm vi phiên bản đầu

- file Adobe Illustrator `.ai`;
- ảnh vệ tinh trong bundle vector;
- ranh khu phố;
- bản đồ địa chính/thửa đất;
- bản đồ quy hoạch pháp lý;
- trình tạo bản đồ tùy biến theo yêu cầu khách;
- tài khoản khách hàng hoặc thư viện đơn đã mua;
- email/SMS giao file;
- DRM hoặc khóa file theo thiết bị;
- refund tự động;
- CMS quản lý sản phẩm;
- các trang/phần bundle riêng cho từng phường.

Các thành phố và phường khác chỉ được triển khai sau khi pipeline Thủ Dầu Một,
checkout và vận hành hỗ trợ đã ổn định.
