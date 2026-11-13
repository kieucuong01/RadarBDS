"""Public content hub and planning category registries.

These registries are the single source of truth for public navigation,
sitemaps and empty-state category pages.
"""

from config.planning_pages import planning_demo_href

NEWS_HUBS = {
    "chu-de-nong": {
        "path": "/tin-tuc/chu-de-nong",
        "title": "Chủ đề nóng bất động sản Bình Dương | Radar BDS",
        "heading": "Chủ đề nóng bất động sản Bình Dương",
        "description": (
            "Tin hạ tầng, quy hoạch và thị trường Bình Dương cùng vùng kết nối, "
            "tổng hợp có dẫn nguồn và phân tích dưới góc nhìn người mua."
        ),
        "item_type": "hot_topic",
        "filter_label": "Lọc theo nguồn",
        "nav_label": "Chủ đề nóng",
        "nav_description": "Phân tích sự kiện và điểm tin có nguồn",
        "updated_at": "2026-07-29",
    },
    "du-lieu-radarbds": {
        "path": "/tin-tuc/du-lieu-radarbds",
        "title": "Phân tích giá rao Bình Dương | Dữ liệu Radar BDS",
        "heading": "Tin từ dữ liệu Radar BDS",
        "description": (
            "Các bài phân tích giá rao, khu vực và cách kiểm tra tin từ dữ liệu "
            "Radar BDS."
        ),
        "item_type": "radar_article",
        "nav_label": "Tin từ dữ liệu Radar BDS",
        "nav_description": "Phân tích giá rao và khu vực",
        "updated_at": "2026-07-29",
    },
    "quyet-dinh-van-ban": {
        "path": "/tin-tuc/quyet-dinh-van-ban",
        "title": "Quyết định và văn bản về Bình Dương | Radar BDS",
        "heading": "Quyết định và văn bản về Bình Dương",
        "description": (
            "Tra cứu văn bản chính thống theo số ký hiệu, cơ quan ban hành, loại "
            "văn bản và năm công bố."
        ),
        "item_type": "legal_document",
        "filter_label": "Lọc theo cơ quan",
        "nav_label": "Quyết định & văn bản",
        "nav_description": "Tra cứu tài liệu chính thống",
        "updated_at": "2026-07-29",
    },
}


PLANNING_CATEGORY_PAGES = {
    "quy-hoach-su-dung-dat": {
        "path": "/quy-hoach-binh-duong/quy-hoach-su-dung-dat",
        "heading": "Bản đồ quy hoạch sử dụng đất",
        "title": "Bản đồ quy hoạch sử dụng đất Bình Dương | Radar BDS",
        "description": (
            "Mở lớp quy hoạch sử dụng đất 2030 ở Thủ Dầu Một và Bến Cát, "
            "kiểm tra nguồn bản đồ và cách đối chiếu khi tra một thửa đất."
        ),
        "categories": ("landuse",),
        "scope": "Địa bàn tỉnh Bình Dương trước sắp xếp hành chính",
        "sources": ("Lớp tham khảo từ Guland", "Hồ sơ công bố để đối chiếu"),
        "nav_label": "QHSDĐ",
        "nav_description": "Quy hoạch sử dụng đất",
        "updated_at": "2026-11-13",
        "map_examples": (
            {"label": "Mở sử dụng đất 2030 ở Thủ Dầu Một", "href": planning_demo_href("THỦ DẦU MỘT")},
            {"label": "Mở sử dụng đất 2030 ở Bến Cát", "href": planning_demo_href("BẾN CÁT")},
        ),
        "map_notes": (
            "Lớp sử dụng đất 2030 trên Radar dùng ảnh bản đồ tham khảo từ Guland. Bắt đầu bằng việc tìm đúng vị trí và giảm độ hiển thị để nhìn đường, công trình và mốc trên nền vệ tinh.",
            "Nếu chỉ thấy mảng màu mà thiếu chú giải của đúng bản đồ, hãy ghi lại vị trí để tra nguồn gốc. Khi đã có số tờ/thửa, kiểm tra địa bàn và hình thửa rồi mới đọc lớp phủ.",
            "Khi vùng cần xem trống, kiểm tra lớp đã bật, độ phóng và phạm vi nguồn. Để xác minh một thửa, đối chiếu hồ sơ công bố áp dụng cho chính vị trí đó.",
        ),
        "guide_links": (
            {"label": "Cách so lớp sử dụng đất 2030 và phân khu tại cùng vị trí", "href": "/tin-tuc/cach-doc-ban-do-su-dung-dat-2030-va-quy-hoach-phan-khu"},
            {"label": "Tra quy hoạch theo số tờ, số thửa hoặc tọa độ", "href": "/tin-tuc/cach-tra-cuu-quy-hoach-theo-so-to-so-thua-toa-do"},
        ),
    },
    "tuyen-duong": {
        "path": "/quy-hoach-binh-duong/tuyen-duong",
        "heading": "Bản đồ quy hoạch tuyến đường",
        "title": "Bản đồ quy hoạch tuyến đường Bình Dương | Radar BDS",
        "description": (
            "Các chuyên đề tuyến giao thông quan trọng qua địa bàn Bình Dương cũ."
        ),
        "categories": ("transport",),
        "scope": "Các tuyến giao thông liên vùng và đô thị",
        "sources": ("Hồ sơ quy hoạch được công bố", "Dữ liệu bản đồ Radar BDS"),
        "nav_label": "Tuyến đường",
        "nav_description": "Giao thông liên vùng và đô thị",
        "updated_at": "2026-07-29",
    },
    "quy-hoach-chi-tiet": {
        "path": "/quy-hoach-binh-duong/quy-hoach-chi-tiet",
        "heading": "Bản đồ quy hoạch chi tiết",
        "title": "Bản đồ quy hoạch chi tiết Bình Dương | Radar BDS",
        "description": (
            "Danh mục chuyên đề quy hoạch chi tiết đang được Radar BDS theo dõi "
            "và chuẩn hóa."
        ),
        "categories": (),
        "scope": "Khu đô thị, dự án và khu vực có hồ sơ chi tiết",
        "sources": ("Cổng thông tin địa phương", "Văn bản phê duyệt chính thống"),
        "nav_label": "Quy hoạch chi tiết",
        "nav_description": "Khu vực và dự án cụ thể",
        "updated_at": "2026-07-29",
    },
    "quy-hoach-phan-khu": {
        "path": "/quy-hoach-binh-duong/quy-hoach-phan-khu",
        "heading": "Bản đồ quy hoạch phân khu",
        "title": "Bản đồ quy hoạch phân khu Bình Dương | Radar BDS",
        "description": (
            "Mở bản đồ quy hoạch phân khu GIS ở Bến Cát, đọc chú giải ô chức năng "
            "và biết cách kiểm tra khi ranh quy hoạch chạy sát thửa đất."
        ),
        "categories": ("industrial",),
        "scope": "Các phân khu đô thị và khu chức năng",
        "sources": ("GIS quy hoạch TP.HCM", "Chú giải và bản vẽ theo từng nguồn"),
        "nav_label": "Quy hoạch phân khu",
        "nav_description": "Phân khu đô thị và chức năng",
        "updated_at": "2026-11-13",
        "map_examples": (
            {"label": "Mở lớp phân khu GIS ở Bến Cát", "href": planning_demo_href("BẾN CÁT", "partition")},
        ),
        "map_notes": (
            "Mở điểm mẫu gần đường Ngô Quyền và Quốc lộ 13 ở Bến Cát. Giữ nguyên vị trí khi tắt lớp sử dụng đất và bật lớp Quy hoạch phân khu để đọc từng lớp.",
            "Dùng Ký hiệu các loại đất và chọn nhóm Quy hoạch phân khu. Nếu đã chọn nguồn bản vẽ riêng, đọc chú giải của bản vẽ đó. Ghi lại tên lớp, nguồn và vị trí trước khi chia sẻ ảnh.",
            "Khi ranh ô chức năng chạy sát thửa, kiểm tra lại ranh thửa và đối chiếu hồ sơ áp dụng. Phạm vi dữ liệu GIS thay đổi theo địa bàn và từng lớp.",
        ),
        "guide_links": (
            {"label": "Cách kiểm tra khi một góc thửa chạm vùng quy hoạch", "href": "/tin-tuc/ranh-thua-chong-lop-quy-hoach-can-kiem-tra-gi"},
            {"label": "Cổng tra cứu quy hoạch TP.HCM", "href": "https://gisxaydung.tphcm.gov.vn/tracuuttqh"},
        ),
    },
}
