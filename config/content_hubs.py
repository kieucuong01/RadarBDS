"""Public content hub and planning category registries.

These registries are the single source of truth for public navigation,
sitemaps and empty-state category pages.
"""

NEWS_HUBS = {
    "chu-de-nong": {
        "path": "/tin-tuc/chu-de-nong",
        "title": "Chủ đề nóng bất động sản Bình Dương | Radar BDS",
        "heading": "Chủ đề nóng bất động sản Bình Dương",
        "description": (
            "Theo dõi tiêu đề, mô tả ngắn và liên kết nguồn của các tin đáng chú ý "
            "về bất động sản Bình Dương."
        ),
        "item_type": "hot_topic",
        "filter_label": "Lọc theo nguồn",
        "nav_label": "Chủ đề nóng",
        "nav_description": "Điểm tin có ghi rõ nguồn",
        "updated_at": "2026-07-29",
    },
    "du-lieu-radarbds": {
        "path": "/tin-tuc/du-lieu-radarbds",
        "title": "Tin từ dữ liệu Radar BDS | Radar BDS",
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
            "Thư viện bản đồ quy hoạch sử dụng đất tại địa bàn Bình Dương cũ, "
            "kèm phạm vi và nguồn tham khảo."
        ),
        "categories": ("landuse",),
        "scope": "Địa bàn tỉnh Bình Dương trước sắp xếp hành chính",
        "sources": ("Cổng thông tin quy hoạch", "Cơ quan quản lý nhà nước"),
        "nav_label": "QHSDĐ",
        "nav_description": "Quy hoạch sử dụng đất",
        "updated_at": "2026-07-29",
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
            "Danh mục bản đồ phân khu theo hồ sơ công khai, phục vụ tra cứu ban "
            "đầu trước khi kiểm tra pháp lý thửa đất."
        ),
        "categories": ("industrial",),
        "scope": "Các phân khu đô thị và khu chức năng",
        "sources": ("Cơ quan phê duyệt quy hoạch", "Cổng dữ liệu công khai"),
        "nav_label": "Quy hoạch phân khu",
        "nav_description": "Phân khu đô thị và chức năng",
        "updated_at": "2026-07-29",
    },
}
