"""Source-reviewed evergreen Facebook angles, not a global paragraph template.

Only exact article paths with the reviewed source sections qualify. No market
numbers are copied into these evergreen captions. New sources require editorial
review, not fuzzy keyword matching against an entire article body.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

TOPICS: dict[str, dict[str, Any]] = {
    'bang-gia-dat-va-gia-rao-khac-nhau-the-nao': {
        'topic': 'Bảng giá đất không phải giá chủ phải bán',
        'reader_benefit': 'Biết dùng bảng giá đất cho đúng việc, không lấy nó làm mức ép người bán chấp nhận.',
        'source_sections': ['bang-gia-dat-la-gi', 'gia-rao-cho-viec-gi', 'dung-hai-moc-cung-luc'],
        'caption': '''Tra bảng giá đất thấy thấp hơn giá chủ đang rao, có phải chủ bán đắt?

Chưa thể kết luận như vậy. Bảng giá đất do Nhà nước ban hành được dùng cho những trường hợp pháp luật quy định, không phải bảng giá buộc mọi chủ đất phải bán theo.

Còn giá rao là số tiền người bán đang chào. Muốn biết mức chào đó có đáng thương lượng, hãy tìm thêm tin cùng khu, cùng loại nhà đất và gần giống về diện tích, đường vào. Đừng lấy một lô trong hẻm làm mốc trả giá cho lô mặt đường.

Trên Radar có cả mục tra bảng giá đất và công cụ tham khảo giá rao. Cần làm hồ sơ thì đọc đúng văn bản áp dụng; cần tìm mua thì so các tin đang chào. Hai việc khác nhau, dùng nhầm sẽ dễ hỏi sai giá.

Bài phân biệt hai loại giá và đường dẫn công cụ ở bình luận đầu tiên.''',
    },
    'gia-rao-khac-gia-giao-dich-the-nao': {
        'topic': 'Giá rao không cho biết người mua trước đã trả bao nhiêu',
        'reader_benefit': 'Không lấy giá trên một tin đăng làm bằng chứng giá giao dịch; biết hỏi lại giá trước khi hẹn xem.',
        'source_sections': ['gia-rao-khong-phai-gia-chot', 'cach-radar-dung-gia-rao', 'cach-hanh-dong'],
        'caption': '''Thấy tin đăng một mức giá, đừng vội nghĩ hàng xóm cũng đã mua bằng mức đó.

Tin rao chỉ cho biết người bán đang chào bao nhiêu. Giá hai bên thật sự đồng ý sau thương lượng có thể khác, và thường không nằm trong tin đăng.

Vì vậy, xem nhiều tin quanh khu vẫn có ích: anh chị biết người bán đang chào ở mức nào để chuẩn bị câu hỏi. Nhưng không thể chỉ từ đó khẳng định “khu này vừa giao dịch giá này”.

Trước khi hẹn xem, hỏi lại giá chào hiện tại, tin còn bán không và những thông tin chưa rõ về vị trí, giấy tờ. Nếu giá thấp hơn hẳn các tin gần giống, cần tìm lý do chứ chưa nên vội mừng.

Radar giúp gom tin rao để so ban đầu, không phải cơ sở dữ liệu giá đã chốt. Bài hướng dẫn đọc giá rao ở bình luận đầu tiên.''',
    },
    'cach-doc-gia-m2-dat-nen-binh-duong': {
        'topic': 'Giá mỗi mét vuông thấp nhưng tổng tiền vẫn vượt túi tiền',
        'reader_benefit': 'Kiểm tổng giá cùng diện tích trước, rồi mới so giá mỗi mét vuông giữa các lô tương đồng.',
        'source_sections': ['gia-m2-chi-la-buoc-dau', 'xem-tong-gia-song-song', 'kiem-tra-phap-ly-quy-hoach'],
        'caption': '''Giá mỗi mét vuông thấp hơn, chưa chắc lô đất đó vừa túi tiền hơn.

Lô rộng hơn có thể rẻ hơn khi tính từng mét, nhưng tổng số tiền phải trả lại cao hơn. Nếu chỉ xếp tin từ giá/m² thấp đến cao, anh chị vẫn có thể mất công đọc những lô vượt ngân sách.

Cách xem đỡ rối: kiểm tổng giá chào có vừa khả năng trước, rồi đối chiếu diện tích. Giá mỗi mét vuông được tính bằng tổng giá rao chia cho diện tích đất; diện tích ghi sai thì phép so cũng sai theo.

Sau đó mới đặt cạnh các lô có đường vào và phần đất ở tương đương. Một lô hẻm nhỏ với một lô mặt đường không tự nhiên trở thành hai lựa chọn ngang nhau chỉ vì cùng phường.

Trên Radar, lọc tổng giá và diện tích trước khi đọc kỹ từng tin. Checklist xem giá đất ở bình luận đầu tiên.''',
    },
    'vi-sao-khong-nen-so-nha-dat-chung-voi-dat-nen': {
        'topic': 'So nhà có sẵn với đất trống dễ bỏ sót tiền sửa hoặc xây',
        'reader_benefit': 'Phân biệt giá đất và giá có công trình, tính tới hiện trạng nhà thay vì chỉ nhìn giá mỗi mét vuông.',
        'source_sections': ['nha-dat-co-gia-tri-cong-trinh', 'mot-gia-chung-de-gay-nham', 'nen-lam-gi-truoc-khi-goi'],
        'caption': '''Đất trống và nhà xây sẵn: so mỗi giá/m² là dễ bỏ sót một khoản lớn.

Với nhà có sẵn, số tiền chủ chào còn gắn với công trình và tình trạng sử dụng. Nhà vào ở được ngay khác với nhà cần sửa nhiều. Còn mua đất để ở thì vẫn phải nghĩ tới việc xây nhà sau đó.

Bởi vậy, thấy một căn nhà có giá/m² cao hơn lô đất gần đó chưa đủ để nói căn nhà bị rao đắt. Ngược lại, nhà cũ rao thấp cũng chưa chắc tiết kiệm nếu cần sửa lớn.

Khi lọc trên Radar, tách nhà đất và đất nền trước. Nếu đang tìm nhà để ở, hãy hỏi thêm hiện trạng căn nhà và phần nào cần sửa, rồi mới so với những căn có điều kiện gần giống.

Bài giải thích cách so hai loại nhà đất ở bình luận đầu tiên. Đừng để một con số giá/m² che mất khoản tiền cần chuẩn bị sau khi mua.''',
    },
    'cach-dinh-gia-nha-dat-binh-duong-bang-gia-rao-theo-phuong': {
        'topic': 'Chọn đúng tin đối chiếu trước khi thương lượng',
        'reader_benefit': 'Biết loại các tin không tương đồng ra khỏi nhóm so sánh trước khi dùng chúng để thương lượng.',
        'source_sections': ['dung-phuong-dung-loai-hinh', 'dung-gia-rao-nhu-moc-loc', 'quy-trinh-truoc-khi-goi-moi-gioi'],
        'caption': '''Muốn thương lượng giá nhà đất, đừng chỉ mang theo một tin rẻ hơn.

Tin đó có cùng khu không? Là đất trống hay nhà xây sẵn? Diện tích và đường vào có gần giống không? Nếu khác những điểm này, người bán hoàn toàn có lý do để nói hai tài sản không so được với nhau.

Hãy gom các tin cùng phường và cùng loại nhà đất trên Radar, rồi bỏ những tin lệch nhiều về diện tích hoặc điều kiện đường vào. Nhóm còn lại mới đáng đọc kỹ để xem mức chủ đang chào có gì khác.

Công cụ định giá giúp thêm một mốc tham khảo, không ấn định số tiền người bán phải nhận. Có nhóm tin đối chiếu rõ ràng thì cuộc gọi cũng cụ thể hơn: hỏi lý do chênh giá, thay vì chỉ hỏi “bớt được bao nhiêu?”.

Bài hướng dẫn và công cụ ở bình luận đầu tiên.''',
    },
    'khi-nao-nen-dung-cong-cu-dinh-gia-truoc-khi-goi-moi-gioi': {
        'topic': 'Thiếu thông tin thì hỏi lại trước khi tin kết quả định giá',
        'reader_benefit': 'Phân biệt lúc có thể tham khảo công cụ với lúc phải bổ sung vị trí, diện tích và loại nhà đất trước.',
        'source_sections': ['mo-cong-cu-khi-chua-co-moc-so', 'goi-moi-gioi-sau-khi-da-loc'],
        'caption': '''Tin chỉ ghi “nhà đẹp, giá tốt” thì mở công cụ định giá ngay cũng chưa giúp được nhiều.

Trước hết cần biết đúng khu vực, diện tích và đó là đất trống hay nhà có sẵn. Nhập nhầm những thông tin này, kết quả tham khảo có thể khiến mình tự tin vào một phép so không đúng.

Nếu đã có thông tin cơ bản nhưng chưa biết giá chào cao hay thấp so với các tin gần giống, lúc đó dùng công cụ sẽ hữu ích hơn. Xem kết quả, quay lại đọc các tin cùng loại rồi ghi ra chỗ cần hỏi người bán.

Ví dụ câu hỏi nên chuẩn bị: đường vào thực tế ra sao, diện tích có khớp hồ sơ không, giá hiện tại còn đúng như tin đăng không? Công cụ không trả lời thay người bán những việc đó.

Link công cụ Radar và hướng dẫn dùng trước cuộc gọi ở bình luận đầu tiên. Mục đích là hỏi đúng hơn, không phải lấy một kết quả ước tính làm giá chốt.''',
    },
    'mos-la-gi-loc-tin-duoi-gia-co-so': {
        'topic': 'Được Radar ưu tiên xem không có nghĩa là chắc mua có lời',
        'reader_benefit': 'Hiểu thứ tự gợi ý là bước lọc để kiểm tra, không phải mức lời hoặc chứng nhận tài sản tốt.',
        'source_sections': ['mos-la-gi', 'tach-loai-hinh', 'quy-trinh-loc-dashboard'],
        'caption': '''Tin được Radar ưu tiên xem có nghĩa là mua sẽ có lời?

Không. Radar so giá người bán đang chào với mức giá hệ thống ước tính. Một tin có khoảng chênh đáng chú ý thì nên mở ra kiểm tra trước, chứ khoảng chênh đó chưa phải khoản tiền mình sẽ kiếm được.

Giá rao có thể đã đổi. Mô tả có thể thiếu thông tin. Và cùng một mức giá, đường vào hay giấy tờ khác nhau cũng khiến quyết định khác hẳn.

Cách dùng thực tế là chọn đúng khu và loại nhà đất đang tìm, bỏ những tin vượt khả năng, rồi đọc kỹ các tin còn lại. Tin được gợi ý nhưng thiếu vị trí hoặc chưa rõ hồ sơ thì ưu tiên hỏi cho rõ, không ưu tiên đặt cọc.

Radar giúp rút ngắn danh sách cần đọc. Kiểm tra tài sản và thương lượng vẫn là bước riêng. Bài giải thích cách đọc gợi ý ở bình luận đầu tiên.''',
    },
    'ty-le-cat-mau-nha-dat-thu-dau-mot-phuong-nao-can-kiem-tra': {
        'topic': 'Tin giảm giá cần hỏi giá mới còn hiệu lực và vì sao giảm',
        'reader_benefit': 'Biết giảm so với giá cũ khác với rẻ so với các nhà đất tương đồng và không suy ra chủ đang kẹt tiền.',
        'source_sections': ['doc-co-giam-gia', 'dung-radar'],
        'caption': '''Tin ghi “cắt máu” chưa nói được chủ đang kẹt tiền hay nhà đất thật sự rẻ.

Giảm giá chỉ cho biết giá chào đã thay đổi so với trước. Nếu mức cũ quá cao, mức mới vẫn có thể cao hơn các tin tương tự. Cũng chưa biết giá mới còn áp dụng khi mình gọi hay không.

Thay vì chỉ hỏi giảm được bao nhiêu, hãy hỏi: “Giá hiện tại còn đúng như tin đăng không, vì sao điều chỉnh, vị trí và giấy tờ có gì cần lưu ý?”. Sau đó mới so với những tin gần giống về diện tích và đường vào.

Trên Radar, nhóm tin có giảm giá là chỗ để bắt đầu đọc kỹ hơn, không phải danh sách chủ buộc phải bán gấp. Không đủ thông tin thì hỏi thêm, đừng tự điền một lý do hấp dẫn thay người bán.

Bài phân tích tin giảm giá ở Thủ Dầu Một nằm trong bình luận đầu tiên.''',
    },
}


def source_topic(page: dict[str, Any]) -> dict[str, Any] | None:
    """Return reviewed copy only when the exact source and sections still exist."""
    path = urlsplit(str(page.get('path') or '')).path.rstrip('/')
    slug = path.rsplit('/', 1)[-1]
    spec = TOPICS.get(slug)
    if not spec or path != '/tin-tuc/' + slug:
        return None
    article = page.get('article')
    if not isinstance(article, dict):
        return None
    sections = article.get('sections')
    if not isinstance(sections, list):
        return None
    by_id = {s.get('id'): s for s in sections if isinstance(s, dict)}
    for section_id in spec['source_sections']:
        section = by_id.get(section_id, {})
        paragraphs = section.get('paragraphs')
        if not isinstance(paragraphs, list) or not any(isinstance(p, str) and len(p.strip()) > 30 for p in paragraphs):
            return None
    return dict(spec)
