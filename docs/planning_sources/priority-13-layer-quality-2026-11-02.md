# Kiểm chất lượng lớp bản đồ: 13 thị trường ưu tiên

**Đính chính sau xử lý cùng ngày:** xem [kết quả kiểm lại và sửa](priority-13-layer-quality-resolution-2026-11-02.md).
Lỗi audit bỏ qua status chuỗi `"200"` và lấy tâm window ngoài vùng ảnh đã được sửa.
63/63 mẫu reference đúng điểm trả ảnh; 3 composite GIS production trả PNG256.
Các lỗi403/404/timeout phía dưới là lịch sử phép kiểm, không phải kết luận nguồn hỏng.

Ngày 02/11/2026. Phạm vi tỉnh cũ, không suy độ phủ tỉnh mới. Đây là rà cấu hình
và mẫu raster có giới hạn, **chưa phải nghiệm thu toàn bộ Maps/độ phủ pháp lý**.
Không thay các nguồn đang chạy chỉ vì một điểm trả trống hoặc máy kiểm timeout.

## Phương pháp và bằng chứng

`scripts/audit_priority_planning_layers.py` đọc registry 2030/phân khu/chung/
xây dựng; 2 mức zoom mỗi lớp (min native và gần tới16, không vượt max native).
Ưu tiên mẫu dương tính cũ có tọa độ nằm trong layer; còn lại lấy tâm window
layer. Điểm tâm không chứng minh nằm trong vùng quy hoạch, có thể ở biển/vùng
không lập đồ án. Đợt đầu còn kiểm tâm focus tỉnh; giữ kết quả riêng, không dùng
điểm BRVT đất liền chứng minh Côn Đảo.

GIS: 3 theme phân khu/chung/chi tiết, primary service tại Tân An/Quận1/Vũng Tàu,
zoom12/16 (18 requests). Chưa kiểm supplement/composite, nên lỗi primary không
chứng minh lớp tổng hợp trên Maps lỗi. Giới hạn4 kết nối, timeout5/15s, tối đa
8MB/image và2048px; TLS bật, không retry/vượt403. Không đổi cache/routing.

Gộp các lượt có **106 URL duy nhất**: 74 URL ít nhất một lần trả ảnh giải mã
được và có alpha, 32 URL chưa có ảnh thành công. Trong đó18 là timeout GIS
primary; còn lại là403/404 của các điểm nguồn tham khảo. Không cộng lượt lặp
thành mẫu độc lập. 32 reference layer–province entries, thêm9 GIS entries.
Đây không phải tỷ lệ phần trăm diện tích phủ hoặc tỷ lệ thửa tra được.

Bằng chứng có ngày/URL/điểm/zoom/status/kích thước/SHA256/alpha:
[JSON audit](priority-13-layer-quality-2026-11-02.json). Ảnh runtime ignored ở
`.local/priority-layer-quality*-20261102/`; contact sheet đã xem tại
`.local/priority-layer-quality-contact.png`. Quan sát ảnh có cả bản ghi chú,
vùng màu đơn và ô gần trắng; HTTP200/alpha không đủ để ghi “ảnh rõ, đầy đủ”.
Chưa độc lập xác minh quyết định phê duyệt/tỷ lệ từ tiêu đề/ảnh từng đồ án.

## Kết quả theo tỉnh cũ

PK=phân khu, C=chung, XD=xây dựng, CT=chi tiết. “Có mẫu” chỉ nói điểm đã kiểm.
Thiếu theme là chưa có trong registry đang rà, không phải địa phương không có.

| Tỉnh cũ | Kết quả ảnh/nguồn đã kiểm | Khoảng trống hoặc vấn đề cần tiếp tục |
| --- | --- | --- |
| Bình Dương | 2030 và XD có mẫu gần/xa | PK/C/CT primary GIS timeout cả2 zoom; cần kiểm composite/source bằng browser/VPS. |
| TP.HCM | 2030 và XD có mẫu gần/xa | PK/C/CT primary GIS timeout; không suy tình trạng cả HCM từ điểm Quận1. |
| Hà Nội | 2030 và PK có mẫu gần/xa | C/CT/XD chưa có trong registry; không đổi lớp tầm nhìn thành QH chung. |
| Đồng Nai | 2030 và XD có mẫu gần/xa | PK/C/CT chưa có; không gán lớp Bình Phước hoặc HCM sang Đồng Nai cũ. |
| Long An | 2030 có mẫu gần/xa | PK/C/CT/XD chưa có. |
| BRVT | 2030 đất liền và Côn Đảo kiểm riêng; XD max native12 có mẫu | PK/C/CT primary GIS timeout. Mẫu XD tổng quan không chứng minh đọc được chi tiết ở zoom16. |
| Hưng Yên | 2030 và XD có mẫu | XD max native12; phóng gần là overzoom, không tạo thêm độ nét. PK/C/CT thiếu. |
| Hải Phòng | 2030/PK/C/XD có mẫu tại điểm focus/điểm đã có ảnh | 2030 tâm layer trả404 ở11/16 nhưng điểm focus có ảnh; window không phải mặt nạ độ phủ. Một số ảnh chỉ nét bản vẽ nhỏ; chưa nghiệm thu đọc chú giải. CT thiếu. |
| Đà Nẵng | 2030/PK/XD có mẫu thành công | Đổi điểm kiểm ghi403 cho2030/PK; chưa xác minh ổn định theo vùng. C/CT thiếu. |
| Khánh Hòa | 2030 và XD có mẫu thành công | PK403 ở12/16; 2030 tâm layer404 ở10/16 nhưng focus có ảnh. C/CT thiếu. Không nới bounds hay hạ zoom để che thiếu nguồn. |
| Bắc Ninh | 2030/PK/C/XD có mẫu gần/xa | CT thiếu; dùng đúng coverage Bắc Ninh cũ. Folder qh-xd của C đã đối chiếu nhãn control nguồn trong audit trước; chưa tái đọc control live đợt này. |
| Quảng Ninh | 2030/PK/C có mẫu | PK overview8 có ảnh, gần15 trả403 ở các điểm kiểm; mẫu2030 gần có ô gần trắng. XD/CT thiếu. |
| Lâm Đồng | 2030 có mẫu gần/xa | PK/C/CT/XD chưa có. Không suy Bình Thuận/Đắk Nông vì cùng tỉnh mới. |

## Đúng theme, địa bàn và chồng lớp

- Registry phân khu public không chứa `/xem-quy-hoach/` của “QH khác”; không
  đưa các sheet đã gỡ trở lại. Kiểm config/runtime giữ exact URL/theme/coverage.
- Trong **nhóm13**, không thấy template tham khảo giống nhau bị dùng cho hai
  theme khác nhau. Ngoài phạm vi có Huế dùng cùng template cho PK/XD: ghi nhận,
  chưa sửa vì chưa kiểm control gốc và không thuộc đợt13 tỉnh.
- BRVT/Côn Đảo dùng chung tile source2030 với hai window riêng; lấy mẫu mỗi
  window riêng. Chia source không tự là lỗi chồng lớp. Một tile overview có thể
  chạm cả window; chưa pixel-audit toàn bộ rìa/biển.
- GIS HCM/BD/BRVT phân biệt service PK/C/CT qua registry/metadata; không thay
  ảnh khi thiếu theme. Chưa có ảnh GIS mới thành công từ máy kiểm lần này.
- Người dùng bật nhiều theme cùng lúc thì chúng phủ lên nhau theo z-index:
  đó là hành vi chủ ý, không phải cơ chế chọn một theme. Chưa thực hiện kiểm
  toàn bộ giao diện13 tỉnh trên điện thoại/browser cho task này.
- Native min/max trong registry được tôn trọng. Nguồn min11/12/13 sẽ chưa
  hiện khi zoom thấp hơn; max12/14 chỉ overzoom khi gần. Chưa làm overview mới.

## Kiểm tra và việc cần làm tiếp

14 Python regressions và7 Node tests cho exact source/theme, historic province,
overview descriptors và giữ GIS đều qua. Không thay registry hoặc tuyên bố
hoàn tất nguồn chỉ từ mẫu ảnh. Script audit và tài liệu mới chưa deploy.

Ưu tiên: (1) kiểm PK Khánh Hòa/Quảng Ninh và ảnh Đà Nẵng bằng browser bình
thường, giữ403 nếu nguồn chặn; (2) kiểm GIS composite từ production/VPS;
(3) audit vùng đô thị và chú giải cho ô gần trắng; (4) chỉ tạo overview đúng
nguồn khi đã có ảnh chi tiết ổn định và artifact được hash-verify.
