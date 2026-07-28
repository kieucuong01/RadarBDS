"""Curated content and geometry identifiers for ``/ban-do-binh-duong``."""

from __future__ import annotations

from urllib.parse import quote


BINH_DUONG_MAP_UPDATED_AT = "2026-07-28"
BINH_DUONG_MAP_UPDATED_LABEL = "28/07/2026"
BINH_DUONG_MAP_DATA_VERSION = "bd-map-data-20260728-1"

GEObOUNDARIES_ADM2_API = "https://www.geoboundaries.org/api/current/gbOpen/VNM/ADM2/"
OPENSTREETMAP_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
OFFICIAL_2025_UNITS_URL = (
    "https://tphcm.baochinhphu.vn/"
    "danh-sach-chinh-thuc-168-phuong-xa-cua-tphcm-sau-sap-xep-101250617000144317.htm"
)


def _dashboard_for_group(group: str) -> tuple[str, str]:
    if group == "Thủ Dầu Một":
        return (
            f"/?tab=signals&city={quote('Thủ Dầu Một')}",
            "Lọc tin Thủ Dầu Một",
        )
    if group == "Bến Cát":
        return (
            f"/?tab=signals&city={quote('Bến Cát')}",
            "Lọc tin Bến Cát",
        )
    return "/?tab=signals", "Xem tin đang bán"


def _legacy_area(
    slug: str,
    name: str,
    unit_type: str,
    summary: str,
    source_name: str,
    *,
    group: str | None = None,
) -> dict:
    market_group = group or name
    dashboard_href, dashboard_label = _dashboard_for_group(market_group)
    return {
        "slug": slug,
        "name": name,
        "unit_type": unit_type,
        "group": market_group,
        "summary": summary,
        "dashboard_href": dashboard_href,
        "dashboard_label": dashboard_label,
        "source_name": source_name,
    }


def _current_area(
    slug: str,
    name: str,
    unit_type: str,
    group: str,
    former_units: str,
    osm_relation_id: int,
) -> dict:
    dashboard_href, dashboard_label = _dashboard_for_group(group)
    return {
        "slug": slug,
        "name": name,
        "unit_type": unit_type,
        "group": group,
        "summary": f"{unit_type} {name} thuộc khu vực Bình Dương cũ sau sắp xếp năm 2025.",
        "former_units": former_units,
        "dashboard_href": dashboard_href,
        "dashboard_label": dashboard_label,
        "osm_relation_id": osm_relation_id,
    }


BINH_DUONG_LEGACY_AREAS = [
    _legacy_area(
        "thu-dau-mot",
        "Thủ Dầu Một",
        "Thành phố cũ",
        "Trung tâm hành chính và thị trường nhà đất lõi của Bình Dương cũ.",
        "Thu Dau Mot",
    ),
    _legacy_area(
        "ben-cat",
        "Bến Cát",
        "Thành phố cũ",
        "Khu công nghiệp và đô thị phát triển dọc Quốc lộ 13, Mỹ Phước và các trục vành đai.",
        "Ben Cat",
    ),
    _legacy_area(
        "di-an",
        "Dĩ An",
        "Thành phố cũ",
        "Cửa ngõ phía nam, kết nối trực tiếp Thủ Đức, Đồng Nai và các khu công nghiệp lâu năm.",
        "Di An",
    ),
    _legacy_area(
        "tan-uyen",
        "Tân Uyên",
        "Thành phố cũ",
        "Vùng đô thị - công nghiệp ven sông Đồng Nai, nối Dĩ An, Bắc Tân Uyên và Bến Cát.",
        "Tan Uyen",
    ),
    _legacy_area(
        "thuan-an",
        "Thuận An",
        "Thành phố cũ",
        "Vùng đô thị mật độ cao giáp Thành phố Hồ Chí Minh, tập trung dọc Quốc lộ 13.",
        "Thuan An",
    ),
    _legacy_area(
        "bau-bang",
        "Bàu Bàng",
        "Huyện cũ",
        "Vùng công nghiệp phía bắc, gắn với Quốc lộ 13 và hành lang phát triển Bến Cát - Chơn Thành.",
        "Bau Bang",
    ),
    _legacy_area(
        "bac-tan-uyen",
        "Bắc Tân Uyên",
        "Huyện cũ",
        "Vùng sinh thái và sản xuất phía đông, có kết nối với Tân Uyên và Phú Giáo.",
        "Bac Tan Uyen",
    ),
    _legacy_area(
        "dau-tieng",
        "Dầu Tiếng",
        "Huyện cũ",
        "Địa bàn có diện tích lớn ở phía tây bắc, nổi bật với hồ Dầu Tiếng và đất nông nghiệp.",
        "Dau Tieng",
    ),
    _legacy_area(
        "phu-giao",
        "Phú Giáo",
        "Huyện cũ",
        "Vùng nông nghiệp - dân cư phía đông bắc, kết nối Bắc Tân Uyên và Đồng Phú.",
        "Phu Giao",
    ),
]


BINH_DUONG_CURRENT_AREAS = [
    _current_area("dong-hoa", "Đông Hòa", "Phường", "Dĩ An", "Bình An, Bình Thắng và Đông Hòa", 3870770),
    _current_area("di-an", "Dĩ An", "Phường", "Dĩ An", "An Bình, Dĩ An và một phần Tân Đông Hiệp", 8448992),
    _current_area("tan-dong-hiep", "Tân Đông Hiệp", "Phường", "Dĩ An", "Tân Bình, một phần Thái Hòa và phần còn lại của Tân Đông Hiệp", 13420411),
    _current_area("an-phu", "An Phú", "Phường", "Thuận An", "An Phú và một phần Bình Chuẩn", 13470504),
    _current_area("binh-hoa", "Bình Hòa", "Phường", "Thuận An", "Bình Hòa và một phần Vĩnh Phú", 13470503),
    _current_area("lai-thieu", "Lái Thiêu", "Phường", "Thuận An", "Bình Nhâm, Lái Thiêu và phần còn lại của Vĩnh Phú", 13470501),
    _current_area("thuan-an", "Thuận An", "Phường", "Thuận An", "Hưng Định, An Thạnh và An Sơn", 13470588),
    _current_area("thuan-giao", "Thuận Giao", "Phường", "Thuận An", "Thuận Giao và phần còn lại của Bình Chuẩn", 13470506),
    _current_area("thu-dau-mot", "Thủ Dầu Một", "Phường", "Thủ Dầu Một", "Phú Cường, Phú Thọ, Chánh Nghĩa, Chánh Mỹ và một phần Hiệp Thành", 8448188),
    _current_area("phu-loi", "Phú Lợi", "Phường", "Thủ Dầu Một", "Phú Hòa, Phú Lợi và phần còn lại của Hiệp Thành", 13455517),
    _current_area("chanh-hiep", "Chánh Hiệp", "Phường", "Thủ Dầu Một", "Định Hòa, Tương Bình Hiệp, một phần Hiệp An và phần còn lại của Chánh Mỹ", 10590955),
    _current_area("binh-duong", "Bình Dương", "Phường", "Thủ Dầu Một", "Phú Mỹ, Hòa Phú, Phú Tân và Phú Chánh", 13455518),
    _current_area("hoa-loi", "Hòa Lợi", "Phường", "Bến Cát", "Tân Định và Hòa Lợi", 13477612),
    _current_area("phu-an", "Phú An", "Phường", "Bến Cát", "Tân An, Phú An và phần còn lại của Hiệp An", 13477595),
    _current_area("tay-nam", "Tây Nam", "Phường", "Bến Cát", "An Tây và một phần Thanh Tuyền, An Lập", 13477596),
    _current_area("long-nguyen", "Long Nguyên", "Phường", "Bến Cát", "An Điền, Long Nguyên và một phần Mỹ Phước", 15044270),
    _current_area("ben-cat", "Bến Cát", "Phường", "Bến Cát", "Tân Hưng, Lai Hưng và phần còn lại của Mỹ Phước", 13477633),
    _current_area("chanh-phu-hoa", "Chánh Phú Hòa", "Phường", "Bến Cát", "Chánh Phú Hòa và Hưng Hòa", 13477632),
    _current_area("vinh-tan", "Vĩnh Tân", "Phường", "Tân Uyên", "Vĩnh Tân và thị trấn Tân Bình", 13477543),
    _current_area("binh-co", "Bình Cơ", "Phường", "Tân Uyên", "Bình Mỹ và Hội Nghĩa", 13477544),
    _current_area("tan-uyen", "Tân Uyên", "Phường", "Tân Uyên", "Uyên Hưng, Bạch Đằng, Tân Lập và một phần Tân Mỹ", 13477425),
    _current_area("tan-hiep", "Tân Hiệp", "Phường", "Tân Uyên", "Khánh Bình và Tân Hiệp", 13477545),
    _current_area("tan-khanh", "Tân Khánh", "Phường", "Tân Uyên", "Thạnh Phước, Tân Phước Khánh, Tân Vĩnh Hiệp, Thạnh Hội và phần còn lại của Thái Hòa", 13477540),
    _current_area("thoi-hoa", "Thới Hòa", "Phường", "Bến Cát", "Đơn vị không thực hiện sắp xếp", 13477634),
    _current_area("thuong-tan", "Thường Tân", "Xã", "Bắc Tân Uyên", "Lạc An, Hiếu Liêm, Thường Tân và phần còn lại của Tân Mỹ", 15071235),
    _current_area("bac-tan-uyen", "Bắc Tân Uyên", "Xã", "Bắc Tân Uyên", "Thị trấn Tân Thành, Đất Cuốc và Tân Định", 15071230),
    _current_area("phu-giao", "Phú Giáo", "Xã", "Phú Giáo", "Thị trấn Phước Vĩnh, An Bình và một phần Tam Lập", 15350067),
    _current_area("phuoc-hoa", "Phước Hòa", "Xã", "Phú Giáo", "Vĩnh Hòa, Phước Hòa và phần còn lại của Tam Lập", 15350008),
    _current_area("phuoc-thanh", "Phước Thành", "Xã", "Phú Giáo", "Tân Hiệp, An Thái và Phước Sang", 15350042),
    _current_area("an-long", "An Long", "Xã", "Phú Giáo", "An Linh, Tân Long và An Long", 15350010),
    _current_area("tru-van-tho", "Trừ Văn Thố", "Xã", "Bàu Bàng", "Trừ Văn Thố, Cây Trường II và một phần thị trấn Lai Uyên", 15044265),
    _current_area("bau-bang", "Bàu Bàng", "Xã", "Bàu Bàng", "Phần còn lại của thị trấn Lai Uyên", 15044266),
    _current_area("long-hoa", "Long Hòa", "Xã", "Dầu Tiếng", "Long Tân, Long Hòa và một phần Minh Tân, Minh Thạnh", 15328437),
    _current_area("thanh-an", "Thanh An", "Xã", "Dầu Tiếng", "Thanh An, một phần Định Hiệp và phần còn lại của Thanh Tuyền, An Lập", 15328441),
    _current_area("dau-tieng", "Dầu Tiếng", "Xã", "Dầu Tiếng", "Thị trấn Dầu Tiếng, Định An, Định Thành và phần còn lại của Định Hiệp", 15328440),
    _current_area("minh-thanh", "Minh Thạnh", "Xã", "Dầu Tiếng", "Minh Hòa và phần còn lại của Minh Tân, Minh Thạnh", 15328433),
]


BINH_DUONG_MAP_PAGE = {
    "path": "/ban-do-binh-duong",
    "title": "Bản đồ Bình Dương cũ và 36 phường xã mới | Radar BDS",
    "description": (
        "Tra cứu bản đồ Bình Dương cũ theo 9 huyện thành phố và đối chiếu 36 phường xã "
        "sau sắp xếp 2025, kèm lối lọc tin nhà đất theo khu vực."
    ),
    "keywords": (
        "bản đồ Bình Dương, bản đồ hành chính Bình Dương, 36 phường xã Bình Dương, "
        "Bình Dương cũ"
    ),
    "hero_badge": "Bản đồ hành chính",
    "hero_title": "Bản đồ Bình Dương",
    "hero_text": (
        "Tra cứu địa giới Bình Dương cũ theo 9 huyện, thành phố quen thuộc và chuyển sang "
        "36 phường, xã sau sắp xếp năm 2025. Chọn khu vực để đối chiếu tên và mở dữ liệu "
        "tin đang bán phù hợp trên Radar BDS."
    ),
    "default_layer": "legacy",
    "legacy_geojson_path": "/static/maps/binh-duong/legacy-districts.geojson",
    "current_geojson_path": "/static/maps/binh-duong/current-36-wards.geojson",
    "legacy_geojson_url": (
        "/static/maps/binh-duong/legacy-districts.geojson"
        f"?v={BINH_DUONG_MAP_DATA_VERSION}"
    ),
    "current_geojson_url": (
        "/static/maps/binh-duong/current-36-wards.geojson"
        f"?v={BINH_DUONG_MAP_DATA_VERSION}"
    ),
    "updated_at": BINH_DUONG_MAP_UPDATED_AT,
    "updated_label": BINH_DUONG_MAP_UPDATED_LABEL,
    "overview_rows": [
        {"label": "Tên tra cứu", "value": "Tỉnh Bình Dương cũ"},
        {"label": "Vùng", "value": "Đông Nam Bộ"},
        {"label": "Diện tích tham khảo", "value": "2.694,64 km²"},
        {"label": "Đơn vị trước sắp xếp", "value": "9 huyện, thành phố"},
        {"label": "Đơn vị sau sắp xếp", "value": "36 phường, xã thuộc TP.HCM mới"},
        {"label": "Mốc vận hành đơn vị mới", "value": "01/07/2025"},
    ],
    "source_links": [
        {
            "label": "geoBoundaries - dữ liệu ranh cấp huyện Việt Nam (năm 2020)",
            "href": GEObOUNDARIES_ADM2_API,
        },
        {
            "label": "OpenStreetMap - bản quyền và nguồn dữ liệu cộng đồng",
            "href": OPENSTREETMAP_COPYRIGHT_URL,
        },
        {
            "label": "Danh sách chính thức 168 phường xã TP.HCM sau sắp xếp",
            "href": OFFICIAL_2025_UNITS_URL,
        },
    ],
    "related_links": [
        {"label": "Thư viện bản đồ quy hoạch Bình Dương", "href": "/quy-hoach-binh-duong"},
        {"label": "Bản đồ địa giới 36 phường xã", "href": "/quy-hoach-binh-duong/dia-gioi-36-phuong-xa-binh-duong-cu"},
        {"label": "Nhà đất Bình Dương", "href": "/binh-duong"},
    ],
    "faq": [
        {
            "question": "Bản đồ Bình Dương này hiển thị địa giới trước hay sau sắp xếp?",
            "answer": (
                "Trang hiển thị cả hai. Lớp mặc định là 9 đơn vị cấp huyện của Bình Dương cũ; "
                "nút chuyển lớp cho phép xem 36 phường, xã sau sắp xếp năm 2025."
            ),
        },
        {
            "question": "Bình Dương cũ hiện thuộc đơn vị hành chính nào?",
            "answer": (
                "Sau sắp xếp năm 2025, khu vực tỉnh Bình Dương cũ thuộc Thành phố Hồ Chí Minh "
                "mới và được tổ chức thành 36 phường, xã trong phạm vi tra cứu của trang này."
            ),
        },
        {
            "question": "Có thể dùng bản đồ này để xác định ranh pháp lý thửa đất không?",
            "answer": (
                "Không. Bản đồ dùng để định hướng và đối chiếu tên khu vực. Ranh thửa, quy hoạch "
                "và tình trạng pháp lý cần được kiểm tra bằng hồ sơ và cơ quan có thẩm quyền."
            ),
        },
        {
            "question": "Làm sao xem tin nhà đất quanh khu vực đang chọn?",
            "answer": (
                "Chọn một khu vực trên bản đồ hoặc trong danh sách, sau đó dùng nút lọc tin để "
                "mở dashboard Radar BDS với phạm vi phù hợp nhất đang được hỗ trợ."
            ),
        },
    ],
}
