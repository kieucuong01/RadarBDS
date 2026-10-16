# Chuẩn biên tập bài SEO Chủ đề nóng

Áp dụng từ 16/10/2026 cho bài mới và lần cập nhật lớn. Đọc cùng
`daily_seo_publisher.md`; đây là tiêu chuẩn nội dung cho Hermes trên VPS.

## Luồng skill bắt buộc trong brief biên tập

1. Đọc `.agents/product-marketing.md` và `.agents/skills/content-strategy/SKILL.md`
   để chọn một ý định đọc, một sự kiện, đúng địa bàn và câu hỏi của người mua.
2. Dùng `.agents/skills/copywriting/SKILL.md` để lập dàn ý và viết bản đầy đủ.
   Bài tin là phân tích biên tập có nguồn, không áp giọng bán hàng hay tạo FOMO.
3. Dùng `.agents/skills/copy-editing/SKILL.md`: rà rõ nghĩa, giọng văn, ích lợi,
   bằng chứng và tính cụ thể. Xóa câu có thể dán nguyên sang bất kỳ dự án nào.
4. Dùng `.agents/skills/seo-audit/SKILL.md` cho title, mô tả, H1/H2, liên kết,
   canonical, sitemap, hình và khả năng đọc mobile. Không nhồi từ khóa.
5. Tạo/chọn hình với công cụ ảnh sẵn có. Nếu Hermes không có imagegen thì dùng
   ảnh sở hữu/được phép hoặc sơ đồ nguyên bản có dữ kiện đã xác minh; ghi nguồn.
   Không giả vờ đã gọi một skill/công cụ không cài trên VPS.

## Brief tối thiểu trước khi viết

Ghi người đọc, truy vấn chính, câu hỏi cần trả lời, event_key, URL bài hiện có,
nguồn gốc và ngày nguồn/sự kiện. Lập bảng nội bộ: dữ kiện → nguồn → phạm vi →
điều chưa biết. Khẳng định về dự án/quy hoạch/pháp lý phải có nguồn chính thức.
Nếu thiếu nguồn thì thu hẹp bài hoặc giữ nháp; không lấy độ dài để bù bằng chứng.

## Cổng chất lượng trước xuất bản

- Mở đầu trả lời thẳng: có gì mới, ở đâu, đến thời điểm nào và ảnh hưởng tới câu
  hỏi nào của người mua. Không mở bằng nhận định chung về thị trường sôi động.
- Bài có phân tích riêng: ít nhất một bảng đối chiếu/mốc, một ví dụ hoặc quy
  trình áp dụng, và danh sách câu hỏi cụ thể trước khi liên hệ/đi xem.
- Ví dụ giả định phải ghi rõ ngay tại ví dụ. Công thức, đơn vị và phép tính phải
  kiểm lại. Không biến số minh họa thành báo giá, tin rao hay dữ liệu Radar.
- Dàn ý khoảng 5–8 phần có ích là điểm khởi đầu cho explainer. Khoảng 1.200–1.800
  đơn vị tách bằng khoảng trắng có thể dùng để ước lượng bản đầy đủ tiếng Việt,
  không phải yêu cầu Google hoặc cổng đếm từ. Bài ngắn chỉ đạt nếu trả lời đủ;
  bài dài vẫn loại nếu lặp cảnh báo, thiếu dữ kiện hoặc kéo dài cho đủ số.
- Dẫn nguồn rõ tại chỗ có số liệu và trong khối nguồn; diễn giải ngắn, bổ sung
  phân tích nguyên bản. Không sao chép toàn bài hoặc thay vài từ của bài báo.
- Giữ ngày xuất bản ban đầu, đổi ngày sửa khi nội dung thay đổi đáng kể. Không
  gọi ghi nhận cũ là giá hiện tại; tách giá rao, giao dịch và vốn dự án.
- FAQ trả lời thắc mắc thực, không lặp nguyên toàn bài. Liên kết nội bộ và CTA
  phù hợp địa bàn/loại tài sản; không ép bài căn hộ vào tín hiệu đất nền.

## Hình ảnh

Mỗi explainer cần ít nhất một hình có ích: ảnh được phép, hình minh họa gốc hoặc
sơ đồ/bảng trực quan đúng dữ kiện. Ưu tiên ảnh thực có quyền dùng khi phản ánh
hiện trường; không tải ảnh báo để thay cho việc kiểm tra quyền sử dụng.

Ảnh AI phải ghi ngay dưới ảnh là minh họa, không phải dự án/hiện trường/bản đồ
quy hoạch. Không vẽ tuyến, nút giao hay phạm vi ngập giả rồi trình bày là thực.
Alt mô tả nội dung ảnh tự nhiên, không nhồi từ khóa. Nén WebP, đặt kích thước
thực để giữ bố cục; kiểm tra URL ảnh HTTP 200, mobile và ảnh chia sẻ/NewsArticle.
Ảnh phục vụ bài và được duyệt tại `static/images/seo/` là asset sản phẩm có thể
commit; ảnh crawl, file nguồn lớn, log và proof runtime vẫn nằm ngoài Git.

## Vòng sửa và kiểm chứng

### Trình bày trang chi tiết

Template bài dùng bố cục editorial trong `templates/seo_article.html` và CSS
riêng `static/css/seo_article.css`. Giữ tiêu đề, tác giả/ngày và ảnh ở đầu;
thân bài là một cột đọc, mục lục bên phải desktop và disclosure native trên
mobile. Nguồn có link trực tiếp từ đầu bài tới khối đầy đủ cuối bài. Không
thêm khối trust lớn hoặc nhiều CTA trước thân bài. Bảng cuộn trong khung có
nhãn và nhận focus bàn phím; mục lục phải nhảy đúng neo, không bị header che.
Thử cả bài có ảnh và bài không ảnh, desktop và mobile sau khi đổi template.

Bốn trang danh mục `/tin-tuc`, `/tin-tuc/chu-de-nong`,
`/tin-tuc/du-lieu-radarbds`, `/tin-tuc/quyet-dinh-van-ban` dùng thanh chuyển mục
chung và stylesheet riêng `static/css/seo_news_hubs.css`. Ảnh bài đã duyệt được
truyền vào thẻ tin; không dựng ảnh hiện trường hoặc thumbnail dữ liệu giả.
Danh mục dữ liệu giữ tìm kiếm/chủ đề/xem thêm; văn bản giữ bộ lọc cơ quan,
loại, năm và chỉ hiện hồ sơ vượt cổng công khai. Phương pháp và thông tin biên
tập nằm trong disclosure có thể mở, tránh đẩy danh sách bài xuống. Kiểm tra
filter, empty/reset, link đích, mục đang chọn và không tràn chiều ngang mobile.

Đọc lại như người mua: sau bài có thể tính gì, phân biệt gì và hỏi gì cụ thể?
Nếu chỉ nhớ “cần kiểm tra pháp lý, quy hoạch” thì bản thảo còn chung chung.
Rà các phép tính; mở nguồn; xem bài ở desktop/mobile; kiểm tra ảnh/caption,
bảng, link nguồn, ngày, schema, canonical và sitemap trước khi báo thành công.

Lưu brief, danh sách nguồn, prompt ảnh, file ảnh, ngày biên tập và proof theo
event_key. Web, Facebook và video có trạng thái riêng; viết lại web không tự
đăng lại hay chỉnh các post/video cũ. Giữ một URL cho một sự kiện/ý định đọc.

## Bốn bài mẫu cập nhật 16/10/2026

- Bà Điểm: phân biệt vốn sơ bộ, hồ sơ người mua và minh họa vốn dự phòng.
- Vành đai 4: bảng hai thành phần, đo đường tới nút giao, ví dụ so giá chào.
- Căn hộ: bảng 50/60/70 m² ở giá giả định 45 triệu, mẫu số diện tích và tổng tiền.
- Chống ngập: tách tiến độ/phạm vi/hiện trạng, mẫu ghi nhận nhà và đường vào.

Bốn cover AI được tạo riêng theo brief 16:9, phong cách biên tập xanh trầm và
trung tính: sân chung khu căn hộ giả định; nút giao giả định; máy tính và mặt
bằng minh họa ngân sách; cửa van kênh giả định. Không có logo, địa danh nhận
diện, bản đồ hay chữ quảng cáo. Bản PNG gốc được giữ trong kho generated_images
của phiên làm việc; bản WebP dùng trên web ở `static/images/seo/news/*-20261016.webp`.
