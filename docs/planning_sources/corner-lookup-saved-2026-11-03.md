# Tra tọa độ/góc ranh, OCR kiểm lại và bản lưu local — 03/11/2026

## Phạm vi

Luồng hiện có WGS84, VN2000, nhập3–100 góc và OCR có bước xác nhận. Đợt này
bổ sung hệ chiếu và lưu/mở lại ranh tự nhập. Không thu thập ranh từ nguồn khác,
không biến ranh người dùng thành thửa GIS hoặc hồ sơ có giá trị pháp lý.

## Hệ chiếu

Backend allowlist16 KTT TM-3:103°00′,104°00′,104°30′,104°45′,105°00′,
105°30′,105°45′,106°00′,106°15′,106°30′,107°00′,107°15′,107°30′,
107°45′,108°15′,108°30′; thêm UTM48N/49N. UI dùng đúng18 khóa backend.
Không cho nhập chuỗi PROJ/URL/EPSG tùy ý.

EPSG9205–9218,5899,3405,3406 từ cơ sở dữ liệu EPSG của pyproj hiện có.
TM-3 105°00′ tạo ProjectedCRS trên **VN2000 EPSG4756**, TransverseMercator,
lat0=0,lon0=105,k=.9999,falseEasting=500000,falseNorthing=0; không thay datum
bằng WGS84 chỉ vì cùng ellipsoid. TransformerGroup vẫn `allow_ballpark=False`,
always_xy; đầu vào UI X=northing,Y=easting, GeoJSON output longitude/latitude.
Lru bound theo kích thước allowlist; không thêm dependency.

Chọn hệ chiếu **theo tờ hồ sơ gốc**, không gán KTT theo tỉnh mới/sáp nhập hoặc
đoán từ vị trí bản đồ. Các hệ cùng tên địa phương có thể khác múi/niên đại;
không tự chọn thay người dùng. Bảng KTT bản đồ hành chính không được dùng như
bảng khẳng định mọi sổ địa chính cùng hệ. Kiểm roundtrip dưới1m chỉ xác nhận
pipeline/axis, không đo sai số khảo sát độc lập của từng địa phương.

## OCR

Giữ crop/rotate, giới hạn file/pixel, same-origin Tesseract, không lưu ảnh hoặc
gửi OCR bên thứ ba. Draft luôn phải đối chiếu ảnh và tick xác nhận. Sửa chữ số
reset xác nhận. Đổi hệ tọa độ **hoặc hệ chiếu** hủy tra cứu và reset OCR, loại
kết quả muộn; không tự vẽ từ draft chưa xác nhận. Các test scanner hiện có qua.

## Lưu và mở lại

Tờ/thửa → Tra cứu theo **Góc ranh** → chọn hệ → nhập/áp dụng tọa độ đã kiểm
→ **Xem ranh từ tọa độ**. Sau khi dựng thành công, ẩn bảng kết quả đo bằng×
(giữ ranh), mở lại Tờ/thửa → Góc ranh, đặt tên và **Lưu ranh đã kiểm tra**.

Module `planning_corner_saved.js`, key `radar.saved-corners.v1` trong
localStorage của origin hiện tại. Tối đa20 bản, tên80 ký tự, tọa độ12000 ký tự,
đọc storage cap300000 ký tự. Chỉ lưu name/system/crs/corners gốc; không lưu
ảnh sổ/tên ảnh/chủ đất/GCN, không gửi dữ liệu lưu lên server hoặc đồng bộ account.
Localhost và domain thật là hai kho khác nhau. Xóa browser data sẽ mất bản lưu.

Chỉ cho lưu nếu payload hiện tại bằng payload đã được corners.json kiểm thành
công. Sửa bất kỳ số/hệ chiếu cần dựng lại trước khi lưu. Đọc kho lỗi/quá giới
hạn trả danh sách rỗng; ghi bị chặn/quota báo lỗi, không khẳng định đã lưu.
Tên render bằng textContent, không HTML. Mở lại dùng raw tọa độ+CRS đã lưu,
kiểm CRS trong allowlist UI và gọi lại corners.json validate; không gọi GIS.
Xóa bản lưu không xóa ranh đang xem. Không tự phục hồi ranh sau mỗi lần mở Maps;
người dùng chọn bản muốn mở.

## Kiểm chứng

- 30 Python tests tọa độ/OCR/asset qua, bao gồm thêm roundtrip105°00′,
105°30′,106°30′,107°45′,108°15′ và fail-closed/missing projection.
- 7 Node tests storage/OCR/đo vẽ qua; runtime parcel viewport/toggle/cleanup qua.
- Chrome mobile emulation390×844: nhập VN2000 TM3 108°15′ từ4 điểm thử,
  dựng ranh HTTP200, lưu, reload, mở lại HTTP200 giữ nguyên từng dòng tọa độ
  và CRS, sửa số bị chặn lưu, xóa hết bản lưu vẫn giữ ranh. Script ignored
  `.local/test-corners-browser.py`, screenshot `.local/corners-browser/restored-mobile.png`.
  Preview riêng port5066 bật RADAR_PLANNING_LIVE_ENABLED=1, không đổi server5055.
- Chưa deploy đợt này, chưa thử trên điện thoại vật lý. OCR UI được kiểm qua
  runtime draft/confirm/reset, không dùng sổ thật làm fixture. Chưa có điểm
  khống chế khảo sát độc lập để kiểm sai số VN2000 ngoài roundtrip.

Không cam kết chính xác địa chính từ phép đổi hệ hoặc OCR. Hệ khác lịch sử/
trục/đơn vị vẫn phải đối chiếu hồ sơ; app không đoán hay tự sửa để ép kết quả.
