"""Practical guides for the Radar BDS tools."""

from config.planning_pages import planning_demo_href

_TDM_LAND_USE = planning_demo_href("THỦ DẦU MỘT")
_BEN_CAT_LAND_USE = planning_demo_href("BẾN CÁT")
_BEN_CAT_PARTITION = planning_demo_href("BẾN CÁT", "partition")

PRODUCT_GUIDES = {
    "cach-doc-ban-do-su-dung-dat-2030-va-quy-hoach-phan-khu": {
        "variant": "knowledge",
        "path": "/tin-tuc/cach-doc-ban-do-su-dung-dat-2030-va-quy-hoach-phan-khu",
        "category": {"key": "huong-dan-doc-du-lieu", "label": "Hướng dẫn đọc dữ liệu"},
        "title": "Cách đọc bản đồ sử dụng đất 2030 và quy hoạch phân khu | Radar BDS",
        "description": "Thực hành xem lớp sử dụng đất 2030 tại Thủ Dầu Một, đổi sang lớp phân khu ở Bến Cát và tìm nguồn bản đồ trước khi đi xem đất.",
        "keywords": "cách đọc bản đồ sử dụng đất 2030, bản đồ quy hoạch phân khu Bến Cát, quy hoạch Thủ Dầu Một",
        "breadcrumb_label": "Đọc bản đồ sử dụng đất 2030 và phân khu",
        "hero_title": "Cách đọc bản đồ sử dụng đất 2030 và quy hoạch phân khu",
        "hero_text": "Thử hai góc nhìn ở Bình Dương cũ để tập đối chiếu vị trí, lớp bản đồ và nguồn dữ liệu.",
        "scope_label": "Thủ Dầu Một · Bến Cát",
        "social_review_only": True,
        "primary_cta": "Thử lớp sử dụng đất 2030 ở Thủ Dầu Một",
        "primary_href": _TDM_LAND_USE,
        "map_demos": [
            {"label": "Thử lớp sử dụng đất 2030 ở Thủ Dầu Một", "href": _TDM_LAND_USE, "id": "maps_demo_tdm_2030"},
            {"label": "Mở sử dụng đất 2030 ở Bến Cát", "href": _BEN_CAT_LAND_USE, "id": "maps_demo_ben_cat_2030"},
            {"label": "Mở phân khu ở cùng điểm Bến Cát", "href": _BEN_CAT_PARTITION, "id": "maps_demo_ben_cat_partition"},
        ],
        "next_step_text": "Mở từng góc nhìn, đọc tên lớp đang bật và kiểm tra nguồn trước khi diễn giải màu trên bản đồ.",
        "local_links": [
            {"label": "Bản đồ địa giới Bến Cát", "href": "/ban-do-ben-cat#layer-legacy/area-my-phuoc", "description": "Hiện ranh Mỹ Phước cũ và đối chiếu các phường hiện tại."},
            {"label": "Tra tờ/thửa và tọa độ", "href": "/tin-tuc/cach-tra-cuu-quy-hoach-theo-so-to-so-thua-toa-do", "description": "Xác định vị trí từ thông tin trên giấy tờ."},
            {"label": "Cổng công khai dữ liệu quy hoạch TP.HCM", "href": "https://gisxaydung.tphcm.gov.vn/tracuuttqh", "description": "Đối chiếu dữ liệu quy hoạch do cơ quan quản lý công bố."},
        ],
        "faq": [
            {"q": "Nên mở lớp sử dụng đất 2030 hay phân khu trước?", "a": "Mở lớp 2030 để nhìn tổng quan, sau đó mở phân khu nếu cần xem ô chức năng và khu vực có dữ liệu GIS. Giữ nguyên vị trí khi chuyển lớp."},
            {"q": "Có thể dùng một bảng màu để đọc cả hai lớp không?", "a": "Hãy đọc chú giải của nguồn đang mở. Lớp sử dụng đất 2030 trên Radar là lớp tham khảo từ Guland, chưa đối chiếu hồ sơ phê duyệt. Với phân khu, dùng chú giải GIS hoặc chú giải của bản vẽ gốc nếu có."},
            {"q": "Vùng không lên màu thì xử lý thế nào?", "a": "Kiểm tra độ phóng, lớp đang bật, trạng thái tải và phạm vi nguồn. Nếu cần kiểm tra một thửa trước giao dịch, hãy đối chiếu đúng vị trí với hồ sơ và cơ quan có thẩm quyền."},
        ],
        "article": {
            "published_at": "2026-11-10",
            "modified_at": "2026-11-10",
            "illustration": {
                "src": "/static/images/seo/maps-phan-khu-ben-cat-20261110.png",
                "alt": "Lớp quy hoạch phân khu trên Radar BDS ở khu vực đường Ngô Quyền và Quốc lộ 13, Bến Cát",
                "width": 1280,
                "height": 800,
                "caption": "Lớp phân khu tại Bến Cát trên Radar BDS, nguồn GIS TP.HCM. Ảnh chụp ngày 10/11/2026 để minh họa cách đọc bản đồ.",
            },
            "intro": [
                "Để đọc quy hoạch của một khu vực, hãy xác định đúng vị trí, mở từng lớp rồi xem chú giải đi kèm. Thử lớp sử dụng đất 2030 ở Thủ Dầu Một để nhìn tổng quan. Sau đó mở hai góc nhìn Bến Cát bên dưới để so lớp sử dụng đất và phân khu tại cùng một điểm.",
                "Các góc nhìn trong bài dùng để tập thao tác. Nếu đang xem một tin rao, hãy lấy vị trí từ giấy tờ hoặc mốc thực địa trước khi áp dụng các bước này cho lô đất.",
            ],
            "sections": [
                {"id": "thu-dau-mot-2030", "heading": "1. Thử đọc lớp sử dụng đất 2030 ở Thủ Dầu Một", "paragraphs": [
                    "Mở góc nhìn Thủ Dầu Một ở đầu bài. Dùng thanh độ hiển thị để nhìn đường và công trình trên nền vệ tinh qua lớp màu. Tắt lớp rồi bật lại để kiểm tra xem mình đang nhìn đúng điểm.",
                    "Trong phần thông tin lớp, kiểm tra tên nguồn và nhãn tham khảo. Lớp 2030 của Bình Dương cũ trên Radar dùng ảnh bản đồ từ Guland. Khi lớp đang xem thiếu chú giải riêng, hãy ghi lại vị trí để đối chiếu hồ sơ thay vì suy ra chức năng đất từ màu.",
                ]},
                {"id": "ben-cat-phan-khu", "heading": "2. So hai lớp tại cùng vị trí ở Bến Cát", "paragraphs": [
                    "Mở hai liên kết Bến Cát trong mục Thử trực tiếp. Hai góc nhìn có cùng vị trí và độ phóng. Nếu đang ở ngay trên Maps, có thể tắt lớp 2030 rồi bật Quy hoạch phân khu để đọc từng lớp.",
                    "Với phân khu, mở Ký hiệu các loại đất, chọn đúng nhóm Quy hoạch phân khu và đối chiếu với nguồn GIS TP.HCM. Nếu đã chọn bản vẽ có chú giải riêng, hãy dùng chú giải của bản vẽ đó. Ghi lại tên lớp và nguồn khi gửi ảnh hoặc link cho người đi xem cùng.",
                ]},
                {"id": "dia-gioi", "heading": "3. Đối chiếu địa giới khi tên trong tin khác tên trên bản đồ", "paragraphs": [
                    "Ví dụ tin rao ghi Mỹ Phước, Bến Cát theo tên cũ. Mở bản đồ Bến Cát, xem ranh Mỹ Phước trước sắp xếp rồi chuyển sang bản sau sắp xếp. Dùng vị trí cụ thể để đối chiếu phường Long Nguyên hoặc phường Bến Cát.",
                    "Sau khi tra xong, nếu muốn xem thị trường quanh đó, bật Hiện tin đăng ngay trên Maps hoặc mở danh sách tin từ trang địa giới.",
                ]},
            ],
            "checklist": ["Xác định đúng khu vực và mốc vị trí.", "Bật từng lớp và đọc chú giải của đúng nguồn.", "Đối chiếu hồ sơ gốc trước khi đặt cọc."],
        },
    },
    "cach-tra-cuu-quy-hoach-theo-so-to-so-thua-toa-do": {
        "variant": "knowledge",
        "path": "/tin-tuc/cach-tra-cuu-quy-hoach-theo-so-to-so-thua-toa-do",
        "category": {"key": "huong-dan-doc-du-lieu", "label": "Hướng dẫn đọc dữ liệu"},
        "title": "Cách tra quy hoạch theo số tờ, số thửa và tọa độ trên bản đồ | Radar BDS",
        "description": "Hướng dẫn chọn khu vực, tìm tờ/thửa hoặc tọa độ, bật lớp quy hoạch và kiểm tra nguồn trên Radar BDS; xử lý khi bản đồ không có kết quả.",
        "keywords": "tra cứu quy hoạch theo số tờ số thửa, xem quy hoạch tọa độ, bản đồ quy hoạch",
        "breadcrumb_label": "Tra quy hoạch theo tờ/thửa và tọa độ",
        "hero_title": "Cách tra quy hoạch theo số tờ, số thửa và tọa độ",
        "hero_text": "Bắt đầu từ thông tin bạn có, xác định đúng vị trí rồi mới đọc lớp quy hoạch.",
        "scope_label": "Hướng dẫn sử dụng · Bản đồ quy hoạch",
        "primary_cta": "Mở bản đồ quy hoạch",
        "primary_href": "/quy-hoach-binh-duong",
        "hide_lead_capture": True,
        "next_step_text": "Chọn khu vực, định vị thửa và đối chiếu nguồn quy hoạch đang có trên bản đồ.",
        "local_links": [
            {"label": "Bản đồ quy hoạch", "href": "/quy-hoach-binh-duong", "description": "Chọn khu vực và lớp bản đồ có dữ liệu."},
            {"label": "Cách dùng Săn Deal BĐS", "href": "/tin-tuc/cach-san-deal-bds-kiem-tra-tin-duoi-gia", "description": "Đối chiếu vị trí với tin đang xem."},
            {"label": "Định giá đất", "href": "/dinh-gia-bds", "description": "Tham khảo giá sau khi xác định đúng vị trí."},
        ],
        "faq": [
            {"q": "Có thể tra số tờ, số thửa ở mọi tỉnh không?", "a": "Không. Ranh thửa và tra cứu phụ thuộc nguồn dữ liệu của từng khu vực. Có lớp quy hoạch toàn quốc không có nghĩa là có ranh thửa toàn quốc."},
            {"q": "Không tìm thấy thửa có nghĩa là đất không vướng quy hoạch?", "a": "Không. Có thể bạn chọn sai khu vực, dùng số thửa cũ hoặc nguồn chưa có dữ liệu. Hãy kiểm tra lại đầu vào và xác minh với cơ quan có thẩm quyền."},
            {"q": "Tại sao nhập tọa độ nhưng vị trí bị lệch?", "a": "Hãy kiểm tra hệ tọa độ, thứ tự X/Y hoặc kinh độ/vĩ độ, kinh tuyến trục và múi chiếu ghi trên tài liệu. Không tự đoán hệ tọa độ khi thiếu thông tin."},
        ],
        "article": {
            "published_at": "2026-11-03", "modified_at": "2026-11-03",
            "intro": [
                "Để tra quy hoạch, trước hết cần xác định đúng vị trí bất động sản. Nếu có số tờ và số thửa, hãy chọn đúng địa bàn trước khi tìm. Nếu có bảng tọa độ, hãy xác định hệ tọa độ trước khi nhập; kết quả lệch vị trí sẽ làm việc đọc lớp quy hoạch sai theo.",
                "Radar BDS có bản đồ nền, các lớp quy hoạch và công cụ tra cứu ở những nơi có nguồn dữ liệu phù hợp. Hướng dẫn này giải thích cách sử dụng và giới hạn của từng bước, không cam kết mọi khu vực đều có ranh thửa hoặc quy hoạch chi tiết.",
            ],
            "sections": [
                {"id": "chuan-bi", "heading": "1. Chuẩn bị thông tin vị trí", "paragraphs": ["Ghi lại tỉnh, huyện và phường/xã theo địa danh trên giấy tờ. Radar BDS có bộ chọn khu vực theo địa danh cũ; hãy đối chiếu khi giấy tờ và địa chỉ hiện tại dùng tên khác nhau."], "bullets": ["Có số tờ/thửa: chuẩn bị cả địa bàn, không chỉ hai con số.", "Có tọa độ: giữ nguyên bảng gốc và thông tin hệ tọa độ, múi chiếu, kinh tuyến trục.", "Chỉ có địa chỉ hoặc vị trí tin rao: dùng làm điểm khởi đầu, sau đó đối chiếu giấy tờ và thực địa."]},
                {"id": "tim-thua", "heading": "2. Mở bản đồ và tìm đúng thửa", "paragraphs": ["Mở Bản đồ quy hoạch, chọn khu vực cần xem rồi mở công cụ Tờ/thửa. Nhập thông tin và đối chiếu kết quả với đường, mốc nhận biết và hình dạng khu đất trên giấy tờ. Chỉ tiếp tục khi vị trí phù hợp.", "Nếu nguồn chưa hỗ trợ tra tờ/thửa, hãy dùng vị trí hoặc tọa độ để định vị trước. Không dùng ranh thửa lân cận để suy ra ranh của bất động sản đang kiểm tra."]},
                {"id": "toa-do", "heading": "3. Tra bằng tọa độ hoặc các góc ranh", "paragraphs": ["Chọn đúng hệ tọa độ được ghi trên tài liệu: WGS84 hoặc hệ VN-2000 mà công cụ hỗ trợ. Với VN-2000, cần đối chiếu cả kinh tuyến trục và múi chiếu. Nhập đúng thứ tự giá trị theo nhãn của công cụ.", "Nếu nhập nhiều góc ranh hoặc quét từ ảnh, hãy soát lại từng chữ số với bản gốc trước khi xem đa giác. Sai một chữ số hoặc đảo thứ tự điểm có thể làm lệch vị trí, hình dạng và diện tích. Không coi diện tích tính từ bản đồ là kết quả đo đạc chính thức."]},
                {"id": "doc-lop", "heading": "4. Bật từng lớp và kiểm tra nguồn", "paragraphs": ["Chọn lớp quy hoạch đang có cho địa bàn, điều chỉnh độ trong suốt để đối chiếu với bản đồ nền. Phân biệt quy hoạch sử dụng đất, phân khu, giao thông và địa giới; các lớp này có mục đích và phạm vi dữ liệu khác nhau.", "Đọc tên nguồn, chú giải và kỳ dữ liệu khi có. Ranh thửa và lớp quy hoạch là hai nguồn thông tin riêng: tìm được thửa không bảo đảm có quy hoạch chi tiết của thửa. Nếu có nút xem thông tin quy hoạch chi tiết, kiểm tra kết quả riêng trước khi diễn giải."]},
                {"id": "khong-ket-qua", "heading": "5. Xử lý khi trống bản đồ hoặc không có kết quả", "paragraphs": ["Kiểm tra khu vực, số tờ/thửa, hệ tọa độ và lớp đang bật; thử đối chiếu lại vị trí trên bản đồ nền. Thông báo lỗi nguồn, chưa có dữ liệu và không tìm thấy kết quả đều không phải xác nhận rằng đất không vướng quy hoạch.", "Trước giao dịch, đối chiếu giấy tờ gốc, hiện trạng và thông tin từ cơ quan có thẩm quyền. Ảnh chụp màn hình trên website chỉ hỗ trợ sàng lọc ban đầu."]},
            ],
            "checklist": ["Đúng địa bàn và vị trí thửa.", "Đúng hệ tọa độ và thứ tự điểm nếu dùng tọa độ.", "Đọc nguồn, chú giải và phạm vi lớp đang bật.", "Xác minh độc lập trước khi đặt cọc hoặc giao dịch."],
        },
    },
    "cach-san-deal-bds-kiem-tra-tin-duoi-gia": {
        "variant": "knowledge",
        "path": "/tin-tuc/cach-san-deal-bds-kiem-tra-tin-duoi-gia",
        "category": {"key": "kiem-tra-tin-rao", "label": "Kiểm tra tin rao"},
        "title": "Cách săn deal BĐS: lọc tin dưới giá và kiểm tra trước khi đi xem | Radar BDS",
        "description": "Cách dùng Săn Deal trên Radar BDS: chọn khu vực, đọc giá rao và MOS, kiểm tra tin giảm giá, đối chiếu quy hoạch rồi lập danh sách đi xem.",
        "keywords": "săn deal BĐS, tin dưới giá, cách tìm bất động sản giảm giá, Radar BDS",
        "breadcrumb_label": "Cách dùng Săn Deal BĐS",
        "hero_title": "Cách săn deal BĐS và kiểm tra tin trước khi đi xem",
        "hero_text": "Dùng tín hiệu để rút ngắn danh sách cần kiểm tra, rồi đối chiếu từng bất động sản.",
        "scope_label": "Hướng dẫn sử dụng · Săn Deal BĐS",
        "primary_cta": "Mở Săn Deal BĐS",
        "primary_href": "/?tab=signals",
        "lead_scope_label": "Bình Dương",
        "next_step_text": "Chọn khu vực và ngân sách để lập danh sách tin cần xác minh trước khi đi xem.",
        "local_links": [
            {"label": "Săn Deal BĐS", "href": "/san-deal-bds", "description": "Hiểu phạm vi và cách đọc tín hiệu."},
            {"label": "MOS là gì?", "href": "/tin-tuc/mos-la-gi-loc-tin-duoi-gia-co-so", "description": "Đọc chênh lệch so với giá cơ sở."},
            {"label": "Tra quy hoạch theo tờ/thửa và tọa độ", "href": "/tin-tuc/cach-tra-cuu-quy-hoach-theo-so-to-so-thua-toa-do", "description": "Đối chiếu vị trí và lớp quy hoạch."},
            {"label": "Định giá đất", "href": "/dinh-gia-bds", "description": "Kiểm tra thêm bất động sản đã chọn."},
            {"label": "Bảng giá đất nhà nước", "href": "/bang-gia-dat-tphcm", "description": "Tra mốc tham chiếu riêng, không dùng làm giá thị trường."},
        ],
        "faq": [
            {"q": "Tin trong Săn Deal có chắc là mua rẻ không?", "a": "Không. Đây là tín hiệu sàng lọc dựa trên dữ liệu và mô hình. Giá cơ sở có sai số; vị trí, giấy tờ, hiện trạng và điều kiện bán vẫn cần kiểm tra độc lập."},
            {"q": "Không có tín hiệu thì tìm bất động sản ở đâu?", "a": "Chuyển sang Tin rao và mở rộng dần bộ lọc. Tin rao có phạm vi rộng hơn Săn Deal; không có tín hiệu không có nghĩa khu vực không có tin đăng."},
            {"q": "Giảm giá có đồng nghĩa thấp hơn thị trường không?", "a": "Không. Giảm giá là thay đổi giá rao của tin theo lịch sử theo dõi, còn thấp hơn giá cơ sở là phép so khác. Cần đọc cả mốc thời gian, thông tin tài sản và độ tin cậy của mẫu so sánh."},
        ],
        "article": {
            "published_at": "2026-11-03", "modified_at": "2026-11-03",
            "intro": [
                "Để săn deal trên Radar BDS, hãy mở Săn Deal, chọn khu vực và loại bất động sản, rồi thu hẹp theo ngân sách. Dùng giá rao, giá/m², chênh lệch với giá cơ sở và lịch sử giá để chọn tin đáng kiểm tra; sau đó đối chiếu vị trí, quy hoạch và giấy tờ.",
                "Săn Deal giúp giảm số tin phải đọc, không xác nhận tài sản đang được bán dưới giá giao dịch thực tế. Nguồn tin rao tập trung tại Bình Dương; phạm vi bản đồ quy hoạch rộng hơn không đồng nghĩa có nguồn deal trên toàn quốc.",
            ],
            "sections": [
                {"id": "loc-nhu-cau", "heading": "1. Chọn khu vực, loại hình và ngân sách", "paragraphs": ["Mở Săn Deal BĐS, chọn phường hoặc khu vực bạn thực sự có thể đi xem. Tách đất nền khỏi nhà đất vì giá nhà đã bao gồm công trình và hiện trạng. Đặt khoảng ngân sách trước khi so giá/m².", "Nếu danh sách trống, nới từng điều kiện hoặc chuyển sang Tin rao. Tránh bỏ tất cả bộ lọc cùng lúc vì khi đó các tài sản khó so sánh trực tiếp với nhau."]},
                {"id": "doc-gia", "heading": "2. Đọc giá rao, giá cơ sở và cảnh báo", "paragraphs": ["Giá trên tin là giá chào bán, không phải giá chốt. Giá cơ sở là ước tính dùng để so sánh trong phạm vi dữ liệu của hệ thống. MOS biểu thị chênh lệch với mốc ước tính này; MOS cao không tự tạo ra mức lợi nhuận tương ứng.", "Đọc cả cảnh báo về mẫu so sánh, thông tin còn thiếu và mức độ tin cậy. Kiểm tra tổng giá, diện tích và giá/m² có nhất quán với nội dung tin hay không; tin nhập sai giá hoặc diện tích có thể tạo cảm giác rẻ bất thường."]},
                {"id": "lich-su-gia", "heading": "3. Kiểm tra lịch sử giá và thời điểm tin", "paragraphs": ["Khi có lịch sử theo dõi, xem mức giá trước và sau cùng mốc ghi nhận. Phân biệt ngày đăng, ngày hệ thống quan sát và thời điểm thay đổi giá. Tin đăng lại không tự chứng minh tài sản đã giao dịch hoặc chủ đang cần bán gấp.", "Một tin giảm giá vẫn có thể cao hơn các tin tương đồng. Hãy so cùng khu vực, loại hình, diện tích, đường vào và tình trạng pháp lý thay vì chỉ chọn mức giảm phần trăm lớn."]},
                {"id": "doi-chieu", "heading": "4. Đối chiếu bản đồ, định giá và bảng giá đất", "paragraphs": ["Mở bản đồ để đối chiếu vị trí; nếu vị trí tin chưa chính xác, xác minh lại trước khi đọc quy hoạch. Kiểm tra lớp và nguồn đang có, rồi dùng công cụ định giá như một phép tham khảo bổ sung.", "Bảng giá đất nhà nước là nguồn tham chiếu riêng. Không lấy chênh lệch giữa bảng giá đất và giá rao làm mức chiết khấu của một deal, và không dùng việc bản đồ chưa có dữ liệu để kết luận đất không vướng quy hoạch."]},
                {"id": "di-xem", "heading": "5. Lập danh sách ngắn và xác minh trước khi đi xem", "paragraphs": ["Chọn vài tin phù hợp nhất, ghi lại những điểm đã biết và câu hỏi còn thiếu: giá còn hiệu lực, địa chỉ chính xác, diện tích trên giấy, lối đi, hiện trạng và điều kiện giao dịch. Sử dụng thao tác liên hệ được website cung cấp cho tài khoản của bạn.", "Đi xem và kiểm tra giấy tờ gốc trước khi ra quyết định. Nếu không xác minh được thông tin trọng yếu, giữ tin ở trạng thái cần kiểm tra; không suy ra đó là cơ hội chỉ từ nhãn Săn Deal."]},
            ],
            "checklist": ["Cùng khu vực, loại hình và ngân sách khi so sánh.", "Giá, diện tích và giá/m² nhất quán.", "Đã đọc cảnh báo, lịch sử giá và thời điểm tin.", "Đã xác minh vị trí, quy hoạch và giấy tờ trước giao dịch."],
        },
    },
}
