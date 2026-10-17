# Audit UI công cụ và báo cáo — 18/10/2026

Phạm vi: `/dinh-gia-bds`, `/bang-gia-dat-tphcm`, `/bao-cao` và báo cáo chi tiết.
Dùng cùng kiểu chữ/màu với phần tin tức: Noto Serif tự lưu cho tiêu đề, nền
trắng, xanh Radar và cột nội dung rõ ràng. Asset nằm trong
`static/css/public_research.css`; không thêm thư viện hay đổi phép tính.

## Vấn đề và điều chỉnh

- Định giá: khối bằng chứng lớn trước form và các lớp gradient làm chậm thao tác.
  Chuyển khối này xuống dưới công cụ, rút gọn hero, tách rõ form/kết quả/mẫu so
  sánh, dùng nhãn “giá tham khảo”. Giữ nguyên input, validation, API và redaction.
- Bảng giá: form nhận tin chen trước bảng kết quả. Giữ một form nhận tin ở cuối
  kết quả; ưu tiên truy vấn, bảng, bộ tính theo vị trí và link văn bản gốc.
  Nhãn/nguồn của bảng giá Nhà nước vẫn khác giá từ tin rao.
- Kho báo cáo: hero và summary chiếm nhiều chỗ. Rút thành header và dải metadata;
  featured và thẻ báo cáo gọn, filter khu vực/phường/kỳ giữ nguyên.
- Báo cáo chi tiết: metadata/trust/CTA dồn ở đầu. Thu gọn metadata, thêm mục lục
  neo tới chỉ số/nhận định/phương pháp; đưa form nhận tin về cuối bài. Giá trong
  thẻ tin ghi “GIÁ RAO”, badge “Trong kỳ” thay vì mô tả snapshot cũ là tin mới.

## Kiểm chứng

Test liên quan: `test_public_research_ui.py`, `test_valuation_tool_ui.py`,
`test_tphcm_land_price_tool.py`, `test_tphcm_land_price_calculator.py`,
`test_public_seo.py`, `test_public_content_hubs.py`.

Browser: desktop và 390px, khu vực/phường/diện tích, lỗi đầu vào và kết quả định
giá, tìm đường/đổi trang/mở-tính-đóng bộ tính; lọc báo cáo, mục lục, biểu đồ/bảng.
Kiểm cả báo cáo tổng hợp và báo cáo phường. Không gửi form lead khi smoke test.
Một browser error từ DB local không chứng minh API production hỏng; kiểm riêng
trên production trước khi tuyên bố đã thử thành công end-to-end.

Deploy: giữ main mới và sao lưu chính xác các file VPS đang sửa trước release;
khôi phục byte/mode, kiểm HEAD/service/public URLs và ghi proof ngoài Git.
