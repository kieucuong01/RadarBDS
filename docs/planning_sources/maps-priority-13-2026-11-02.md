# 13 thị trường trọng tâm — hồ sơ thị trường và kế hoạch Maps

Ngày rà: **02/11/2026**. Đơn vị: **địa bàn tỉnh/thành trước sáp nhập 2025**.
Đây là đề xuất ưu tiên sản phẩm theo yêu cầu mới của người dùng, chưa phải bảng
xếp hạng giao dịch hoặc tìm kiếm toàn quốc đã được kiểm chứng. Người dùng yêu
cầu giữ 12 địa bàn đã đề xuất và **thêm Lâm Đồng cũ**. Thứ tự cụ thể dưới đây
là thứ tự triển khai do agent đề xuất, có thể điều chỉnh; không phải hạng giao dịch.

Đọc nhanh: [danh sách và nguồn](#kết-luận-làm-việc) ·
[ma trận tính năng](#ma-trận-tính-năng-đối-chiếu-cấu-hình-hiện-tại) ·
[hồ sơ từng thị trường](#hồ-sơ-triển-khai-từng-thị-trường) ·
[kế hoạch và nghiệm thu](#kế-hoạch-nguồn-lực-và-điều-kiện-nghiệm-thu).

## Kết luận làm việc

Giữ toàn bộ 10 địa bàn trong hồ sơ trước, thêm **Bà Rịa–Vũng Tàu, Bắc Ninh cũ,
Quảng Ninh**, tổng cộng **13 địa bàn**. Lâm Đồng cũ là thị trường trọng tâm theo
chỉ đạo mới, không còn là dự phòng. Giữ dữ liệu và sửa lỗi của Bình Phước/các
tỉnh ngoài danh sách. Hồ sơ lịch sử và sổ
tính năng còn thiếu vẫn ở [maps-priority-markets.md](maps-priority-markets.md).

| Thứ tự triển khai đề xuất | Địa bàn cũ / ID | Nhóm | Cơ sở và việc đáng tập trung |
| --- | --- | --- | --- |
| 1 | Bình Dương / `binh-duong` | A | N1/N2: có bằng chứng nhu cầu và giao dịch khảo sát; địa bàn sản phẩm gốc. Làm sâu Thủ Dầu Một, Bến Cát, Dĩ An, Thuận An trước; hoàn thiện phủ nguồn, ranh, tra thửa và luồng sang tin rao. |
| 2 | TP.HCM cũ / `hcm` | A | N3 cùng hồ sơ cũ: thị trường lõi lớn, nhu cầu nhà ở đa dạng. Ưu tiên độ chính xác, hiệu năng và nối Maps–tin rao; không gán số của TP.HCM mới cho riêng HCM cũ. |
| 3 | Hà Nội / `ha-noi` | A | N3 và S3 của hồ sơ cũ: đầu mối tìm kiếm/nhà ở lớn. Chọn cụm quận/huyện để làm sâu; ranh công khai chưa đạt điều kiện thì ghi thiếu, không giả lập. |
| 4 | Đồng Nai cũ / `dong-nai` | A | N1 và S4 cũ hỗ trợ vai trò thị trường vệ tinh. Ưu tiên Biên Hòa, Long Thành, Nhơn Trạch; không lấy dữ liệu Bình Phước làm độ phủ Đồng Nai cũ. |
| 5 | Long An / `long-an` | A | N1 cùng S2 cũ: có sức hút trong nhóm phía Nam. Thí điểm Đức Hòa, Bến Lức, Cần Giuộc; cần xác minh nguồn ranh và tin rao ngoài Bình Dương. |
| 6 | Bà Rịa–Vũng Tàu / `brvt` | A, thêm | N1/N2 bổ sung cả tìm kiếm và khảo sát căn hộ. Ưu tiên Phú Mỹ, Vũng Tàu, Bà Rịa; nguồn HCM mới chỉ được tính khi thật sự giao địa bàn này. |
| 7 | Hưng Yên cũ / `hung-yen` | B | N3/N6 cùng S5 cũ: cầu vệ tinh Hà Nội. Bắt đầu Văn Giang, Văn Lâm; phân biệt đất/nhà với nhu cầu căn hộ, không nhập Thái Bình cũ vào kết quả. |
| 8 | Hải Phòng cũ / `hai-phong` | B | N6 bổ sung tín hiệu quan tâm có tách địa giới cũ. Ưu tiên lõi đô thị, Thủy Nguyên, An Dương; không suy tăng quan tâm bằng tăng thanh khoản. |
| 9 | Đà Nẵng cũ / `da-nang` | B | N4 và S8 cũ: thị trường đáng giữ trong chiến lược miền Trung. Làm Liên Chiểu, Cẩm Lệ, Hòa Vang theo cụm; nhu cầu đất đang điều chỉnh, không chạy theo giá. |
| 10 | Khánh Hòa cũ / `khanh-hoa` | B | N4 và S7 cũ: có căn cứ nhu cầu khu vực và giao dịch báo cáo trước. Ưu tiên Nha Trang, Cam Lâm, Diên Khánh; adapter ranh không đồng nghĩa đã có giao quy hoạch chi tiết. |
| 11 | Bắc Ninh cũ / `bac-ninh` | C, thêm | N5/N6: có cầu gắn Hà Nội và phân bố cụ thể trong địa bàn cũ. Thí điểm Từ Sơn, TP Bắc Ninh cũ, Tiên Du; chưa mở đồng loạt Bắc Giang vì cùng tỉnh mới. |
| 12 | Quảng Ninh / `quang-ninh` | C, thêm | N3/N6: có tín hiệu tìm kiếm ngoài hai đô thị lõi. Thử Hạ Long, Quảng Yên trước; cần chứng minh thêm nhu cầu đất/nhà và khả năng giữ người dùng Maps. |
| 13 | Lâm Đồng cũ / `lam-dong` | C, bổ sung theo yêu cầu | N7 và S9 cũ: có giao dịch công chứng thiên về đất nền, phù hợp tra thửa/quy hoạch. Ưu tiên Đà Lạt, Bảo Lộc, Đức Trọng; cần kiểm lại GIS/CRS và nguồn quy hoạch còn thiếu, không suy đã phủ Bình Thuận/Đắk Nông. |

Các cụm huyện/thành phố trong bảng là **đề xuất chọn điểm triển khai**, không
phải tuyên bố toàn bộ đều đứng đầu tìm kiếm. Nhóm A: làm sâu trước; B: mở rộng
có kiểm chứng; C: thí điểm nhỏ. Đây không phải thứ tự đo lường hạng 1–13.

## Cách chọn và mức chắc chắn

Đánh giá định tính theo bốn câu hỏi, không tạo điểm số giả từ các kỳ khác nhau:

1. Có bằng chứng tìm kiếm thực tế trên nền tảng, quy mô hay chỉ tăng trưởng?
2. Có hoạt động giao dịch/nhu cầu nhà ở trong hồ sơ trước để đối chiếu không?
3. Có phù hợp RadarBDS: tra quy hoạch, thửa đất, nhà/đất và quay lại xem tin rao?
4. Có thể làm sâu bằng nguồn đúng và duy trì hiệu năng, hay chi phí nguồn quá lớn?

Nhu cầu căn hộ giúp chọn thị trường nhưng **không chứng minh nhu cầu tra thửa
đất cùng tỷ lệ**. Bình Dương/HCM có lợi thế sản phẩm sẵn có; ưu tiên Bắc Ninh,
Quảng Ninh vẫn là quyết định cần thử nghiệm. Chưa dùng GA4/Search Console hay
phỏng vấn khách hàng của RadarBDS trong đợt này. Chưa có cùng một bảng mức độ
quan tâm của đủ 63 địa bàn cũ, cùng kỳ/cùng loại hình, để gọi là top 13 đo được.

### Nguồn mới và giới hạn sử dụng

Đọc/truy xuất ngày 02/11/2026. Nguồn báo dẫn cùng Batdongsan.com.vn không phải
các bộ dữ liệu độc lập. Tỷ lệ nền tảng không đại diện toàn bộ người mua Việt Nam.

| Mã | Nguồn / kỳ dữ liệu | Bằng chứng dùng và điều không được suy ra |
| --- | --- | --- |
| N1 | [CafeF, 31/10/2025, dẫn báo cáo Batdongsan.com.vn Q3/2025](https://cafef.vn/bat-dong-san-dang-hinh-thanh-vanh-dai-ve-tinh-soi-dong-quanh-tphcm-188251031090806932.chn) | Bốn địa bàn cũ Bình Dương, Đồng Nai, BRVT, Long An chiếm 84% quan tâm miền Nam **ngoài HCM** theo bài dẫn. Dùng làm bằng chứng cụm, không phải 84% toàn quốc hay số giao dịch. Dữ liệu đã hơn một năm; không gọi là tăng trưởng hiện tại. |
| N2 | [Cushman & Wakefield, HCMC MarketBeat Q1/2026, trang trong mục 06/2026](https://www.cushmanwakefield.com/en/vietnam/news/2026/06/hcmc-apartment-market-rebalances-as-core-prices-rise-and-demand-moves-outward) | Khảo sát bán 5.484 căn Bình Dương và khoảng 634 BRVT. Chỉ phân khúc căn hộ; không đại diện toàn bộ nhà/đất hay xếp hạng quốc gia. |
| N3 | [Batdongsan.com.vn, cập nhật 18/06/2026, dữ liệu T5/2026](https://wiki.batdongsan.com.vn/tin-tuc/thi-truong-chung-cu-giam-gia-rao-ban-tang-nhu-cau-thue-855446) | Nền tảng nói HCM **mới** gần 50%, Hà Nội 27,6% tỷ trọng quan tâm; không chia phần HCM mới cho ba tỉnh cũ. Quan tâm chung cư bán ở Đà Nẵng cũ, Quảng Ninh, Hưng Yên cũ tăng trong khoảng 9–13% so T4; bài không gán số riêng cho từng tỉnh. Đây là ngắn hạn, riêng căn hộ. |
| N4 | [Batdongsan.com.vn, cập nhật 15/10/2026, Q3/2026](https://wiki.batdongsan.com.vn/tin-tuc/thi-truong-bat-dong-san-quy-32026-gia-ha-nhiet-chung-cu-tiep-tuc-dan-dat-nhu-cau-857618) | Trong so sánh miền Trung của nguồn: Đà Nẵng 62%, Khánh Hòa 29%, Thanh Hóa 4% quan tâm BĐS bán. Không phải tỷ trọng toàn quốc; chưa tách chắc toàn bộ ranh cũ trong biểu đồ này. Chỉ dùng hỗ trợ nhóm khu vực; đất Đà Nẵng/Quảng Nam đã giảm quan tâm sau đỉnh Q3/2025. |
| N5 | [Tạp chí Kinh tế Tài chính, bài 03/07/2026, dẫn Batdongsan.com.vn Q1/2026 và dữ liệu 2026](https://tapchikinhtetaichinh.vn/bat-dong-san-bac-ninh-tu-thi-truong-ve-tinh-den-cuc-tang-truong-moi-160715.html) | Bài tách Bắc Ninh cũ và Bắc Giang cũ. Trong phần Bắc Ninh cũ, Từ Sơn 31%, TP Bắc Ninh cũ 27% quan tâm. Đây là tỷ trọng **nội bộ địa bàn**, không phải cả nước; không dùng nguồn cung làm nhu cầu hoặc mức tăng Gia Bình khi thiếu mẫu số/kỳ gốc. |
| N6 | [Cổng Hải Phòng, điểm báo 25/06/2026, dẫn dữ liệu Batdongsan.com.vn 2026](https://haiphong.gov.vn/diem-bao/diem-bao-hang-ngay-ve-hai-phong-25-6-2026-921949) | Chỉ đọc được bản lập chỉ mục tìm kiếm trong đợt này; mở toàn trang timeout. Bản chỉ mục nêu Hải Phòng cũ chiếm 93% quan tâm bán trong Hải Phòng mới; nhóm địa phương được người Hà Nội quan tâm: Hưng Yên 23%, Hải Phòng 19%, Quảng Ninh/Bắc Ninh 10% mỗi nơi. Chưa chốt mẫu số đầy đủ, không dùng để xếp hạng toàn quốc hoặc tách địa giới cũ HY/BN. Đất Hải Phòng Q1/2026 giảm quan tâm YoY là tín hiệu ngược cần giữ. |
| N7 | [Kinh doanh & Phát triển, 25/06/2025, dẫn Sở Tư pháp Lâm Đồng](https://kinhdoanhvaphattrien.vn/giao-dich-bat-dong-san-thanh-cong-o-lam-dong-tang-gan-50-sau-mot-quy-43265.html) và [VnExpress cùng ngày](https://vnexpress.net/giao-dich-dat-nen-da-lat-bao-loc-tang-40-theo-quy-4905938.html) | Đọc lại trong đợt bổ sung: 6.591 đất nền + 388 nhà riêng + 18 căn hộ = 6.997 giao dịch báo cáo Q2/2025 qua 47 tổ chức công chứng. Đây là Lâm Đồng cũ; bài xuất bản trước hết quý, chưa chốt ngày khóa sổ, không so như quý đủ. Hai bài cùng dựa báo cáo Sở, không phải hai mẫu độc lập. Không dùng làm chỉ số tìm kiếm hay bằng chứng tăng cầu năm 2026. |

Nguồn S1–S9 và giới hạn giao dịch của báo cáo trước được giữ nguyên trong
[hồ sơ top 10 lịch sử](maps-priority-markets.md#nguồn-thị-trường--truy-cập-ngày-2026-11-02).
Không coi việc dẫn lại hồ sơ là đã xác minh mới toàn bộ chín báo cáo đó. N2 đã
đọc lại trực tiếp. PDF báo cáo tháng 4/2026 trên mirror NHSV gặp 404, nên các
con số chưa kiểm được từ PDF đó **không được dùng** để chốt danh sách.

### Những nơi ngoài nhóm 13

| Địa bàn | Quyết định và điều kiện xem lại |
| --- | --- |
| Bắc Giang cũ | Có thị trường trong N5, nhưng số nội bộ không chứng minh quy mô vượt Bắc Ninh cũ; thí điểm Bắc Ninh trước. Xem lại khi có quy mô cầu so sánh được hoặc nguồn GIS khả thi hơn. |
| Thanh Hóa | Có tín hiệu trong N4 nhưng không đủ căn cứ đứng trên Đà Nẵng/Khánh Hòa về phù hợp sản phẩm hiện tại. Theo dõi khi có dữ liệu đất/nhà và người dùng thực. |
| Bình Phước cũ | Giữ toàn bộ ranh/lớp đã làm. Không tự chuyển thành ưu tiên mở rộng chỉ vì có snapshot; cần chứng minh nhu cầu sử dụng/chuyển đổi. |
| Các địa bàn khác | Chưa mở rộng công việc thu thập mới trong đợt nghiên cứu này; tiếp tục giữ nguồn đã chạy và sửa lỗi. Không kết luận ít giao dịch. |

## Sổ tiếp tục cho agent sau

- Chất lượng lớp: [audit 13 tỉnh, mẫu gần/xa và lỗi nguồn](priority-13-layer-quality-2026-11-02.md).
  Không coi mẫu HTTP200 là nghiệm thu phủ kín; giữ riêng403/404 và timeout GIS primary.

- Ranh GIS: xem [đợt rà lại đủ 13 địa bàn sau release b59294a6](priority-13-parcel-gis-recheck-2026-11-02.md).
  Chưa tìm được provider mới đạt điều kiện; Bắc Ninh tenant hiện là Bắc Giang cũ,
  Hải Phòng mới xác minh API quy hoạch/DVHC, các nguồn blocked vẫn chưa phục hồi.

- **Đợt này chỉ cập nhật nghiên cứu và định hướng**, không khởi động crawl hoặc
  tuyên bố hoàn thiện 13 địa bàn. Đọc guide, HEAD và deployed SHA trước khi làm.
- Mười nơi giữ lại: tiếp tục ma trận tính năng trong hồ sơ cũ và audit GIS 3–10.
  Ma trận đó là snapshot; không lấy trạng thái local/blocked cũ làm production hiện tại.
- Ba nơi thêm: đối chiếu registry thật rồi lập ma trận SDĐ 2030 / phân khu /
  chung / chi tiết / xây dựng / địa giới / ranh / tọa độ / chi tiết thửa /
  tin rao / mobile / hiệu năng. **Chưa audit đủ, không đánh dấu hoàn tất**.
  QH chung mới có thể xem `general-reference.md`; nguồn HCM xem các doc GIS
  trong guide. Lớp đã đăng ký không chứng minh phủ kín hoặc còn hiệu lực.
- Ranh thửa: GIS công khai hoạt động trước; Guland cần thu thập thì ghi
  `deferred_guland`, không mở collector chỉ vì tỉnh vào danh sách này.
- Giữ nguyên quy tắc đo bằng polygon gốc, CRS địa phương, GIS chi tiết chỉ gọi
  khi người dùng yêu cầu, viewport/cancellation/cache/privacy. Không ghép QH
  khác vào phân khu tổng để tạo cảm giác có đủ dữ liệu.
- Nên kiểm kết quả sau 4–8 tuần triển khai: người dùng Maps theo **địa bàn đang
  xem**, quay lại, tra thửa thành công/không có nguồn, thời gian tải, xem tin rao
  và hành động liên hệ hợp lệ. Đây là kế hoạch đo, chưa phải đã cài sự kiện.
  So cùng khoảng thời gian và phân biệt nguồn traffic; không dùng vài lượt
  tăng đột biến hoặc số tin đăng làm tiêu chí thắng.
- Nếu chỉ đủ làm một cụm: hoàn thiện Bình Dương → HCM cũ → Đồng Nai/Long An/BRVT;
  mở cụm phía Bắc có Hà Nội làm đầu mối, rồi miền Trung. Chất lượng mỗi cụm quan
  trọng hơn đồng loạt bật lớp cho đủ tên tỉnh.

## Ma trận tính năng đối chiếu cấu hình hiện tại

Đối chiếu local HEAD `0249024cae7c5e62ab4d2a4e8a7114853177c830` và worktree
ngày 02/11/2026. **Không kiểm lại VPS, edge hoặc toàn bộ tile trong đợt tổng hợp**.
Đã chạy truy vấn Graphify để định tuyến module, rồi đọc registry/doc nguồn trực
tiếp; graph có cảnh báo lệch phiên bản và kết quả rút gọn nên không dùng nó để
chứng nhận độ phủ.

Ký hiệu: **R** = nguồn ảnh tham khảo đã đăng ký; **G** = GIS đã tích hợp theo
phạm vi nguồn; **—** = chưa thấy tích hợp đúng theme trong cấu hình đã rà,
không có nghĩa địa phương không có quy hoạch. Một lớp có thể chỉ có ảnh ở một
số mức zoom/vài đô thị. Không cột nào dưới đây có nghĩa hoàn tất toàn tỉnh.

| Địa bàn cũ | SDĐ 2030 | Phân khu | QH chung | QH chi tiết | QH xây dựng | Ranh/góc ranh và tra thửa |
| --- | --- | --- | --- | --- | --- | --- |
| Bình Dương | R | G + giữ PDF | G | G, từng đồ án | R | Snapshot + GIS, 91 đơn vị lịch sử trong registry; phải rà phần thiếu/định danh và ngày cập nhật. |
| TP.HCM cũ | R | G | G | G, từng đồ án | R | GIS live; không suy đã có snapshot/offline toàn thành phố. |
| Hà Nội | R | R | — | — | — | Mẫu trước chưa thành provider được xác minh; audit GIS ghi lỗi TLS. |
| Đồng Nai cũ | R | — | — | — | R | 18 tham chiếu mẫu cũ, không phải toàn tỉnh; cổng địa chính audit ghi bảo trì. |
| Long An | R | — | — | — | — | WFS có schema/count, GetFeature lỗi; chưa có adapter ranh dùng được. |
| BRVT | R, hai layer ID | G | G | G, từng đồ án | R | GIS HCM mở rộng; cần kiểm từng khu, đặc biệt Côn Đảo; không gán snapshot Bình Dương sang đây. |
| Hưng Yên cũ | R | — | — | — | R, có đồ án Văn Giang | Chưa xác minh nguồn đúng Hưng Yên cũ; đầu mối Thái Bình không thay thế. |
| Hải Phòng cũ | R | R | R | — | R | Cổng có trang quy hoạch, chưa xác minh polygon địa chính; route đất đai audit ghi 404. |
| Đà Nẵng cũ | R | R | — | — | R | Portal/ArcGIS audit ghi timeout/503; chưa thêm provider ranh. |
| Khánh Hòa cũ | R | R | — | — | R | Adapter GIS 134 tham chiếu/8 huyện đã có trong code/doc; cần kiểm release hiện hành. WGS84 có, hệ VN-2000 riêng và giao QH chi tiết còn thiếu. |
| Bắc Ninh cũ | R | R | R | — | R | Đợt tổng hợp này chưa có bằng chứng provider ranh đúng địa bàn; cần audit riêng. |
| Quảng Ninh | R | R | R | — | — | Chưa có bằng chứng provider ranh trong hồ sơ đã rà; cần audit riêng. |
| Lâm Đồng cũ | R | — | — | — | — | Audit trước ghi TLS hết hạn; chưa tích hợp polygon địa chính được xác minh. |

Các số đếm cấu hình chỉ dùng làm self-check: 13/13 có liên kết SDĐ2030;
6/13 có **reference** phân khu ngoài ba địa bàn GIS HCM; 3/13 có **reference**
QH chung ngoài ba địa bàn GIS HCM; 9/13 có reference xây dựng. Không gọi các
tỷ lệ này là tỷ lệ hoàn thiện hoặc phần trăm diện tích phủ.

Nguồn kiểm: `config/planning_landuse_areas.json`, `planning_landuse_2030.json`,
`planning_partition_reference.json`, `planning_general_reference.json`,
`planning_construction.json` cùng hai audit general/construction; các doc
[phân khu HCM](hcm-expanded-partition.md), [QH chung GIS](general-planning-speed.md),
[QH chi tiết GIS](detailed-gis.md), [QH chung tham khảo](general-reference.md),
[xây dựng](construction-reference.md), [ranh Khánh Hòa](khanh-hoa-parcels.md),
[audit GIS](priority-gis-parcels-2026-11-02.md). Các doc cũ có mốc local/deploy
khác nhau: trước release phải đối chiếu code và SHA thực, không chép trạng thái
cũ thành kết luận production hiện tại.

Địa giới cũ/mới đã có nền tảng toàn quốc, nhưng phải kiểm hover/zoom, tên và
membership từng tỉnh. Vẽ đo, chỉ đường, marker chọn thửa, OCR góc ranh và nhập
tọa độ là **công cụ dùng chung**; thiếu nguồn thửa hoặc hệ chiếu đúng thì không
thể đánh dấu chức năng tra cứu của tỉnh đã đầy đủ. Các lớp giao thông/tầm nhìn
HCM không tự mở rộng sang cả 13 tỉnh.

## Hồ sơ triển khai từng thị trường

Các địa bàn con bên dưới đều dùng tên cũ để khớp dữ liệu Maps. Chọn điểm đầu
là quyết định sản phẩm, không phải thống kê mỗi huyện đứng đầu tìm kiếm.
Mỗi hồ sơ có một việc có thể bắt đầu và một điều kiện chặn để tránh làm lan man.

### 1. Bình Dương — làm chuẩn cho toàn bộ sản phẩm

- **Vai trò:** địa bàn có dữ liệu tin rao và quy trình sản phẩm sâu nhất; dùng
  làm mẫu chất lượng rồi mới nhân rộng. Căn cứ N1/N2 và sổ giao dịch trước.
- **Điểm đầu:** Thủ Dầu Một/Tân An để hồi quy click thửa; Bến Cát/Mỹ Phước,
  Dĩ An, Thuận An để mở kiểm nguồn. Sau đó rà các huyện còn lại theo danh mục.
- **Ưu tiên:** kiểm lớp nguồn theo vùng nhìn; ranh đúng khi bật/tắt/zoom; popup
  cơ bản ngay, chi tiết GIS theo yêu cầu; giữ lọc giá/diện tích/thời gian/loại
  hình khi kéo bản đồ; marker tin rao ưu tiên click và link share giữ camera.
- **Cần bổ sung bằng chứng:** ma trận huyện/phường–nguồn, mẫu thửa méo/multipart,
  hồ sơ VN-2000 và tình trạng cập nhật. Có snapshot không có nghĩa dữ liệu mới.
- **Điều kiện qua:** luồng tìm khu vực → chọn thửa → đo/vẽ → chi tiết → xem tin
  rao chạy đúng trên desktop/mobile; thiếu nguồn phải báo rõ, không treo Maps.

### 2. TP.HCM cũ — độ ổn định ở đô thị lớn

- **Vai trò:** giữ người dùng tìm nhà ở và tra khu vực; dùng N3 với ranh giới
  mới/cũ được tách rõ, không phân bổ tỷ trọng của HCM mới theo phỏng đoán.
- **Điểm đầu:** Thủ Đức; một cụm nội thành; một cụm ngoại thành như Củ Chi/Hóc Môn
  để kiểm nguồn và nhu cầu khác nhau. Đây là mẫu triển khai, chưa là bảng cầu.
- **Ưu tiên:** đo tải lạnh/nóng của tile/cell; tránh chồng bản tổng với đồ án
  khác; chọn thửa không cản listing marker; giữ camera khi đóng modal tin rao.
- **Khoảng trống:** GIS live có thể lỗi/trống theo vùng. Cần đối chiếu source,
  phê duyệt và độ phủ từng lớp; không gán đồng loạt tỷ lệ 1/500 hay 1/10000.
- **Điều kiện qua:** nhiều lớp đang bật vẫn hủy request cũ, kết quả mới nhất
  thắng; nguồn lỗi không khóa nền/ranh đang có hoặc làm sai trạng thái chọn.

### 3. Hà Nội — đầu mối cụm phía Bắc

- **Vai trò:** nhu cầu nhà ở/tìm kiếm lớn trong N3 và S3; cần tách căn hộ khỏi
  giá trị sử dụng của tính năng ranh đất. Không dùng căn hộ bán để dự báo lượt tra thửa.
- **Điểm đầu:** Gia Lâm/Đông Anh/Hoài Đức để thử đất–nhà vệ tinh; Hà Đông để kiểm
  nhu cầu nhà ở đô thị. Chỉ mở khi danh mục nguồn thật phù hợp từng nơi.
- **Ưu tiên:** kiểm source phân khu tổng đang có, lập vùng trống; kiểm lại TLS
  cổng chính thức trước khi viết thêm adapter; tách QH2045–2065/100 năm khỏi QH chung.
- **Khoảng trống:** chưa có ranh được xác minh dùng được trong audit hiện tại;
  QH chung/chi tiết/xây dựng chưa có theme đúng trong bảng rà.
- **Điều kiện qua:** ít nhất một cụm có polygon + số tờ/thửa thật nếu bật ranh;
  nếu chưa có, công khai chỉ dùng được lớp tham khảo, không dựng polygon từ ảnh.

### 4. Đồng Nai cũ — tách dứt khoát khỏi Bình Phước

**Đợt xử lý tiếp theo 02/11/2026:** xem [audit và việc đã sửa](dongnai-priority-review-2026-11-02.md).
44 mẫu ảnh 2030/xây dựng tải được; đã sửa notice sai phạm vi. Cổng địa chính
vẫn bảo trì; provider hiện tại trả 0 thửa cho 11 mã huyện Đồng Nai cũ. Chưa
thêm ranh/phân khu/chung/chi tiết khi chưa xác minh được nguồn; chưa deploy.

- **Vai trò:** mở tiếp phía Đông từ hệ sinh thái Bình Dương/HCM; N1/S4 là căn cứ
  thị trường, chưa có tổng giao dịch chuẩn toàn tỉnh cùng kỳ để xếp hạng.
- **Điểm đầu:** Biên Hòa → Long Thành → Nhơn Trạch; mở cụm theo khả năng nguồn.
- **Ưu tiên:** giữ lớp 2030 và xây dựng đã đăng ký; kiểm lại cổng địa chính cũ
  khi hết bảo trì, xác minh polygon bằng điểm trong Đồng Nai cũ trước tích hợp.
- **Khoảng trống:** phân khu/chung/chi tiết chưa đăng ký trong bộ cấu hình rà;
  mẫu 18 tham chiếu chưa phải nguồn bulk hoặc 18 vùng phủ.
- **Điều kiện qua:** test âm ở rìa giáp Bình Phước; chọn Đồng Nai không được
  trả thửa hoặc báo đủ nguồn chỉ vì provider có tên “Đồng Nai mới”.

### 5. Long An — thí điểm vệ tinh phía Tây

- **Vai trò:** nhu cầu vệ tinh có căn cứ N1/S2, phù hợp thử Maps nhà/đất;
  không gán số giao dịch nhà phố/biệt thự cả vùng DKRA cho riêng Long An.
- **Điểm đầu:** Đức Hòa, Bến Lức, Cần Giuộc; Châu Thành là nơi kiểm kỹ thuật WFS,
  không mặc định là điểm thu hút người dùng mạnh nhất.
- **Ưu tiên:** xử lý điều kiện nguồn GetFeature trả lỗi, kiểm polygon/ID đúng
  Long An cũ, xác minh CRS; chỉ thêm adapter sau khi có geometry dùng được.
- **Khoảng trống:** hiện bảng rà chỉ có SDĐ2030; thiếu các theme khác và ranh.
  WFS count không phải kho polygon đã tải thành công.
- **Điều kiện qua:** tra điểm/tờ-thửa cùng trả đúng định danh và đường bao; nếu
  upstream vẫn lỗi, giữ `blocked_source`, chuyển việc sang địa bàn khác.

### 6. BRVT — tận dụng nguồn HCM mở rộng, kiểm đúng phạm vi

- **Vai trò:** bổ sung vào nhóm làm sâu nhờ N1/N2; dữ liệu căn hộ là căn cứ phụ
  cho thị trường, chưa đủ chứng minh nhu cầu tra đất mọi huyện.
- **Điểm đầu:** Phú Mỹ, Vũng Tàu, Bà Rịa; sau đó Long Điền/Đất Đỏ/Châu Đức/Xuyên Mộc.
  Côn Đảo cần ca kiểm riêng, không để ngoài bbox rồi vẫn ghi toàn tỉnh.
- **Ưu tiên:** rà polygon/metadata/độ phủ nguồn GIS HCM mới giao địa bàn;
  xử lý hai layer ID 2030 đúng chủ ý, không bật chồng tự động gây rối.
- **Khoảng trống:** cần kiểm ranh và chi tiết từng khu, thiếu bằng chứng snapshot
  bao phủ toàn địa bàn; nguồn ảnh có màu không bảo đảm định vị thửa chính xác.
- **Điều kiện qua:** mẫu đất liền và đảo nếu có source, lỗi thiếu nguồn riêng;
  dữ liệu cũ/mới có nhãn rõ và không bị nhập nhầm với Bình Dương.

### 7. Hưng Yên cũ — cầu gắn Hà Nội

- **Vai trò:** N3/S5 hỗ trợ thử cụm vệ tinh; tăng quan tâm căn hộ theo tháng
  không chứng minh tương tự với đất thổ cư hay ranh hộ lẻ.
- **Điểm đầu:** Văn Giang, Văn Lâm; mở rộng sau khi có nhu cầu sử dụng thực.
- **Ưu tiên:** dùng đúng lớp xây dựng đã có theo phạm vi Văn Giang; giữ tên
  theme nguồn; tìm DB GIS thuộc Hưng Yên cũ trước khi bật ranh.
- **Khoảng trống:** chưa có phân khu/chung/chi tiết riêng trong registry rà;
  DB `thaibinhcsdl` không dùng để lấp thiếu Hưng Yên cũ.
- **Điều kiện qua:** mẫu polygon nằm đúng địa bàn và số tờ/thửa đúng namespace;
  menu chỉ hiện lớp có nguồn, không lấy xây dựng đổi tên thành phân khu.

### 8. Hải Phòng cũ — lớp nguồn tương đối sẵn, ranh chưa xác minh

- **Vai trò:** N6 bổ sung góc nhìn nhu cầu, nhưng chỉ đọc được bản chỉ mục;
  không nâng confidence bằng cách cộng nhiều bài cùng một báo cáo.
- **Điểm đầu:** lõi đô thị, Thủy Nguyên, An Dương; tách Hải Dương cũ khỏi scope.
- **Ưu tiên:** kiểm phân khu/chung/xây dựng đã đăng ký, vùng trống và mức zoom
  native. Tìm lại route đất đai hoạt động trước khi phát triển adapter ranh.
- **Khoảng trống:** QH chi tiết và polygon địa chính chưa xác minh; cổng quy hoạch
  mở được không chứng minh có endpoint thửa. Cần kiểm lại tín hiệu cầu đất đang giảm.
- **Điều kiện qua:** các lớp có ảnh đúng tỉnh qua vài mức zoom, không tạo request
  hàng loạt để lấp overview; tra cứu thiếu nguồn trả trạng thái riêng.

### 9. Đà Nẵng cũ — giữ điểm tập trung miền Trung

- **Vai trò:** N4 hỗ trợ vị trí thị trường, nhưng cần giữ tín hiệu ngược về
  giảm quan tâm đất sau đỉnh. Không dùng tỷ trọng miền Trung thành tỷ trọng quốc gia.
- **Điểm đầu:** Liên Chiểu, Cẩm Lệ, Hòa Vang; bổ sung Sơn Trà/Ngũ Hành Sơn nếu
  thử nghiệm cho thấy Maps nhà ở cần thiết. Không tự bao gồm Quảng Nam cũ.
- **Ưu tiên:** nguồn phân khu/xây dựng đang có; kiểm cổng GIS/ArcGIS khi phục hồi,
  tách trạng thái timeout, không có dữ liệu và không có quy hoạch.
- **Khoảng trống:** chưa có QH chung/chi tiết đúng theme trong bộ rà và ranh
  chưa xác minh; không coi portal lỗi là toàn Đà Nẵng không có GIS.
- **Điều kiện qua:** định vị đúng khu vực cũ; các công cụ đo vẫn dùng được khi
  nguồn quy hoạch lỗi; không hiện kết luận pháp lý từ pixel ảnh.

### 10. Khánh Hòa cũ — ưu tiên hoàn thiện adapter đã có

- **Vai trò:** N4/S7 hỗ trợ nhu cầu và hoạt động giao dịch; có lợi thế nguồn
  ranh đã xác minh trong code, phù hợp hoàn thiện thay vì mở collector mới.
- **Điểm đầu:** Nha Trang, Cam Lâm, Diên Khánh; sau đó kiểm đủ tám huyện trong
  phạm vi adapter. Không bao gồm Ninh Thuận/Trường Sa theo phỏng đoán.
- **Ưu tiên:** kiểm viewport/cell/point/sheet-parcel, namespace và tên huyện/xã;
  bổ sung bằng chứng release hiện tại, tính nhất quán geometry gốc khi đo.
- **Khoảng trống:** VN-2000 TM-3 địa phương chưa tích hợp trong hồ sơ adapter;
  chưa có giao quy hoạch chi tiết thửa, QH chung/chi tiết raster riêng chưa đăng ký.
- **Điều kiện qua:** thửa tìm bằng điểm và tờ/thửa khớp nhau; thông tin cơ bản
  chạy được; chi tiết chưa có phải báo unavailable, không kết luận không vướng QH.

### 11. Bắc Ninh cũ — thử cụm đô thị–công nghiệp

- **Vai trò:** N5 có phân bố cầu trong địa bàn cũ; đủ chọn thí điểm, chưa chứng
  minh đứng trên các tỉnh khác về số lượt tìm kiếm tuyệt đối.
- **Điểm đầu:** Từ Sơn, TP Bắc Ninh cũ, Tiên Du; sau đó Thuận Thành/Yên Phong
  tùy nguồn và hiệu quả. Không lấy biến động giá Gia Bình làm bằng chứng cầu bền.
- **Ưu tiên:** kiểm phân khu/chung/xây dựng hiện có, tọa độ và tên cũ; audit
  nguồn địa chính riêng trước khi hứa có tra ranh/góc ranh.
- **Khoảng trống:** chưa có bằng chứng provider ranh và QH chi tiết tích hợp;
  không gộp Bắc Giang cũ vì dùng chung tên tỉnh mới.
- **Điều kiện qua:** một cụm Maps có nguồn đúng và đo được người dùng quay lại;
  kết quả nguồn/tìm kiếm trong địa bàn phải tách rõ Bắc Giang.

### 12. Quảng Ninh — thử nhu cầu Maps ngoài hai vùng lõi

- **Vai trò:** N3/N6 có tín hiệu quan tâm, còn bằng chứng riêng đất/nhà và
  chuyển đổi RadarBDS cần bổ sung; không suy nhu cầu từ giá căn hộ tăng.
- **Điểm đầu:** Hạ Long, Quảng Yên; mở Cẩm Phả/Uông Bí sau khi có căn cứ sử dụng.
- **Ưu tiên:** kiểm phân khu/QH chung đang có và khả năng nhìn khi zoom xa;
  không kéo vượt min native để gọi tile không tồn tại.
- **Khoảng trống:** chưa có xây dựng/chi tiết đúng theme trong registry rà,
  ranh chưa audit riêng; không nói “không có GIS” khi chưa rà nguồn chính thức.
- **Điều kiện qua:** lớp hiện đúng window, menu không hứa loại chưa có; quyết
  định mở rộng dựa cả nhu cầu đất/nhà và nguồn ranh có thể duy trì.

### 13. Lâm Đồng cũ — bổ sung chính thức vào phạm vi tập trung

- **Vai trò:** theo chỉ đạo người dùng giữ lại trong nhóm trọng tâm. N7/S9 có
  hoạt động công chứng thiên về đất nền, phù hợp sản phẩm tra thửa/quy hoạch.
  Độ chắc chắn về **quan tâm tìm kiếm hiện tại** thấp hơn bằng chứng giao dịch lịch sử.
- **Điểm đầu đề xuất:** Đà Lạt, Bảo Lộc, Đức Trọng; cụm tiếp theo Bảo Lâm/Lâm Hà.
  Đà Lạt/Bảo Lộc phục vụ kiểm nhà–đất đô thị; Đức Trọng giúp thử đất hộ lẻ.
  Chưa tự mở Bình Thuận/Đắk Nông vì cùng Lâm Đồng mới.
- **Ưu tiên:** kiểm lại điều kiện TLS của cổng trước; tìm đồ án chính thức đúng
  địa bàn, nguồn polygon/CRS/ID. Giữ 2030 hiện có; không đổi lớp đó thành phân khu.
- **Khoảng trống:** phân khu/chung/chi tiết/xây dựng chưa có đúng theme trong
  registry; ranh chưa có adapter xác minh, không trace ảnh quy hoạch làm địa chính.
- **Điều kiện qua:** công bố rõ phạm vi của một cụm dùng được, mẫu tra điểm và
  tờ/thửa nếu có polygon; mọi góc ranh/đo cạnh phải dùng geometry gốc, không suy
  từ ranh hành chính. GIS không dùng được thì ghi chờ nguồn; Guland ranh làm sau.
- **Bằng chứng cần làm mới:** kỳ công chứng sau này tách Lâm Đồng cũ, mức quan
  tâm nhà/đất theo địa bàn, dữ liệu dùng Maps thực. Không lấy số 2026 gộp ba
  tỉnh hoặc nội dung SEO của trang rao bán làm chỉ số cầu đã xác minh.

## Kế hoạch nguồn lực và điều kiện nghiệm thu

### Thứ tự thực hiện

1. **Làm mẫu chất lượng:** Bình Dương, HCM cũ. Chốt cách đo coverage, độ trễ,
   trạng thái thiếu nguồn, công cụ chọn/đo/tra thửa và mobile trước khi nhân rộng.
2. **Mở cụm phía Nam:** Đồng Nai cũ, Long An, BRVT. Có thể làm BRVT trước nếu
   GIS đã dùng được trong khi hai nơi kia chờ nguồn; không sửa số thứ tự thị
   trường thành tuyên bố thứ hạng tìm kiếm.
3. **Mở cụm phía Bắc:** Hà Nội làm đầu mối, Hưng Yên/Hải Phòng theo nguồn;
   Bắc Ninh/Quảng Ninh thí điểm trước mở rộng. Nguồn blocked thì chuyển việc
   có ích tiếp theo, không crawl Guland hàng loạt để thay thế mặc định.
4. **Miền Trung và Lâm Đồng:** hoàn thiện adapter Khánh Hòa đang có; kiểm Đà Nẵng
   khi nguồn phục hồi; Lâm Đồng bắt đầu bằng audit nguồn theo cụm đã chọn.

Đây là các đợt theo phụ thuộc, không phải lịch cam kết ngày hoàn thành hoặc
phân bổ ngân sách đo được. Mỗi lúc nên có một cụm đang hoàn thiện và một hàng
nguồn đang kiểm; tránh bật đồng loạt 13 tỉnh rồi mới kiểm chất lượng.

### Checklist cần lưu theo từng tỉnh/cụm

| Mục | Bằng chứng cần có trước khi ghi hoàn thành |
| --- | --- |
| Nguồn/địa bàn | URL nguồn, ngày kiểm, tỉnh/huyện/xã cũ, theme đúng, phạm vi thật; ghi riêng quyết định/tỷ lệ/hiệu lực còn chưa xác minh. |
| Độ phủ | Danh mục vùng cần có, các vùng đã kiểm và còn thiếu; bbox và vài tile dương tính không thay thế audit độ phủ. |
| Lớp ảnh | Tải theo viewport, đúng native zoom; bật/tắt/độ mờ/đổi tỉnh không lệch; vùng trống và lỗi nguồn phân biệt được. |
| Ranh/tra thửa | Polygon gốc hợp lệ, số tờ/thửa/diện tích/ID đúng; ca biên, multipart/holes; không thu thập dữ liệu chủ đất. |
| Tọa độ/OCR | WGS84 và VN-2000 đúng hệ chiếu địa phương; OCR để người dùng kiểm lại, không tự coi nhận diện là tọa độ chuẩn. |
| Popup/chi tiết | Cơ bản mở nhanh; GIS chi tiết chỉ theo thao tác; diện tích giao thực và provenance, unavailable không đồng nghĩa không có QH. |
| Đo/vẽ | Vẽ tự do chồng lên thửa đã chọn, marker/diện tích/cạnh không chồng nhãn; đóng popup không tự xóa ranh chọn. |
| Tin rao | Chỉ hiện dữ liệu thực có; giữ filter phi địa lý khi kéo; nhóm marker mở danh sách; đóng modal giữ camera/map mode. |
| UI | Mobile gọn, dock/popup không che phần lớn bản đồ; bấm ngoài đóng panel; loading và lỗi dễ hiểu. |
| Share | URL giữ map mode, khu vực/camera/lớp cần thiết; không chứa cookie, thông tin cá nhân hay token nguồn. |
| Hiệu năng | So tải lạnh/nóng, request/byte, p95 và khung hình trên thiết bị thật; cache/cancellation/newest-wins; không lặp tải cả tỉnh. |
| Release | SHA local/push/VPS tách rõ, CI phù hợp, service/API/edge/browser proof, assets và rollback; không ghi deployed từ local test. |

### Cách quyết định tỉnh nào đáng đầu tư tiếp

Đo theo **địa bàn bản đồ đang xem**, không chỉ vị trí IP người dùng. Tối thiểu
theo dõi người dùng Maps có hoạt động, người quay lại, chọn thửa/tìm thửa thành
công, tỷ lệ lỗi/thiếu nguồn, xem tin rao từ Maps và hành động liên hệ hợp lệ.
Đây là danh mục đo cần thiết, **chưa cài mới tracking trong task này**.

So theo cùng cửa sổ 28 ngày sau khi tính năng ổn định, cùng nguồn traffic và
phạm vi tính năng; quan sát thêm khi lượng mẫu nhỏ. Không ép một tỉnh chưa có
tin rao phải đạt chuyển đổi liên hệ như Bình Dương. Chưa đủ traffic thì dùng
kiểm tác vụ với người dùng thực; không bịa ngưỡng tăng trưởng hoặc KPI hoàn thành.

Mỗi lần tiếp tục, cập nhật hàng tỉnh bằng: **ngày → phạm vi → nguồn → trạng
thái → bằng chứng → blocker → bước kế tiếp**. `registered`, `verified_local`,
`deployed`, `partial` và `complete` là các trạng thái khác nhau. Giữ lại lịch sử
không đạt/thiếu nguồn để agent sau không lặp lại nghiên cứu thất bại.
