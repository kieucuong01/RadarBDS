# National Guland Partition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm phân khu các tỉnh còn lại từ Guland, theo cùng quy trình đã dùng cho QH2030.

**Architecture:** Quan sát public controls/network, lưu exact descriptors, lấy mẫu tile và vị trí, rồi đăng ký nguồn theo tỉnh cũ. Giữ nguồn HCM hiện có, chỉ tải viewport và không đổi SDĐ2030 thành phân khu.

**Tech Stack:** Flask, JSON config, Leaflet/JavaScript, Python/Pillow, existing Maps cache.

**Spec:** `docs/superpowers/specs/2026-11-01-national-partition-design.md`, được người dùng duyệt ngày 2026-11-01.

## Global Constraints

- Guland cho phần phân khu mới; GIS HCM hiện có giữ nguyên.
- UI không ghi tên Guland; metadata nguồn kỹ thuật vẫn giữ để kiểm/cập nhật.
- Ranh thửa tỉnh thiếu vẫn tạm dừng. Không stage dirty work Đồng Nai.
- Default partition50%, vệ tinh; filters, listing markers và viewport-loading giữ nguyên.
- Không vượt403/challenge, TLS hoặc quyền browser bị tắt.

## Review Focus

Sai loại bản đồ; sai CRS/grid; template chưa quan sát; tải ngoài viewport; cache hoặc catalogue làm hỏng nguồn đang chạy.

## Task 1 — Quan sát và audit source

- [x] Kiểm quy trình cũ `.local/planning-national-2030/{controls.json,prepare.py,audit.py}`.
- [x] Xác định captures cũ chỉ có control2030, không đủ làm partition source.
- [x] Kết nối tab Guland public đang mở và quan sát nút/layer phân khu thật.
- [x] Thu exact control label/template và coverage từng tỉnh vào ignored captures; không lấy token/cookie.
- [x] Tạo `config/planning_partition_reference_audit.json`: metadata+hash và mẫu tile có tọa độ/zoom/alpha/dimensions, status riêng cho tỉnh chưa có.
- [x] Negative checks: không chấp nhận2030/chung/chi tiết/draft; không coi trang SEO là evidence layer.

**Cập nhật 2026-11-01:** browser đã hoạt động. Đã rà63 controls,318 tile samples; commit `6b5ae926` tích hợp16 nguồn có mẫu dương tính.43 tỉnh chưa thấy control tổng hợp và Kiên Giang chưa có mẫu dương tính vẫn chưa tích hợp; cần rà đồ án lẻ để mở rộng tiếp. Chưa push/deploy commit này.

**Đợt tiếp:** rà43 danh mục QH khác,387 tên đồ án,17 trang phân khu,262 mẫu bổ sung.
Đăng ký thêm10 nguồn (tổng26); bảy ứng viên chưa có ảnh zoom gần dùng được giữ ngoài registry.
Ruling: tên hồ sơ có phân khu và mẫu zoom15+ đọc được mới tích hợp; ảnh nhỏ hoặc403
không đủ. Giữ phạm vi đồ án riêng, không nhận phủ kín tỉnh. `focus_bounds` chỉ điều hướng.
134 JS +29 Python +overlay/native runtime đạt, browser Cần Thơ desktop/mobile có ảnh.
Hai terminal-browser tests bị treo đã dừng; không báo chúng đạt. Chưa push/deploy.
Review phát hiện floor lấy nhầm theme khác khi bật đồng thời; đã sửa và kiểm
runtime Bình Phước +2030, tái hiện lỗi12≠15 trước sửa và đạt sau sửa.

**Đợt ghép huyện theo yêu cầu tiếp:**671 huyện/60 tỉnh,438 hồ sơ,422 template;
395 nguồn mới đạt samplegate; loại thêm5 bản `(lyk)` lấy ý kiến,390 nguồn mới dùng,
tổng416 nguồn48 tỉnh.11 nguồn mới chưa dùng được;
12 tỉnh chưa có nguồn đạt. Huyện query ward_id rỗng để gom cả đồ án xã/phường.
Ruling: dùng chung nút tỉnh nhưng mỗi template có load envelope từ alpha pixel,
exactrules, nativezoom đã kiểm; không tạo ảnh giả phủ kín tỉnh hoặc xóa GIS hiện có.
Catalogue cap1024 và theme zIndex band1024; pool4 cùng nativeGIS cho ảnh reference,
cancel queued+active khi rời vùng. Tests135JS+30Python+overlay/native pass.
Browser Long An/Vinh trước tối ưu cuối thấy ảnh; sau đó browser bị Work settings
tắt, chưa có rendered proof sau thu envelope/pool4. Chưa push/deploy.
Final review phát hiện TileLayer zoomabort khác tileunload và sentinel timeout
làm Leaflet bỏ done. Đã thêm `_abortLoading` hủy queued/active, `tileabort` idempotent,
timeout src fragment riêng; tests tái hiện lỗi trước sửa và đạt sau sửa.

**Yêu cầu mới nhất sau releasef7784145:** gỡ400 sheet QH khác để tránh chồng với
phân khu tổng, chỉ giữ16 entries từ control tỉnh. Không tự khôi phục các sheet đã gỡ.
Tạo overview Bình Phước offline từ8742 tile15, không ô thiếu;3069 PNG zoom0–14,
release035963b04e2436b6. Đã chuyển lên VPS và verify tất cả SHA256 trước kích hoạt.
135JS+29Python+overlay/native runtime đạt; fresh review không có lỗi quan trọng.
Ảnh zoom15+ vẫn trực tiếp source gốc, zoom thấp chỉ đọc pyramid local theo viewport.

## Task 2 — Registry và tích hợp theo tỉnh

- [x] Sau khi có source đã kiểm: thêm `config/planning_partition_reference.json`, registry revision và exact descriptors trong `config/planning_regions.py`/context template.
- [x] Thêm tests Python registry và JS `planning_partition_reference.test.cjs`: reject modified template, source-kind/theme mismatch, coverage ngoài tỉnh và native zoom sai.
- [x] Sửa `services/planning_live.py` append catalogue hợp lệ; sửa `planning_overlay.js` nhận reference partition theo descriptor exact; giữ catalogue cap256.
- [x] Reuse `planning_area.js:coversProvince`, thêm coverage_provinces xác minh; source picker trung tính, giữ GIS/document HCM cũ.
- [x] Đảm bảo provider+revision/render signature+zxy là cache identity; toggle off/on không lỗi transform; viewport/one-buffer/native zoom/abort giữ bounded.
- [x] Không thêm generic tile proxy hoặc nới host wildcard để che lỗi source.

## Task 3 — Verify và bàn giao

- [x] Run registry tests, `node --test tests/js/*.cjs tests/js/test_*.js`, overlay/native runtime tests và asset/version render tests.
- [x] Browser desktop/mobile: tỉnh mới đúng lớp; toggle+zoom+pan+opacity; requests chỉ vùng nhìn; HCM/2030/bộ lọc tin rao không regression.
- [x] Kiểm bản release sạch; cập nhật tài liệu với số nguồn/tỉnh thật và gaps. Stage riêng intended changes.
- [ ] Commit/push; chờ Quality gates exact SHA; deploy và verify nếu đến bước release được yêu cầu. Không gọi scaffolding hoặc audit-only là đã thêm bản đồ.

## Stop condition

Nếu browser vẫn disabled hoặc nguồn cần quyền chưa được cấp, dừng bước phụ thuộc và báo chính xác blocker. Giữ trạng thái chưa tích hợp cho tỉnh chưa xác minh; không publish nguồn mẫu/URL giả.
