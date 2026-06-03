"""Location SEO landing pages for Bình Dương.

These pages are intentionally curated instead of mass-generated, so each URL has
enough local intent and internal links to avoid thin doorway pages.
"""
from __future__ import annotations


LOCATION_DEFINITIONS = [
    {
        "slug": "thu-dau-mot",
        "kind": "khu vực",
        "name": "Thủ Dầu Một",
        "context": "khu trung tâm của Bình Dương, nhiều nhu cầu nhà ở thật, đất hẻm xe hơi và các tuyến đường nội đô.",
        "intent": "nhà đất Thủ Dầu Một",
        "watch": ["Chánh Nghĩa", "Phú Mỹ", "Hiệp An", "Tân An"],
        "related": ["phuong-chanh-nghia", "phuong-phu-my", "phuong-hiep-an", "duong-dx20"],
    },
    {
        "slug": "ben-cat",
        "kind": "khu vực",
        "name": "Bến Cát",
        "context": "vùng công nghiệp và đô thị đang mở rộng, phù hợp theo dõi đất nền, nhà phố và các khu Mỹ Phước.",
        "intent": "nhà đất Bến Cát",
        "watch": ["Mỹ Phước", "Thới Hòa", "Tân Định", "Chánh Phú Hòa"],
        "related": ["my-phuoc", "phuong-thoi-hoa", "duong-dl12", "duong-dx013"],
    },
    {
        "slug": "my-phuoc",
        "kind": "khu vực",
        "name": "Mỹ Phước",
        "context": "cụm khu dân cư và công nghiệp lớn của Bến Cát, có nhiều tin đất nền, nhà trọ và nhà phố cần so giá kỹ.",
        "intent": "đất Mỹ Phước Bến Cát",
        "watch": ["Mỹ Phước 1", "Mỹ Phước 2", "Mỹ Phước 3", "khu L"],
        "related": ["ben-cat", "phuong-thoi-hoa", "duong-dl12", "duong-dx013"],
    },
    {
        "slug": "phuong-phu-my",
        "kind": "phường",
        "name": "Phú Mỹ",
        "context": "phường có nhiều tin đất hẻm, đất gần chợ và các tuyến DX cần bóc tách đúng vị trí trước khi so giá.",
        "intent": "nhà đất phường Phú Mỹ Thủ Dầu Một",
        "watch": ["DX20", "DX013", "chợ Phú Mỹ", "đất thổ cư"],
        "related": ["thu-dau-mot", "duong-dx20", "duong-dx013", "phuong-hiep-an"],
    },
    {
        "slug": "phuong-chanh-nghia",
        "kind": "phường",
        "name": "Chánh Nghĩa",
        "context": "khu trung tâm có mặt bằng giá cao hơn, nhiều tin nhà đất cần phân biệt giữa nhà ở thật và tin đầu tư.",
        "intent": "nhà đất Chánh Nghĩa Thủ Dầu Một",
        "watch": ["nhà phố", "đất hẻm", "gần trung tâm", "sổ riêng"],
        "related": ["thu-dau-mot", "phuong-phu-my", "phuong-tan-an", "san-deal-bds"],
    },
    {
        "slug": "phuong-hiep-an",
        "kind": "phường",
        "name": "Hiệp An",
        "context": "khu có nhiều tin đất dân cư, đất vườn và hẻm xe hơi, cần chuẩn hóa diện tích để tránh định giá lệch.",
        "intent": "nhà đất Hiệp An Thủ Dầu Một",
        "watch": ["đất nền", "hẻm xe hơi", "thổ cư", "giá/m2"],
        "related": ["thu-dau-mot", "phuong-phu-my", "phuong-tan-an", "duong-dx20"],
    },
    {
        "slug": "phuong-tan-an",
        "kind": "phường",
        "name": "Tân An",
        "context": "phường ven đô của Thủ Dầu Một, hay có tin đất diện tích vừa và lớn cần so với mặt bằng cùng phân khúc.",
        "intent": "nhà đất Tân An Thủ Dầu Một",
        "watch": ["đất vườn", "đất thổ cư", "diện tích lớn", "đường nhựa"],
        "related": ["thu-dau-mot", "phuong-hiep-an", "phuong-chanh-nghia", "san-deal-bds"],
    },
    {
        "slug": "phuong-thoi-hoa",
        "kind": "phường",
        "name": "Thới Hòa",
        "context": "khu vực Bến Cát gần trục công nghiệp, có nhiều tin nhà đất quanh Đại học Việt Đức và Mỹ Phước.",
        "intent": "nhà đất Thới Hòa Bến Cát",
        "watch": ["Đại học Việt Đức", "Mỹ Phước", "nhà trọ", "đất nền"],
        "related": ["ben-cat", "my-phuoc", "duong-dl12", "san-deal-bds"],
    },
    {
        "slug": "duong-dx013",
        "kind": "đường",
        "name": "DX013",
        "context": "tuyến đường được nhắc nhiều trong tin Phú Mỹ, thường cần kiểm tra mặt tiền, hẻm, vỉa hè và khoảng cách tới chợ.",
        "intent": "đất đường DX013 Phú Mỹ",
        "watch": ["mặt tiền DX013", "chợ Phú Mỹ", "5x30", "thổ cư"],
        "related": ["phuong-phu-my", "duong-dx20", "thu-dau-mot", "san-deal-bds"],
    },
    {
        "slug": "duong-dx20",
        "kind": "đường",
        "name": "DX20",
        "context": "tuyến nội khu Phú Mỹ có nhiều tin đất 5x20, 5x30, cần so giá theo hẻm, mặt tiền và pháp lý.",
        "intent": "đất đường DX20 Phú Mỹ",
        "watch": ["DX20 Phú Mỹ", "5x20", "5x30", "ô tô né nhau"],
        "related": ["phuong-phu-my", "duong-dx013", "phuong-hiep-an", "thu-dau-mot"],
    },
    {
        "slug": "duong-dl12",
        "kind": "đường",
        "name": "DL12",
        "context": "tuyến thuộc cụm Mỹ Phước, thường xuất hiện trong tin đất nền Bến Cát và cần tách đúng khu để định giá.",
        "intent": "đất đường DL12 Mỹ Phước",
        "watch": ["Mỹ Phước 3", "khu L", "đất nền", "đường nội khu"],
        "related": ["my-phuoc", "ben-cat", "phuong-thoi-hoa", "san-deal-bds"],
    },
]


def _dashboard_cta(name: str) -> dict:
    return {
        "title": f"Muốn xem tín hiệu nhà đất {name} đang có?",
        "body": "Mở dashboard Radar BDS để xem tin mới, fair value, MOS và các cảnh báo chất lượng nguồn trước khi đi xem thực tế.",
        "button": "Mở dashboard Radar BDS",
    }


def _value_cards(item: dict) -> list[dict]:
    name = item["name"]
    kind = item["kind"]
    return [
        {
            "title": f"Đọc đúng mặt bằng {kind} {name}",
            "body": f"Radar BDS gom tin theo {kind}, phường và tuyến đường liên quan để so sánh giá sát hơn thay vì lấy trung bình toàn tỉnh.",
        },
        {
            "title": "Lọc tin rẻ nhưng vẫn có kiểm soát",
            "body": "Các tin có MOS tốt được kiểm tra thêm nguồn, diện tích, loại tài sản và dấu hiệu mồi giá trước khi đẩy lên feed chính.",
        },
        {
            "title": "Theo dõi biến động giá theo cụm",
            "body": "Lịch sử giá, tin đăng lại và tin giảm giá được gom theo lô/khu để người mua không bỏ sót cơ hội thật.",
        },
    ]


def _process(name: str) -> list[dict]:
    return [
        {
            "title": "1. Gom tin theo khu vực",
            "body": f"Thu thập tin có nhắc đến {name}, các phường lân cận, tuyến đường và mô tả vị trí liên quan.",
        },
        {
            "title": "2. Chuẩn hóa vị trí",
            "body": "Tách phường, đường, diện tích, thổ cư và loại tài sản để giảm nhầm lẫn khi so giá.",
        },
        {
            "title": "3. So với mặt bằng gần nhất",
            "body": "Ước tính fair value bằng nhóm tin cùng khu và cùng phân khúc thay vì so chéo những khu quá khác nhau.",
        },
        {
            "title": "4. Tính MOS và cảnh báo",
            "body": "Đánh dấu tin rẻ hơn đáng kể, đồng thời cảnh báo tin có rủi ro nguồn hoặc dữ liệu chưa đủ chắc.",
        },
        {
            "title": "5. Đưa vào dashboard",
            "body": "Tin đủ điều kiện được đưa vào Săn Deal, Toàn bộ tin rao hoặc watchlist để theo dõi tiếp.",
        },
    ]


def _faq(item: dict) -> list[dict]:
    name = item["name"]
    intent = item["intent"]
    return [
        {
            "q": f"Trang {name} dùng để làm gì?",
            "a": f"Trang này giúp người mua theo dõi nhanh mặt bằng {intent}, hiểu cách Radar BDS lọc tin và đi tiếp vào dashboard để xem dữ liệu thật.",
        },
        {
            "q": "Dữ liệu có thay thế việc đi xem đất không?",
            "a": "Không. Đây là lớp lọc dữ liệu ban đầu để ưu tiên tin đáng kiểm tra; người mua vẫn cần kiểm tra pháp lý, quy hoạch và hiện trạng.",
        },
        {
            "q": "Vì sao cùng Bình Dương nhưng phải tách theo phường/đường?",
            "a": "Giá đất thay đổi mạnh theo phường, hẻm, mặt tiền, chiều ngang và thổ cư. Tách nhỏ giúp fair value và MOS bớt lệch hơn.",
        },
        {
            "q": "Tôi có thể nhận cảnh báo khu này không?",
            "a": "Có. Bạn có thể mở dashboard, lọc theo khu vực phù hợp và lưu watchlist để theo dõi tin mới hoặc tin giảm giá.",
        },
    ]


def _related_links(current_slug: str, related_slugs: list[str]) -> list[dict]:
    by_slug = {item["slug"]: item for item in LOCATION_DEFINITIONS}
    links = []
    for slug in related_slugs:
        if slug == "san-deal-bds":
            links.append({
                "label": "Cách lọc deal BĐS",
                "href": "/san-deal-bds",
                "description": "Hiểu fair value, MOS và bộ lọc chất lượng nguồn.",
            })
            continue
        item = by_slug.get(slug)
        if not item or item["slug"] == current_slug:
            continue
        links.append({
            "label": item["name"],
            "href": f"/binh-duong/{item['slug']}",
            "description": f"Landing {item['kind']} cho {item['intent']}.",
        })
    return links[:6]


def _sentence_case(value: str) -> str:
    return value[:1].upper() + value[1:] if value else value


def _page(item: dict) -> dict:
    name = item["name"]
    kind = item["kind"]
    watch_text = ", ".join(item["watch"][:3])
    intent_label = _sentence_case(item["intent"])
    title = f"{intent_label} - Radar BDS lọc deal bằng dữ liệu"
    description = (
        f"Landing {kind} {name} Bình Dương: theo dõi {item['intent']}, so giá theo dữ liệu, "
        "tính fair value, MOS và lọc tin rẻ đáng kiểm tra."
    )
    return {
        "variant": "location",
        "path": f"/binh-duong/{item['slug']}",
        "title": title,
        "description": description,
        "keywords": f"{item['intent']}, nhà đất Bình Dương, Radar BDS, săn deal BĐS, định giá bất động sản, MOS BĐS",
        "hero_badge": f"SEO địa phương - {kind.title()} Bình Dương",
        "hero_title": f"{intent_label} bằng dữ liệu",
        "hero_text": (
            f"{name} là {item['context']} Radar BDS giúp gom tin rao, chuẩn hóa vị trí, "
            "so giá theo mặt bằng gần nhất và ưu tiên những tin có biên an toàn rõ ràng."
        ),
        "hero_checks": [watch_text, "Fair value theo khu", "Cảnh báo tin nhiễu"],
        "primary_cta": f"Xem tin {name}",
        "secondary_cta": "Cách lọc deal",
        "secondary_href": "/san-deal-bds",
        "map_label": f"Bình Dương / {name}",
        "hero_metric": {
            "label": "Bộ lọc dữ liệu",
            "value": "MOS",
            "delta": "live",
            "note": f"theo {kind} và phân khúc",
        },
        "property_card": {
            "status": "Cần so giá",
            "title": f"Tin nhà đất {name}",
            "price": f"Theo dõi: {watch_text}",
            "metric_a": "Fair value",
            "metric_a_value": "theo khu",
            "metric_b": "MOS",
            "metric_b_value": "ưu tiên",
        },
        "value_cards": _value_cards(item),
        "process_title": f"Cách Radar BDS đọc dữ liệu {name}",
        "process": _process(name),
        "faq": _faq(item),
        "final_cta": _dashboard_cta(name),
        "local_links_title": "Khu vực liên quan",
        "local_links": _related_links(item["slug"], item["related"]),
    }


SEO_LOCATION_PAGES = {f"binh-duong/{item['slug']}": _page(item) for item in LOCATION_DEFINITIONS}

SEO_LOCATION_INDEX_LINKS = [
    {
        "label": item["name"],
        "href": f"/binh-duong/{item['slug']}",
        "description": f"{item['kind'].capitalize()} cho {item['intent']}.",
    }
    for item in LOCATION_DEFINITIONS
]
