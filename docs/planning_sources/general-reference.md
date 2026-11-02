# QH chung bổ sung từ Guland — 2026-11-02

Bổ sung theme `urban_general` tại **Bắc Giang, Bắc Ninh, Hải Dương, Hải Phòng,
Nam Định, Quảng Ninh**. Giữ GIS Bình Dương/TP.HCM/BRVT và bản vẽ/PDF đã có.
Không lấy QH xây dựng, phân khu, SDĐ2030 hay bản tầm nhìn để đổi tên thành QH chung.

## Nguồn và phạm vi

Rà 60 trang tỉnh cũ ngoài ba tỉnh đã có GIS. Đọc nút “QH chung” (cả biến thể
có tên QH ... chung), `data-url` và `data-type` qua Chrome công khai; không xuất
cookie/token hoặc dùng API trả phí. 6 trang có control riêng; 54 trang chưa thấy
control riêng trong lần rà, không kết luận không tồn tại đồ án ở mọi huyện/xã.
Hà Nội có QH2045–2065/100 năm với nhãn riêng; chưa tự gán vào QH chung.

`planning_general_reference.json` đăng ký 6 nguồn, audit tương ứng giữ 63 trạng
thái (3 existing_gis_preserved, 6 verified_samples, 54 no_public_control), URL và
mẫu ảnh HTTP/PNG/SHA256/tọa độ. Nguồn Bắc Ninh có thư mục qh-xd nhưng được trang
hiển thị dưới nút QH chung; dùng đúng nhãn nguồn và không suy chỉ theo tên folder.
Giữ nguyên query `?v=ok` của template Bắc Giang.

Bounds là window điều hướng tỉnh cũ, không phải polygon pháp lý. Một số nguồn chỉ
phủ đô thị hoặc vài đồ án; mẫu thành công không chứng minh phủ kín tỉnh, tỷ lệ hay
hiệu lực hồ sơ. Mẫu gần Hải Dương/Quảng Ninh đã kiểm tại window các thành phố,
không lấy vài pixel ở rìa ô overview làm bằng chứng đủ chi tiết. Native min/max
chỉ dùng mức có ảnh thật; Bắc Giang hiện min12/max16, một số tỉnh min12 nên cần
zoom gần. Chưa tạo overview offline, không fan-out ảnh lớn khi zoom xa.

## Tích hợp và giới hạn

`GENERAL_REFERENCE_LAYERS` thêm vào catalog; `GENERAL_SOURCE_RULES` inject riêng,
merge vào exact-rules khi validate. Không sửa partition/construction rules và
không nới wildcard nguồn. UI thêm lựa chọn nguồn QH chung tham khảo trong theme
đã có; tự chọn Guland khi không có GIS. Chọn PDF mà thiếu ảnh vẫn giữ trạng thái
thiếu, không âm thầm đổi sang GIS. Khi đổi tỉnh, nút ẩn nếu không có nguồn.

Dùng queue/viewport/abort/LRU của renderer XYZ hiện có, opacity35% mặc định, chỉ
load tỉnh chọn. Theme/URL share vẫn là urban_general; không thay mặc định mở Maps,
ranh thửa, tin rao hay các lớp đang có. Mọi nguồn có attribution và nhãn tham khảo.

## Kiểm chứng

- Mẫu ảnh tại đúng tỉnh cho cả 6 nguồn, có ảnh thật zoom14+; không xác minh mọi ô.
- Runtime kiểm cả 6: chọn đúng nguồn, chỉ một tỉnh, opacity35%, rời window gỡ lớp.
- Regression giữ GIS/PDF cũ, không tự gán nguồn khác, exact rules chặn URL/theme giả.
- Chrome local Hải Phòng: QH chung có ảnh, opacity35%, không lỗi console.

Release: code + hai config JSON, catalog và overlay JS version
`general-reference-20261102`. Không cần chuyển kho ảnh runtime vì dùng XYZ nguồn.
Rollback bằng release code trước; snapshot/cache ranh và GIS hiện có không đổi.
