# Audit SEO / UI / UX công khai — 19/10/2026

Phạm vi: 19 URL đại diện qua HTTP, robots/sitemap, đối chiếu nguồn template,
browser desktop và 8 URL mobile 390px. Sau đó kiểm riêng cả 9 URL quy hoạch
trong sitemap. Đây là audit; chưa sửa hoặc deploy trong lượt này.

## P1 — Trang thị trường có số liệu mô phỏng dễ bị hiểu là hiện tại

`/binh-duong` hiển thị “128”, “+24% so với hôm qua”, thẻ giá rao 2.35 tỷ,
giá trị ước tính 2.95 tỷ từ cấu hình tĩnh (`config/seo_pages.py`, hero_metric /
property_card). Có aria-label “Mô phỏng…” trên aside nhưng không có nhãn minh
họa nhìn thấy. Đồ thị và các pin giá là nội dung mô phỏng. Không có bằng chứng
trong audit rằng những giá trị này là thống kê hiện tại.

Đề xuất: lấy snapshot có nguồn/ngày/phạm vi, hoặc bỏ số liệu; nếu giữ minh họa,
đặt nhãn nhìn thấy sát hình và không gắn nhãn tăng trưởng theo ngày. Landing
khu vực dùng cùng hero nên cần rà cả biến thể. Không thay bằng số 0 khi lỗi dữ liệu.

## P1 — 3 chuyên đề trống nằm trong sitemap

Cả ba trả 200, canonical tự trỏ, không có noindex trong meta/header và còn trong
sitemap, nhưng nội dung chính chỉ là “Đang cập nhật chuyên đề”:

- `/quy-hoach-binh-duong/quy-hoach-su-dung-dat`
- `/quy-hoach-binh-duong/quy-hoach-chi-tiet`
- `/quy-hoach-binh-duong/quy-hoach-phan-khu`

Đề xuất: tạm noindex và loại khỏi sitemap cho đến khi có bản đồ/nội dung và nguồn
đủ dùng; giữ đường quay về thư viện cho người truy cập. Không cần xóa URL đang
được sử dụng. Chưa có dữ liệu GSC để kết luận Google đã index các URL này.

## P2 — Trang bản đồ đặt công cụ quá sâu

`/ban-do-thu-dau-mot`: tại viewport 390×844, form lead bắt đầu khoảng y=1536,
Leaflet bắt đầu y=2828. Trang có nhiều đoạn giải thích phạm vi trước công cụ.
`/ban-do-ben-cat` dùng chung cấu trúc sản phẩm, cần áp dụng cùng nguyên tắc sau
khi kiểm riêng viewport. `/ban-do-binh-duong` và nhóm bản đồ thành phố còn dùng
giao diện cũ với nhiều khối/gradient và chưa đồng bộ typography của tin tức.

Đề xuất: giữ một ghi chú phạm vi ngắn, đưa lựa chọn trước/sau và bản đồ lên sớm;
thêm nút neo xem bản đồ trong hero; chuyển form lead xuống sau công cụ; thu gọn
nguồn, phương pháp, tải file thành các phần rõ ràng. Không đổi ranh giới/dữ liệu.

## P2 — Landing khu vực / bán đất còn chung chung, copy form ghép máy móc

Nhóm `/binh-duong/thu-dau-mot`, `/binh-duong/ben-cat`, `/binh-duong/my-phuoc`,
`/ban-dat-binh-duong` còn thiên về mô tả tính năng và các khối lặp. H2 form lead
ghép cả hero_title sau chữ “ở”, ví dụ “... ở Nhà đất Thủ Dầu Một bằng dữ liệu?”.
`/binh-duong/phuong-phu-my` đã có Dataset và dữ liệu thực, nên giữ nội dung đó.

Đề xuất: tên khu vực ngắn riêng cho lead_scope_label; ưu tiên dữ liệu đúng khu,
tin phù hợp, mẫu so sánh, link báo cáo/công cụ. Dữ liệu chưa đủ phải nói rõ;
không sao chép snapshot Thủ Dầu Một sang Bến Cát/Mỹ Phước.

## P2 — Trang phương pháp cần minh họa quy trình

`/san-deal-bds` còn dùng hero mô phỏng, form lead xuất hiện trước phần giải thích.
Đề xuất: sơ đồ tin rao → lọc trùng → so phân khúc → giá tham khảo → kiểm tra thực
địa; một ví dụ có nhãn và giả định rõ; mục lục ngắn thay khối quảng bá lớn.

## P2 — Dashboard mobile ưu tiên tin chưa đủ sớm

Tại `/` ở 390×844, phần giới thiệu, bằng chứng/phạm vi, đổi khu vực và tìm kiếm
chiếm phần lớn màn hình đầu; thẻ tin đầu bắt đầu khoảng mép dưới màn hình.
Nút Maps nổi và thanh tab dưới cũng chiếm chỗ trên vùng tin. Đây là nhận xét UI,
không phải kết luận tỷ lệ chuyển đổi kém.

Đề xuất: thu gọn giới thiệu/phạm vi thành phần mở thêm, giữ khu vực tóm tắt +
bộ lọc thiết yếu; kiểm tra nút nổi không che tin. Giữ bất biến request/filter,
cancellation, newest-response-wins và phân quyền hiện tại.

## Những phần đang ổn / giới hạn

- robots và sitemap trả 200; sitemap có 193 phần tử loc tại thời điểm đọc.
- Trong các HTML công khai đã đọc: mỗi trang có một H1, title/description,
  canonical và JSON-LD phân tích được. Browser xác nhận schema hiện diện trên
  các trang kiểm tra; chưa chạy Google Rich Results Test cho toàn bộ website.
- 8 URL mobile không tràn ngang. Không có ảnh HTML thiếu alt/kích thước trong
  mẫu HTTP. Hai background ảnh hero trả 200; không kết luận ảnh hỏng từ lần
  screenshot đầu chưa tải xong.
- `/kien-thuc` chuyển tới `/tin-tuc`, không coi là trang trùng độc lập.
- `/hoi-radar-bds` trả 401 cho khách và không có trong sitemap; đây là phân quyền,
  không được ghi nhận như lỗi SEO của trang công khai.
- Nhóm tin tức/công cụ/báo cáo mới làm không phải ưu tiên thiết kế tiếp theo.
- Chưa đo Lighthouse, CWV thực tế, GSC, Google index hoặc chuyển đổi; các timing
  HTTP đơn lẻ không được dùng để kết luận tốc độ hay thứ hạng.

Thứ tự: xử lý mô phỏng + 3 trang trống → landing khu vực → bản đồ → trang phương
pháp → tối ưu dashboard mobile với kiểm tra chức năng riêng.

## Khắc phục P1 — 19/10/2026

- Hero không có snapshot thật dùng hướng dẫn quy trình, bỏ số lượng/tăng trưởng,
  pin giá, đường biểu đồ giả và thẻ tài sản mẫu. Nhánh có snapshot thật giữ nguyên.
- Bỏ số cố định 876+/100+ ở phần giới thiệu dashboard; ảnh chụp giao diện có nhãn
  rõ rằng số liệu trong ảnh không phản ánh hiện tại.
- Chuyên đề quy hoạch không có bài vẫn trả 200 và giữ canonical/link về hub;
  thêm meta robots và HTTP X-Robots-Tag `noindex, follow`, loại khỏi sitemap.
  Cả route và sitemap dùng `_planning_category_items()` nên tự mở lại khi có bài.
  Giữ robots cho phép crawl để công cụ tìm kiếm đọc được noindex. Không tuyên bố
  URL đã biến mất khỏi Google ngay sau deploy.
- 86 kiểm tra liên quan đạt: 60 SEO/content/navigation/P1, 26 live ward/trust.
  Có kiểm tra thêm nội dung để xác nhận cơ chế tự mở index; không đổi dữ liệu
  định giá, ranh giới bản đồ, tín hiệu hay phân quyền.

## Khắc phục P2 — 19/10/2026

- Bản đồ thành phố dùng cùng template: đưa canvas lên trước bảng khu vực đang
  chọn và form lead; chuyển chứng cứ/phạm vi, phương pháp, nguồn/giấy phép vào
  phần mở thêm. Giữ ghi chú giới hạn ngắn, chọn trước/sau và nút neo tới bản đồ.
  Giữ nguyên GeoJSON, lớp nền, IDs/hooks, điều kiện mua và API checkout.
- Thư viện bản đồ Bình Dương: thu gọn hero, đưa panel thông tin nhanh và hướng
  dẫn/nguồn xuống phần mở thêm; bỏ CTA nổi che nội dung trên mobile.
- Landing: kiểu chữ đồng bộ phần tin tức, nội dung theo khu vực và liên kết tra
  cứu lên sớm; nguồn/phương pháp và lead xuống cuối. `lead_scope_label` tách khỏi
  tiêu đề. CTA khu vực mang city/ward; Mỹ Phước có q tương ứng, bán đất có
  prop_type=dat_nen. Nhánh live ward giữ snapshot/Dataset/cảnh báo hiện hành.
  Không tạo thêm truy vấn DB để bù bằng số liệu của khu khác.
- Trang phương pháp có mục lục, luồng 5 bước và ví dụ giả định 2 / 2,5 tỷ → MOS
  20%, ghi rõ đây không phải lợi nhuận dự kiến; kèm checklist kiểm tra thực tế.
- Dashboard: nguồn/giới thiệu trong details; nút Maps duy nhất chuyển vào header,
  mobile hiển thị trong luồng header, desktop giữ vị trí nổi cũ. Tắt backdrop
  filter của header desktop để không tạo containing block giữ nút fixed trong
  header. Thanh khu vực gọn hơn. Không đổi JS lọc/request, API hay phân quyền.
- Kiểm tra: 137 pytest đạt; 2 bài browser trong pytest không chạy vì browser
  được kiểm trực tiếp bằng CUA. 6 kiểm tra filter runtime đạt; range/area-scope
  Node scripts đạt. Lỗi tmp_path ban đầu được xử lý bằng basetemp trong `.local/`.
- Local 390px: canvas Thủ Dầu Một từ khoảng y=2828 xuống y=1194; Bến Cát/Thuận
  An/Dĩ An khoảng y=1158. Đổi lớp Thủ Dầu Một hiển thị 5 ranh hiện tại. 9 trang
  mobile không tràn ngang; header dashboard kiểm cả 320px và desktop. Bản local
  chưa có kết nối DB khỏe, nên kết quả feed/bộ lọc cần xác nhận trên production.
