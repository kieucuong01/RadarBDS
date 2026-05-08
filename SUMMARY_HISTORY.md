# RADAR BDS - Lịch sử phát triển & Bàn giao

File này lưu trữ các mốc thay đổi quan trọng giữa các phiên làm việc để AI Agent sau này có thể nắm bắt nhanh.

---

## Phiên làm việc: 27/04/2026

### 🚀 Thành tựu chính
1.  **Phủ sóng 13 phường Thủ Dầu Một**: Đã thêm Phú Tân, Phú Thọ. Toàn bộ 13 phường hiện đã có dữ liệu đầy đủ và định dạng có dấu đúng chuẩn trên Dashboard.
2.  **Dữ liệu "khủng"**: Cào thành công **4.641 tin rao mới** từ Guland, nâng tổng số tin trong hệ thống lên hơn **5.700 tin**.
3.  **Tối ưu thuật toán Dedup**: Chuyển từ so sánh toàn cục O(N^2) sang so sánh theo Nhóm (Bucket) theo Phường + Loại BĐS. Tốc độ xử lý tăng gấp 50-100 lần đối với tập dữ liệu lớn.
4.  **Cải thiện Dashboard**:
    *   Mặc định xem xu hướng giá **Theo tuần**.
    *   Thêm nút **"Xem Thêm"** cho phần Top Signal để Dashboard gọn gàng hơn.
    *   Nâng cấp cột nội dung tin rao (hover để xem chi tiết, tích hợp Gallery ảnh).
5.  **Fix Bug quan trọng**:
    *   Sửa lỗi Regex không đọc được diện tích dạng `9m2 x 12.6m`. Hiện tại đã nhận diện đúng là 9m ngang và tính ra tổng diện tích 113.4m².
    *   Sửa lỗi mất phường Phú Tân do lỗi kết nối (ERR_ABORTED) bằng cách tối ưu tham số crawler.

### 🛠️ Thay đổi kỹ thuật
*   **crawler/guland_pw.py**: Thêm `WARD_MAP`, giảm `BATCH_SIZE=5`, tăng `BTN_WAIT_MS=3000`.
*   **cleansing/normalizer.py**: Cập nhật `_WARD_KEYWORDS` và refactor `match_area_helper` để tự động nhận diện 13 phường.
*   **cleansing/dedup.py**: Implement bucketing trong `flag_duplicates_in_db`.
*   **app.py**: Cập nhật logic hiển thị biểu đồ và nút "Xem Thêm".

### 📋 Lưu ý cho phiên sau
*   Khi chạy reprocess lần đầu cho dữ liệu cực lớn, hãy luôn dùng bản `dedup.py` đã tối ưu.
*   Nếu Dashboard không hiện phường nào đó, hãy kiểm tra `raw_listings` xem URL có chứa slug phường đó không, rồi check `_WARD_KEYWORDS` trong `normalizer.py`.

## Phiên làm việc: 06/05/2026

### 🚀 Thành tựu chính
1.  **Giao diện Fintech (High Density)**: Chuyển đổi toàn bộ Dashboard sang phong cách "Compact UI", tăng mật độ thông tin hiển thị lên gấp đôi. Sidebar hỗ trợ thu gọn (Collapsed) cho desktop, giúp không gian làm việc rộng rãi hơn.
2.  **Signal Detail Modal 2.0**: Thiết kế lại Modal chi tiết theo phong cách Glassmorphism hiện đại. Tích hợp **Image Slider** đầy đủ ảnh, bộ đếm ảnh, và các badge MOS/Profit/Price-drop nổi bật trực tiếp trên ảnh đại diện.
3.  **Tối ưu Mobile-First**: Thu gọn Navbar Mobile về 1 dòng duy nhất (Compact row). Tích hợp số lượng Signals và Tin rao trực tiếp vào nhãn Tab dưới dạng Badge, hỗ trợ cuộn ngang (horizontal scroll) mượt mà.
4.  **Hoàn thiện Dữ liệu & Chuyển đổi**:
    *   Bổ sung đầy đủ `description` và toàn bộ mảng `imgs` cho Signal API (Fix lỗi trống mô tả).
    *   Tích hợp nút **Chat Zalo tư vấn** (Zalo: 0343216024) trực tiếp trên card và trong modal để tối ưu hóa tỷ lệ chuyển đổi.
5.  **Sửa lỗi & UX**:
    *   Khắc phục triệt để lỗi bảng tin bị mờ hoặc không click được sau khi áp dụng bộ lọc.
    *   Toàn bộ thẻ Signal giờ là vùng bấm để mở Modal, hỗ trợ mở trang chi tiết ở tab mới (`/listing/:id`).

### 🛠️ Thay đổi kỹ thuật
*   **templates/index.html**: Refactor CSS mobile `@media`, thêm logic `buildSlider` và `slideSignal` JS, tối ưu `switchTab` để xử lý badge click.
*   **app.py**: Cập nhật SQL Query trong `load_data` để SELECT thêm cột `description` cho signals.

### 📋 Lưu ý cho phiên sau
*   Dữ liệu `description` hiện đã được trả về trong API signals, không cần fetch thêm.
*   Cần lưu ý thứ tự `order` của các phần tử trong Header mobile để tránh bị vỡ hàng khi thêm tab mới.

## Phiên làm việc: 06/05/2026 (Phần 2)

### 🚀 Thành tựu chính
1.  **Refactor `app.py` (MVC Architecture)**:
    *   Chia nhỏ "God Object" `app.py` thành mô hình MVC sạch sẽ.
    *   Chuyển toàn bộ logic HTML/CSS sang thư mục `templates/` (file `index.html`).
    *   Tách phần xử lý Database SQL sang `services/market_data.py`.
    *   `app.py` hiện tại mỏng, nhẹ và đóng vai trò đúng nghĩa là một HTTP Router (Controller).
2.  **Refactor `radar.py` (Modular CLI)**:
    *   Chia nhỏ "God Object" `radar.py` (1500 dòng) thành các file theo chức năng trong thư mục `cli/`.
    *   Các module mới: `data_import.py`, `crawlers.py`, `queries.py`, `system.py`, `utils.py`.
    *   `radar.py` trở thành Argparse Router điều hướng lệnh, bảo đảm mọi automation (`crawl_all.bat`) vẫn chạy trơn tru mà không cần sửa file bat.
3.  **Chuẩn hóa AI Agent**: Áp dụng bộ quy tắc *Andrej Karpathy Skills* vào `CLAUDE.md` để đảm bảo phong cách làm việc đơn giản hóa, chính xác, tránh over-engineer của AI trong tương lai.

### 🛠️ Thay đổi kỹ thuật
*   Tạo thư mục `templates/` và `services/`.
*   Tạo thư mục `cli/` chứa toàn bộ lệnh terminal.
*   Cập nhật lớn cho `CLAUDE.md` thêm bộ nguyên tắc AI.

---

## Phiên làm việc: 07/05/2026

### 🚀 Thành tựu chính
1.  **Mở rộng Bến Cát**: Thêm danh sách môi giới và 8 phường thuộc Bến Cát. Crawler Facebook hỗ trợ cào theo khu vực (`--area`).
2.  **Kiến trúc Xử lý Tịnh tiến (Incremental)**: 
    *   Nâng cấp `reprocess` để chỉ quét và định giá những tin mới nạp (Incremental Reprocess).
    *   Tăng tốc độ xử lý từ hàng chục phút xuống còn < 5 giây cho các lượt cào hàng ngày.
3.  **Tối ưu Định giá Big Data**:
    *   Giới hạn tập huấn luyện về **30.000 tin gần nhất** để tối ưu RAM và độ tươi của dữ liệu.
    *   Hỗ trợ append định giá thay vì xóa trắng bảng `valuation_results`.
4.  **Fix Bug phân loại phường**:
    *   Xử lý triệt để việc nhầm tên đường "Mỹ Phước - Tân Vạn" sang phường Mỹ Phước.
    *   Thêm cơ chế City Scoping: Cào khu vực nào thì chỉ map phường thuộc khu vực đó.

### 🛠️ Thay đổi kỹ thuật
*   **cleansing/reprocess.py**: Refactor `reprocess_listings` và `reprocess_valuation` hỗ trợ `incremental_ids`.
*   **config/database_sqlite.py**: Thêm logic `LEFT JOIN` trong `get_raw_for_reprocess`.
*   **cleansing/normalizer.py**: Cập nhật logic `CITY_WARDS` và regex lọc đường.
*   **radar.py**: Thêm tham số `--full` cho lệnh `reprocess` và `--area` cho `crawl-facebook`.

### 📋 Lưu ý cho phiên sau
*   Luôn ưu tiên chạy `radar reprocess` (incremental) hàng ngày.
*   Chỉ dùng `--full` khi có thay đổi logic cốt lõi ở `normalizer.py` hoặc `valuation.py`.
*   Dữ liệu Bến Cát đang được ưu tiên cào bổ sung để làm dầy mẫu.

---
*Người thực hiện: Antigravity AI*
