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
- [ ] Kiểm bản release sạch, stage riêng intended changes; cập nhật Maps guide với số nguồn/tỉnh thật và gaps.
- [ ] Commit/push; chờ Quality gates exact SHA; deploy và verify nếu đến bước release được yêu cầu. Không gọi scaffolding hoặc audit-only là đã thêm bản đồ.

## Stop condition

Nếu browser vẫn disabled hoặc nguồn cần quyền chưa được cấp, dừng bước phụ thuộc và báo chính xác blocker. Giữ trạng thái chưa tích hợp cho tỉnh chưa xác minh; không publish nguồn mẫu/URL giả.
