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
        "related": ["phuong-chanh-nghia", "phuong-phu-my", "phuong-hiep-an", "phuong-phu-cuong"],
    },
    {
        "slug": "ben-cat",
        "kind": "khu vực",
        "name": "Bến Cát",
        "context": "vùng công nghiệp và đô thị đang mở rộng, phù hợp theo dõi đất nền, nhà phố và các khu Mỹ Phước.",
        "intent": "nhà đất Bến Cát",
        "watch": ["Mỹ Phước", "Thới Hòa", "Tân Định", "Chánh Phú Hòa"],
        "related": ["my-phuoc", "phuong-thoi-hoa", "phuong-tan-dinh", "phuong-chanh-phu-hoa"],
    },
    {
        "slug": "my-phuoc",
        "kind": "khu vực",
        "name": "Mỹ Phước",
        "context": "cụm khu dân cư và công nghiệp lớn của Bến Cát, có nhiều tin đất nền, nhà trọ và nhà phố cần so giá kỹ.",
        "intent": "đất Mỹ Phước Bến Cát",
        "watch": ["Mỹ Phước 1", "Mỹ Phước 2", "Mỹ Phước 3", "khu L"],
        "related": ["my-phuoc-1", "my-phuoc-2", "my-phuoc-3", "ben-cat", "phuong-thoi-hoa", "phuong-tan-dinh"],
    },
    {
        "slug": "my-phuoc-1",
        "kind": "khu vực",
        "name": "Mỹ Phước 1",
        "context": "cụm dân cư và công nghiệp lâu đời hơn trong Mỹ Phước, hay có tin đất nền, nhà trọ và lô thổ cư cần so theo giá/m2.",
        "intent": "đất Mỹ Phước 1 Bình Dương",
        "watch": ["đất nền", "nhà trọ", "thổ cư", "giá/m2"],
        "related": ["my-phuoc", "my-phuoc-2", "my-phuoc-3", "ben-cat", "phuong-thoi-hoa", "phuong-tan-dinh"],
    },
    {
        "slug": "my-phuoc-2",
        "kind": "khu vực",
        "name": "Mỹ Phước 2",
        "context": "khu có nguồn đất nền và nhà phố gần các trục kết nối công nghiệp, cần tách rõ vị trí trong khu trước khi so fair value.",
        "intent": "đất Mỹ Phước 2 Bình Dương",
        "watch": ["đất nền", "nhà phố", "gần khu công nghiệp", "sổ riêng"],
        "related": ["my-phuoc", "my-phuoc-1", "my-phuoc-3", "ben-cat", "phuong-tan-dinh", "phuong-thoi-hoa"],
    },
    {
        "slug": "my-phuoc-3",
        "kind": "khu vực",
        "name": "Mỹ Phước 3",
        "context": "khu có nhiều tin đất nền, lô gần khu công nghiệp và nhà trọ đầu tư, phù hợp theo dõi riêng để tránh so chéo với toàn Bến Cát.",
        "intent": "đất Mỹ Phước 3 Bình Dương",
        "watch": ["đất nền", "nhà trọ", "khu công nghiệp", "diện tích vừa"],
        "related": ["my-phuoc", "my-phuoc-1", "my-phuoc-2", "ben-cat", "phuong-chanh-phu-hoa", "phuong-tan-dinh"],
    },
    {
        "slug": "phuong-phu-my",
        "live_ward": "Phú Mỹ",
        "ward_slug": "phu-my",
        "kind": "phường",
        "name": "Phú Mỹ",
        "context": "phường có nhiều tin đất hẻm, đất gần chợ và nhà phố dân cư cần bóc tách đúng vị trí trước khi so giá.",
        "intent": "nhà đất phường Phú Mỹ Thủ Dầu Một",
        "watch": ["chợ Phú Mỹ", "đất thổ cư", "hẻm xe hơi", "nhà phố"],
        "related": ["thu-dau-mot", "phuong-hiep-an", "phuong-phu-cuong", "phuong-phu-hoa"],
    },
    {
        "slug": "phuong-chanh-nghia",
        "live_ward": "Chánh Nghĩa",
        "ward_slug": "chanh-nghia",
        "kind": "phường",
        "name": "Chánh Nghĩa",
        "context": "khu trung tâm có mặt bằng giá cao hơn, nhiều tin nhà đất cần phân biệt giữa nhà ở thật và tin đầu tư.",
        "intent": "nhà đất Chánh Nghĩa Thủ Dầu Một",
        "watch": ["nhà phố", "đất hẻm", "gần trung tâm", "sổ riêng"],
        "related": ["thu-dau-mot", "phuong-phu-my", "phuong-tan-an", "san-deal-bds"],
    },
    {
        "slug": "phuong-hiep-an",
        "live_ward": "Hiệp An",
        "ward_slug": "hiep-an",
        "kind": "phường",
        "name": "Hiệp An",
        "context": "khu có nhiều tin đất dân cư, đất vườn và hẻm xe hơi, cần chuẩn hóa diện tích để tránh định giá lệch.",
        "intent": "nhà đất Hiệp An Thủ Dầu Một",
        "watch": ["đất nền", "hẻm xe hơi", "thổ cư", "giá/m2"],
        "related": ["thu-dau-mot", "phuong-phu-my", "phuong-tan-an", "phuong-tuong-binh-hiep"],
    },
    {
        "slug": "phuong-tan-an",
        "live_ward": "Tân An",
        "ward_slug": "tan-an",
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
        "related": ["ben-cat", "my-phuoc", "phuong-tan-dinh", "san-deal-bds"],
    },
    {
        "slug": "phuong-tuong-binh-hiep",
        "kind": "phường",
        "name": "Tương Bình Hiệp",
        "context": "phường có nhiều tin đất dân cư, đất vườn và nhà ở ven trục kết nối Thủ Dầu Một.",
        "intent": "nhà đất Tương Bình Hiệp Thủ Dầu Một",
        "watch": ["đất dân cư", "đất vườn", "hẻm xe hơi", "thổ cư"],
        "related": ["thu-dau-mot", "phuong-hiep-an", "phuong-tan-an", "phuong-dinh-hoa"],
    },
    {
        "slug": "phuong-dinh-hoa",
        "live_ward": "Định Hòa",
        "ward_slug": "dinh-hoa",
        "kind": "phường",
        "name": "Định Hòa",
        "context": "phường có nguồn tin đất nền, nhà phố và đất diện tích vừa cần so với nhóm lân cận.",
        "intent": "nhà đất Định Hòa Thủ Dầu Một",
        "watch": ["đất nền", "nhà phố", "diện tích vừa", "sổ riêng"],
        "related": ["thu-dau-mot", "phuong-tuong-binh-hiep", "phuong-chanh-my", "phuong-hiep-thanh"],
    },
    {
        "slug": "phuong-chanh-my",
        "kind": "phường",
        "name": "Chánh Mỹ",
        "context": "phường ven sông, gần trung tâm Thủ Dầu Một, phù hợp theo dõi nhà ở thật và đất hẻm.",
        "intent": "nhà đất Chánh Mỹ Thủ Dầu Một",
        "watch": ["nhà ở thật", "đất hẻm", "gần trung tâm", "pháp lý"],
        "related": ["thu-dau-mot", "phuong-dinh-hoa", "phuong-phu-cuong", "phuong-chanh-nghia"],
    },
    {
        "slug": "phuong-phu-cuong",
        "kind": "phường",
        "name": "Phú Cường",
        "context": "phường trung tâm có mặt bằng giá cao, nhiều tin nhà phố và đất hẻm cần so đúng phân khúc.",
        "intent": "nhà đất Phú Cường Thủ Dầu Một",
        "watch": ["nhà phố", "đất hẻm", "trung tâm", "giá/m2"],
        "related": ["thu-dau-mot", "phuong-chanh-nghia", "phuong-phu-my", "phuong-phu-hoa"],
    },
    {
        "slug": "phuong-phu-hoa",
        "live_ward": "Phú Hòa",
        "ward_slug": "phu-hoa",
        "kind": "phường",
        "name": "Phú Hòa",
        "context": "phường dân cư sôi động, có nhiều tin nhà phố, đất nền nhỏ và nhu cầu ở thật.",
        "intent": "nhà đất Phú Hòa Thủ Dầu Một",
        "watch": ["nhà phố", "đất nền nhỏ", "dân cư", "sổ riêng"],
        "related": ["thu-dau-mot", "phuong-phu-cuong", "phuong-phu-loi", "phuong-phu-my"],
    },
    {
        "slug": "phuong-phu-loi",
        "live_ward": "Phú Lợi",
        "ward_slug": "phu-loi",
        "kind": "phường",
        "name": "Phú Lợi",
        "context": "phường có nhiều tin nhà phố và đất dân cư, cần so giá theo vị trí và loại tài sản.",
        "intent": "nhà đất Phú Lợi Thủ Dầu Một",
        "watch": ["nhà phố", "đất dân cư", "hẻm xe hơi", "thổ cư"],
        "related": ["thu-dau-mot", "phuong-phu-hoa", "phuong-hiep-thanh", "phuong-dinh-hoa"],
    },
    {
        "slug": "phuong-hiep-thanh",
        "live_ward": "Hiệp Thành",
        "ward_slug": "hiep-thanh",
        "kind": "phường",
        "name": "Hiệp Thành",
        "context": "phường rộng, nguồn tin đa dạng nên cần tách kỹ phân khúc nhà phố, đất nền và hẻm.",
        "intent": "nhà đất Hiệp Thành Thủ Dầu Một",
        "watch": ["nhà phố", "đất nền", "hẻm xe hơi", "giá/m2"],
        "related": ["thu-dau-mot", "phuong-phu-loi", "phuong-dinh-hoa", "phuong-hoa-phu"],
    },
    {
        "slug": "phuong-phu-tan",
        "kind": "phường",
        "name": "Phú Tân",
        "context": "phường đô thị mới, phù hợp theo dõi đất nền, nhà phố và nguồn hàng quanh khu dân cư mới.",
        "intent": "nhà đất Phú Tân Thủ Dầu Một",
        "watch": ["đô thị mới", "đất nền", "nhà phố", "khu dân cư"],
        "related": ["thu-dau-mot", "phuong-hoa-phu", "phuong-hiep-thanh", "phuong-phu-loi"],
    },
    {
        "slug": "phuong-hoa-phu",
        "kind": "phường",
        "name": "Hòa Phú",
        "context": "phường đô thị mới của Thủ Dầu Một, có nhiều tin nhà phố, đất nền và khu dân cư quy hoạch.",
        "intent": "nhà đất Hòa Phú Thủ Dầu Một",
        "watch": ["đất nền", "nhà phố", "khu dân cư", "quy hoạch"],
        "related": ["thu-dau-mot", "phuong-phu-tan", "phuong-hiep-thanh", "phuong-dinh-hoa"],
    },
    {
        "slug": "phuong-phu-an",
        "kind": "phường",
        "name": "Phú An",
        "context": "phường Bến Cát có nguồn tin đất dân cư và đất vườn, cần so giá theo diện tích và pháp lý.",
        "intent": "nhà đất Phú An Bến Cát",
        "watch": ["đất dân cư", "đất vườn", "thổ cư", "diện tích lớn"],
        "related": ["ben-cat", "phuong-an-tay", "phuong-an-dien", "phuong-tan-dinh"],
    },
    {
        "slug": "phuong-an-tay",
        "kind": "phường",
        "name": "An Tây",
        "context": "phường Bến Cát có nhiều tin đất diện tích lớn, đất vườn và đất gần khu công nghiệp.",
        "intent": "nhà đất An Tây Bến Cát",
        "watch": ["đất diện tích lớn", "đất vườn", "khu công nghiệp", "thổ cư"],
        "related": ["ben-cat", "phuong-phu-an", "phuong-an-dien", "phuong-hoa-loi"],
    },
    {
        "slug": "phuong-an-dien",
        "kind": "phường",
        "name": "An Điền",
        "context": "phường Bến Cát có nguồn đất dân cư và đất vườn cần kiểm tra kỹ vị trí, diện tích và giá/m2.",
        "intent": "nhà đất An Điền Bến Cát",
        "watch": ["đất dân cư", "đất vườn", "giá/m2", "pháp lý"],
        "related": ["ben-cat", "phuong-an-tay", "phuong-phu-an", "phuong-chanh-phu-hoa"],
    },
    {
        "slug": "phuong-chanh-phu-hoa",
        "kind": "phường",
        "name": "Chánh Phú Hòa",
        "context": "phường Bến Cát gần các cụm công nghiệp, có nhiều tin đất nền và nhà phố cần so với Mỹ Phước.",
        "intent": "nhà đất Chánh Phú Hòa Bến Cát",
        "watch": ["đất nền", "nhà phố", "khu công nghiệp", "Mỹ Phước"],
        "related": ["ben-cat", "my-phuoc", "phuong-tan-dinh", "phuong-thoi-hoa"],
    },
    {
        "slug": "phuong-tan-dinh",
        "kind": "phường",
        "name": "Tân Định",
        "context": "phường Bến Cát có nhiều tin đất nền, nhà phố và đất gần trục kết nối công nghiệp.",
        "intent": "nhà đất Tân Định Bến Cát",
        "watch": ["đất nền", "nhà phố", "khu dân cư", "giá/m2"],
        "related": ["ben-cat", "my-phuoc", "phuong-chanh-phu-hoa", "phuong-thoi-hoa"],
    },
    {
        "slug": "phuong-hoa-loi",
        "kind": "phường",
        "name": "Hòa Lợi",
        "context": "phường Bến Cát đang phát triển, phù hợp theo dõi đất nền, nhà phố và nguồn hàng khu dân cư.",
        "intent": "nhà đất Hòa Lợi Bến Cát",
        "watch": ["đất nền", "nhà phố", "khu dân cư", "quy hoạch"],
        "related": ["ben-cat", "phuong-an-tay", "phuong-tan-dinh", "phuong-chanh-phu-hoa"],
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
            "body": f"Radar BDS gom tin theo {kind}, phường và cụm dân cư liên quan để so sánh giá sát hơn thay vì lấy trung bình toàn tỉnh.",
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
            "body": f"Thu thập tin có nhắc đến {name}, các phường lân cận, cụm dân cư và mô tả vị trí liên quan.",
        },
        {
            "title": "2. Chuẩn hóa vị trí",
            "body": "Tách phường, cụm vị trí, diện tích, thổ cư và loại tài sản để giảm nhầm lẫn khi so giá.",
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
            "q": "Vì sao cùng Bình Dương nhưng phải tách theo phường?",
            "a": "Giá đất thay đổi mạnh theo phường, cụm dân cư, hẻm, chiều ngang và thổ cư. Tách theo phường giúp fair value và MOS bớt lệch hơn.",
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
    if item.get("live_ward"):
        title = f"Giá nhà đất {name}, Thủ Dầu Một | Radar BDS"
        description = (
            f"Giá nhà đất {name}, Thủ Dầu Một theo dữ liệu tin rao Radar BDS: "
            "số tin đang theo dõi, tín hiệu, giá tham khảo và ngày cập nhật."
        )
        hero_title = f"Giá nhà đất {name}, Thủ Dầu Một"
        hero_text = (
            f"Trang dữ liệu {name}, Thủ Dầu Một – Bình Dương cũ, tổng hợp tin rao công khai "
            "để tham khảo mặt bằng giá và ưu tiên các tín hiệu cần kiểm tra."
        )
    else:
        title = f"{intent_label} - Radar BDS lọc deal bằng dữ liệu"
        description = (
            f"Landing {kind} {name} Bình Dương: theo dõi {item['intent']}, so giá theo dữ liệu, "
            "tính fair value, MOS và lọc tin rẻ đáng kiểm tra."
        )
        hero_title = f"{intent_label} bằng dữ liệu"
        hero_text = (
            f"{name} là {item['context']} Radar BDS giúp gom tin rao, chuẩn hóa vị trí, "
            "so giá theo mặt bằng gần nhất và ưu tiên những tin có biên an toàn rõ ràng."
        )
    return {
        "variant": "location",
        "live_ward": item.get("live_ward"),
        "ward_slug": item.get("ward_slug"),
        "path": f"/binh-duong/{item['slug']}",
        "title": title,
        "description": description,
        "keywords": f"{item['intent']}, nhà đất Bình Dương, Radar BDS, săn deal BĐS, định giá bất động sản, MOS BĐS",
        "hero_badge": f"Khu vực {kind.title()} Bình Dương",
        "hero_title": hero_title,
        "hero_text": hero_text,
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
