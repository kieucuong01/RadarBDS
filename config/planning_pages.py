"""Public planning map pages for Radar BDS.

The coordinates in this registry and the GeoJSON files are hand-authored,
approximate planning illustrations for public SEO pages. They are not parcel
boundary or legal planning extracts.
"""

PLANNING_UPDATED_AT = "2026-07-23"
PLANNING_UPDATED_LABEL = "23/07/2026"

SOURCE_QD_790 = "https://congbao.chinhphu.vn/van-ban/quyet-dinh-so-790-qd-ttg-42530/51366.htm"
SOURCE_NQ_57 = "https://congbao.chinhphu.vn/thuoc-tinh-van-ban-so-57-2022-qh15-37457?cbid=41073"
SOURCE_VD4 = "https://tphcm.baochinhphu.vn/trinh-hdnd-thanh-pho-ban-hanh-nghi-quyet-trien-khai-du-an-vanh-dai-4-101250409095914783.htm"
SOURCE_36_WARDS = "https://xaydungchinhsach.chinhphu.vn/binh-duong-thong-qua-de-an-sap-xep-dvhc-con-36-phuong-xa-119250422210421893.htm"

PLANNING_HUB = {
    "path": "/quy-hoach-binh-duong",
    "title": "Bản đồ quy hoạch Bình Dương cũ | Radar BDS",
    "description": (
        "Hub bản đồ quy hoạch Bình Dương cũ: Vành đai 3, Mỹ Phước - Tân Vạn, "
        "Vành đai 4, Quốc lộ 13 và địa giới 36 phường xã sau sáp nhập."
    ),
    "keywords": (
        "bản đồ quy hoạch Bình Dương, quy hoạch Bình Dương cũ, Vành đai 3 Bình Dương, "
        "Mỹ Phước Tân Vạn, Vành đai 4 TP.HCM, địa giới 36 phường xã Bình Dương"
    ),
    "hero_badge": "Bản đồ quy hoạch",
    "hero_title": "Bản đồ quy hoạch Bình Dương cũ",
    "hero_text": (
        "Tập hợp các tuyến giao thông, địa giới và khu vực cần kiểm tra quy hoạch "
        "trên nền bản đồ tương tác. Mỗi bài có lớp bật/tắt, khu vực bị ảnh hưởng, "
        "nguồn văn bản và lối sang dashboard Radar BDS để xem tin đang bán quanh khu đó."
    ),
    "updated_at": PLANNING_UPDATED_AT,
    "updated_label": PLANNING_UPDATED_LABEL,
    "map_label": "Bình Dương cũ",
    "source_links": [
        {"label": "Quyết định 790/QĐ-TTg về Quy hoạch tỉnh Bình Dương", "href": SOURCE_QD_790},
        {"label": "Nghị quyết 57/2022/QH15 về Vành đai 3 TP.HCM", "href": SOURCE_NQ_57},
        {"label": "Thông tin sắp xếp 36 phường xã Bình Dương cũ", "href": SOURCE_36_WARDS},
    ],
    "tabs": [
        {"id": "all", "label": "Tất cả"},
        {"id": "transport", "label": "Tuyến giao thông"},
        {"id": "boundary", "label": "Địa giới"},
        {"id": "landuse", "label": "Quy hoạch sử dụng đất"},
        {"id": "industrial", "label": "KCN/Khu đô thị"},
    ],
    "trending_slugs": [
        "vanh-dai-3",
        "duong-my-phuoc-tan-van",
        "quoc-lo-13",
        "dia-gioi-36-phuong-xa-binh-duong-cu",
    ],
    "local_links": [
        {"label": "Vành đai 3 Bình Dương", "href": "/quy-hoach-binh-duong/vanh-dai-3"},
        {"label": "Mỹ Phước - Tân Vạn", "href": "/quy-hoach-binh-duong/duong-my-phuoc-tan-van"},
        {"label": "Địa giới 36 phường xã", "href": "/quy-hoach-binh-duong/dia-gioi-36-phuong-xa-binh-duong-cu"},
    ],
}


def _section(section_id, heading, paragraphs, focus_feature="", bullets=None):
    return {
        "id": section_id,
        "heading": heading,
        "paragraphs": paragraphs,
        "focus_feature": focus_feature,
        "bullets": bullets or [],
    }


def _faq(question, answer):
    return {"question": question, "answer": answer}


PLANNING_PAGES = {
    "vanh-dai-3": {
        "sort_order": 10,
        "slug": "vanh-dai-3",
        "path": "/quy-hoach-binh-duong/vanh-dai-3",
        "title": "Bản đồ Vành đai 3 qua Bình Dương cũ | Radar BDS",
        "description": (
            "Bản đồ tương tác Vành đai 3 qua Bình Dương cũ, các đoạn Tân Vạn, "
            "Bình Chuẩn, Thuận An, Thủ Dầu Một và khu vực cần kiểm tra quy hoạch."
        ),
        "keywords": "Vành đai 3 Bình Dương, bản đồ Vành đai 3 TP.HCM, Tân Vạn, Bình Chuẩn, Thuận An",
        "category": "transport",
        "category_label": "Tuyến giao thông",
        "breadcrumb_label": "Vành đai 3",
        "hero_badge": "Tuyến giao thông trọng điểm",
        "hero_title": "Bản đồ Vành đai 3 qua Bình Dương cũ",
        "hero_text": (
            "Vành đai 3 đi qua trục phía nam Bình Dương cũ, kết nối khu Tân Vạn, "
            "Bình Chuẩn, Thuận An và hướng về Thủ Đức - Đồng Nai. Người mua đất nên "
            "xem vị trí tuyến, nút giao và vùng ảnh hưởng trước khi đọc tin rao."
        ),
        "summary": "Map-first bài Vành đai 3: tuyến chính, nút giao, vùng hưởng lợi và khu cần kiểm tra lộ giới.",
        "thumbnail_label": "VĐ3",
        "map_label": "Vành đai 3 TP.HCM - đoạn Bình Dương cũ",
        "read_time": "7 phút đọc",
        "updated_at": PLANNING_UPDATED_AT,
        "updated_label": PLANNING_UPDATED_LABEL,
        "geojson_path": "/static/maps/planning/vanh-dai-3.geojson",
        "dashboard_href": "/?tab=signals&city=Thủ%20Dầu%20Một",
        "areas": ["Tân Vạn", "Bình Chuẩn", "Thuận An", "Thủ Dầu Một"],
        "source_badge": "Nguồn: NQ 57/2022/QH15 + Quy hoạch tỉnh",
        "source_links": [
            {"label": "Nghị quyết 57/2022/QH15 - Vành đai 3 TP.HCM", "href": SOURCE_NQ_57},
            {"label": "Quyết định 790/QĐ-TTg - Quy hoạch tỉnh Bình Dương", "href": SOURCE_QD_790},
        ],
        "map_layers": [
            {"id": "route", "label": "Tuyến chính", "checked": True},
            {"id": "impact", "label": "Vùng tác động", "checked": True},
            {"id": "nodes", "label": "Nút giao/cầu", "checked": True},
            {"id": "signals", "label": "Tin đang bán quanh khu này", "checked": False},
        ],
        "legend": [
            {"label": "Tuyến chính", "color": "#0f766e"},
            {"label": "Vùng hưởng lợi", "color": "#f59e0b"},
            {"label": "Điểm cần kiểm tra", "color": "#dc2626"},
            {"label": "Signal quanh khu", "color": "#0369a1"},
        ],
        "impact_cards": [
            {"label": "Tuyến đi qua đâu", "value": "Tân Vạn - Bình Chuẩn - Thuận An", "tone": "info"},
            {"label": "Khu hưởng lợi", "value": "Cửa ngõ logistics, đất gần nút giao", "tone": "good"},
            {"label": "Khu cần kiểm tra", "value": "Lô sát lộ giới, hành lang nút giao", "tone": "warn"},
            {"label": "Nguồn văn bản", "value": "Nghị quyết 57/2022/QH15", "tone": "source"},
        ],
        "segment_rows": [
            {
                "segment": "Đoạn 1",
                "route": "Nhơn Trạch - Tân Vạn",
                "length": "khoảng 34 km",
                "note": "Đặt bối cảnh kết nối Đồng Nai, TP.HCM và cửa ngõ Tân Vạn.",
            },
            {
                "segment": "Đoạn 2",
                "route": "Tân Vạn - Bình Chuẩn",
                "length": "khoảng 17 km",
                "note": "Đoạn Bình Dương cũ cần soi kỹ khi đọc tin quanh Thuận An, Dĩ An và Tân Vạn.",
            },
            {
                "segment": "Đoạn 3",
                "route": "Bình Chuẩn - Quốc lộ 22",
                "length": "khoảng 19 km",
                "note": "Liên quan hướng Bình Chuẩn, Thủ Dầu Một phía nam và luồng kết nối về TP.HCM.",
            },
            {
                "segment": "Đoạn 4",
                "route": "Quốc lộ 22 - Bến Lức",
                "length": "khoảng 29 km",
                "note": "Bối cảnh liên vùng phía tây nam, hữu ích để hiểu toàn tuyến thay vì chỉ nhìn một đoạn.",
            },
        ],
        "sections": [
            _section(
                "tong-quan",
                "Vành đai 3 tác động thế nào tới Bình Dương cũ?",
                [
                    "Vành đai 3 tạo một vòng kết nối liên vùng quanh TP.HCM, trong đó Bình Dương cũ là đoạn then chốt ở phía bắc - đông bắc đô thị lõi.",
                    "Với người đọc tin rao, giá trị của bản đồ không nằm ở một đường vẽ duy nhất mà ở việc nhìn tuyến trong tương quan với khu dân cư, khu công nghiệp và các trục hiện hữu.",
                ],
                "Tuyến Vành đai 3 Bình Dương",
            ),
            _section(
                "doan-tan-van",
                "Đoạn Tân Vạn - Bình Chuẩn",
                [
                    "Đây là đoạn dễ tạo nhu cầu tra cứu vì nằm gần cửa ngõ Dĩ An - Thuận An, kết nối về Xa lộ Hà Nội, logistics và khu dân cư dày đặc.",
                    "Các lô đất trong bán kính gần tuyến cần kiểm tra kỹ ranh, lộ giới và tình trạng giải phóng mặt bằng trước khi suy luận tăng giá từ hạ tầng.",
                ],
                "Tân Vạn",
            ),
            _section(
                "nut-giao",
                "Nút giao và vùng cần kiểm tra",
                [
                    "Nút giao thường là nơi câu chuyện hưởng lợi dễ bị thổi phồng trong tin rao. Radar BDS đánh dấu các điểm này để người dùng biết nên kiểm tra bản đồ quy hoạch chi tiết hơn.",
                    "Lớp vùng tác động chỉ là vùng đọc nhanh, không thay thế hồ sơ pháp lý, bản vẽ ranh thu hồi đất hay tra cứu quy hoạch cấp thửa.",
                ],
                "Nút giao Bình Chuẩn",
            ),
        ],
        "impact_rows": [
            {
                "area": "Tân Vạn - Dĩ An/Thuận An",
                "impact": "Cửa ngõ kết nối TP.HCM, Đồng Nai và trục logistics phía nam Bình Dương cũ.",
                "risk": "Kiểm tra lộ giới, hành lang nút giao và pháp lý các lô sát tuyến.",
                "status": "Cần kiểm tra",
                "landing_href": "/binh-duong",
                "dashboard_href": "/?tab=signals",
            },
            {
                "area": "Bình Chuẩn - Thuận An",
                "impact": "Có thể hưởng lợi từ nhu cầu ở thực và dịch vụ quanh trục hạ tầng.",
                "risk": "Dễ xuất hiện tin gắn nhãn gần Vành đai 3 nhưng vị trí thực tế xa tuyến.",
                "status": "Hưởng lợi có chọn lọc",
                "landing_href": "/binh-duong",
                "dashboard_href": "/?tab=signals&ward=Bình%20Chuẩn",
            },
            {
                "area": "Thủ Dầu Một phía nam",
                "impact": "Tăng kết nối về các khu công nghiệp, khu đô thị và trục Mỹ Phước - Tân Vạn.",
                "risk": "Nên đối chiếu thêm quy hoạch sử dụng đất và quy hoạch phân khu.",
                "status": "Theo dõi",
                "landing_href": "/binh-duong/thu-dau-mot",
                "dashboard_href": "/?tab=signals&city=Thủ%20Dầu%20Một",
            },
        ],
        "related_links": [
            {"label": "Mỹ Phước - Tân Vạn", "href": "/quy-hoach-binh-duong/duong-my-phuoc-tan-van"},
            {"label": "Quốc lộ 13", "href": "/quy-hoach-binh-duong/quoc-lo-13"},
            {"label": "Giá nhà đất Thủ Dầu Một", "href": "/binh-duong/thu-dau-mot"},
        ],
        "faq": [
            _faq("Bản đồ Vành đai 3 trên Radar BDS có phải bản đồ pháp lý không?", "Không. Đây là lớp minh họa tham khảo để đọc tin rao và định hướng kiểm tra. Người dùng cần tra cứu hồ sơ quy hoạch, ranh thu hồi và pháp lý thửa đất tại cơ quan có thẩm quyền."),
            _faq("Tôi nên dùng trang này thế nào khi xem tin bán đất?", "Hãy bật lớp tuyến chính, vùng tác động và nút giao để xem tin rao nằm gần đoạn nào, sau đó mở dashboard Radar BDS để lọc tín hiệu quanh khu vực liên quan."),
        ],
    },
    "duong-my-phuoc-tan-van": {
        "sort_order": 20,
        "slug": "duong-my-phuoc-tan-van",
        "path": "/quy-hoach-binh-duong/duong-my-phuoc-tan-van",
        "title": "Bản đồ đường Mỹ Phước - Tân Vạn Bình Dương cũ | Radar BDS",
        "description": "Bản đồ tương tác đường Mỹ Phước - Tân Vạn, vùng kết nối KCN Mỹ Phước, Bến Cát, Thuận An, Dĩ An và Tân Vạn.",
        "keywords": "Mỹ Phước Tân Vạn, đường Mỹ Phước Tân Vạn Bình Dương, bản đồ quy hoạch Bến Cát, KCN Mỹ Phước",
        "category": "transport",
        "category_label": "Tuyến giao thông",
        "breadcrumb_label": "Mỹ Phước - Tân Vạn",
        "hero_badge": "Trục logistics - công nghiệp",
        "hero_title": "Bản đồ đường Mỹ Phước - Tân Vạn",
        "hero_text": (
            "Mỹ Phước - Tân Vạn là trục đọc bản đồ quan trọng khi xem đất Bến Cát, "
            "Mỹ Phước, Thuận An và cửa ngõ Tân Vạn. Trang này giúp thấy tuyến, "
            "điểm kết nối KCN và khu dân cư để tránh chỉ đọc tin rao theo tên đường."
        ),
        "summary": "Trục công nghiệp - logistics từ Bàu Bàng/Mỹ Phước về Tân Vạn, kèm lớp KCN và vùng đọc tin rao.",
        "thumbnail_label": "MPTV",
        "map_label": "Bàu Bàng - Mỹ Phước - Tân Vạn",
        "read_time": "6 phút đọc",
        "updated_at": PLANNING_UPDATED_AT,
        "updated_label": PLANNING_UPDATED_LABEL,
        "geojson_path": "/static/maps/planning/duong-my-phuoc-tan-van.geojson",
        "dashboard_href": "/?tab=signals&city=Bến%20Cát",
        "areas": ["Bàu Bàng", "Mỹ Phước", "Bến Cát", "Tân Vạn"],
        "source_badge": "Nguồn: Quyết định 790/QĐ-TTg",
        "source_links": [
            {"label": "Quyết định 790/QĐ-TTg - danh mục giao thông Bình Dương", "href": SOURCE_QD_790},
        ],
        "map_layers": [
            {"id": "route", "label": "Tuyến chính", "checked": True},
            {"id": "industrial", "label": "KCN/Khu đô thị", "checked": True},
            {"id": "nodes", "label": "Điểm kết nối", "checked": True},
            {"id": "signals", "label": "Tin đang bán quanh khu này", "checked": False},
        ],
        "legend": [
            {"label": "Tuyến chính", "color": "#0f766e"},
            {"label": "KCN/Khu đô thị", "color": "#7c3aed"},
            {"label": "Điểm kết nối", "color": "#dc2626"},
            {"label": "Signal quanh khu", "color": "#0369a1"},
        ],
        "impact_cards": [
            {"label": "Tuyến đi qua đâu", "value": "Bàu Bàng - Mỹ Phước - Tân Vạn", "tone": "info"},
            {"label": "Khu hưởng lợi", "value": "KCN Mỹ Phước, dân cư ven trục", "tone": "good"},
            {"label": "Khu cần kiểm tra", "value": "Tin rao mượn tên đường nhưng xa tuyến", "tone": "warn"},
            {"label": "Nguồn văn bản", "value": "Quyết định 790/QĐ-TTg", "tone": "source"},
        ],
        "sections": [
            _section(
                "vai-tro",
                "Vì sao tuyến này kéo nhiều nhu cầu tìm bản đồ?",
                [
                    "Đây là trục liên kết khu công nghiệp, đô thị và logistics kéo dài từ khu Bàu Bàng - Mỹ Phước về cửa ngõ Tân Vạn.",
                    "Nhiều tin rao dùng tên Mỹ Phước - Tân Vạn như một tín hiệu vị trí, nên bản đồ giúp kiểm tra lô đất thực sự nằm gần đoạn nào.",
                ],
                "Mỹ Phước - Tân Vạn",
            ),
            _section(
                "my-phuoc",
                "Cụm Mỹ Phước - Bến Cát",
                [
                    "Khu Mỹ Phước có nhiều nhu cầu ở thuê, ở thực và đầu tư quanh khu công nghiệp. Tuy nhiên, giá trị từng lô phụ thuộc mạnh vào khoảng cách tới trục, pháp lý và đường nội bộ.",
                    "Radar BDS ưu tiên liên kết sang các trang Bến Cát, Mỹ Phước để người dùng xem thêm dữ liệu tin rao đã chuẩn hóa.",
                ],
                "KCN Mỹ Phước",
            ),
            _section(
                "tan-van",
                "Cửa ngõ Tân Vạn",
                [
                    "Đoạn cuối Tân Vạn là điểm đọc quan trọng vì giao với nhiều hướng kết nối vùng. Đây cũng là nơi dễ bị dùng trong nội dung quảng cáo dù lô đất không thật gần điểm kết nối.",
                    "Nên kết hợp bản đồ tuyến với kiểm tra thời gian di chuyển và dữ liệu giá/m² theo phường trước khi đánh giá một tin rao.",
                ],
                "Tân Vạn",
            ),
        ],
        "impact_rows": [
            {
                "area": "Mỹ Phước 1-3",
                "impact": "Gần cụm KCN, nhu cầu thuê và giao thương ổn định hơn các khu xa trục.",
                "risk": "Cần phân biệt đất trong khu dân cư hiện hữu với đất quảng cáo theo tên dự án.",
                "status": "Hưởng lợi",
                "landing_href": "/binh-duong/my-phuoc",
                "dashboard_href": "/?tab=signals&ward=Mỹ%20Phước",
            },
            {
                "area": "Bến Cát",
                "impact": "Được hưởng kết nối về phía nam Bình Dương cũ và các khu công nghiệp.",
                "risk": "Tin rao có thể ghi gần Mỹ Phước - Tân Vạn nhưng khoảng cách thực tế lớn.",
                "status": "Cần lọc dữ liệu",
                "landing_href": "/binh-duong/ben-cat",
                "dashboard_href": "/?tab=signals&city=Bến%20Cát",
            },
            {
                "area": "Tân Vạn",
                "impact": "Cửa ngõ về TP.HCM, Đồng Nai và Vành đai 3.",
                "risk": "Kiểm tra lộ giới, nút giao và quy hoạch chi tiết quanh các điểm kết nối.",
                "status": "Cần kiểm tra",
                "landing_href": "/binh-duong",
                "dashboard_href": "/?tab=signals",
            },
        ],
        "related_links": [
            {"label": "Vành đai 3 Bình Dương", "href": "/quy-hoach-binh-duong/vanh-dai-3"},
            {"label": "Quy hoạch Bến Cát", "href": "/binh-duong/ben-cat"},
            {"label": "Khu Mỹ Phước", "href": "/binh-duong/my-phuoc"},
        ],
        "faq": [
            _faq("Đường Mỹ Phước - Tân Vạn dài bao nhiêu trong quy hoạch?", "Trong Quyết định 790/QĐ-TTg, trục Bàu Bàng - Mỹ Phước - Tân Vạn được nêu trong danh mục giao thông tỉnh với chiều dài quy hoạch khoảng 54,3 km."),
            _faq("Có nên mua đất chỉ vì gần Mỹ Phước - Tân Vạn?", "Không nên. Tuyến đường chỉ là một yếu tố. Cần kiểm tra pháp lý, khoảng cách thực tế, đường vào lô đất, quy hoạch sử dụng đất và mặt bằng giá đã chuẩn hóa."),
        ],
    },
    "vanh-dai-4": {
        "sort_order": 30,
        "slug": "vanh-dai-4",
        "path": "/quy-hoach-binh-duong/vanh-dai-4",
        "title": "Bản đồ Vành đai 4 TP.HCM qua Bình Dương cũ | Radar BDS",
        "description": "Bản đồ Vành đai 4 TP.HCM qua Bình Dương cũ, vùng Bến Cát - Tân Uyên - sông Đồng Nai và các khu cần kiểm tra.",
        "keywords": "Vành đai 4 Bình Dương, Vành đai 4 TP.HCM, Bến Cát, Tân Uyên, bản đồ Vành đai 4",
        "category": "transport",
        "category_label": "Tuyến giao thông",
        "breadcrumb_label": "Vành đai 4",
        "hero_badge": "Tuyến liên vùng",
        "hero_title": "Bản đồ Vành đai 4 TP.HCM qua Bình Dương cũ",
        "hero_text": (
            "Vành đai 4 là tuyến liên vùng dài, trong đó đoạn Bình Dương cũ tạo kết nối "
            "Bến Cát, Tân Uyên và các hướng sang Đồng Nai, Tây Ninh. Trang này ưu tiên "
            "đọc vị trí đoạn qua Bình Dương thay vì sao chép sơ đồ toàn tuyến."
        ),
        "summary": "Đọc nhanh đoạn Vành đai 4 qua Bình Dương cũ, vùng Bến Cát - Tân Uyên và các nút cần kiểm tra.",
        "thumbnail_label": "VĐ4",
        "map_label": "Vành đai 4 TP.HCM - đoạn Bình Dương cũ",
        "read_time": "7 phút đọc",
        "updated_at": PLANNING_UPDATED_AT,
        "updated_label": PLANNING_UPDATED_LABEL,
        "geojson_path": "/static/maps/planning/vanh-dai-4.geojson",
        "dashboard_href": "/?tab=signals&city=Bến%20Cát",
        "areas": ["Bến Cát", "Tân Uyên", "Thủ Biên", "Phú An"],
        "source_badge": "Nguồn: Báo Chính phủ + Quy hoạch tỉnh",
        "source_links": [
            {"label": "Thông tin triển khai Vành đai 4 TP.HCM", "href": SOURCE_VD4},
            {"label": "Quyết định 790/QĐ-TTg - Quy hoạch tỉnh Bình Dương", "href": SOURCE_QD_790},
        ],
        "map_layers": [
            {"id": "route", "label": "Tuyến chính", "checked": True},
            {"id": "impact", "label": "Vùng tác động", "checked": True},
            {"id": "nodes", "label": "Nút giao/cầu", "checked": True},
            {"id": "signals", "label": "Tin đang bán quanh khu này", "checked": False},
        ],
        "legend": [
            {"label": "Tuyến chính", "color": "#0f766e"},
            {"label": "Vùng tác động", "color": "#f59e0b"},
            {"label": "Nút giao/cầu", "color": "#dc2626"},
            {"label": "Signal quanh khu", "color": "#0369a1"},
        ],
        "impact_cards": [
            {"label": "Tuyến đi qua đâu", "value": "Bến Cát - Tân Uyên - hướng Đồng Nai", "tone": "info"},
            {"label": "Khu hưởng lợi", "value": "Vùng ven KCN, logistics liên vùng", "tone": "good"},
            {"label": "Khu cần kiểm tra", "value": "Đất gần ranh giải phóng mặt bằng", "tone": "warn"},
            {"label": "Nguồn văn bản", "value": "Thông tin triển khai VĐ4", "tone": "source"},
        ],
        "sections": [
            _section(
                "tong-quan",
                "Đoạn Bình Dương cũ nằm trong câu chuyện Vành đai 4 thế nào?",
                [
                    "Vành đai 4 là tuyến liên vùng, nên người xem đất Bình Dương cần tách riêng đoạn qua địa bàn cũ để tránh bị nhiễu bởi bản đồ toàn tuyến.",
                    "Các điểm đáng chú ý là vùng Bến Cát, Tân Uyên và hướng kết nối qua sông Đồng Nai, nơi câu chuyện hạ tầng thường được dùng trong nội dung bán đất.",
                ],
                "Vành đai 4 Bình Dương",
            ),
            _section(
                "ben-cat",
                "Bến Cát và các vùng ven khu công nghiệp",
                [
                    "Bến Cát là khu vực người dùng Radar BDS đã có nhu cầu lọc tin rao cao, vì vậy tuyến mới cần được đọc cùng giá/m² và lịch sử tin đăng.",
                    "Không nên đánh giá chỉ bằng khoảng cách đường chim bay tới tuyến; đường tiếp cận, quy hoạch sử dụng đất và thời điểm triển khai mới là yếu tố cần kiểm tra.",
                ],
                "Bến Cát",
            ),
            _section(
                "tan-uyen",
                "Tân Uyên - hướng kết nối Đồng Nai",
                [
                    "Hướng Tân Uyên có lợi thế kết nối vùng công nghiệp nhưng cũng có nhiều khu đất cần kiểm tra hiện trạng hạ tầng và mục đích sử dụng đất.",
                    "Các lớp bản đồ trong MVP được thiết kế để người dùng biết nên hỏi gì trước khi xuống tiền: tuyến ở đâu, nút giao nào gần nhất và nguồn văn bản là gì.",
                ],
                "Tân Uyên",
            ),
        ],
        "impact_rows": [
            {
                "area": "Bến Cát",
                "impact": "Kết nối liên vùng, có thể hỗ trợ khu công nghiệp và dân cư vệ tinh.",
                "risk": "Cần kiểm tra ranh quy hoạch, thời điểm thi công và đường tiếp cận thực tế.",
                "status": "Theo dõi",
                "landing_href": "/binh-duong/ben-cat",
                "dashboard_href": "/?tab=signals&city=Bến%20Cát",
            },
            {
                "area": "Tân Uyên",
                "impact": "Hướng kết nối sang Đồng Nai và các trục logistics phía đông.",
                "risk": "Không suy luận tăng giá nếu lô đất xa nút giao hoặc pháp lý yếu.",
                "status": "Cần kiểm tra",
                "landing_href": "/binh-duong",
                "dashboard_href": "/?tab=signals",
            },
            {
                "area": "Phú An - Thủ Biên",
                "impact": "Vùng đọc bản đồ quan trọng vì gắn với cầu và kết nối qua sông.",
                "risk": "Cần đối chiếu bản đồ thu hồi đất và quy hoạch phân khu.",
                "status": "Cần hồ sơ",
                "landing_href": "/binh-duong/ben-cat",
                "dashboard_href": "/?tab=signals&city=Bến%20Cát",
            },
        ],
        "related_links": [
            {"label": "Quốc lộ 13", "href": "/quy-hoach-binh-duong/quoc-lo-13"},
            {"label": "Mỹ Phước - Tân Vạn", "href": "/quy-hoach-binh-duong/duong-my-phuoc-tan-van"},
            {"label": "Bến Cát", "href": "/binh-duong/ben-cat"},
        ],
        "faq": [
            _faq("Vành đai 4 qua Bình Dương cũ có nên xem như một trang riêng không?", "Có. Toàn tuyến đi qua nhiều địa phương, nhưng người mua đất Bình Dương cần đọc riêng đoạn Bến Cát - Tân Uyên và các điểm kết nối ảnh hưởng trực tiếp tới tin rao."),
            _faq("Lớp vùng tác động trên bản đồ có phải vùng thu hồi đất không?", "Không. Đó là vùng tham khảo để đọc tin rao và điều hướng kiểm tra. Vùng thu hồi đất phải dựa trên hồ sơ dự án, mốc GPMB và văn bản của cơ quan chức năng."),
        ],
    },
    "quoc-lo-13": {
        "sort_order": 40,
        "slug": "quoc-lo-13",
        "path": "/quy-hoach-binh-duong/quoc-lo-13",
        "title": "Bản đồ Quốc lộ 13 qua Bình Dương cũ | Radar BDS",
        "description": "Bản đồ Quốc lộ 13 qua Thuận An, Thủ Dầu Một, Bến Cát, Bàu Bàng và cách đọc tác động tới tin rao nhà đất.",
        "keywords": "Quốc lộ 13 Bình Dương, bản đồ QL13, Thuận An, Thủ Dầu Một, Bến Cát, Bàu Bàng",
        "category": "transport",
        "category_label": "Tuyến giao thông",
        "breadcrumb_label": "Quốc lộ 13",
        "hero_badge": "Trục đô thị - thương mại",
        "hero_title": "Bản đồ Quốc lộ 13 qua Bình Dương cũ",
        "hero_text": (
            "Quốc lộ 13 là trục xương sống đô thị - công nghiệp của Bình Dương cũ, "
            "đi qua Thuận An, Thủ Dầu Một, Bến Cát và hướng Bàu Bàng. Bản đồ giúp "
            "người đọc tin rao phân biệt đất thật gần trục chính với nội dung quảng cáo mơ hồ."
        ),
        "summary": "Theo dõi QL13 qua các đô thị chính, vùng thương mại và điểm giao với Vành đai 4, Mỹ Phước - Tân Vạn.",
        "thumbnail_label": "QL13",
        "map_label": "Quốc lộ 13 - trục Bình Dương cũ",
        "read_time": "6 phút đọc",
        "updated_at": PLANNING_UPDATED_AT,
        "updated_label": PLANNING_UPDATED_LABEL,
        "geojson_path": "/static/maps/planning/quoc-lo-13.geojson",
        "dashboard_href": "/?tab=signals&city=Thủ%20Dầu%20Một",
        "areas": ["Thuận An", "Thủ Dầu Một", "Bến Cát", "Bàu Bàng"],
        "source_badge": "Nguồn: Quy hoạch tỉnh Bình Dương",
        "source_links": [
            {"label": "Quyết định 790/QĐ-TTg - Quy hoạch tỉnh Bình Dương", "href": SOURCE_QD_790},
        ],
        "map_layers": [
            {"id": "route", "label": "Quốc lộ 13", "checked": True},
            {"id": "impact", "label": "Vùng thương mại", "checked": True},
            {"id": "nodes", "label": "Điểm giao chính", "checked": True},
            {"id": "signals", "label": "Tin đang bán quanh khu này", "checked": False},
        ],
        "legend": [
            {"label": "Quốc lộ 13", "color": "#0f766e"},
            {"label": "Vùng thương mại", "color": "#f59e0b"},
            {"label": "Điểm giao chính", "color": "#dc2626"},
            {"label": "Signal quanh khu", "color": "#0369a1"},
        ],
        "impact_cards": [
            {"label": "Tuyến đi qua đâu", "value": "Thuận An - Thủ Dầu Một - Bến Cát", "tone": "info"},
            {"label": "Khu hưởng lợi", "value": "Mặt tiền thương mại, khu dân cư hiện hữu", "tone": "good"},
            {"label": "Khu cần kiểm tra", "value": "Hẻm nhỏ gắn nhãn gần QL13", "tone": "warn"},
            {"label": "Nguồn văn bản", "value": "Quy hoạch tỉnh Bình Dương", "tone": "source"},
        ],
        "sections": [
            _section(
                "vai-tro",
                "Quốc lộ 13 là trục đọc giá quan trọng",
                [
                    "QL13 đi qua các đô thị và khu công nghiệp lớn của Bình Dương cũ, nên thường xuất hiện trong mô tả tin rao dù khoảng cách tới tuyến có thể rất khác nhau.",
                    "Bản đồ giúp người dùng đặt câu hỏi đúng: lô đất nằm sát trục, trong hẻm kết nối, hay chỉ dùng QL13 như mốc quảng cáo.",
                ],
                "Quốc lộ 13",
            ),
            _section(
                "tdm",
                "Thủ Dầu Một - vùng lõi đô thị",
                [
                    "Đoạn Thủ Dầu Một cần đọc cùng dữ liệu giá/m², mật độ dân cư và khả năng khai thác thương mại.",
                    "Các lô mặt tiền hoặc gần trục chính có logic giá khác với đất hẻm sâu, nên dashboard Radar BDS dùng bộ lọc riêng theo phường và loại tài sản.",
                ],
                "Thủ Dầu Một",
            ),
            _section(
                "ben-cat",
                "Bến Cát - Bàu Bàng",
                [
                    "Hướng bắc QL13 gắn với công nghiệp, đô thị vệ tinh và kết nối về Bình Phước.",
                    "Với nhà đầu tư, điểm cần kiểm tra là khoảng cách tới KCN, pháp lý đất ở và khả năng thanh khoản ở từng khu dân cư cụ thể.",
                ],
                "Bến Cát",
            ),
        ],
        "impact_rows": [
            {
                "area": "Thủ Dầu Một",
                "impact": "Trục thương mại, dịch vụ và dân cư lõi.",
                "risk": "Giá mặt tiền và giá hẻm có thể chênh mạnh; cần lọc theo loại đường.",
                "status": "Hưởng lợi",
                "landing_href": "/binh-duong/thu-dau-mot",
                "dashboard_href": "/?tab=signals&city=Thủ%20Dầu%20Một",
            },
            {
                "area": "Bến Cát",
                "impact": "Kết nối khu công nghiệp, đô thị Mỹ Phước và hướng Vành đai 4.",
                "risk": "Tin rao xa trục vẫn có thể ghi gần QL13; cần kiểm tra vị trí bản đồ.",
                "status": "Cần lọc",
                "landing_href": "/binh-duong/ben-cat",
                "dashboard_href": "/?tab=signals&city=Bến%20Cát",
            },
            {
                "area": "Bàu Bàng",
                "impact": "Hưởng lợi từ trục bắc - nam và công nghiệp mở rộng.",
                "risk": "Cần kiểm tra quy hoạch sử dụng đất và tính thanh khoản từng cụm.",
                "status": "Theo dõi",
                "landing_href": "/binh-duong/ben-cat",
                "dashboard_href": "/?tab=signals",
            },
        ],
        "related_links": [
            {"label": "Vành đai 4", "href": "/quy-hoach-binh-duong/vanh-dai-4"},
            {"label": "Thủ Dầu Một", "href": "/binh-duong/thu-dau-mot"},
            {"label": "Mỹ Phước", "href": "/binh-duong/my-phuoc"},
        ],
        "faq": [
            _faq("Vì sao QL13 nên có bản đồ riêng?", "Vì QL13 là trục được nhắc nhiều trong tin rao Bình Dương cũ. Bản đồ giúp kiểm tra khoảng cách thật và phân biệt các khu hưởng lợi trực tiếp với khu chỉ dùng tên tuyến để quảng cáo."),
            _faq("Radar BDS có dùng QL13 để định giá tự động không?", "Trang này chỉ là lớp tra cứu công khai. Dashboard Radar BDS vẫn cần dữ liệu tin rao, vị trí, loại tài sản, giá/m² và các bộ lọc chất lượng khác để đánh giá tín hiệu."),
        ],
    },
    "dia-gioi-36-phuong-xa-binh-duong-cu": {
        "sort_order": 50,
        "slug": "dia-gioi-36-phuong-xa-binh-duong-cu",
        "path": "/quy-hoach-binh-duong/dia-gioi-36-phuong-xa-binh-duong-cu",
        "title": "Bản đồ địa giới 36 phường xã Bình Dương cũ | Radar BDS",
        "description": "Bản đồ tham khảo 36 phường xã Bình Dương cũ sau sắp xếp, kèm cách đối chiếu tên phường khi xem tin rao bất động sản.",
        "keywords": "36 phường xã Bình Dương cũ, địa giới Bình Dương sau sáp nhập, bản đồ phường xã Bình Dương",
        "category": "boundary",
        "category_label": "Địa giới",
        "breadcrumb_label": "36 phường xã",
        "hero_badge": "Địa giới hành chính",
        "hero_title": "Bản đồ địa giới 36 phường xã Bình Dương cũ",
        "hero_text": (
            "Sau sắp xếp đơn vị hành chính, tên phường xã mới có thể khiến người đọc tin rao "
            "khó đối chiếu khu cũ. Trang này hiển thị lớp địa giới tham khảo và bảng quy đổi "
            "để nối dữ liệu Radar BDS với cách gọi quen thuộc trên thị trường."
        ),
        "summary": "Đối chiếu tên phường xã mới - cũ để đọc tin rao, dashboard và các bài quy hoạch theo khu vực.",
        "thumbnail_label": "36 PX",
        "map_label": "36 phường xã Bình Dương cũ",
        "read_time": "8 phút đọc",
        "updated_at": PLANNING_UPDATED_AT,
        "updated_label": PLANNING_UPDATED_LABEL,
        "geojson_path": "/static/maps/planning/dia-gioi-36-phuong-xa-binh-duong-cu.geojson",
        "dashboard_href": "/?tab=signals",
        "areas": ["Thủ Dầu Một", "Thuận An", "Dĩ An", "Bến Cát", "Tân Uyên"],
        "source_badge": "Nguồn: thông tin sắp xếp ĐVHC 2025",
        "source_links": [
            {"label": "Bình Dương dự kiến còn 36 phường xã sau sắp xếp", "href": SOURCE_36_WARDS},
        ],
        "map_layers": [
            {"id": "boundary", "label": "Cụm địa giới", "checked": True},
            {"id": "nodes", "label": "Trung tâm khu vực", "checked": True},
            {"id": "signals", "label": "Tin đang bán quanh khu này", "checked": False},
        ],
        "legend": [
            {"label": "Cụm địa giới tham khảo", "color": "#0f766e"},
            {"label": "Trung tâm khu vực", "color": "#dc2626"},
            {"label": "Signal quanh khu", "color": "#0369a1"},
        ],
        "impact_cards": [
            {"label": "Nội dung chính", "value": "Quy đổi tên phường xã mới - cũ", "tone": "info"},
            {"label": "Khu hưởng lợi", "value": "Người tìm đất theo tên cũ", "tone": "good"},
            {"label": "Khu cần kiểm tra", "value": "Tin rao dùng tên phường chưa thống nhất", "tone": "warn"},
            {"label": "Nguồn văn bản", "value": "Đề án sắp xếp ĐVHC 2025", "tone": "source"},
        ],
        "sections": [
            _section(
                "vi-sao-can",
                "Vì sao cần một bản đồ địa giới riêng?",
                [
                    "Thị trường bất động sản thường giữ cách gọi khu vực cũ rất lâu sau khi địa giới hành chính thay đổi. Điều này làm người mua khó đối chiếu tin rao, giá/m² và bản đồ quy hoạch.",
                    "Trang địa giới giúp nối cách gọi cũ với các vùng dữ liệu đang có trên Radar BDS, đặc biệt ở Thủ Dầu Một, Bến Cát, Thuận An và Dĩ An.",
                ],
                "Cụm Bình Dương",
            ),
            _section(
                "bang-doi-chieu",
                "Cách đọc bảng quy đổi khi xem tin rao",
                [
                    "Một tin rao có thể ghi tên phường cũ, tên phường mới hoặc tên khu dân cư. Khi lọc dữ liệu, nên ưu tiên vị trí bản đồ và mốc đường thay vì chỉ dựa vào tên hành chính trong tiêu đề.",
                    "Radar BDS sẽ tiếp tục giữ các landing page theo tên quen thuộc để người dùng tìm được dữ liệu, đồng thời thêm liên kết sang các bài địa giới và quy hoạch liên quan.",
                ],
                "Thủ Dầu Một",
            ),
            _section(
                "ung-dung",
                "Ứng dụng vào dashboard Radar BDS",
                [
                    "Khi tên phường thay đổi, dashboard cần giữ khả năng lọc theo khu người dùng đang quen gọi và theo cách phân vùng dữ liệu cũ.",
                    "Các CTA trong trang đưa người dùng về bộ lọc signal, nơi có thể tiếp tục xem giá, diện tích, MOS và cảnh báo nguồn tin.",
                ],
                "Bến Cát",
            ),
        ],
        "impact_rows": [
            {
                "area": "Thủ Dầu Một",
                "impact": "Cần nối tên phường cũ với dữ liệu phường trong dashboard.",
                "risk": "Tin rao có thể dùng tên khu phố hoặc tên phường cũ không còn khớp văn bản.",
                "status": "Cần đối chiếu",
                "landing_href": "/binh-duong/thu-dau-mot",
                "dashboard_href": "/?tab=signals&city=Thủ%20Dầu%20Một",
            },
            {
                "area": "Bến Cát - Mỹ Phước",
                "impact": "Tên khu công nghiệp và khu dân cư vẫn là intent tìm kiếm mạnh.",
                "risk": "Cần kiểm tra vị trí map thay vì chỉ dựa tên phường mới.",
                "status": "Theo dõi",
                "landing_href": "/binh-duong/ben-cat",
                "dashboard_href": "/?tab=signals&city=Bến%20Cát",
            },
            {
                "area": "Thuận An - Dĩ An",
                "impact": "Nhiều tin rao giáp ranh, dễ nhầm khu nếu chỉ đọc tiêu đề.",
                "risk": "Cần xác minh mốc đường, ranh phường và địa chỉ trên giấy tờ.",
                "status": "Cần kiểm tra",
                "landing_href": "/binh-duong",
                "dashboard_href": "/?tab=signals",
            },
        ],
        "related_links": [
            {"label": "Vành đai 3", "href": "/quy-hoach-binh-duong/vanh-dai-3"},
            {"label": "Thủ Dầu Một", "href": "/binh-duong/thu-dau-mot"},
            {"label": "Bến Cát", "href": "/binh-duong/ben-cat"},
        ],
        "faq": [
            _faq("Bản đồ này có hiển thị đủ ranh 36 phường xã pháp lý không?", "MVP hiện hiển thị các cụm địa giới tham khảo để hỗ trợ đọc tin rao. Khi có bộ ranh chính thức ở định dạng GIS có thể kiểm chứng, Radar BDS sẽ thay lớp minh họa bằng dữ liệu chính xác hơn."),
            _faq("Vì sao vẫn dùng cụm từ Bình Dương cũ?", "Người dùng bất động sản vẫn tìm kiếm theo địa danh Bình Dương cũ. Cách gọi này giúp họ tra cứu đúng thị trường trước sáp nhập, đồng thời vẫn cần đối chiếu văn bản hành chính mới."),
        ],
    },
}


PLANNING_PAGE_LIST = sorted(PLANNING_PAGES.values(), key=lambda page: page["sort_order"])
