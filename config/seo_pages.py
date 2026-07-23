"""SEO landing page content for public Radar BDS pages."""

SEO_PAGES = {
    "bao-cao": {
        "final_cta": {
            "title": "Xem báo cáo Tháng 06/2026 mới nhất",
            "body": "Báo cáo tháng chỉ publish sau khi chốt dữ liệu cuối tháng; hiện bản đã chốt mới nhất là 06/2026.",
            "button": "Xem báo cáo",
            "button_href": "/bao-cao/bds-binh-duong-thang-06-2026",
        },

        "variant": "hub",
        "path": "/bao-cao",
        "title": "Báo cáo thị trường BĐS Bình Dương — Radar BDS",
        "description": "Tổng hợp các báo cáo thị trường bất động sản Bình Dương theo tháng: giá đất nền trung vị, nguồn cung, tín hiệu mua bán tại 13 phường Thủ Dầu Một.",
        "keywords": "báo cáo thị trường BĐS Bình Dương, báo cáo Thủ Dầu Một, radar bds, phân tích thị trường",
        "hero_badge": "Báo cáo thị trường",
        "hero_title": "Báo cáo thị trường BĐS Bình Dương",
        "hero_text": "Tổng hợp tất cả báo cáo thị trường bất động sản khu vực Bình Dương do Radar BDS thực hiện. Mỗi báo cáo dựa trên dữ liệu tin rao Facebook thực tế tại 13 phường Thủ Dầu Một: giá/m² trung vị, nguồn cung, tín hiệu hot và giảm giá.",
        "hero_checks": ["Dữ liệu tin rao thực tế", "13 phường Thủ Dầu Một", "Cập nhật theo tháng"],
        "primary_cta": "Xem báo cáo mới nhất",
        "primary_href": "/bao-cao/bds-binh-duong-thang-06-2026",
        "secondary_cta": "Mở dashboard",
        "secondary_href": "/dashboard",
        "map_label": "Báo cáo / Hub",
        "hero_metric": {
            "label": "Báo cáo đã xuất bản",
            "value": "14",
            "delta": "1 tháng đã chốt (06/2026)",
            "note": "1 tổng quan + 13 phường/tháng"
        },
        "property_card": {
            "status": "Report hub",
            "title": "Báo cáo thị trường BĐS Bình Dương",
            "price": "Tổng hợp báo cáo theo tháng — dữ liệu từ radar bds",
            "metric_a": "Số tháng",
            "metric_a_value": "2",
            "metric_b": "Số phường",
            "metric_b_value": "13"
        },
        "value_cards": [
            {"title": "Báo cáo tổng quan (master)",
             "body": "So sánh tất cả 13 phường Thủ Dầu Một trên cùng một bảng: nguồn cung, giá/m² trung vị, phường rẻ nhất/đắt nhất, tín hiệu đáng chú ý."},
            {"title": "Báo cáo chi tiết từng phường",
             "body": "Mỗi phường có báo cáo riêng: phân bố loại hình, giá theo từng phân khúc, biểu đồ trực quan, nhận định từ dữ liệu."},
            {"title": "Cập nhật mỗi tháng",
             "body": "Đầu mỗi tháng, Radar BDS tự động tổng hợp lại dữ liệu thị trường từ hàng trăm tin rao Facebook để ra báo cáo mới nhất."}
        ],
        "local_links_title": "Chọn tháng",
        "local_links": [
            {
                "label": "Tháng 06/2026",
                "href": "/bao-cao/bds-binh-duong-thang-06-2026",
                "description": "4.865 tin rao, giá đất nền 22.0 tr/m²"
            }
        ],
    },

    "binh-duong": {
        "variant": "market",
        "path": "/binh-duong",
        "title": "Nhà đất Bình Dương: radar săn deal giá tốt theo dữ liệu thị trường",
        "description": (
            "Radar BDS theo dõi nhà đất Bình Dương, bất động sản Bình Dương và mua bán nhà đất Bình Dương "
            "bằng dữ liệu tin rao, fair value, MOS và cảnh báo nguồn."
        ),
        "keywords": (
            "nhà đất Bình Dương, bất động sản Bình Dương, mua bán nhà đất Bình Dương, bds Bình Dương, "
            "Radar BDS, săn deal nhà đất, định giá bất động sản, margin of safety BDS"
        ),
        "hero_badge": "Bình Dương - Dữ liệu thật - Deal chất",
        "hero_title": "Nhà đất Bình Dương: radar săn deal giá tốt theo dữ liệu thị trường",
        "hero_text": (
            "Radar BDS là hub theo dõi nhà đất Bình Dương và bất động sản Bình Dương: gom tin mua bán, "
            "chuẩn hóa phường/khu, so mặt bằng giá và ưu tiên các cơ hội có biên an toàn rõ ràng."
        ),
        "hero_checks": ["Thủ Dầu Một", "Bến Cát - Mỹ Phước", "MOS theo từng khu vực"],
        "primary_cta": "Mở dashboard Bình Dương",
        "secondary_cta": "Xem cách hoạt động",
        "secondary_href": "/san-deal-bds",
        "map_label": "Thu Dau Mot City",
        "hero_metric": {
            "label": "Tín hiệu Bình Dương",
            "value": "128",
            "delta": "+24%",
            "note": "so với hôm qua",
        },
        "property_card": {
            "status": "Tín hiệu tốt",
            "title": "P. Chánh Nghĩa, TP. Thủ Dầu Một",
            "price": "Giá rao: 2.35 tỷ · 100 m²",
            "metric_a": "Giá trị ước tính",
            "metric_a_value": "2.95 tỷ",
            "metric_b": "Biên an toàn (MOS)",
            "metric_b_value": "20.3%",
        },
        "value_cards": [
            {
                "title": "Tập trung đúng khu vực nóng",
                "body": "Theo dõi Thủ Dầu Một, Bến Cát, Mỹ Phước và các phường có nguồn hàng dày để tránh so sánh lệch vùng.",
            },
            {
                "title": "So giá theo mặt bằng địa phương",
                "body": "Định giá theo loại tài sản, diện tích, vị trí và dữ liệu cùng khu vực thay vì nhìn một mức giá toàn tỉnh.",
            },
            {
                "title": "Ưu tiên deal có biên an toàn",
                "body": "Đẩy các tin có MOS tốt, mô tả rõ và ít dấu hiệu mồi giá lên trước để bạn kiểm tra nhanh hơn.",
            },
        ],
        "dashboard_preview": {
            "eyebrow": "Dashboard thật",
            "title": "Mở là thấy ngay deal nào đáng soi trước",
            "body": "Feed tín hiệu gom giá rao, định giá, biên an toàn, khu vực và trạng thái tin mới trong một màn hình để nhà đầu tư không phải đọc từng bài thủ công.",
            "image": "/static/images/seo/dashboard-preview.png",
            "alt": "Preview dashboard Radar BDS hiển thị các card deal nhà đất Bình Dương",
            "cta": "Xem dashboard thật",
            "metrics": [
                {"value": "876+", "label": "Tin rao được chuẩn hóa"},
                {"value": "100+", "label": "Tín hiệu đang theo dõi"},
                {"value": "Hàng ngày", "label": "Cập nhật dữ liệu định kỳ"},
            ],
        },
        "process_title": "Radar BDS đọc thị trường Bình Dương như thế nào",
        "process": [
            {
                "title": "1. Gom nguồn địa phương",
                "body": "Tổng hợp tin từ Facebook, Guland và các phường/khu vực đang theo dõi.",
            },
            {
                "title": "2. Chuẩn hóa phường/khu",
                "body": "Tách Thủ Dầu Một, Bến Cát, Mỹ Phước, diện tích, giá và loại tài sản.",
            },
            {
                "title": "3. So mặt bằng giá",
                "body": "So sánh với các tin cùng phân khúc để ước tính fair value địa phương.",
            },
            {
                "title": "4. Chấm điểm MOS",
                "body": "Ưu tiên tin có giá thấp hơn đáng kể so với mặt bằng đã chuẩn hóa.",
            },
            {
                "title": "5. Đưa lên bộ lọc",
                "body": "Theo dõi tin mới, tin giảm giá và các khu vực có tín hiệu tốt.",
            },
        ],
        "faq": [
            {
                "q": "Radar BDS hiện tập trung khu nào ở Bình Dương?",
                "a": "Trọng tâm là Thủ Dầu Một, Bến Cát và các khu Mỹ Phước có dữ liệu đủ dày để so sánh giá đáng tin hơn.",
            },
            {
                "q": "Dữ liệu Bình Dương có cập nhật liên tục không?",
                "a": "Có. Hệ thống gom tin mới định kỳ, chuẩn hóa lại dữ liệu và ưu tiên những tín hiệu có biến động đáng chú ý.",
            },
            {
                "q": "Có phù hợp cho người mua ở thực không?",
                "a": "Có, vì dashboard giúp lọc tin rẻ hơn mặt bằng và giảm thời gian đọc tin thủ công trước khi đi xem thực tế.",
            },
            {
                "q": "Radar BDS có thay môi giới hay thẩm định pháp lý không?",
                "a": "Không. Radar BDS là lớp lọc dữ liệu ban đầu; người mua vẫn cần kiểm tra pháp lý, hiện trạng và quy hoạch.",
            },
        ],
        "final_cta": {
            "title": "Sẵn sàng theo dõi thị trường Bình Dương sát hơn?",
            "body": "Mở dashboard để xem tín hiệu mới, khu vực đang có nguồn hàng và các deal có MOS đáng kiểm tra.",
            "button": "Mở dashboard Bình Dương",
        },
    },
    "ban-dat-binh-duong": {
        "variant": "land",
        "path": "/ban-dat-binh-duong",
        "title": "Bán đất Bình Dương: lọc đất nền, đất thổ cư có biên an toàn",
        "description": (
            "Trang bán đất Bình Dương của Radar BDS tập trung đất nền, đất thổ cư, giá/m² theo phường, "
            "số tin đang theo dõi, khu có tín hiệu MOS tốt và cảnh báo tin giá ảo."
        ),
        "keywords": (
            "đất Bình Dương, bán đất Bình Dương, dat binh duong, đất nền Bình Dương, đất thổ cư Bình Dương, "
            "giá đất Bình Dương, Radar BDS"
        ),
        "hero_badge": "Đất Bình Dương - Đất nền - Đất thổ cư",
        "hero_title": "Bán đất Bình Dương: lọc đất nền, đất thổ cư có biên an toàn",
        "hero_text": (
            "Trang này tách riêng nhu cầu đất Bình Dương và bán đất Bình Dương khỏi hub nhà đất chung. "
            "Radar BDS soi giá/m², thổ cư, diện tích, phường/khu và tín hiệu MOS để giảm thời gian đọc tin đất nền bị nhiễu."
        ),
        "hero_checks": ["dat binh duong", "Giá/m² theo phường", "Cảnh báo tin giá ảo"],
        "primary_cta": "Xem feed đất Bình Dương",
        "secondary_cta": "Hub nhà đất Bình Dương",
        "secondary_href": "/binh-duong",
        "map_label": "Land Signals / Binh Duong",
        "hero_metric": {
            "label": "Tin đang theo dõi",
            "value": "100+",
            "delta": "đất",
            "note": "đất nền, thổ cư, diện tích lớn",
        },
        "property_card": {
            "status": "Đất có MOS",
            "title": "Đất thổ cư Tân Định - Mỹ Phước",
            "price": "Giá rao: 18-26 tr/m² · lọc theo phường",
            "metric_a": "Giá/m²",
            "metric_a_value": "so khu",
            "metric_b": "Tin giá ảo",
            "metric_b_value": "cảnh báo",
        },
        "value_cards": [
            {
                "title": "Tập trung đất nền và đất thổ cư",
                "body": "Không trộn nhu cầu đất với nhà phố. Trang này ưu tiên diện tích, ngang sâu, thổ cư, đường vào và giá/m² của từng phường.",
            },
            {
                "title": "So giá/m² theo phường",
                "body": "Bảng tham chiếu giúp phân biệt mặt bằng Thủ Dầu Một, Bến Cát, Mỹ Phước, Tân Định và các khu có nguồn hàng dày.",
            },
            {
                "title": "Cảnh báo tin đất bị nhiễu",
                "body": "Tin quá rẻ, thiếu diện tích, mập mờ thổ cư hoặc mô tả lệch vị trí được đưa vào nhóm cần kiểm tra kỹ trước khi gọi là deal.",
            },
        ],
        "market_snapshot": {
            "eyebrow": "Dữ liệu đất Bình Dương",
            "title": "Bảng giá/m² tham chiếu và tín hiệu cần soi",
            "body": (
                "Các mốc bên dưới là khung theo dõi SEO/sản phẩm để người mua biết nơi nào có nguồn hàng dày, "
                "nơi nào thường xuất hiện MOS tốt và nơi nào dễ gặp tin giá ảo."
            ),
            "columns": ["Khu vực", "Giá/m² tham chiếu", "Tin đang theo dõi", "Tín hiệu chính"],
            "rows": [
                {
                    "area": "Thủ Dầu Một",
                    "price": "32-58 tr/m²",
                    "tracked": "Nguồn ổn định",
                    "signal": "Đất hẻm, đất thổ cư cần so theo phường",
                },
                {
                    "area": "Bến Cát",
                    "price": "15-32 tr/m²",
                    "tracked": "Nguồn dày",
                    "signal": "Khu có tín hiệu MOS tốt khi tách đúng phân khúc",
                },
                {
                    "area": "Mỹ Phước 1/2/3",
                    "price": "18-36 tr/m²",
                    "tracked": "Theo dõi riêng",
                    "signal": "Đất nền, nhà trọ, lô gần khu công nghiệp",
                },
                {
                    "area": "Tân Định - Thới Hòa",
                    "price": "16-30 tr/m²",
                    "tracked": "Đang mở rộng",
                    "signal": "Nhiều tin cần cảnh báo giá ảo và nhầm vị trí",
                },
            ],
            "cards": [
                {
                    "title": "Tin đang theo dõi",
                    "value": "100+",
                    "body": "Tập trung đất nền, đất thổ cư, diện tích lớn và các tin có giá/m² đủ rõ để so sánh.",
                },
                {
                    "title": "Khu có tín hiệu MOS tốt",
                    "value": "Bến Cát",
                    "body": "Ưu tiên Mỹ Phước, Tân Định, Thới Hòa khi dữ liệu cùng phân khúc đủ dày.",
                },
                {
                    "title": "Cảnh báo tin giá ảo",
                    "value": "Luôn bật",
                    "body": "Đánh dấu tin quá rẻ, thiếu thổ cư, sai diện tích hoặc mô tả vị trí không nhất quán.",
                },
            ],
        },
        "process_title": "Radar BDS lọc đất Bình Dương như thế nào",
        "process": [
            {
                "title": "1. Tách đúng loại đất",
                "body": "Phân biệt đất nền, đất thổ cư, đất vườn, đất diện tích lớn và tin nhà phố để không so chéo sai mặt bằng.",
            },
            {
                "title": "2. Chuẩn hóa phường/khu",
                "body": "Gắn tin về Thủ Dầu Một, Bến Cát, Mỹ Phước, Tân Định, Thới Hòa hoặc phường liên quan trước khi định giá.",
            },
            {
                "title": "3. Tính giá/m² và fair value",
                "body": "So giá/m² với nhóm tương đồng về vị trí, diện tích, thổ cư và mặt tiền để phát hiện tin thấp hơn mặt bằng.",
            },
            {
                "title": "4. Chấm MOS và cảnh báo nguồn",
                "body": "Kết hợp biên an toàn với dấu hiệu tin giá ảo, thiếu dữ liệu hoặc rủi ro mô tả để xếp hạng cơ hội.",
            },
            {
                "title": "5. Đưa vào feed kiểm tra",
                "body": "Tin đủ điều kiện được đưa vào dashboard để người mua mở rộng xem ảnh, lịch sử giá và khu vực liên quan.",
            },
        ],
        "faq": [
            {
                "q": "Trang bán đất Bình Dương khác gì hub nhà đất Bình Dương?",
                "a": "Hub nhà đất bao quát bất động sản Bình Dương, còn trang này chỉ tập trung đất nền, đất thổ cư, giá/m² và các cảnh báo riêng của tin đất.",
            },
            {
                "q": "Bảng giá/m² có thay thế thẩm định thực tế không?",
                "a": "Không. Đây là lớp tham chiếu để ưu tiên tin đáng kiểm tra; người mua vẫn cần xác minh pháp lý, quy hoạch và hiện trạng lô đất.",
            },
            {
                "q": "Radar BDS phát hiện tin đất giá ảo bằng cách nào?",
                "a": "Hệ thống so giá với khu gần nhất, kiểm tra diện tích, thổ cư, mô tả vị trí, lịch sử đăng lại và mức chênh bất thường.",
            },
            {
                "q": "Khu nào nên theo dõi trước khi mua đất Bình Dương?",
                "a": "Nên bắt đầu từ Thủ Dầu Một, Bến Cát, Mỹ Phước, Tân Định, Thới Hòa và các phường có dữ liệu đủ dày trên dashboard.",
            },
        ],
        "final_cta": {
            "title": "Muốn lọc đất Bình Dương trước khi đi xem?",
            "body": "Mở dashboard Radar BDS để xem tin đất đã chuẩn hóa, giá/m², MOS và cảnh báo nguồn cần kiểm tra.",
            "button": "Mở feed đất Bình Dương",
        },
        "local_links_title": "Khu đất nên theo dõi tiếp",
    },
    "san-deal-bds": {
        "variant": "method",
        "path": "/san-deal-bds",
        "title": "Săn deal BĐS bằng dữ liệu - Cách Radar BDS lọc tin rẻ thật",
        "description": (
            "Radar BDS giải thích cách lọc deal bất động sản: chuẩn hóa tin rao, định giá, tính MOS, "
            "kiểm tra chất lượng nguồn và cảnh báo tin đáng chú ý."
        ),
        "keywords": (
            "săn deal BĐS, săn deal bất động sản, lọc tin rẻ thật, định giá bất động sản, "
            "margin of safety BDS, Radar BDS"
        ),
        "hero_badge": "Phương pháp lọc deal - Giảm nhiễu trước khi đi xem",
        "hero_title": "Cách Radar BDS lọc tin rẻ thật",
        "hero_text": (
            "Một tin rao giá thấp chưa chắc là deal tốt. Radar BDS kết hợp định giá, biên an toàn, "
            "lịch sử giá và bộ lọc chất lượng nguồn để giảm nhiễu trước khi bạn đi kiểm tra thực tế."
        ),
        "hero_checks": ["Lọc tin ảo", "Tính fair value", "Xếp hạng MOS"],
        "primary_cta": "Xem tín hiệu đang có",
        "secondary_cta": "Thị trường Bình Dương",
        "secondary_href": "/",
        "map_label": "Deal Filtering Flow",
        "hero_metric": {
            "label": "Tin qua bộ lọc",
            "value": "86",
            "delta": "sạch",
            "note": "từ nguồn tin mới",
        },
        "property_card": {
            "status": "Qua bộ lọc",
            "title": "Tin có giá thấp + nguồn đủ sạch",
            "price": "Giá rao: 2.35 tỷ · Fair value: 2.95 tỷ",
            "metric_a": "MOS",
            "metric_a_value": "20.3%",
            "metric_b": "Rủi ro nguồn",
            "metric_b_value": "Thấp",
        },
        "value_cards": [
            {
                "title": "Không chỉ nhìn giá rao thấp",
                "body": "Tách các trường hợp mồi giá, sai diện tích, nhầm vị trí hoặc thiếu dữ liệu trước khi gọi là deal.",
            },
            {
                "title": "Fair value trước, MOS sau",
                "body": "Ước tính giá trị hợp lý rồi mới tính biên an toàn để biết mức rẻ có thật sự đáng chú ý không.",
            },
            {
                "title": "Chỉ đẩy tín hiệu đáng kiểm tra",
                "body": "Kết hợp MOS, điểm nguồn, lịch sử giá và dấu hiệu bất thường để xếp hạng tin nên xem trước.",
            },
        ],
        "process_title": "Quy trình lọc tin rẻ thật",
        "process": [
            {
                "title": "1. Đọc tin rao",
                "body": "Tách giá, diện tích, vị trí, loại tài sản và các tín hiệu mô tả quan trọng.",
            },
            {
                "title": "2. Loại nhiễu nguồn",
                "body": "Ẩn tin trùng, tin sai rõ ràng, giá cọc trá hình hoặc mô tả thiếu nhất quán.",
            },
            {
                "title": "3. Ước tính fair value",
                "body": "So sánh với phân khúc tương tự để biết mức giá hợp lý của tài sản.",
            },
            {
                "title": "4. Tính MOS",
                "body": "Đo khoảng chênh giữa giá rao và fair value để ưu tiên cơ hội có biên an toàn.",
            },
            {
                "title": "5. Cảnh báo tin đáng xem",
                "body": "Đưa tin sạch, MOS tốt và phù hợp bộ lọc lên dashboard hoặc thông báo VIP.",
            },
        ],
        "faq": [
            {
                "q": "Tin có MOS cao có chắc là deal tốt không?",
                "a": "Không. MOS là tín hiệu ưu tiên kiểm tra, không phải cam kết lợi nhuận hay thay thế thẩm định thực địa.",
            },
            {
                "q": "Vì sao phải lọc nguồn trước khi định giá?",
                "a": "Nếu dữ liệu đầu vào là mồi giá, sai diện tích hoặc nhầm vị trí thì fair value và MOS đều có thể bị lệch.",
            },
            {
                "q": "Radar BDS xử lý tin trùng như thế nào?",
                "a": "Hệ thống gom lịch sử cùng tin, theo dõi thay đổi giá và hạn chế đẩy các tin đăng lại không tạo tín hiệu mới.",
            },
            {
                "q": "Tôi nên dùng trang này để làm gì?",
                "a": "Dùng để hiểu phương pháp lọc deal của Radar BDS trước khi mở dashboard và tự kiểm tra danh sách tín hiệu.",
            },
        ],
        "final_cta": {
            "title": "Muốn xem bộ lọc deal hoạt động trên dữ liệu thật?",
            "body": "Vào dashboard để xem tin đã qua chuẩn hóa, fair value, MOS và các cảnh báo nguồn cần chú ý.",
            "button": "Xem tín hiệu đang có",
        },
    },
    "bao-cao/bds-binh-duong-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/bds-binh-duong-thang-06-2026',
        "title": 'Báo cáo thị trường BĐS Bình Dương tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS Bình Dương Tháng 06/2026: 4865 tin rao, giá đất nền 22.0 tr/m². Phân tích 13 phường TDM.',
        "keywords": 'báo cáo thị trường BĐS Bình Dương, báo cáo Thủ Dầu Một, tháng 06 2026, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường BĐS Bình Dương Tháng 06/2026',
        "hero_text": 'Báo cáo Tháng 06/2026 tập trung 13 phường Thủ Dầu Một. 4865 tin rao, giá đất nền 22.0 tr/m², 698 tín hiệu.',
        "hero_checks": ['13 phường Thủ Dầu Một', '4.865 tin rao', 'Giá/m² trung vị 22.0 tr/m²'],
        "primary_cta": 'Mở dashboard Radar BDS',
        "secondary_cta": 'Xem hub Bình Dương',
        "secondary_href": '/binh-duong',
        "map_label": 'Report / Bình Dương snapshot',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '13', 'delta': 'phường TDM', 'note': '4865 tin rao, 698 tín hiệu'},
        "property_card": {'status': 'Market report', 'title': 'Bình Dương — snapshot Tháng 06/2026', 'price': 'Nguồn: 4865 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² trung vị', 'metric_a_value': '22.0 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '698'},
        "value_cards": [{'title': 'Chỉ dùng phạm vi đủ dày dữ liệu', 'body': 'Báo cáo tập trung 13 phường Thủ Dầu Một — nhóm có dữ liệu đủ dày để so giá.'}, {'title': 'Đọc theo phường thay vì đọc cả thành phố', 'body': 'Chênh lệch giá/m² giữa các phường TDM khá lớn. Lọc theo ward trước khi kết luận.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Mở dashboard để lọc chi tiết theo từng phường và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: Facebook listings tại 13 phường TDM, đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '4.865', 'note': 'facebook listings tại TDM'}, {'label': 'Giá/m² trung vị', 'value': '22.0 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Phường rẻ nhất', 'value': 'Định Hòa', 'note': '15.2 tr/m²'}, {'label': 'Tổng tín hiệu', 'value': '698', 'note': 'hot + giảm giá toàn TDM'}], 'area_rows': [{'area': 'Hiệp An', 'slug': 'hiep-an', 'new_listings': '646', 'median_price': '16.0', 'drop_signal': '9', 'radar_signal': '56'}, {'area': 'Phú Mỹ', 'slug': 'phu-my', 'new_listings': '605', 'median_price': '23.7', 'drop_signal': '18', 'radar_signal': '98'}, {'area': 'Phú Tân', 'slug': 'phu-tan', 'new_listings': '593', 'median_price': '23.8', 'drop_signal': '5', 'radar_signal': '269'}, {'area': 'Tân An', 'slug': 'tan-an', 'new_listings': '481', 'median_price': '16.9', 'drop_signal': '12', 'radar_signal': '20'}, {'area': 'Định Hòa', 'slug': 'dinh-hoa', 'new_listings': '470', 'median_price': '15.2', 'drop_signal': '5', 'radar_signal': '61'}, {'area': 'Phú Hòa', 'slug': 'phu-hoa', 'new_listings': '456', 'median_price': '26.5', 'drop_signal': '3', 'radar_signal': '19'}, {'area': 'Hiệp Thành', 'slug': 'hiep-thanh', 'new_listings': '433', 'median_price': '23.4', 'drop_signal': '4', 'radar_signal': '34'}, {'area': 'TB Hiệp', 'slug': 'tuong-binh-hiep', 'new_listings': '397', 'median_price': '18.6', 'drop_signal': '2', 'radar_signal': '23'}, {'area': 'Phú Lợi', 'slug': 'phu-loi', 'new_listings': '319', 'median_price': '32.3', 'drop_signal': '10', 'radar_signal': '42'}, {'area': 'Chánh Nghĩa', 'slug': 'chanh-nghia', 'new_listings': '216', 'median_price': '31.8', 'drop_signal': '2', 'radar_signal': '36'}, {'area': 'Chánh Mỹ', 'slug': 'chanh-my', 'new_listings': '153', 'median_price': '24.6', 'drop_signal': '2', 'radar_signal': '10'}, {'area': 'Hòa Phú', 'slug': 'hoa-phu', 'new_listings': '57', 'median_price': '23.7', 'drop_signal': '0', 'radar_signal': '27'}, {'area': 'Phú Cường', 'slug': 'phu-cuong', 'new_listings': '39', 'median_price': '28.9', 'drop_signal': '0', 'radar_signal': '3'}], 'insights': [{'title': 'Phường rẻ nhất: Định Hòa (15.2 tr/m²)', 'body': 'Trong 13 phường TDM, Định Hòa giá thấp nhất 15.2 tr/m². Phú Lợi đắt nhất 32.3 tr/m².'}, {'title': 'Nhiều tín hiệu nhất: Phú Tân', 'body': 'Phú Tân dẫn đầu với 269 tín hiệu.'}, {'title': 'Nhiều giảm giá: Phú Mỹ', 'body': 'Phú Mỹ có 18 tin giảm giá.'}], 'methodology': ['Dữ liệu từ Facebook tại 13 phường TDM trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "local_links_title": '13 phường Thủ Dầu Một',
        "local_links": [{'label': 'Hiệp An', 'href': '/bao-cao/hiep-an-thang-06-2026', 'description': '646 tin rao, giá đất nền 16.0 tr/m²'}, {'label': 'Phú Mỹ', 'href': '/bao-cao/phu-my-thang-06-2026', 'description': '605 tin rao, giá đất nền 23.7 tr/m²'}, {'label': 'Phú Tân', 'href': '/bao-cao/phu-tan-thang-06-2026', 'description': '593 tin rao, giá đất nền 23.8 tr/m²'}, {'label': 'Tân An', 'href': '/bao-cao/tan-an-thang-06-2026', 'description': '481 tin rao, giá đất nền 16.9 tr/m²'}, {'label': 'Định Hòa', 'href': '/bao-cao/dinh-hoa-thang-06-2026', 'description': '470 tin rao, giá đất nền 15.2 tr/m²'}, {'label': 'Phú Hòa', 'href': '/bao-cao/phu-hoa-thang-06-2026', 'description': '456 tin rao, giá đất nền 26.5 tr/m²'}, {'label': 'Hiệp Thành', 'href': '/bao-cao/hiep-thanh-thang-06-2026', 'description': '433 tin rao, giá đất nền 23.4 tr/m²'}, {'label': 'TB Hiệp', 'href': '/bao-cao/tuong-binh-hiep-thang-06-2026', 'description': '397 tin rao, giá đất nền 18.6 tr/m²'}, {'label': 'Phú Lợi', 'href': '/bao-cao/phu-loi-thang-06-2026', 'description': '319 tin rao, giá đất nền 32.3 tr/m²'}, {'label': 'Chánh Nghĩa', 'href': '/bao-cao/chanh-nghia-thang-06-2026', 'description': '216 tin rao, giá đất nền 31.8 tr/m²'}, {'label': 'Chánh Mỹ', 'href': '/bao-cao/chanh-my-thang-06-2026', 'description': '153 tin rao, giá đất nền 24.6 tr/m²'}, {'label': 'Hòa Phú', 'href': '/bao-cao/hoa-phu-thang-06-2026', 'description': '57 tin rao, giá đất nền 23.7 tr/m²'}, {'label': 'Phú Cường', 'href': '/bao-cao/phu-cuong-thang-06-2026', 'description': '39 tin rao, giá đất nền 28.9 tr/m²'}],
        "charts": [{'id': 'ward-supply-chart', 'type': 'bar', 'title': 'Số tin rao theo phường', 'labels': ['Hiệp An', 'Phú Mỹ', 'Phú Tân', 'Tân An', 'Định Hòa', 'Phú Hòa', 'Hiệp Thành', 'TB Hiệp', 'Phú Lợi', 'Chánh Nghĩa', 'Chánh Mỹ', 'Hòa Phú', 'Phú Cường'], 'datasets': [{'label': 'Số tin rao', 'data': [646, 605, 593, 481, 470, 456, 433, 397, 319, 216, 153, 57, 39], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}, {'id': 'ward-price-chart', 'type': 'bar', 'title': 'Giá/m² trung vị theo phường (tr/m²)', 'labels': ['Hiệp An', 'Phú Mỹ', 'Phú Tân', 'Tân An', 'Định Hòa', 'Phú Hòa', 'Hiệp Thành', 'TB Hiệp', 'Phú Lợi', 'Chánh Nghĩa', 'Chánh Mỹ', 'Hòa Phú', 'Phú Cường'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [16.0, 23.7, 23.8, 16.9, 15.2, 26.5, 23.4, 18.6, 32.3, 31.8, 24.6, 23.7, 28.9], 'backgroundColor': '#10b981', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'So sánh tất cả phường TDM — mở dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin theo từng phường, loại hình và ngân sách.', 'button': 'Mở dashboard'}
    },
    "bao-cao/tan-an-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/tan-an-thang-06-2026',
        "title": 'Báo cáo thị trường Tân An Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Tân An, Thủ Dầu Một tháng 06/2026: 16.9 tr/m² đất nền, 481 tin rao, 20 tín hiệu.',
        "keywords": 'báo cáo thị trường Tân An, giá đất Tân An, nhà đất Tân An, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Tân An, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Tân An, phường giá rẻ nhất Thủ Dầu Một. Số liệu thực từ 481 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 16.9 tr/m² (282 tin)', 'Nhà đất: 23.1 tr/m² (165 tin)', 'Nhà trọ: 6.4 tr/m² (3 tin)', '20 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Tân An',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Tân An', 'note': 'chi tiết theo loại hình — 16.9 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Tân An — snapshot Tháng 06/2026', 'price': 'Nguồn: 481 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '16.9 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '20'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Tân An — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Tân An. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Tân An (481 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '481', 'note': 'tin rao Facebook tại Tân An'}, {'label': 'Giá/m² trung vị', 'value': '16.9 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '1.8 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '20', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '282 tin', 'median_price': '16.9 tr/m²', 'drop_signal': '13 tín hiệu', 'radar_signal': '13 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '165 tin', 'median_price': '23.1 tr/m²', 'drop_signal': '7 tín hiệu', 'radar_signal': '7 tín hiệu'}, {'area': 'Nhà trọ', 'new_listings': '3 tin', 'median_price': '6.4 tr/m²', 'drop_signal': '0 tín hiệu', 'radar_signal': '0 tín hiệu'}, {'area': 'Kho xưởng', 'new_listings': '1 tin', 'median_price': '17.5 tr/m²', 'drop_signal': '0 tín hiệu', 'radar_signal': '0 tín hiệu'}], 'insights': [{'title': 'Giá đất nền tăng 14.2% so với tháng trước', 'body': 'Đất nền Tân An Tháng 06/2026 có giá trung vị 16.9 tr/m², tăng 2.1 tr/m² (🔺 14.2%) so với tháng trước (14.8 tr/m²).'}, {'title': 'Nguồn cung tăng 50.8%', 'body': 'Nguồn cung Tân An tháng này tăng 162 tin (50.8%), thị trường đang sôi động.'}, {'title': '20 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 20 tín hiệu (hot + giảm giá) tại Tân An tháng này. 8 tin nóng, 12 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Tân An trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Kho xưởng'], 'datasets': [{'data': [282, 165, 3, 1], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Kho xưởng'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [16.9, 23.1, 6.4, 17.5], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Tân An trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Tân An theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/hiep-an-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/hiep-an-thang-06-2026',
        "title": 'Báo cáo thị trường Hiệp An Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Hiệp An, Thủ Dầu Một tháng 06/2026: 16.0 tr/m² đất nền, 646 tin rao, 56 tín hiệu.',
        "keywords": 'báo cáo thị trường Hiệp An, giá đất Hiệp An, nhà đất Hiệp An, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Hiệp An, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Hiệp An, nguồn cung số 1 Thủ Dầu Một. Số liệu thực từ 646 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 16.0 tr/m² (240 tin)', 'Nhà đất: 21.1 tr/m² (348 tin)', 'Nhà trọ: 26.2 tr/m² (1 tin)', '56 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Hiệp An',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Hiệp An', 'note': 'chi tiết theo loại hình — 16.0 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Hiệp An — snapshot Tháng 06/2026', 'price': 'Nguồn: 646 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '16.0 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '56'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Hiệp An — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Hiệp An. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Hiệp An (646 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '646', 'note': 'tin rao Facebook tại Hiệp An'}, {'label': 'Giá/m² trung vị', 'value': '16.0 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '2.19 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '56', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '240 tin', 'median_price': '16.0 tr/m²', 'drop_signal': '30 tín hiệu', 'radar_signal': '30 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '348 tin', 'median_price': '21.1 tr/m²', 'drop_signal': '26 tín hiệu', 'radar_signal': '26 tín hiệu'}, {'area': 'Nhà trọ', 'new_listings': '1 tin', 'median_price': '26.2 tr/m²', 'drop_signal': '0 tín hiệu', 'radar_signal': '0 tín hiệu'}], 'insights': [{'title': 'Giá đất nền giảm 1.8% so với tháng trước', 'body': 'Đất nền Hiệp An Tháng 06/2026 có giá trung vị 16.0 tr/m², giảm 0.3 tr/m² (🔻 1.8%) so với tháng trước (16.3 tr/m²).'}, {'title': 'Nguồn cung tăng 75.1%', 'body': 'Nguồn cung Hiệp An tháng này tăng 277 tin (75.1%), thị trường đang sôi động.'}, {'title': '56 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 56 tín hiệu (hot + giảm giá) tại Hiệp An tháng này. 47 tin nóng, 9 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Hiệp An trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ'], 'datasets': [{'data': [240, 348, 1], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [16.0, 21.1, 26.2], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Hiệp An trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Hiệp An theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/tuong-binh-hiep-thang-06-2026": {'variant': 'report',
 'path': '/bao-cao/tuong-binh-hiep-thang-06-2026',
 'title': 'Giá đất Tương Bình Hiệp tháng 06/2026: 397 tin rao, đất nền 18.6 tr/m² — Radar BDS',
 'description': 'Báo cáo BĐS Tương Bình Hiệp tháng 06/2026 từ 397 tin rao Facebook: đất nền 18.6 tr/m², nhà đất 30.8 tr/m², tỷ lệ cắt máu '
                '0.3%.',
 'keywords': 'báo cáo thị trường Tương Bình Hiệp, giá đất Tương Bình Hiệp, nhà đất Tương Bình Hiệp, Thủ Dầu Một, radar bds',
 'hero_badge': 'Báo cáo thị trường — Tháng 06/2026',
 'hero_title': 'Giá đất Tương Bình Hiệp tháng 06/2026: đất nền 18.6 tr/m² từ 397 tin rao',
 'hero_text': 'Trong tháng 06/2026, Radar BDS ghi nhận 397 tin rao Facebook tại Tương Bình Hiệp. Giá trung vị đất nền đạt 18.6 tr/m², thấp '
              'hơn mức trung vị Thủ Dầu Một 22.0 tr/m². Nguồn cung tăng mạnh, nhưng tỷ lệ cắt máu vẫn rất thấp.',
 'hero_checks': ['Đất nền: giá trung vị 18.6 tr/m² (155 tin)',
                 'Nhà đất: giá trung vị 30.8 tr/m² (205 tin)',
                 'Tỷ lệ cắt máu 0.3% · Nguồn cung +179.6% MoM'],
 'primary_cta': 'Mở dashboard để lọc tin Tương Bình Hiệp',
 'secondary_cta': 'Xem báo cáo tổng quan',
 'secondary_href': '/bao-cao/bds-binh-duong-thang-06-2026',
 'map_label': 'Report / Tương Bình Hiệp',
 'hero_metric': {'label': 'Phạm vi báo cáo',
                 'value': '1 phường',
                 'delta': 'Tương Bình Hiệp',
                 'note': 'chi tiết theo loại hình — 18.6 tr/m² đất nền'},
 'property_card': {'status': 'Market report',
                   'title': 'Tương Bình Hiệp — snapshot Tháng 06/2026',
                   'price': '397 tin rao Facebook đã lọc theo tháng',
                   'metric_a': 'Giá trung vị đất nền',
                   'metric_a_value': '18.6 tr/m²',
                   'metric_b': 'Cắt máu',
                   'metric_b_value': '0.3%'},
 'value_cards': [{'title': 'Đọc theo xu hướng, không chỉ nhìn 1 tháng',
                  'body': 'Báo cáo bổ sung đường giá 6 tháng để thấy tháng 06 tăng sau giai đoạn tháng 04-05 đi ngang ở nhóm đất nền.'},
                 {'title': 'Tách đất nền và nhà đất để tránh so sai',
                  'body': 'Đất nền có giá trung vị 18.6 tr/m², trong khi nhà đất là 30.8 tr/m². Hai loại hình cần đọc riêng.'},
                 {'title': 'Có thêm chỉ báo cắt máu và bất thường nguồn cung',
                  'body': 'Nguồn cung tăng rất mạnh, nhưng tỷ lệ tin giảm giá vẫn thấp. Đây là tín hiệu sôi động hơn, chưa phải bán tháo '
                          'diện rộng.'}],
 'report': {'period': 'Tháng 06/2026',
            'published_at': '2026-07-09',
            'updated_label': 'Cập nhật Tháng 06/2026',
            'source_note': 'Nguồn: tin rao Facebook tại Tương Bình Hiệp trong tháng 06/2026, đã lọc blacklist, hidden, outlier theo dữ '
                           'liệu Radar BDS.',
            'metrics': [{'label': 'Tin rao trong tháng', 'value': '397', 'note': 'tin Facebook tại Tương Bình Hiệp sau lọc'},
                        {'label': 'Giá trung vị đất nền', 'value': '18.6 tr/m²', 'note': '155 tin đất nền đủ dữ liệu giá/m²'},
                        {'label': 'Giá trung vị nhà đất', 'value': '30.8 tr/m²', 'note': '205 tin nhà đất đủ dữ liệu giá/m²'},
                        {'label': 'Dấu hiệu đáng chú ý', 'value': '22', 'note': '21 tin nóng + 1 tin giảm giá'}],
            'indicators': [{'label': 'Xu hướng giá đất nền',
                            'value': '+6.3%',
                            'status': 'Tăng nhẹ',
                            'note': 'Giá trung vị đất nền đi từ 17.5 tr/m² tháng 05 lên 18.6 tr/m² tháng 06.'},
                           {'label': 'Tỷ lệ cắt máu',
                            'value': '0.3%',
                            'status': 'Rất thấp',
                            'note': '1/397 tin có dấu hiệu giảm giá; chưa phải tín hiệu bán tháo diện rộng.'},
                           {'label': 'Bất thường nguồn cung',
                            'value': '+179.6%',
                            'status': 'Rất cao',
                            'note': 'Nguồn cung tăng từ 142 tin tháng 05 lên 397 tin tháng 06, thêm 255 tin.'}],
            'trend_intro': ['Dữ liệu đủ để đọc xu hướng tại Tương Bình Hiệp bắt đầu rõ từ tháng 04/2026; ba tháng 01-03 chưa có tin rao đủ '
                            'điều kiện sau lọc nên không nội suy giá.',
                            'Từ tháng 04 đến tháng 06, giá trung vị đất nền đi ngang ở 17.5 tr/m² trong tháng 04-05, sau đó lên 18.6 tr/m² '
                            'trong tháng 06. Nhà đất biến động mạnh hơn: 29.4 → 27.4 → 30.8 tr/m².'],
            'trend_rows': [{'month': '01/2026',
                            'total': '0',
                            'dat_nen_count': '0',
                            'dat_nen_price': 'Chưa đủ dữ liệu',
                            'nha_dat_count': '0',
                            'nha_dat_price': 'Chưa đủ dữ liệu',
                            'hot': '0',
                            'dropped': '0',
                            'signals': '0'},
                           {'month': '02/2026',
                            'total': '0',
                            'dat_nen_count': '0',
                            'dat_nen_price': 'Chưa đủ dữ liệu',
                            'nha_dat_count': '0',
                            'nha_dat_price': 'Chưa đủ dữ liệu',
                            'hot': '0',
                            'dropped': '0',
                            'signals': '0'},
                           {'month': '03/2026',
                            'total': '0',
                            'dat_nen_count': '0',
                            'dat_nen_price': 'Chưa đủ dữ liệu',
                            'nha_dat_count': '0',
                            'nha_dat_price': 'Chưa đủ dữ liệu',
                            'hot': '0',
                            'dropped': '0',
                            'signals': '0'},
                           {'month': '04/2026',
                            'total': '75',
                            'dat_nen_count': '38',
                            'dat_nen_price': '17.5 tr/m²',
                            'nha_dat_count': '37',
                            'nha_dat_price': '29.4 tr/m²',
                            'hot': '8',
                            'dropped': '0',
                            'signals': '8'},
                           {'month': '05/2026',
                            'total': '142',
                            'dat_nen_count': '92',
                            'dat_nen_price': '17.5 tr/m²',
                            'nha_dat_count': '48',
                            'nha_dat_price': '27.4 tr/m²',
                            'hot': '2',
                            'dropped': '3',
                            'signals': '5'},
                           {'month': '06/2026',
                            'total': '397',
                            'dat_nen_count': '155',
                            'dat_nen_price': '18.6 tr/m²',
                            'nha_dat_count': '205',
                            'nha_dat_price': '30.8 tr/m²',
                            'hot': '21',
                            'dropped': '1',
                            'signals': '22'}],
            'area_rows': [{'area': 'Đất nền',
                           'new_listings': '155 tin',
                           'median_price': '18.6 tr/m²',
                           'drop_signal': '1 tin giảm giá',
                           'radar_signal': '3 dấu hiệu'},
                          {'area': 'Nhà đất',
                           'new_listings': '205 tin',
                           'median_price': '30.8 tr/m²',
                           'drop_signal': '0 tin giảm giá',
                           'radar_signal': '19 dấu hiệu'}],
            'comparison_rows': [{'area': 'Hiệp An', 'new_listings': '646', 'median_price': '16.0 tr/m²', 'radar_signal': '56'},
                                {'area': 'Phú Mỹ', 'new_listings': '605', 'median_price': '23.7 tr/m²', 'radar_signal': '98'},
                                {'area': 'Tân An', 'new_listings': '481', 'median_price': '16.9 tr/m²', 'radar_signal': '20'},
                                {'area': 'Định Hòa', 'new_listings': '470', 'median_price': '15.2 tr/m²', 'radar_signal': '61'},
                                {'area': 'Hiệp Thành', 'new_listings': '433', 'median_price': '23.4 tr/m²', 'radar_signal': '34'},
                                {'area': 'Tương Bình Hiệp', 'new_listings': '397', 'median_price': '18.6 tr/m²', 'radar_signal': '22'}],
            'insights': [{'title': 'Giá đất nền tăng nhưng vẫn dưới mặt bằng trung vị Thủ Dầu Một',
                          'body': 'Giá trung vị đất nền Tương Bình Hiệp tăng 6.3% so với tháng 05, từ 17.5 lên 18.6 tr/m². Mức này vẫn '
                                  'thấp hơn giá trung vị đất nền Thủ Dầu Một tháng 06 là 22.0 tr/m², nên khu vực này còn đáng theo dõi nếu '
                                  'người mua ưu tiên ngân sách vừa phải.'},
                         {'title': 'Nguồn cung tăng bất thường, cần lọc kỹ chất lượng từng tin',
                          'body': 'Số tin rao tăng từ 142 lên 397 tin, tức +179.6% so với tháng trước. Nhiều tin hơn giúp người mua có '
                                  'thêm lựa chọn, nhưng cũng làm chất lượng tin không đồng đều hơn. Cần tách loại hình, vị trí, pháp lý và '
                                  'quy hoạch trước khi so giá.'},
                         {'title': 'Tỷ lệ cắt máu rất thấp, chưa phải bán tháo diện rộng',
                          'body': 'Tháng 06 chỉ ghi nhận 1 tin có dấu hiệu giảm giá trên 397 tin, tương đương khoảng 0.3%. Nguồn cung tăng '
                                  'mạnh nhưng tin giảm giá công khai vẫn ít, nên dữ liệu nghiêng về trạng thái thị trường sôi động hơn '
                                  'thay vì xả hàng hàng loạt.'}],
            'methodology': ['Dữ liệu từ tin rao Facebook tại Tương Bình Hiệp trong Tháng 06/2026, lọc theo crawled_at trong tháng.',
                            'Giá trung vị được tính bằng PERCENTILE_CONT(0.5): một nửa số tin thấp hơn mức này, một nửa cao hơn.',
                            'Đã loại tin blacklist, hidden và outlier theo bộ lọc Radar BDS.',
                            'Tỷ lệ cắt máu = số tin có dấu hiệu giảm giá / tổng số tin rao trong tháng.',
                            'Bất thường nguồn cung = mức tăng/giảm số tin rao so với tháng trước và nhóm tháng gần nhất có dữ liệu.',
                            'Radar BDS là bộ lọc dữ liệu ban đầu, không thay thẩm định pháp lý, quy hoạch hay cam kết lợi nhuận.']},
 'charts': [{'id': 'price-trend-6m-chart',
             'type': 'line',
             'title': 'Biểu đồ Xu hướng Giá (6 tháng gần nhất)',
             'wide': True,
             'legend': True,
             'labels': ['01/2026', '02/2026', '03/2026', '04/2026', '05/2026', '06/2026'],
             'datasets': [{'label': 'Đất nền (tr/m²)',
                           'data': [None, None, None, 17.5, 17.5, 18.6],
                           'borderColor': '#0f766e',
                           'backgroundColor': 'rgba(15, 118, 110, 0.14)',
                           'pointBackgroundColor': '#0f766e',
                           'borderWidth': 3,
                           'tension': 0.25,
                           'spanGaps': False},
                          {'label': 'Nhà đất (tr/m²)',
                           'data': [None, None, None, 29.4, 27.4, 30.8],
                           'borderColor': '#f97316',
                           'backgroundColor': 'rgba(249, 115, 22, 0.14)',
                           'pointBackgroundColor': '#f97316',
                           'borderWidth': 3,
                           'tension': 0.25,
                           'spanGaps': False}],
             'options': {'scales': {'y': {'beginAtZero': False,
                                          'suggestedMin': 10,
                                          'suggestedMax': 35,
                                          'title': {'display': True, 'text': 'triệu đồng/m²'},
                                          'grid': {'color': '#e2e8f0'}},
                                    'x': {'grid': {'display': False}}}}},
            {'id': 'type-dist-chart',
             'type': 'doughnut',
             'title': 'Phân bố loại hình',
             'legend': True,
             'labels': ['Đất nền', 'Nhà đất'],
             'datasets': [{'data': [155, 205], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]},
            {'id': 'type-price-chart',
             'type': 'bar',
             'title': 'Giá trung vị theo loại hình (tr/m²)',
             'labels': ['Đất nền', 'Nhà đất'],
             'datasets': [{'label': 'Giá trung vị (tr/m²)', 'data': [18.6, 30.8], 'backgroundColor': '#3b82f6', 'borderRadius': 3}],
             'legend': False}],
 'final_cta': {'title': 'Lọc tin Tương Bình Hiệp bằng dashboard Radar BDS',
               'body': 'Dùng báo cáo này làm bước sàng lọc ban đầu, sau đó mở dashboard để xem từng tin theo loại hình, giá/m², dấu hiệu '
                       'nóng và tin giảm giá.',
               'button': 'Mở dashboard'},
 'scope_label': 'Tương Bình Hiệp'},
    "bao-cao/dinh-hoa-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/dinh-hoa-thang-06-2026',
        "title": 'Báo cáo thị trường Định Hòa Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Định Hòa, Thủ Dầu Một tháng 06/2026: 15.2 tr/m² đất nền, 470 tin rao, 61 tín hiệu.',
        "keywords": 'báo cáo thị trường Định Hòa, giá đất Định Hòa, nhà đất Định Hòa, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Định Hòa, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Định Hòa, phường Định Hòa. Số liệu thực từ 470 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 15.2 tr/m² (274 tin)', 'Nhà đất: 34.9 tr/m² (110 tin)', 'Nhà trọ: 12.4 tr/m² (2 tin)', '61 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Định Hòa',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Định Hòa', 'note': 'chi tiết theo loại hình — 15.2 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Định Hòa — snapshot Tháng 06/2026', 'price': 'Nguồn: 470 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '15.2 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '61'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Định Hòa — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Định Hòa. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Định Hòa (470 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '470', 'note': 'tin rao Facebook tại Định Hòa'}, {'label': 'Giá/m² trung vị', 'value': '15.2 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '2.38 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '61', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '274 tin', 'median_price': '15.2 tr/m²', 'drop_signal': '48 tín hiệu', 'radar_signal': '48 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '110 tin', 'median_price': '34.9 tr/m²', 'drop_signal': '11 tín hiệu', 'radar_signal': '11 tín hiệu'}, {'area': 'Nhà trọ', 'new_listings': '2 tin', 'median_price': '12.4 tr/m²', 'drop_signal': '1 tín hiệu', 'radar_signal': '1 tín hiệu'}, {'area': 'Kho xưởng', 'new_listings': '3 tin', 'median_price': '38.9 tr/m²', 'drop_signal': '0 tín hiệu', 'radar_signal': '0 tín hiệu'}], 'insights': [{'title': 'Giá đất nền tăng 17.8% so với tháng trước', 'body': 'Đất nền Định Hòa Tháng 06/2026 có giá trung vị 15.2 tr/m², tăng 2.3 tr/m² (🔺 17.8%) so với tháng trước (12.9 tr/m²).'}, {'title': 'Nguồn cung tăng 213.3%', 'body': 'Nguồn cung Định Hòa tháng này tăng 320 tin (213.3%), thị trường đang sôi động.'}, {'title': '61 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 61 tín hiệu (hot + giảm giá) tại Định Hòa tháng này. 58 tin nóng, 5 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Định Hòa trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Kho xưởng'], 'datasets': [{'data': [274, 110, 2, 3], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Kho xưởng'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [15.2, 34.9, 12.4, 38.9], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Định Hòa trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Định Hòa theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/chanh-my-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/chanh-my-thang-06-2026',
        "title": 'Báo cáo thị trường Chánh Mỹ Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Chánh Mỹ, Thủ Dầu Một tháng 06/2026: 24.6 tr/m² đất nền, 153 tin rao, 10 tín hiệu.',
        "keywords": 'báo cáo thị trường Chánh Mỹ, giá đất Chánh Mỹ, nhà đất Chánh Mỹ, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Chánh Mỹ, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Chánh Mỹ, phường Chánh Mỹ. Số liệu thực từ 153 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 24.6 tr/m² (85 tin)', 'Nhà đất: 36.2 tr/m² (38 tin)', '10 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Chánh Mỹ',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Chánh Mỹ', 'note': 'chi tiết theo loại hình — 24.6 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Chánh Mỹ — snapshot Tháng 06/2026', 'price': 'Nguồn: 153 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '24.6 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '10'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Chánh Mỹ — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Chánh Mỹ. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Chánh Mỹ (153 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '153', 'note': 'tin rao Facebook tại Chánh Mỹ'}, {'label': 'Giá/m² trung vị', 'value': '24.6 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '2.15 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '10', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '85 tin', 'median_price': '24.6 tr/m²', 'drop_signal': '6 tín hiệu', 'radar_signal': '6 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '38 tin', 'median_price': '36.2 tr/m²', 'drop_signal': '4 tín hiệu', 'radar_signal': '4 tín hiệu'}], 'insights': [{'title': 'Giá đất nền giảm 1.2% so với tháng trước', 'body': 'Đất nền Chánh Mỹ Tháng 06/2026 có giá trung vị 24.6 tr/m², giảm 0.3 tr/m² (🔻 1.2%) so với tháng trước (24.9 tr/m²).'}, {'title': 'Nguồn cung tăng 163.8%', 'body': 'Nguồn cung Chánh Mỹ tháng này tăng 95 tin (163.8%), thị trường đang sôi động.'}, {'title': '10 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 10 tín hiệu (hot + giảm giá) tại Chánh Mỹ tháng này. 8 tin nóng, 2 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Chánh Mỹ trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất'], 'datasets': [{'data': [85, 38], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [24.6, 36.2], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Chánh Mỹ trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Chánh Mỹ theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/phu-my-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/phu-my-thang-06-2026',
        "title": 'Báo cáo thị trường Phú Mỹ Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Phú Mỹ, Thủ Dầu Một tháng 06/2026: 23.7 tr/m² đất nền, 605 tin rao, 98 tín hiệu.',
        "keywords": 'báo cáo thị trường Phú Mỹ, giá đất Phú Mỹ, nhà đất Phú Mỹ, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Phú Mỹ, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Phú Mỹ, phường ven sông Sài Gòn. Số liệu thực từ 605 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 23.7 tr/m² (228 tin)', 'Nhà đất: 39.4 tr/m² (263 tin)', 'Nhà trọ: 30.0 tr/m² (1 tin)', '98 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Phú Mỹ',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Phú Mỹ', 'note': 'chi tiết theo loại hình — 23.7 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Phú Mỹ — snapshot Tháng 06/2026', 'price': 'Nguồn: 605 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '23.7 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '98'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Phú Mỹ — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Phú Mỹ. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Phú Mỹ (605 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '605', 'note': 'tin rao Facebook tại Phú Mỹ'}, {'label': 'Giá/m² trung vị', 'value': '23.7 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '3.0 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '98', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '228 tin', 'median_price': '23.7 tr/m²', 'drop_signal': '67 tín hiệu', 'radar_signal': '67 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '263 tin', 'median_price': '39.4 tr/m²', 'drop_signal': '30 tín hiệu', 'radar_signal': '30 tín hiệu'}, {'area': 'Nhà trọ', 'new_listings': '1 tin', 'median_price': '30.0 tr/m²', 'drop_signal': '0 tín hiệu', 'radar_signal': '0 tín hiệu'}, {'area': 'Kho xưởng', 'new_listings': '4 tin', 'median_price': '25.8 tr/m²', 'drop_signal': '1 tín hiệu', 'radar_signal': '1 tín hiệu'}], 'insights': [{'title': 'Giá đất nền tăng 21.5% so với tháng trước', 'body': 'Đất nền Phú Mỹ Tháng 06/2026 có giá trung vị 23.7 tr/m², tăng 4.2 tr/m² (🔺 21.5%) so với tháng trước (19.5 tr/m²).'}, {'title': 'Nguồn cung tăng 1041.5%', 'body': 'Nguồn cung Phú Mỹ tháng này tăng 552 tin (1041.5%), thị trường đang sôi động.'}, {'title': '98 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 98 tín hiệu (hot + giảm giá) tại Phú Mỹ tháng này. 88 tin nóng, 18 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Phú Mỹ trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Kho xưởng'], 'datasets': [{'data': [228, 263, 1, 4], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Kho xưởng'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [23.7, 39.4, 30.0, 25.8], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Phú Mỹ trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Phú Mỹ theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/phu-cuong-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/phu-cuong-thang-06-2026',
        "title": 'Báo cáo thị trường Phú Cường Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Phú Cường, Thủ Dầu Một tháng 06/2026: 28.9 tr/m² đất nền, 39 tin rao, 3 tín hiệu.',
        "keywords": 'báo cáo thị trường Phú Cường, giá đất Phú Cường, nhà đất Phú Cường, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Phú Cường, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Phú Cường, phường Phú Cường. Số liệu thực từ 39 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 28.9 tr/m² (16 tin)', 'Nhà đất: 33.2 tr/m² (12 tin)', '3 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Phú Cường',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Phú Cường', 'note': 'chi tiết theo loại hình — 28.9 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Phú Cường — snapshot Tháng 06/2026', 'price': 'Nguồn: 39 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '28.9 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '3'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Phú Cường — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Phú Cường. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Phú Cường (39 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '39', 'note': 'tin rao Facebook tại Phú Cường'}, {'label': 'Giá/m² trung vị', 'value': '28.9 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '2.5 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '3', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '16 tin', 'median_price': '28.9 tr/m²', 'drop_signal': '2 tín hiệu', 'radar_signal': '2 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '12 tin', 'median_price': '33.2 tr/m²', 'drop_signal': '1 tín hiệu', 'radar_signal': '1 tín hiệu'}], 'insights': [{'title': 'Giá đất nền tăng 189.0% so với tháng trước', 'body': 'Đất nền Phú Cường Tháng 06/2026 có giá trung vị 28.9 tr/m², tăng 18.9 tr/m² (🔺 189.0%) so với tháng trước (10.0 tr/m²).'}, {'title': 'Nguồn cung tăng 457.1%', 'body': 'Nguồn cung Phú Cường tháng này tăng 32 tin (457.1%), thị trường đang sôi động.'}, {'title': '3 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 3 tín hiệu (hot + giảm giá) tại Phú Cường tháng này. 3 tin nóng, 0 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Phú Cường trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất'], 'datasets': [{'data': [16, 12], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [28.9, 33.2], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Phú Cường trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Phú Cường theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/phu-hoa-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/phu-hoa-thang-06-2026',
        "title": 'Báo cáo thị trường Phú Hòa Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Phú Hòa, Thủ Dầu Một tháng 06/2026: 26.5 tr/m² đất nền, 456 tin rao, 19 tín hiệu.',
        "keywords": 'báo cáo thị trường Phú Hòa, giá đất Phú Hòa, nhà đất Phú Hòa, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Phú Hòa, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Phú Hòa, phường Phú Hòa. Số liệu thực từ 456 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 26.5 tr/m² (148 tin)', 'Nhà đất: 38.5 tr/m² (196 tin)', 'Nhà trọ: 23.3 tr/m² (7 tin)', '19 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Phú Hòa',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Phú Hòa', 'note': 'chi tiết theo loại hình — 26.5 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Phú Hòa — snapshot Tháng 06/2026', 'price': 'Nguồn: 456 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '26.5 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '19'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Phú Hòa — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Phú Hòa. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Phú Hòa (456 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '456', 'note': 'tin rao Facebook tại Phú Hòa'}, {'label': 'Giá/m² trung vị', 'value': '26.5 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '2.79 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '19', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '148 tin', 'median_price': '26.5 tr/m²', 'drop_signal': '6 tín hiệu', 'radar_signal': '6 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '196 tin', 'median_price': '38.5 tr/m²', 'drop_signal': '12 tín hiệu', 'radar_signal': '12 tín hiệu'}, {'area': 'Nhà trọ', 'new_listings': '7 tin', 'median_price': '23.3 tr/m²', 'drop_signal': '1 tín hiệu', 'radar_signal': '1 tín hiệu'}, {'area': 'Kho xưởng', 'new_listings': '1 tin', 'median_price': '5.6 tr/m²', 'drop_signal': '0 tín hiệu', 'radar_signal': '0 tín hiệu'}], 'insights': [{'title': 'Giá đất nền tăng 3.9% so với tháng trước', 'body': 'Đất nền Phú Hòa Tháng 06/2026 có giá trung vị 26.5 tr/m², tăng 1.0 tr/m² (🔺 3.9%) so với tháng trước (25.5 tr/m²).'}, {'title': 'Nguồn cung tăng 812.0%', 'body': 'Nguồn cung Phú Hòa tháng này tăng 406 tin (812.0%), thị trường đang sôi động.'}, {'title': '19 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 19 tín hiệu (hot + giảm giá) tại Phú Hòa tháng này. 17 tin nóng, 3 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Phú Hòa trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Kho xưởng'], 'datasets': [{'data': [148, 196, 7, 1], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Kho xưởng'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [26.5, 38.5, 23.3, 5.6], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Phú Hòa trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Phú Hòa theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/phu-loi-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/phu-loi-thang-06-2026',
        "title": 'Báo cáo thị trường Phú Lợi Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Phú Lợi, Thủ Dầu Một tháng 06/2026: 32.3 tr/m² đất nền, 319 tin rao, 42 tín hiệu.',
        "keywords": 'báo cáo thị trường Phú Lợi, giá đất Phú Lợi, nhà đất Phú Lợi, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Phú Lợi, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Phú Lợi, phường Phú Lợi. Số liệu thực từ 319 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 32.3 tr/m² (117 tin)', 'Nhà đất: 41.3 tr/m² (105 tin)', 'Nhà trọ: 27.5 tr/m² (2 tin)', '42 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Phú Lợi',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Phú Lợi', 'note': 'chi tiết theo loại hình — 32.3 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Phú Lợi — snapshot Tháng 06/2026', 'price': 'Nguồn: 319 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '32.3 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '42'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Phú Lợi — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Phú Lợi. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Phú Lợi (319 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '319', 'note': 'tin rao Facebook tại Phú Lợi'}, {'label': 'Giá/m² trung vị', 'value': '32.3 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '3.49 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '42', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '117 tin', 'median_price': '32.3 tr/m²', 'drop_signal': '26 tín hiệu', 'radar_signal': '26 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '105 tin', 'median_price': '41.3 tr/m²', 'drop_signal': '16 tín hiệu', 'radar_signal': '16 tín hiệu'}, {'area': 'Nhà trọ', 'new_listings': '2 tin', 'median_price': '27.5 tr/m²', 'drop_signal': '0 tín hiệu', 'radar_signal': '0 tín hiệu'}, {'area': 'Chung cư', 'new_listings': '1 tin', 'median_price': '36.5 tr/m²', 'drop_signal': '0 tín hiệu', 'radar_signal': '0 tín hiệu'}], 'insights': [{'title': 'Giá đất nền tăng 49.5% so với tháng trước', 'body': 'Đất nền Phú Lợi Tháng 06/2026 có giá trung vị 32.3 tr/m², tăng 10.7 tr/m² (🔺 49.5%) so với tháng trước (21.6 tr/m²).'}, {'title': 'Nguồn cung tăng 1176.0%', 'body': 'Nguồn cung Phú Lợi tháng này tăng 294 tin (1176.0%), thị trường đang sôi động.'}, {'title': '42 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 42 tín hiệu (hot + giảm giá) tại Phú Lợi tháng này. 36 tin nóng, 10 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Phú Lợi trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Chung cư'], 'datasets': [{'data': [117, 105, 2, 1], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Chung cư'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [32.3, 41.3, 27.5, 36.5], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Phú Lợi trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Phú Lợi theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/hiep-thanh-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/hiep-thanh-thang-06-2026',
        "title": 'Báo cáo thị trường Hiệp Thành Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Hiệp Thành, Thủ Dầu Một tháng 06/2026: 23.4 tr/m² đất nền, 433 tin rao, 34 tín hiệu.',
        "keywords": 'báo cáo thị trường Hiệp Thành, giá đất Hiệp Thành, nhà đất Hiệp Thành, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Hiệp Thành, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Hiệp Thành, phường Hiệp Thành. Số liệu thực từ 433 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 23.4 tr/m² (83 tin)', 'Nhà đất: 38.9 tr/m² (211 tin)', 'Chung cư: 23.0 tr/m² (3 tin)', '34 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Hiệp Thành',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Hiệp Thành', 'note': 'chi tiết theo loại hình — 23.4 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Hiệp Thành — snapshot Tháng 06/2026', 'price': 'Nguồn: 433 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '23.4 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '34'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Hiệp Thành — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Hiệp Thành. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Hiệp Thành (433 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '433', 'note': 'tin rao Facebook tại Hiệp Thành'}, {'label': 'Giá/m² trung vị', 'value': '23.4 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '3.4 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '34', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '83 tin', 'median_price': '23.4 tr/m²', 'drop_signal': '9 tín hiệu', 'radar_signal': '9 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '211 tin', 'median_price': '38.9 tr/m²', 'drop_signal': '25 tín hiệu', 'radar_signal': '25 tín hiệu'}, {'area': 'Chung cư', 'new_listings': '3 tin', 'median_price': '23.0 tr/m²', 'drop_signal': '0 tín hiệu', 'radar_signal': '0 tín hiệu'}], 'insights': [{'title': 'Giá đất nền giảm 15.2% so với tháng trước', 'body': 'Đất nền Hiệp Thành Tháng 06/2026 có giá trung vị 23.4 tr/m², giảm 4.2 tr/m² (🔻 15.2%) so với tháng trước (27.6 tr/m²).'}, {'title': 'Nguồn cung tăng 1446.4%', 'body': 'Nguồn cung Hiệp Thành tháng này tăng 405 tin (1446.4%), thị trường đang sôi động.'}, {'title': '34 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 34 tín hiệu (hot + giảm giá) tại Hiệp Thành tháng này. 30 tin nóng, 4 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Hiệp Thành trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất', 'Chung cư'], 'datasets': [{'data': [83, 211, 3], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất', 'Chung cư'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [23.4, 38.9, 23.0], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Hiệp Thành trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Hiệp Thành theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/chanh-nghia-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/chanh-nghia-thang-06-2026',
        "title": 'Báo cáo thị trường Chánh Nghĩa Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Chánh Nghĩa, Thủ Dầu Một tháng 06/2026: 31.8 tr/m² đất nền, 216 tin rao, 36 tín hiệu.',
        "keywords": 'báo cáo thị trường Chánh Nghĩa, giá đất Chánh Nghĩa, nhà đất Chánh Nghĩa, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Chánh Nghĩa, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Chánh Nghĩa, phường Chánh Nghĩa. Số liệu thực từ 216 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 31.8 tr/m² (67 tin)', 'Nhà đất: 45.9 tr/m² (93 tin)', 'Chung cư: 28.1 tr/m² (1 tin)', '36 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Chánh Nghĩa',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Chánh Nghĩa', 'note': 'chi tiết theo loại hình — 31.8 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Chánh Nghĩa — snapshot Tháng 06/2026', 'price': 'Nguồn: 216 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '31.8 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '36'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Chánh Nghĩa — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Chánh Nghĩa. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Chánh Nghĩa (216 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '216', 'note': 'tin rao Facebook tại Chánh Nghĩa'}, {'label': 'Giá/m² trung vị', 'value': '31.8 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '2.49 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '36', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '67 tin', 'median_price': '31.8 tr/m²', 'drop_signal': '11 tín hiệu', 'radar_signal': '11 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '93 tin', 'median_price': '45.9 tr/m²', 'drop_signal': '25 tín hiệu', 'radar_signal': '25 tín hiệu'}, {'area': 'Chung cư', 'new_listings': '1 tin', 'median_price': '28.1 tr/m²', 'drop_signal': '0 tín hiệu', 'radar_signal': '0 tín hiệu'}], 'insights': [{'title': 'Giá đất nền tăng 144.6% so với tháng trước', 'body': 'Đất nền Chánh Nghĩa Tháng 06/2026 có giá trung vị 31.8 tr/m², tăng 18.8 tr/m² (🔺 144.6%) so với tháng trước (13.0 tr/m²).'}, {'title': 'Nguồn cung tăng 1863.6%', 'body': 'Nguồn cung Chánh Nghĩa tháng này tăng 205 tin (1863.6%), thị trường đang sôi động.'}, {'title': '36 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 36 tín hiệu (hot + giảm giá) tại Chánh Nghĩa tháng này. 35 tin nóng, 2 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Chánh Nghĩa trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất', 'Chung cư'], 'datasets': [{'data': [67, 93, 1], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất', 'Chung cư'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [31.8, 45.9, 28.1], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Chánh Nghĩa trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Chánh Nghĩa theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/phu-tan-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/phu-tan-thang-06-2026',
        "title": 'Báo cáo thị trường Phú Tân Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Phú Tân, Thủ Dầu Một tháng 06/2026: 23.8 tr/m² đất nền, 593 tin rao, 269 tín hiệu.',
        "keywords": 'báo cáo thị trường Phú Tân, giá đất Phú Tân, nhà đất Phú Tân, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Phú Tân, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Phú Tân, phường Phú Tân. Số liệu thực từ 593 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 23.8 tr/m² (318 tin)', 'Nhà đất: 34.8 tr/m² (49 tin)', 'Nhà trọ: 20.0 tr/m² (1 tin)', '269 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Phú Tân',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Phú Tân', 'note': 'chi tiết theo loại hình — 23.8 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Phú Tân — snapshot Tháng 06/2026', 'price': 'Nguồn: 593 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '23.8 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '269'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Phú Tân — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Phú Tân. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Phú Tân (593 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '593', 'note': 'tin rao Facebook tại Phú Tân'}, {'label': 'Giá/m² trung vị', 'value': '23.8 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '2.9 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '269', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '318 tin', 'median_price': '23.8 tr/m²', 'drop_signal': '206 tín hiệu', 'radar_signal': '206 tín hiệu'}, {'area': 'Nhà đất', 'new_listings': '49 tin', 'median_price': '34.8 tr/m²', 'drop_signal': '33 tín hiệu', 'radar_signal': '33 tín hiệu'}, {'area': 'Nhà trọ', 'new_listings': '1 tin', 'median_price': '20.0 tr/m²', 'drop_signal': '1 tín hiệu', 'radar_signal': '1 tín hiệu'}, {'area': 'Kho xưởng', 'new_listings': '44 tin', 'median_price': '38.7 tr/m²', 'drop_signal': '10 tín hiệu', 'radar_signal': '10 tín hiệu'}, {'area': 'Chung cư', 'new_listings': '3 tin', 'median_price': '23.7 tr/m²', 'drop_signal': '19 tín hiệu', 'radar_signal': '19 tín hiệu'}], 'insights': [{'title': 'Giá đất nền Phú Tân: 23.8 tr/m²', 'body': 'Đất nền Phú Tân Tháng 06/2026 có giá trung vị 23.8 tr/m².'}, {'title': 'Nguồn cung tăng 19666.7%', 'body': 'Nguồn cung Phú Tân tháng này tăng 590 tin (19666.7%), thị trường đang sôi động.'}, {'title': '269 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 269 tín hiệu (hot + giảm giá) tại Phú Tân tháng này. 265 tin nóng, 5 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Phú Tân trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Kho xưởng', 'Chung cư'], 'datasets': [{'data': [318, 49, 1, 44, 3], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền', 'Nhà đất', 'Nhà trọ', 'Kho xưởng', 'Chung cư'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [23.8, 34.8, 20.0, 38.7, 23.7], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Phú Tân trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Phú Tân theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
    "bao-cao/hoa-phu-thang-06-2026": {
        "variant": 'report',
        "path": '/bao-cao/hoa-phu-thang-06-2026',
        "title": 'Báo cáo thị trường Hòa Phú Thủ Dầu Một tháng 06/2026 — Radar BDS',
        "description": 'Báo cáo thị trường BĐS phường Hòa Phú, Thủ Dầu Một tháng 06/2026: 23.7 tr/m² đất nền, 57 tin rao, 27 tín hiệu.',
        "keywords": 'báo cáo thị trường Hòa Phú, giá đất Hòa Phú, nhà đất Hòa Phú, Thủ Dầu Một, radar bds',
        "hero_badge": 'Báo cáo thị trường — Tháng 06/2026',
        "hero_title": 'Báo cáo thị trường phường Hòa Phú, Thủ Dầu Một Tháng 06/2026',
        "hero_text": 'Báo cáo chi tiết thị trường BĐS phường Hòa Phú, phường Hòa Phú. Số liệu thực từ 57 tin rao Facebook trong tháng.',
        "hero_checks": ['Đất nền: 23.7 tr/m² (27 tin)', '27 tín hiệu đáng chú ý'],
        "primary_cta": 'Mở dashboard để lọc bộ lọc',
        "secondary_cta": 'Xem báo cáo tổng quan',
        "secondary_href": '/bao-cao/bds-binh-duong-thang-06-2026',
        "map_label": 'Report / Hòa Phú',
        "hero_metric": {'label': 'Phạm vi báo cáo', 'value': '1 phường', 'delta': 'Hòa Phú', 'note': 'chi tiết theo loại hình — 23.7 tr/m² đất nền'},
        "property_card": {'status': 'Market report', 'title': 'Hòa Phú — snapshot Tháng 06/2026', 'price': 'Nguồn: 57 tin rao + định giá + tín hiệu', 'metric_a': 'Giá/m² đất nền', 'metric_a_value': '23.7 tr/m²', 'metric_b': 'Tín hiệu', 'metric_b_value': '27'},
        "value_cards": [{'title': 'Chỉ dùng dữ liệu Hòa Phú — không so chéo phường', 'body': 'Báo cáo này chỉ tập trung phường Hòa Phú. Để so sánh với các phường khác, xem báo cáo tổng quan Thủ Dầu Một.'}, {'title': 'Đọc theo loại hình để không so sai', 'body': 'Đất nền và nhà đất có giá/m² chênh lệch lớn. Bảng bên dưới tách riêng từng loại.'}, {'title': 'Dùng số liệu để mở dashboard đúng chỗ', 'body': 'Sau khi đọc báo cáo, mở dashboard để lọc tin cụ thể theo ngân sách và loại hình.'}],
        "report": {'period': 'Tháng 06/2026', 'published_at': '2026-07-09', 'updated_label': 'Cập nhật Tháng 06/2026', 'source_note': 'Nguồn: tin rao Facebook tại Hòa Phú (57 tin). Đã lọc blacklist, hidden, outlier.', 'metrics': [{'label': 'Tin đang theo dõi', 'value': '57', 'note': 'tin rao Facebook tại Hòa Phú'}, {'label': 'Giá/m² trung vị', 'value': '23.7 tr/m²', 'note': 'đất nền (phân khúc chính)'}, {'label': 'Giá tỷ trung vị', 'value': '3.2 tỷ', 'note': 'đất nền'}, {'label': 'Tín hiệu đáng chú ý', 'value': '27', 'note': 'hot + giảm giá trong tháng'}], 'area_rows': [{'area': 'Đất nền', 'new_listings': '27 tin', 'median_price': '23.7 tr/m²', 'drop_signal': '27 tín hiệu', 'radar_signal': '27 tín hiệu'}], 'insights': [{'title': 'Giá đất nền Hòa Phú: 23.7 tr/m²', 'body': 'Đất nền Hòa Phú Tháng 06/2026 có giá trung vị 23.7 tr/m².'}, {'title': 'Nguồn cung Hòa Phú: 57 tin', 'body': 'Tháng này Hòa Phú có 57 tin rao từ Facebook đang hoạt động.'}, {'title': '27 tín hiệu đáng chú ý — cơ hội cho người mua', 'body': 'Có 27 tín hiệu (hot + giảm giá) tại Hòa Phú tháng này. 27 tin nóng, 0 tin giảm giá. Dùng dashboard để lọc theo phường, MOS và liên hệ tin phù hợp.'}], 'methodology': ['Dữ liệu từ tin rao Facebook tại Hòa Phú trong Tháng 06/2026.', 'Giá/m² trung vị = PERCENTILE_CONT(0.5).', 'Đã loại sold, blacklist, hidden, outlier.', 'Tín hiệu = is_hot=1 hoặc price_dropped=1.', 'Radar BDS là bộ lọc dữ liệu, không thay thẩm định pháp lý.']},
        "charts": [{'id': 'type-dist-chart', 'type': 'doughnut', 'title': 'Phân bố loại hình', 'legend': True, 'labels': ['Đất nền'], 'datasets': [{'data': [27], 'backgroundColor': ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']}]}, {'id': 'type-price-chart', 'type': 'bar', 'title': 'Giá/m² theo loại hình (tr/m²)', 'labels': ['Đất nền'], 'datasets': [{'label': 'Giá/m² (tr/m²)', 'data': [23.7], 'backgroundColor': '#3b82f6', 'borderRadius': 3}], 'legend': False}],
        "final_cta": {'title': 'Xem danh sách tin rao Hòa Phú trên dashboard', 'body': 'Mở dashboard Radar BDS để lọc tin rao Hòa Phú theo loại hình, ngân sách và khu vực cụ thể.', 'button': 'Mở dashboard'}
    },
}


from config.seo_locations import SEO_LOCATION_INDEX_LINKS, SEO_LOCATION_PAGES

SEO_PAGES.update(SEO_LOCATION_PAGES)
SEO_PAGES["binh-duong"]["local_links_title"] = "Khu vực liên quan"
SEO_PAGES["binh-duong"]["local_links"] = SEO_LOCATION_INDEX_LINKS
SEO_PAGES["ban-dat-binh-duong"]["local_links"] = [
    SEO_LOCATION_PAGES[slug]
    for slug in (
        "binh-duong/ben-cat",
        "binh-duong/my-phuoc",
        "binh-duong/my-phuoc-1",
        "binh-duong/my-phuoc-2",
        "binh-duong/my-phuoc-3",
        "binh-duong/phuong-tan-dinh",
    )
]
SEO_PAGES["ban-dat-binh-duong"]["local_links"] = [
    {
        "label": page["map_label"].split(" / ", 1)[-1],
        "href": page["path"],
        "description": page["description"],
    }
    for page in SEO_PAGES["ban-dat-binh-duong"]["local_links"]
]


for _report_page in SEO_PAGES.values():
    if _report_page.get("variant") == "report" and not _report_page.get("scope_label"):
        _map_label = str(_report_page.get("map_label") or "")
        _report_page["scope_label"] = _map_label.split(" / ", 1)[1] if " / " in _map_label else "Thủ Dầu Một"

REPORT_HUB = {
    "path": "/bao-cao",
    "title": "Báo cáo thị trường BĐS Bình Dương | Radar BDS",
    "description": "Kho báo cáo thị trường bất động sản Bình Dương; hiện ưu tiên dữ liệu Thủ Dầu Một.",
    "keywords": "báo cáo BĐS Bình Dương, báo cáo Thủ Dầu Một, thị trường bất động sản",
    "hero_title": "Báo cáo thị trường BĐS Bình Dương",
    "hero_text": "Theo dõi các báo cáo tháng đã chốt dữ liệu. Báo cáo tháng mới chỉ publish sau khi hết tháng để số liệu đầy đủ hơn.",
    "scope_label": "Hiện ưu tiên Thủ Dầu Một",
}

_REPORT_JUNE_2026 = SEO_PAGES["bao-cao/bds-binh-duong-thang-06-2026"]
_REPORT_JUNE_2026.update(
    {
        "title": "Báo cáo thị trường BĐS Thủ Dầu Một tháng 06/2026 | Radar BDS",
        "hero_title": "Báo cáo thị trường BĐS Thủ Dầu Một tháng 06/2026",
        "hero_text": "Báo cáo tháng 06/2026 chỉ tập trung các phường Thủ Dầu Một, trình bày phạm vi, kỳ dữ liệu, chỉ số và phương pháp trước khi đi vào từng nhóm giá.",
        "breadcrumb_label": "Báo cáo tháng 06/2026",
        "scope_label": "Thủ Dầu Một",
        "description": "Báo cáo thị trường BĐS Thủ Dầu Một tháng 06/2026 với phạm vi, kỳ dữ liệu, chỉ số và phương pháp của Radar BDS.",
        "value_cards": [
            {
                "title": "Phạm vi dữ liệu rõ ràng",
                "body": "Báo cáo này chỉ tập trung các phường Thủ Dầu Một, không dùng dữ liệu Bến Cát hay Mỹ Phước để kéo lệch mặt bằng.",
            },
            {
                "title": "Đọc theo phường trước khi đọc giá chung",
                "body": "Chênh lệch giữa Phú Mỹ, Hiệp An, Định Hòa và Hiệp Thành đủ lớn để cần tách nhóm trước khi so tin.",
            },
            {
                "title": "Dùng báo cáo để mở dashboard đúng chỗ",
                "body": "Sau khi nắm mặt bằng tháng, mở dashboard để lọc từng phường, loại tài sản và ngân sách cụ thể.",
            },
        ],
        "local_links_title": "Phường nên mở tiếp từ báo cáo",
        "local_links": [
            {
                "label": "Phú Mỹ",
                "href": "/binh-duong/phuong-phu-my",
                "description": "Khu vực cần tách riêng khi đọc giá Thủ Dầu Một.",
            },
            {
                "label": "Hiệp An",
                "href": "/binh-duong/phuong-hiep-an",
                "description": "Nguồn cung lớn, nên so riêng theo loại tài sản và tuyến đường.",
            },
        ],
    }
)

# --- Hermes Phu Tan internal links 2026-07-22 ---
def _rb_prepend_unique_page_link(page_slug, link):
    page = SEO_PAGES.get(page_slug)
    if not page:
        return
    links = list(page.get("local_links") or [])
    href = link.get("href")
    links = [item for item in links if item.get("href") != href]
    page["local_links"] = [link] + links
    if not page.get("local_links_title"):
        page["local_links_title"] = "Đọc tiếp từ dữ liệu Radar"

_PHU_TAN_ARTICLE_LINK = {
    "label": "Giá đất Phú Tân tháng 7/2026",
    "href": "/bao-cao/gia-dat-phu-tan-thu-dau-mot-cap-nhat-thang-7-2026",
    "description": "Bài phân tích data-driven: 708 tin active, 321 tín hiệu, đất nền trung vị 23,8 tr/m².",
}
_PHU_TAN_REPORT_LINK = {
    "label": "Báo cáo Phú Tân tháng 07/2026",
    "href": "/bao-cao/phu-tan-thang-07-2026",
    "description": "Báo cáo tháng có bảng loại hình, biểu đồ và phương pháp tính giá/m².",
}
_MASTER_REPORT_LINK = {
    "label": "Báo cáo Thủ Dầu Một tháng 07/2026",
    "href": "/bao-cao/bds-binh-duong-thang-07-2026",
    "description": "So Phú Tân với 12 phường còn lại trong cùng kỳ dữ liệu.",
}
_WARD_LINK = {
    "label": "Trang phường Phú Tân",
    "href": "/binh-duong/phuong-phu-tan",
    "description": "Landing nhà đất Phú Tân để mở dashboard theo khu vực.",
}
_rb_prepend_unique_page_link("binh-duong/phuong-phu-tan", _PHU_TAN_ARTICLE_LINK)
_rb_prepend_unique_page_link("binh-duong/phuong-phu-tan", _PHU_TAN_REPORT_LINK)
_rb_prepend_unique_page_link("bao-cao/phu-tan-thang-07-2026", _PHU_TAN_ARTICLE_LINK)
_rb_prepend_unique_page_link("bao-cao/phu-tan-thang-07-2026", _WARD_LINK)
_rb_prepend_unique_page_link("bao-cao/phu-tan-thang-07-2026", _MASTER_REPORT_LINK)
_rb_prepend_unique_page_link("san-deal-bds", _PHU_TAN_ARTICLE_LINK)
_rb_prepend_unique_page_link("san-deal-bds", _PHU_TAN_REPORT_LINK)
_rb_prepend_unique_page_link("binh-duong/thu-dau-mot", _PHU_TAN_ARTICLE_LINK)

# --- Hermes Dinh Hoa article internal links 2026-07-22 ---
def _rb_prepend_unique_link_dinh_hoa_demo(page_key, link):
    page = SEO_PAGES.get(page_key)
    if not page:
        return
    links = page.setdefault("local_links", [])
    if not any(item.get("href") == link.get("href") for item in links):
        links.insert(0, link)

_dinh_hoa_article_link = {"label": "Giá đất Định Hòa tháng 7/2026", "href": "/bao-cao/gia-dat-dinh-hoa-thu-dau-mot-cap-nhat-thang-7-2026", "description": "Bài mới có bảng giá, biểu đồ và cách đọc theo loại hình."}
for _key in ["bao-cao/dinh-hoa-thang-07-2026", "binh-duong/phuong-dinh-hoa", "binh-duong/thu-dau-mot", "bao-cao/bds-binh-duong-thang-07-2026"]:
    _rb_prepend_unique_link_dinh_hoa_demo(_key, _dinh_hoa_article_link)
