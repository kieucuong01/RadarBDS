# Implementation plan: Nâng cấp trust-first cho `/bao-cao`

> Thực hiện tuần tự, mỗi hạng mục viết test thất bại trước rồi mới sửa tối thiểu để pass.

**Mục tiêu:** Đồng bộ báo cáo tháng với canonical/quality/actionable contract, bảo vệ PII của lead và cải thiện funnel/accessibility/mobile của hub lẫn trang báo cáo.

**Kiến trúc:** Dồn truy vấn báo cáo vào `services/monthly_report_data.py`; script generator/enhancer chỉ chuyển kết quả thành snapshot. Template hub/detail nhận metadata rõ nghĩa. API lead có fallback POST an toàn; analytics dùng event/context hữu hạn.

---

## Task 1: Khóa hợp đồng dữ liệu bằng test

**Files**

- Add: `tests/test_monthly_report_data.py`
- Add: `services/monthly_report_data.py`
- Modify: `scripts/generate_monthly_report.py`
- Modify: `scripts/enhance_monthly_report_rich.py`

**Các bước**

1. Viết fixture có raw repost, canonical, possibly duplicate, outlier, sold, hidden và nhiều valuation version.
2. Assert raw count, basis count, median và actionable count tách biệt.
3. Assert latest valuation được chọn và featured chỉ có canonical/actionable.
4. Chạy test để xác nhận đỏ.
5. Tạo service/query tối thiểu, chuyển hai script sang dùng service.
6. Chạy targeted test đến khi xanh.

## Task 2: Cập nhật snapshot contract và copy

**Files**

- Modify: `scripts/generate_monthly_report.py`
- Modify: `scripts/enhance_monthly_report_rich.py`
- Modify: `templates/seo_report.html`
- Modify: `tests/test_public_content_hubs.py`

**Các bước**

1. Viết test cho `raw_listing_count`, `basis_count`, `actionable_signal_count`, `data_contract_version`, `data_as_of`.
2. Viết test không còn copy legacy “is_hot/price_dropped”.
3. Cập nhật metric/methodology/structured data và nhãn snapshot.
4. Chạy targeted tests.

## Task 3: Lead form fail-closed

**Files**

- Modify: `templates/partials/seo_lead_capture.html`
- Modify: `templates/partials/seo_lead_capture_script.html`
- Modify: `app.py`
- Modify/Add: `tests/test_lead_capture.py`

**Các bước**

1. Test markup bắt buộc `method=post`, action `/api/leads`, hidden return path.
2. Test form-encoded success redirect chỉ có status, không có phone.
3. Test invalid/open-redirect `return_path` quay về path an toàn.
4. Cập nhật endpoint nhận JSON/form dùng chung service.
5. Chạy targeted tests và xác nhận JSON client cũ không đổi.

## Task 4: Hub coverage, filter URL và card semantics

**Files**

- Modify: `templates/seo_report_hub.html`
- Modify: `static/css/seo.css`
- Modify: `app.py` hoặc helper xây page context
- Modify: `tests/test_public_content_hubs.py`

**Các bước**

1. Test coverage copy theo dữ liệu, city count 0 bị disabled.
2. Test có period filter và query state restoration.
3. Test `aria-pressed`, một primary link/tab stop mỗi card, latest không lặp.
4. Implement JS filter với allowlisted values và `history.replaceState`/`popstate`.
5. Set control font 16px và target 44px.
6. Chạy tests.

## Task 5: CTA sớm và analytics chuyên biệt

**Files**

- Modify: `templates/seo_report.html`
- Modify: `templates/seo_report_hub.html`
- Modify: `templates/partials/seo_tracking.html` nếu cần
- Modify: `app.py`
- Modify: `tests/test_public_seo.py`

**Các bước**

1. Test CTA gần hero có URL dashboard đúng city/ward/date range/MOS.
2. Test allowlist có bốn event report mới.
3. Test client chỉ gửi enum/slug/id, không gửi query/phone/title/original URL.
4. Implement event delegation và context an toàn.
5. Chạy tests.

## Task 6: Accessibility, mobile và tải ảnh

**Files**

- Modify: `templates/seo_report.html`
- Modify: `static/css/seo.css`
- Modify: `tests/test_public_content_hubs.py`

**Các bước**

1. Test canvas có role/name hoặc text summary.
2. Test featured image lazy, có width/height.
3. Thêm CSS report-specific để card mobile gọn, không phá dashboard card.
4. Test HTML/static assertions và browser smoke 375/390px.

## Task 7: Regenerate và kiểm chứng snapshot tháng 06/2026

**Files**

- Modify generated: `config/seo_pages.py`

**Các bước**

1. Chạy generator tháng 06/2026 với DB canonical.
2. Kiểm tra 14 reports, metric contract mới, không featured invalid/duplicate.
3. Chạy:
   - `pytest tests/test_monthly_report_data.py tests/test_public_content_hubs.py tests/test_public_seo.py`
   - Python compile các file đổi
   - JavaScript syntax check cho file JS đổi
4. Browser smoke desktop/mobile cho hub và ít nhất một ward report.

## Task 8: Release và production proof

**Các bước**

1. Rà `git diff`, stage đúng file trong scope.
2. Commit và push branch/main theo workflow repo.
3. Deploy production bằng `scripts/deploy_production.ps1`.
4. Xác minh HTTP/live DOM:
   - coverage và filter;
   - snapshot/basis/actionable labels;
   - CTA dashboard;
   - lead form POST;
   - chart accessibility/lazy images;
   - event allowlist.
5. Ghi rõ bằng chứng local, DB snapshot và public production.
