# Thiết kế đo hành vi người dùng Radar BDS

Mở rộng **Admin → Tăng trưởng** để mỗi tuần chọn được một việc cải thiện nội dung,
UI hoặc dữ liệu sản phẩm. Báo cáo chính trả lời bốn câu hỏi. Có bao nhiêu lượt
truy cập mỗi ngày? Khách vào trang nào? Họ dừng ở phần nào hoặc bước nào? Thay đổi
đã làm có giúp nhiều người hoàn thành tác vụ hơn không?

## Nền hiện có

- `/admin/api/growth` đã có kỳ ngày, tuần, tháng và năm theo giờ Việt Nam. Báo cáo
  có nguồn traffic, CTA, hành vi, D1/D7 của tài khoản, đơn và thanh toán xác nhận.
- `page_engagement` ghi các bản cập nhật cộng dồn theo mã ngẫu nhiên của một lần
  mở trang. Admin hiện hiển thị tối đa 30 trang, thời gian tương tác trung bình,
  lượt thoát dưới 10 giây có tín hiệu rời trang, và các mốc cuộn của bài dài.
- Mã lần mở trang chưa nối các trang trong cùng phiên. Dữ liệu cũ dùng để so sánh
  các chỉ số vốn đã đo được. Chỉ số phiên và phễu mới bắt đầu từ ngày bật đo.

## Báo cáo trong Admin

| Màn hình | Hiển thị mặc định | Quyết định có thể đưa ra |
| --- | --- | --- |
| Traffic theo ngày | Lượt xem, số phiên bắt đầu, số trình duyệt đo được nếu có định danh được bật, đường so sánh kỳ trước. Bấm ngày để xem bảng trang và nguồn. | Ngày tăng traffic đến từ trang và nguồn nào? |
| Trang được xem | URL, lượt xem, số phiên có xem, số phiên bắt đầu ở trang đó, thời gian tương tác trung vị, thoát sớm, đích tiếp theo và tỷ lệ làm hành động chính. Lọc theo nguồn, thiết bị, nhóm trang. | Trang nào kéo khách vào, trang nào dẫn khách dùng sản phẩm? |
| Chi tiết trang | Với bài viết, hiển thị số tới từng H2 hoặc mốc cuộn. Với công cụ, hiển thị số đến từng bước, lỗi, kết quả trống và số rời trước bước kế tiếp. | Cần sửa đoạn nội dung, nút, form hay bổ sung độ phủ dữ liệu? |
| So sánh thay đổi | Hai kỳ hoàn chỉnh cùng số ngày, số mẫu, chênh lệch điểm phần trăm và mốc phát hành do người vận hành ghi. Xuất CSV số liệu tổng hợp theo bộ lọc. | Sau khi sửa, tỷ lệ hoàn thành thay đổi ra sao? |

Mặc định mở 7 ngày trọn vẹn gần nhất, chọn được 28 ngày hoặc kỳ có ngày bắt đầu
và kết thúc. Hôm nay có nhãn “chưa hết ngày”. Bảng phân trang đầy đủ và tìm được
một URL cụ thể dù có ít lượt xem. Đồ thị ngày có ngày không phát sinh lượt xem,
phân biệt với ngày nằm trước mốc đo hoặc có lỗi thu thập. Giữ bộ lọc nguồn traffic
độc lập với công tắc nguồn tin rao Facebook/Guland.

## Định nghĩa chỉ số

- **Lượt xem** là một lần mở URL công khai đo được, đếm một lần theo
  `view_id`. Các bản cập nhật thời gian, cuộn và rời trang dùng chung mã đó.
  Xếp lượt xem theo thời điểm mở đầu tiên theo giờ Việt Nam, kể cả cập nhật đến
  sau nửa đêm. Lượt xem trực tiếp Maps từ URL trang chủ vẫn là lượt xem `/`.
  Phân biệt Maps, Săn Deal và Tin rao bằng tên tính năng cố định.
- **Phiên** bắt đầu khi có hoạt động đầu tiên hoặc sau 30 phút không có hoạt động.
  Dùng mã phiên ngẫu nhiên, chuyển giữa các trang cùng website khi việc đo được
  cho phép. Biểu đồ đếm phiên theo ngày bắt đầu. Bảng trang đếm phiên có xem
  trang trong kỳ, vì vậy một phiên có thể góp mặt ở nhiều trang.
- **Trình duyệt đo được** cần mã trình duyệt riêng, chỉ bổ sung nếu có nhu cầu và
  cơ chế cho phép phù hợp. Thiết bị khác, cửa sổ riêng tư và việc xóa dữ liệu có
  thể tạo mã mới. Giai đoạn đầu báo cáo lượt xem và phiên. D1/D7 của tài khoản
  tiếp tục dùng báo cáo hiện có.
- **Thời gian tương tác** dùng thời gian tab hiển thị theo cách đo hiện tại,
  dừng cộng sau 60 giây không hoạt động, tối đa 30 phút mỗi lần mở. Hiển thị trung
  vị và số lượt đủ dữ liệu. Lượt chỉ nhận tín hiệu mở đầu có trạng thái thiếu dữ
  liệu thời gian, tránh quy thành 0 giây.
- **Rớt khi đọc** là số lượt tới một mốc nhưng chưa thấy tới mốc kế tiếp trong
  các lượt đủ dữ liệu. Ví dụ 60 lượt tới mục A, 24 tới mục B thì còn 36 lượt
  chưa ghi nhận tới B. Tách số đã bấm hành động chính, số rời trang quan sát được
  và số mất tín hiệu. Với bài có cấu trúc ổn định, dùng ID của H2 đã hiển thị ít
  nhất một giây trong vùng nhìn. Các bài còn lại dùng mốc cuộn 25/50/75/90%.
- **Rớt trong phễu** tính trên phiên đi đúng thứ tự, trong cùng luồng từ bước
  đầu. Đếm mỗi phiên một lần mỗi bước. Chỉ kết luận rớt sau khi phiên đã hết
  cửa sổ 30 phút. Hiển thị rớt tại bước X bằng số phiên tới X trừ số đến X+1,
  chia cho số tới X. Ghi riêng lỗi tải, không có kết quả và phiên chưa có tín hiệu
  tiếp theo. Loại trừ phiên đang mở khỏi phép so sánh tỷ lệ rớt.
- **Trang hấp dẫn** phụ thuộc mục tiêu. Bài hướng dẫn dùng độ sâu đọc và tỷ lệ
  mở công cụ. Trang công cụ dùng tỷ lệ xem được kết quả. Trang bán hàng dùng
  đơn xác nhận thanh toán, theo khái niệm cohort và ngày thanh toán đã có.
  Thao tác nhanh và thành công vẫn là tín hiệu tốt.

## Luồng ưu tiên và hợp đồng đo

| Luồng | Thứ tự tín hiệu | Tín hiệu cần đọc riêng |
| --- | --- | --- |
| Bài quy hoạch → Maps | Mở bài → tới phần hướng dẫn → bấm mở Maps → Maps hiển thị | Mất tín hiệu sau click, Maps lỗi tải, chuyển trang khác trong site |
| Tra tờ/thửa, tọa độ | Maps hiển thị → gửi tra cứu → hiện kết quả | Không có dữ liệu, lỗi kỹ thuật, kết quả thành công |
| Định giá và bảng giá đất | Mở công cụ → gửi truy vấn → hiện kết quả → bấm xem tin nếu có | Form chưa gửi, lỗi đầu vào, kết quả trống |
| Bản đồ địa giới → mua | Xem trang → mở checkout → tạo đơn → thanh toán xác nhận | Lỗi tạo đơn, đơn chưa thanh toán. Xác nhận tiền từ máy chủ |

Tái sử dụng `page_engagement`, `cta_clicked`, `listing_map_opened`,
`planning_lookup`, `tool_used` và sự kiện checkout hiện có. Kiểm tra thời điểm
phát trước khi đưa vào phễu. Ví dụ mở chú giải và mở nguồn trong
`planning_lookup` chỉ là tương tác, còn kết quả tra cứu cần dựa trên thao tác tra
thửa hoặc tọa độ. Bổ sung tín hiệu gửi hoặc kết quả chỉ ở nơi thiếu. Khi người dùng
thử lại nhiều lần, ghép gửi và kết quả theo mã lần tra ngẫu nhiên nếu cần phân
tích lỗi theo lần thử. Phễu checkout dùng xác nhận đơn phía máy chủ và liên kết
phiên chỉ khi truyền được trực tiếp. Đơn thiếu liên kết vẫn thuộc báo cáo doanh
thu hiện có.

## Thu thập và bảo vệ dữ liệu

- Dùng tracker first-party và Admin hiện có. Giữ registry URL và tính năng được
  phép, bỏ query/hash khỏi URL trang. Lưu nguồn theo nhóm, tên chiến dịch đã
  kiểm tra, loại thiết bị và ID mục nội dung ổn định. Bỏ chuỗi tìm kiếm, số thửa,
  tọa độ, nội dung form, IP thô và dữ liệu liên hệ khỏi telemetry phân tích.
- Dùng mã phiên ngắn hạn, không ghép hồ sơ khách và không dùng fingerprint.
  Giữ GPC/DNT và các lựa chọn quyền riêng tư hiện có. Lọc admin, lượt kiểm thử
  và bot nhận diện được. Hiển thị độ phủ của instrumentation và tỷ lệ lượt xem
  có tín hiệu rời trang. CSV chỉ xuất số tổng hợp và yêu cầu quyền admin.
- Ghi thời điểm mở trang ngay lần đầu nhận, giới hạn kích thước và tần suất
  event. Gửi cập nhật theo mốc hoặc theo nhịp hiện có, gộp retry bằng khóa sự kiện.
  Báo cáo đọc bảng tổng hợp hoặc truy vấn có giới hạn và index theo ngày/URL.
  Tránh thêm truy vấn vào request trả HTML công khai để giữ đường cache.
  Đề xuất giữ event chi tiết 90 ngày, bảng tổng hợp theo ngày 13 tháng.

## Lịch sử dụng báo cáo và tiêu chí nghiệm thu

**Mỗi tuần**, so 7 ngày hoàn chỉnh với 7 ngày trước. Chọn tối đa ba điểm nghẽn có
nhiều lượt bị ảnh hưởng. Giai đoạn đầu dùng ngưỡng tham khảo 30 lượt ở mẫu số
trước khi gắn cờ; dưới ngưỡng thì ghi “mẫu thấp” và gom 28 ngày hoặc theo nhóm
trang. Ghi URL, bước rớt, số liệu gốc, giả thuyết, người phụ trách và một thay đổi
cụ thể. Ví dụ nhiều lượt bấm mở Maps nhưng không thấy Maps tải thì thử trên
thiết bị tương ứng. Maps tải tốt mà nhiều truy vấn hợp lệ bị trống thì ưu tiên
kiểm tra độ phủ nguồn và cách thông báo trạng thái trống.

**Mỗi tháng**, so 28 ngày với 28 ngày trước. Kiểm tra lượt xem, tỷ lệ hoàn thành,
lỗi và số mẫu trước/sau. Dùng Search Console để đối chiếu impression, click và CTR
khi câu hỏi là người tìm kiếm có vào trang hay không. Dùng Admin cho hành vi sau
khi vào. Ghi lại đợt SEO, thay đổi nguồn traffic và ngày phát hành trước khi quy
kết hiệu quả cho một thay đổi UI.

1. **Đợt 1.** Traffic theo ngày và URL, so kỳ trước, chi tiết cuộn, xuất CSV.
   Kiểm chứng refresh tạo lượt mới, heartbeat không tăng lượt, mở gần nửa đêm
   chỉ được tính một lần, ngày trống hiển thị đúng, khách bị chặn khỏi dữ liệu admin.
2. **Đợt 2.** Nối phiên và phễu bài quy hoạch → Maps → tra cứu trước. Kiểm chứng
   hai trang trong một phiên, Maps mở thành công, gửi tra rồi nhận kết quả,
   không có dữ liệu, retry, rời giữa chừng, hai tab và trình duyệt opt-out.
   Đối chiếu một hành trình hoàn chỉnh trên mobile và desktop.
3. **Đợt 3.** Bổ sung H2 cho mẫu bài chính và phễu định giá, bảng giá, checkout
   sau khi phễu Maps ổn định. Dùng một báo cáo tuần thật để tạo việc cải thiện
   đầu tiên và một báo cáo tháng để đánh giá.
### Tra phường Thủ Dầu Một

Trong màn hình tăng trưởng, chọn kỳ rồi đọc ô **Tra phường Thủ Dầu Một**. Mẫu số là số phiên đo được có tìm hoặc chọn phường trong kỳ. Tử số là số phiên đã hiện thông tin của một phường được chọn trên bản đồ hoặc từ danh mục dự phòng. Chỉ mở trang, nhận liên kết hay hiển thị gợi ý chưa tính là hoàn tất. Mỗi phiên chỉ tính một lần trong kỳ. Hai số bấm quy hoạch và tin rao thể hiện lượt chuyển tiếp theo phiên, chưa xác nhận trang đích đã tải. Số liệu bắt đầu từ lúc triển khai; trước đó chưa đo được tỷ lệ này.

**Nghiệm thu với 5 người mới.** Dùng điện thoại của người tham gia, mở trang từ đầu và bấm giờ khi giao đề. Nhờ họ tìm Hiệp Thành cũ, kể tên các phường hiện tại có liên quan rồi gửi liên kết để người nhận mở lại đúng ranh. Dừng ở 60 giây. Ghi thời gian, lựa chọn đúng/sai, nơi bị kẹt và loại điện thoại, không ghi thông tin liên hệ. Mục tiêu 4/5 người tự hoàn thành. Kiểm tra riêng Phú Lợi trùng tên, Hòa Phú có ranh suy luận và trường hợp mạng yếu.

**Mẫu bài Facebook/Zalo.** “Tin rao ghi Hiệp Thành cũ, giờ tìm ở phường nào? Tùy vị trí, địa chỉ có thể thuộc phường Thủ Dầu Một hoặc Phú Lợi. Mở ranh Hiệp Thành, chọn một trong hai phường hiện tại để đối chiếu rồi gửi đúng góc tra cứu cho người đang đi xem đất cùng bạn.” [Tra Hiệp Thành trên Radar BDS](https://radarbds.vn/ban-do-thu-dau-mot#layer-legacy/area-hiep-thanh).

Sau 28 ngày đầy đủ kể từ phát hành, so sánh lượt nhấp và truy vấn Google của chính URL này với 28 ngày trước phát hành. Báo số phiên tra đạt/tổng trong cùng kỳ và ghi riêng các phiên bấm chuyển tiếp. Chọn câu hỏi tiếp theo từ các truy vấn thực tế. Quyết định mở rộng Bến Cát sau khi đã xem mẫu thực địa và số liệu.
