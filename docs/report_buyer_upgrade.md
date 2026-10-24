# Nâng cấp báo cáo Radar BDS theo câu hỏi của người mua

Ngày đánh giá: 25/10/2026. Trạng thái: đã được chủ sản phẩm duyệt triển khai; chi tiết và kiểm chứng tại `superpowers/plans/2026-10-25-buyer-reports.md`.

## Mục tiêu và phạm vi

Một báo cáo chung cho người mua bất động sản, theo yêu cầu của chủ sản phẩm;
không tách thành báo cáo mua ở và báo cáo đầu tư. Phân loại đất nền/nhà đất vẫn
cần thiết để so sánh đúng tài sản. Báo cáo tổng quan giúp chọn khu vực; báo cáo
phường giúp kiểm tra phân khúc cụ thể. Cả hai đi theo cùng một mạch đọc.

Sau khi đọc, người dùng cần biết:

1. Với khoảng ngân sách của mình, dữ liệu đang ghi nhận những lựa chọn nào?
2. Giá rao của tài sản tương tự thường nằm trong khoảng nào?
3. Những khu vực nào có thể đem ra so sánh, với cùng điều kiện tài sản?
4. Có dấu hiệu giảm giá hay thay đổi cơ cấu mẫu nào cần xem kỹ?
5. Số liệu dựa trên bao nhiêu mẫu, thiếu gì và dùng được đến mức nào?
6. Nên mở những tin nào để kiểm tra tiếp, và hỏi gì trước khi đi xem/đặt cọc?

Đầy đủ được hiểu là trả lời đủ các câu hỏi trên bằng bằng chứng. Số trang tăng
theo lượng thông tin có ích, không phải theo một chỉ tiêu độ dài.

## Bằng chứng từ báo cáo hiện tại

Đã đọc trực tiếp hai trang public ngày 25/10/2026 và đối chiếu config/generator:

- [Tổng quan Thủ Dầu Một 09/2026](https://radarbds.vn/bao-cao/bds-binh-duong-thang-09-2026).
- [Tân An 09/2026](https://radarbds.vn/bao-cao/tan-an-thang-09-2026).

Những phần đã có: số tin thu thập, mẫu sau lọc, giá trung vị, biểu đồ, số tín
hiệu, nhận định, phương pháp, liên kết dashboard và PDF tải xuống.

Những điểm cần xử lý trước khi thêm chỉ số:

| Quan sát có bằng chứng | Vấn đề đối với người mua | Thay đổi đề xuất |
|---|---|---|
| Tân An: 52 tin thu thập, 17 mẫu sau lọc, 7 mẫu đất nền đủ giá/m²; mức thay đổi giá đất nền +16,4% đang được làm nổi bật | 17 mẫu toàn bộ không phải 17 mẫu dùng để tính giá đất nền. Thay đổi cơ cấu của vài tin có thể làm trung vị biến động mạnh | Hiển thị n của chính phân khúc cạnh giá; chỉ so sánh xu hướng khi cả hai kỳ đạt ngưỡng và cùng định nghĩa |
| Hai ô MOS ≥10% và ≥15% đều 100% (3/3) | Đầu vào `featured_records_query` đã lọc MOS theo ngưỡng mặc định 15%; tỷ lệ này không mô tả toàn bộ thị trường. Truy vấn còn giới hạn tối đa 50 dòng | Ưu tiên số tuyệt đối 3 tín hiệu. Muốn có tỷ lệ, tính trên toàn bộ mẫu đủ định giá của cùng kỳ/phạm vi, không dùng danh sách top-N |
| 17 mẫu sau lọc nhưng bảng loại hình chỉ có 7 đất nền + 7 nhà đất | Người đọc không biết vì sao bảng có 14 thay vì 17 mẫu | Nêu số mẫu đủ từng trường và phần chưa tham gia bảng; không tự gán 3 mẫu còn lại là tin trùng hay sai dữ liệu |
| Chỉ báo “nguồn cung -59,5%” dùng số mẫu tháng trước 42 → tháng này 17 | Số mẫu Radar ghi nhận không chứng minh tồn kho toàn thị trường hoặc sức mua giảm | Ghi “số mẫu quan sát sau lọc”, kèm độ phủ crawl; chỉ gọi tồn kho khi có trạng thái theo dõi phù hợp |
| Giá/m² tham chiếu tổng quan được tính bằng trung bình có trọng số của trung vị từng phường, trọng số là tổng mẫu phường | Người đọc có thể hiểu thành trung vị đất nền gộp của toàn khu vực | Dùng phân phối mẫu đất nền gộp đủ điều kiện để tính trung vị; nếu giữ chỉ số tổng hợp thì ghi rõ công thức và không đổi tên thành trung vị toàn khu |
| Truy vấn tháng dùng `crawled_at` và latest valuation; `data_as_of` đặt về cuối tháng | Cần phân biệt cửa sổ thu thập, ngày tính giá/mô hình và ngày tạo báo cáo. Không đủ để khẳng định mọi trường là trạng thái lịch sử tại cuối tháng | Lưu snapshot bất biến, ngày quan sát giá, ngày chạy, phiên bản mô hình và phạm vi dữ liệu. Kiểm tra trước khi tái tạo báo cáo cũ |

Nguồn code: `services/monthly_report_data.py`, `scripts/enhance_monthly_report_rich.py`,
`services/signal_quality.py`, `templates/seo_report.html`.

Ngoài ra, điều kiện thống kê cần quy định tường minh tin **bán**, tách tin thuê;
hiện gate cơ sở của báo cáo không có điều kiện `tx_type` riêng. Đây là khoảng
trống hợp đồng dữ liệu cần kiểm chứng, chưa phải bằng chứng đã có tin thuê làm
sai một con số cụ thể.

## Cấu trúc nội dung mới

| Thứ tự | Câu hỏi của người đọc | Nội dung và cách trình bày |
|---|---|---|
| 1. Đọc nhanh | Tháng này cần lưu ý gì? | Một trang: 3–5 phát hiện có số liệu, 1 cảnh báo dữ liệu chính, khu vực/kỳ/n của từng chỉ số. Không mở đầu bằng tổng số lượt crawl |
| 2. Ngân sách | Tầm tiền này có lựa chọn gì? | Ma trận khoảng tổng giá × phường × loại hình, n mẫu, khoảng diện tích thực tế và số mẫu còn đang theo dõi tại ngày chốt nếu có bằng chứng |
| 3. Mặt bằng giá | Giá nào phổ biến trong phân khúc? | Giá rao tổng và giá/m²: trung vị, P25–P75, cỡ mẫu. Tách loại hình, nhóm diện tích, đường/hẻm và thông tin đất khi đủ dữ liệu |
| 4. So sánh khu vực | Có thể mở rộng tìm sang đâu? | Bảng so sánh cùng phân khúc; biểu đồ khoảng giá ngang; bản đồ phường thể hiện phạm vi quan sát, chú giải n và vùng thiếu mẫu |
| 5. Diễn biến | Giá rao và số lựa chọn thay đổi ra sao? | Đồ thị thời gian kèm n mỗi kỳ, khoảng giá và thay đổi cơ cấu. Phân biệt chỉ số giá rao của mẫu với mức tăng giá của cùng tài sản |
| 6. Giảm giá/lịch sử quan sát | Có tin nào đáng hỏi kỹ hơn? | Số tin hạ giá được quan sát, số tiền/tỷ lệ thay đổi, ngày trước/sau. Số ngày Radar ghi nhận nếu có lịch sử đủ, không gọi là số ngày bán được |
| 7. Mẫu so sánh | Những tin nào giúp kiểm chứng nhận định? | 3–6 tin có tính so sánh, phân bố theo khoảng giá; giá tổng, diện tích, giá/m², vị trí ở độ chính xác đã xác nhận, dữ kiện còn thiếu và link public |
| 8. Bối cảnh khu vực | Có thay đổi thực tế nào liên quan? | Tối đa 3–5 sự kiện hạ tầng/quy hoạch có nguồn chính thức, ngày và trạng thái rõ; giải thích điều cần kiểm tra cho vị trí cụ thể |
| 9. Trước khi đi xem | Cần hỏi và đối chiếu những gì? | Checklist: vị trí/lối đi, quy hoạch, giấy tờ, diện tích đất ở, hiện trạng, người có quyền giao dịch, điều kiện thanh toán và các khoản chi phí cần xác nhận |
| 10. Phương pháp/phụ lục | Đáng tin đến đâu? | Định nghĩa, nguồn, độ phủ, cửa sổ thời gian, dữ liệu bị loại, n theo từng bảng, phiên bản snapshot; bảng đầy đủ và liên kết đọc tiếp |

### Ma trận ngân sách

Các khoảng khởi đầu đề xuất: dưới 1,5 tỷ; 1,5–dưới 2; 2–dưới 3;
3–dưới 5; từ 5 tỷ. Đây là nhóm để tổ chức tìm kiếm, không phải kết luận về
giá trị tài sản. Một tin chỉ thuộc một khoảng; chỉ lấy tin có tổng giá hợp lệ.

Mỗi hàng trả lời: “Trong nhóm giá này, Radar ghi nhận loại tài sản nào, diện
tích phân bố ra sao và ở phường nào?”. Khoảng diện tích phải tính trên mẫu
thực tế trong nhóm; không lấy ngân sách chia giá/m² trung vị để hứa một diện tích.
Không suy tổng giá mua nhà từ giá đất/m² vì còn phần công trình và điều kiện khác.

Mẫu hàng, không chứa số liệu giả:

| Khoảng giá rao | Phường | Loại hình | n đủ giá | Diện tích P25–P75 | Giá/m² P25–P75 | Giới hạn | Mở tin hiện tại |
|---|---|---|---|---|---|---|---|
| 2–dưới 3 tỷ | Tên phường có dữ liệu | Đất nền/nhà đất | Tính từ snapshot | Tính từ đúng nhóm | Chỉ hiện khi đủ mẫu | Nêu thiếu sót | Giữ phường + loại hình + khoảng giá |

### Mẫu mở đầu từ bằng chứng hiện có

> **Tân An · dữ liệu quan sát 09/2026**
>
> Radar ghi nhận 52 tin trong cửa sổ thu thập; 17 mẫu còn lại sau các điều kiện
> lọc của báo cáo. Phân khúc đất nền đủ giá/m² chỉ có 7 mẫu, vì vậy chưa đủ
> cơ sở để dùng biến động +16,4% làm kết luận chắc chắn về giá toàn phường.
> Có 3 tín hiệu vượt bộ lọc để kiểm tra tiếp. Đây không phải số giao dịch hoặc
> bằng chứng cả phường có tỷ lệ cơ hội 100%.
>
> Để đánh giá một tin, cần đối chiếu cùng loại hình, diện tích, đường vào,
> thông tin đất và hiện trạng. Bản này chưa có ma trận ngân sách hoặc khoảng
> P25–P75 để kết luận ngân sách cụ thể mua được loại tài sản nào.

Đoạn trên là ví dụ sửa cách diễn giải các số đã có, chưa phải bản nâng cấp
hoàn chỉnh hay kết quả tính lại số liệu. Không dùng 52−17 để gọi số tin trùng:
chênh lệch còn bao gồm các điều kiện chất lượng khác.

## Quy tắc dữ liệu để báo cáo thực sự hữu ích

1. **Đúng mẫu so sánh:** Facebook theo phạm vi hiện hành, tin bán, loại hình
   đúng, giá/diện tích hợp lệ, chất lượng và lọc trùng theo hợp đồng hiện có.
   Không đổi chính sách nguồn hay mở Guland công khai trong dự án này.
2. **Giá rao và giao dịch:** dùng nhãn “giá rao” trên tiêu đề, bảng và trục.
   Chưa có giao dịch đã xác minh thì không đưa tỷ lệ bán thành công, mức chốt,
   tỷ lệ hấp thụ hay “mất bao lâu để bán” dưới dạng số liệu thực tế.
3. **Mỗi chỉ số có n riêng:** n toàn bộ, n đủ tổng giá, n đủ giá/m², n đủ
   định giá, n đủ lịch sử giá không được thay thế cho nhau. Không gọi n tin
   thu thập là số bất động sản duy nhất được chứng thực ngoài thực địa.
4. **Ngưỡng mẫu:** đề xuất dùng mức 15 đã có trong `docs/data_price_seo.md`
   cho thống kê giá theo phân khúc; dưới mức này ghi chưa đủ dữ liệu và cho
   xem mẫu riêng lẻ. Đây là ngưỡng vận hành, không phải cam kết tin cậy thống
   kê. Cả kỳ hiện tại và kỳ so sánh phải đạt ngưỡng; không tự gộp hai nhóm
   khác loại hay gán dữ liệu của phường khác thành dữ liệu địa phương.
5. **Không chỉ nhìn trung vị:** P25–P75 biểu thị khoảng chứa 50% mẫu quan sát
   ở giữa, không phải khoảng tin cậy hoặc “giá mua an toàn”. Biến động cơ cấu
   mẫu được nêu bên cạnh thay đổi giá; chưa có panel thì không gọi là chỉ số
   tăng giá của cùng tài sản.
6. **Không có dữ liệu khác với số 0:** kỳ trống, trường chưa biết và cơ sở quá
   ít phải hiển thị khác nhau; không dựng đường giá liên tục qua khoảng thiếu.
7. **Tỷ lệ đúng mẫu số:** tỷ lệ MOS dùng toàn bộ mẫu đủ định giá trong phạm vi,
   không dùng top 50 đã chọn MOS ≥15%. Khi chỉ có danh sách tuyển chọn, ghi
   số lượng và tiêu chí chọn, không vẽ tỷ lệ thị trường.
8. **Khả năng đối soát:** bảng giá toàn khu tính từ mẫu gộp phù hợp, không lấy
   trung bình của các trung vị rồi gọi là trung vị gộp. Loại hình chưa xác
   định/thiếu giá có nhóm giải thích. Lý do loại có thể chồng lặp thì công bố
   điều đó, không cộng như các nhóm loại trừ nhau.
9. **Lịch sử thật:** lưu `observed_at`, cửa sổ dữ liệu, `generated_at`,
   `valuation_as_of`, phiên bản hợp đồng/mô hình và trạng thái hiệu chỉnh.
   Dữ liệu giá tháng mới đã có snapshot bất biến trong phân hệ data-price;
   cần rà sự tương thích, không nối thẳng với chuỗi báo cáo cũ khác định nghĩa.
   Tái tạo từ bản ghi hiện tại không tự trở thành lịch sử cuối tháng.
10. **Pháp lý/vị trí:** phân biệt lời tin đăng, dữ liệu trích xuất và điều đã
    xác minh. `has_so` không chứng minh đã xem giấy tờ; không gọi là pháp lý
    an toàn. Không đặt pin chính xác từ dữ liệu chỉ xác định được tới phường.
11. **Chi phí mua:** nếu có phần dự trù tổng ngân sách, để người đọc nhập giả
    định và đánh dấu chi phí cần xác nhận. Không mặc định lãi vay, thuế/phí hay
    lợi nhuận cho mọi giao dịch; nội dung pháp lý cần nguồn phù hợp tại thời điểm.

## Thiết kế web và PDF

- Trang đầu: tên khu vực + kỳ + thông điệp chính; 4–6 chỉ số thiết yếu, mỗi
  chỉ số có đơn vị/n; một khối “Điều cần lưu ý” và nút mở tin đúng điều kiện.
- Mỗi biểu đồ có câu trả lời bằng lời, nhận xét 2–3 câu dựa trên số, phạm vi
  và ngày dữ liệu. Ưu tiên biểu đồ khoảng giá ngang, cột ngân sách và đồ thị
  thời gian; không thêm biểu đồ tròn chỉ để tăng số trang.
- Thứ tự đọc chung: **ngân sách → khu vực → khoảng giá → diễn biến → mẫu
  so sánh → điều phải kiểm tra**. Chỉ số phục vụ vận hành crawl để ở phụ lục.
- Màu chủ đạo xanh dương và font theo bộ nhận diện hiện có. Màu tăng/giảm có
  dấu/chữ đi kèm; không mặc định tăng giá là tin tốt cho người mua.
- Mobile: bảng ngân sách/khu vực trình bày 4–5 trường chính hoặc card tóm tắt;
  bảng chi tiết mở riêng, không bắt đọc 9 cột chữ nhỏ. Biểu đồ có nhãn/tóm tắt
  đọc được mà không cần hover.
- PDF: tóm tắt ở đầu, mục lục có liên kết, lặp tiêu đề bảng, số trang, nguồn
  dưới biểu đồ; khổ A4 dọc, bảng rộng bố trí lại thay vì thu chữ quá nhỏ.
  Điểm khởi đầu khoảng 8–12 trang cho tổng quan và 6–10 trang cho phường,
  linh hoạt theo dữ liệu; bỏ mục trống thay vì viết dài để đủ trang.
- Web đọc online và PDF dùng cùng snapshot đã kiểm tra. CTA “Xem tin đang
  theo dõi hiện tại” ghi rõ đó là dữ liệu hiện tại, có thể khác báo cáo tháng.
- Các tin ví dụ trong PDF được ghi trạng thái tại ngày snapshot; không hứa
  còn bán ở ngày người dùng tải hoặc liên hệ. Luôn có đường mở danh sách hiện tại.

## Khả năng thực hiện và thứ tự ưu tiên

| Giai đoạn | Nội dung | Điều kiện |
|---|---|---|
| P0: độ đúng | Mẫu số MOS, ngưỡng mẫu, nhãn giá rao/số mẫu quan sát, n từng chỉ số, nhóm thiếu dữ liệu, ngày snapshot, tin bán và công thức tổng hợp | Làm trước khi thêm lời khuyên hoặc biểu đồ |
| P1: câu hỏi mua hàng | Tóm tắt người mua, ma trận ngân sách, phân phối giá/diện tích, so sánh cùng phân khúc, checklist và trình bày web/PDF mới | Có cohort và snapshot đủ điều kiện; không tính trực tiếp trên mỗi lượt tải |
| P2: bối cảnh/lịch sử sâu | Bản đồ độ phủ, giảm giá theo lịch sử có chứng cứ, thời gian được Radar quan sát, 3–6 mẫu so sánh có giải thích, tin hạ tầng có nguồn chính thức | Đủ trường, lịch sử và nguồn xác minh; phần thiếu dữ liệu được công bố |

Sẵn có: config báo cáo, dữ liệu giá/diện tích/phường/loại hình, lịch sử giá,
đặc điểm đường/đất ở với độ đầy đủ chưa được đo trong lần đánh giá này, bộ
lọc chất lượng, pipeline tháng và xuất PDF. Phân hệ giá mới có cơ chế snapshot
bất biến cần xem xét tái sử dụng khi định nghĩa tương thích.

Cần tính và kiểm tra thêm: phân bố tổng giá, P25–P75, n từng phân khúc, chất
lượng trích xuất, độ phủ theo phường/kỳ, thời gian quan sát và lịch sử giảm
giá theo đúng cửa sổ. Không khẳng định đã có đủ dữ liệu chỉ vì DB có cột.

Cần nguồn ngoài: tình trạng hạ tầng/quy hoạch và tiện ích theo vị trí cụ thể.
Chưa có bằng chứng phù hợp: giao dịch chốt, thanh khoản thực, giá thuê/lợi
suất cho toàn phân khúc, mức thương lượng thành công. Không đưa thành số liệu
định lượng trong bản đầu.

## Tiêu chí nghiệm thu nâng cấp

- Người đọc tìm được cách tra ngân sách, so sánh phân khúc, n/độ phủ và bước
  kiểm tra tiếp trong hai trang đầu hoặc phần đầu tương ứng trên mobile.
- Mỗi phần mới có dữ liệu và câu trả lời cụ thể; không lặp lại một đoạn chung
  cho 13 phường hoặc chỉ đổi tên phường và con số.
- Kiểm tra mẫu số tỷ lệ, n, đơn vị, kỳ, cohort bán/thuê và công thức tổng hợp.
- Kiểm tra các ca: 0 mẫu, 7 mẫu, đủ mẫu, thiếu tháng trước, nhóm khác loại,
  có nhiều hơn 50 tín hiệu, thiếu pháp lý/vị trí, bản lịch sử không có snapshot.
- Chưa có đủ lịch sử: chỉ bổ sung cách đọc/giới hạn vào báo cáo cũ, không bù
  số liệu bằng giá hiện tại. Thêm chỉ số mới cho kỳ có bằng chứng phù hợp.
- Soát một báo cáo tổng quan và hai phường khác cỡ mẫu, cả web mobile và toàn
  bộ PDF. Không lỗi dấu, biểu đồ, tràn bảng; mọi liên kết và tải file hoạt động.
- Giữ pipeline deterministic, nguồn/quyền truy cập và snapshot chung; không
  đưa LLM vào tính toán hay tái xử lý dữ liệu. Có thể biên tập diễn giải sau QA.

## Tài liệu tham khảo về định nghĩa và trình bày

- [Redfin: định nghĩa các chỉ số](https://www.redfin.com/news/data-center-metrics-definitions/):
  tách giá chốt, tin đang bán, tồn kho và các mẫu số của từng metric. Tham
  khảo định nghĩa; không sử dụng số thị trường Mỹ cho Bình Dương.
- [Realtor.com: data library và giới hạn](https://www.realtor.com/research/data/):
  công bố thiếu độ phủ, mẫu nhỏ, khả năng so sánh và thay đổi chuỗi lịch sử.
- Nội bộ: `.agents/product-marketing.md`, `docs/seo-monthly-reports.md`,
  `docs/data_price_seo.md`, skills `cro`, `content-strategy`, `ui-ux-pro-max`.
