# Thị trường ưu tiên Maps — định hướng hiện hành và sổ tiến độ

**Cập nhật định hướng 02/11/2026:** người dùng yêu cầu giữ 12 địa bàn vừa đề
xuất và thêm Lâm Đồng cũ. Dùng [hồ sơ chi tiết 13 thị trường](maps-priority-13-2026-11-02.md)
làm định hướng hiện hành: toàn bộ 10 nơi cũ + BRVT/Bắc Ninh cũ/Quảng Ninh.
Lâm Đồng không còn dự phòng. Thứ tự thực hiện vẫn là đề xuất sản phẩm, không
phải xếp hạng giao dịch/tìm kiếm quốc gia. Hồ sơ mới có nguồn, giới hạn, ma trận
cấu hình, từng cụm triển khai và checklist; không chứng nhận đầy đủ/deployed.
Các phần top 10 và tiến độ dưới là **hồ sơ lịch sử**, không xóa backlog.

Nghiên cứu mới không tự khởi động thu thập ranh hàng loạt: GIS hoạt động trước,
Guland tra thửa tiếp tục để sau. Ngoài 13 nơi, giữ dữ liệu và sửa lỗi; hoãn mở
rộng khi thiếu nguồn. Không suy ranh phủ toàn quốc từ lớp 2030/địa giới.

Ngày nghiên cứu/đối chiếu: **2026-11-02**. Code đối chiếu:
`20246dfbf8ed489c12bc1fdb696bea9fbcff62db`.

**Cập nhật GIS 3–10 cùng ngày:** người dùng yêu cầu hoàn thiện nguồn GIS dùng
được, còn tra Guland ghi lại làm sau. Xem
[audit GIS tám địa bàn](priority-gis-parcels-2026-11-02.md) và
[adapter Khánh Hòa mới](khanh-hoa-parcels.md). Các hàng tiến độ dưới đã cập nhật;
baseline SHA trên là mốc đối chiếu ban đầu, không phải deployed SHA mới.

## Quyết định của người dùng và giới hạn nghiên cứu

Người dùng yêu cầu ưu tiên làm Maps **kỹ, chính xác, đủ tính năng** cho 10 địa bàn
có hoạt động giao dịch lớn; lưu cả việc chưa làm để AI/dev sau tiếp tục. Ngoài
danh sách, có thể hoãn khi thiếu nguồn hoặc chưa triển khai được. Sau khi được
thông báo chưa có dữ liệu đồng nhất, người dùng chọn: **“Lưu 10 thị trường ưu
tiên tạm thời, ghi rõ giới hạn”**.

Đây là **danh sách ưu tiên sản phẩm tạm thời**, KHÔNG phải bảng top 10 giao dịch
toàn quốc đã được chứng minh. Không có bộ số liệu đã kiểm chứng đủ 63 tỉnh cũ
hoặc 34 tỉnh mới, cùng kỳ, cùng phương pháp và cùng loại giao dịch trong đợt rà
này. Các nguồn dưới khác kỳ, phạm vi khảo sát và phân khúc; không cộng hoặc xếp
hạng trực tiếp. Tin đăng, lượt tìm kiếm, nguồn cung, tỷ lệ hấp thụ và số dự án
không được đổi tên thành tổng giao dịch thành công.

Đơn vị làm việc là **tỉnh/thành cũ**, khớp registry QH 2030/địa chính hiện tại.
Cột tên mới chỉ để đối chiếu; không tự mở rộng ưu tiên sang mọi tỉnh cũ cùng
sáp nhập. Đây là 10 địa bàn cũ, không phải 10 đơn vị cấp tỉnh mới độc lập.
Thứ tự trong bảng là **thứ tự làm việc dự kiến**, cân đối nguồn hiện có và thị
trường, không phải hạng 1–10 về số giao dịch. Cập nhật khi có bằng chứng tốt hơn.

| Thứ tự làm việc | Địa bàn cũ / ID registry | Đối chiếu đơn vị mới | Cơ sở chọn và giới hạn |
| --- | --- | --- | --- |
| 1 | Bình Dương / `binh-duong` | TP.HCM | S1: 5.484 căn hộ bán trong Q1/2026; chỉ căn hộ trong khảo sát. Là địa bàn sản phẩm gốc, nguồn local/GIS đã sâu nhất. |
| 2 | TP.HCM / `hcm` | TP.HCM | S2: thị trường căn hộ/nhà phố chủ lực trong khảo sát vùng; không có tổng giao dịch toàn TP cùng kỳ để xếp hạng quốc gia. |
| 3 | Hà Nội / `ha-noi` | Hà Nội | S3: khoảng 119.000 giao dịch nhà ở năm 2024 trong 12 quận và Gia Lâm; không phải toàn bộ tỉnh/thành và đất nông nghiệp. |
| 4 | Đồng Nai / `dong-nai` | Đồng Nai | S2/S4: địa bàn khảo sát phía Nam, dự án và thanh khoản phục hồi; chưa xác minh tổng giao dịch toàn tỉnh. Mẫu ranh Đồng Nai cũ chưa thành nguồn bulk. |
| 5 | Long An / `long-an` | Tây Ninh | S2: giao dịch nhà phố/biệt thự của vùng tập trung ở Long An cũ. **3.438 là số giao dịch cả vùng**, không gán toàn bộ cho Long An. |
| 6 | Hưng Yên / `hung-yen` | Hưng Yên | S5: các đại đô thị Văn Giang thuộc thị trường nhà ở Hà Nội mở rộng; số liệu gộp với Hà Nội không tách thành số giao dịch riêng của Hưng Yên. |
| 7 | Hải Phòng / `hai-phong` | Hải Phòng | S6: báo cáo hoạt động dự án/nghỉ dưỡng cho thấy thị trường cần theo dõi. Chưa có số tuyệt đối riêng Hải Phòng cũ; số tăng trưởng 2026 có thể dùng địa giới mới. Mức chắc chắn thấp hơn nhóm có số giao dịch. |
| 8 | Khánh Hòa / `khanh-hoa` | Khánh Hòa | S7: 9.202 giao dịch trong Q2/2025 theo Sở Xây dựng được báo dẫn; dùng địa giới trước sáp nhập, không trộn số Q3/2025 mở rộng. |
| 9 | Đà Nẵng / `da-nang` | Đà Nẵng | S8: khảo sát H1/2025 ghi nhận hấp thụ tích cực trong phân khúc nhà ở; chưa xác minh tổng giao dịch mọi loại hình toàn địa bàn. |
| 10 | Lâm Đồng / `lam-dong` | Lâm Đồng | S9: 6.591 đất nền + 388 nhà riêng + 18 căn hộ = **6.997** giao dịch theo báo cáo công chứng Q2/2025; số cộng tính từ thành phần. Văn bản được báo dẫn ngày 25/6, cần kiểm lại ngày chốt kỳ trước so sánh quý đầy đủ. |

Hải Phòng, Hưng Yên và các tỉnh chỉ có bằng chứng khảo sát/định tính cần được
rà lại trước nếu sau này có bảng giao dịch chuẩn. Chưa có căn cứ loại Bắc Ninh,
Thanh Hóa, BRVT hoặc tỉnh khác khỏi top 10 giao dịch thực tế: ngoài danh sách
ở đây chỉ có nghĩa **chưa ưu tiên nguồn lực**, không có nghĩa ít giao dịch.

## Nguồn thị trường — truy cập ngày 2026-11-02

| Mã | Nguồn, kỳ số liệu | Cách dùng |
| --- | --- | --- |
| S1 | [Cushman & Wakefield, HCMC MarketBeat Q1/2026](https://www.cushmanwakefield.com/en/vietnam/news/2026/06/hcmc-apartment-market-rebalances-as-core-prices-rise-and-demand-moves-outward), bài trong chuyên mục 06/2026 | Tách Bình Dương cũ khỏi vùng lõi HCM; chỉ căn hộ. Không dùng nguồn cung mới làm số giao dịch. |
| S2 | [DKRA Consulting, TP.HCM & vùng phụ cận Q2/2025](https://dkra.vn/pdf/dkra-consultingbao-cao-thi-tru%CC%9Bo%CC%9Bng-ba%CC%82t-do%CC%82ng-san-nha-o%CC%9B-tp-hcm--vung-phu-ca%CC%82n-quy-22025_vi_1752217953.pdf), trang in 14–19 / PDF 9–11 | Phạm vi gồm HCM, Bình Dương, Đồng Nai, BRVT, Long An, Tây Ninh cũ. Đất nền chỉ dự án >=1 ha có QH 1/500, không gồm đất hộ lẻ/thứ cấp. Thông tin nguồn cung chỉ là bằng chứng phụ, không phải thước đo giao dịch. |
| S3 | [OneHousing/One Mount, Tiêu điểm BĐS số 48, 02/2025](https://cdn.onehousing.vn/HD/Reports/Tieu_diem_BDS/TieudiemBDS_so48PDF.pdf) và [Báo Chính phủ dẫn báo cáo Q1/2025, 21/4/2025](https://thanglong.baochinhphu.vn/thi-truong-nha-thap-tang-o-ha-noi-phuc-hoi-an-tuong-103250421183749886.htm) | Lưu phạm vi 12 quận + Gia Lâm cho số năm 2024. Bài Q1/2025 nói khoảng 18.300; các thành phần làm tròn không cộng khớp hoàn toàn, không tự sửa hoặc cộng vào số năm 2024. |
| S4 | [Báo Đấu thầu, Đồng Nai ấm dần sau TP.HCM, 12/9/2025](https://baodauthau.vn/thi-truong-bat-dong-san-dong-nai-am-dan-sau-tphcm-post184972.html) | Bằng chứng định tính dẫn DKRA 08/2025, không phải bảng giao dịch cả tỉnh. |
| S5 | [MBS Research, VN Dynamics BĐS dân cư, 11/7/2025](https://www.mbs.com.vn/files/uploads/2025/07/VN-Dynamics_BDS-Dan-cu_20250711.pdf), phân tích thấp tầng và Văn Giang/Hưng Yên | Bằng chứng bổ trợ về đô thị vệ tinh/nhu cầu và triển vọng cung, không phải số giao dịch riêng Hưng Yên. Không dùng số thị trường Hà Nội mở rộng làm số của hai tỉnh riêng. |
| S6 | [Báo Hải Phòng, Resurgence of resort real estate, 10/4/2026](https://news.baohaiphong.vn/resurgence-of-resort-real-estate-in-hai-phong-540213.html) | Dẫn HPREA/VNREA về 2025/Q1/2026; không đủ mẫu số/ranh cũ để xếp hạng tổng lượng giao dịch. |
| S7 | [TTXVN/Báo Tin tức, Khánh Hòa, 21/9/2025](https://baotintuc.vn/thi-truong-bat-dong-san-khanh-hoa-bai-1-van-nhip-bat-tu-bien-n20250921104201356.htm) và [Báo Khánh Hòa tổng kết 2025, 01/2026](https://baokhanhhoa.vn/kinh-te/202601/thi-truong-bat-dong-san-nam-2025-giao-dich-tang-xu-huong-chuyen-dich-theo-chieu-sau-49736ee/) | Tách Q1–Q2 trước sáp nhập khỏi Q3–Q4 sau sáp nhập; ưu tiên lấy lại báo cáo Sở Xây dựng gốc khi cập nhật. |
| S8 | [Savills, Đà Nẵng H1/2025](https://vn.savills.com.vn/research_articles/226806/223925-0) | Nghiên cứu nhà ở, không phải sổ giao dịch tất cả loại đất. |
| S9 | [Báo Lâm Đồng dẫn Sở Tư pháp, 25/6/2025](https://demo.baolamdong.vn/kinh-te/202506/giao-dich-dat-nen-quy-ii-tang-voi-tong-gia-tri-hon-9303-ty-dong-b9d021e/) và [bản tin đối chiếu 25/6/2025](https://kinhdoanhvaphattrien.vn/giao-dich-bat-dong-san-thanh-cong-o-lam-dong-tang-gan-50-sau-mot-quy-43265.html) | Từ 47 tổ chức hành nghề công chứng; mở trực tiếp URL báo địa phương gặp 502 nhưng có nội dung search-index và nguồn đối chiếu. Không coi công bố trước 30/6 là đã kiểm chứng đủ trọn quý. |

Không khẳng định đây là các kỳ mới nhất toàn thị trường tính đến 02/11/2026.
Khi có báo cáo mới, lưu cả ngày công bố và kỳ dữ liệu; không thay âm thầm một
kỳ khác vào cột số lượng. Không có thông tin giao dịch cá nhân trong hồ sơ này.

## Tiến độ Maps hiện có — cấu hình/code, không phải kiểm định phủ kín

Ký hiệu: **R** = lớp tham khảo đã đăng ký; **G** = GIS đã tích hợp nhưng chỉ theo
độ phủ nguồn; **L** = chỉ mục local; **M** = mẫu thử; **—** = chưa tích hợp;
**?** = chưa kiểm chứng. Mọi R/G vẫn cần kiểm nguồn, quyết định, thời điểm,
độ phủ và thử giao diện; không tự ghi “xong toàn tỉnh”. Production của từng
địa bàn **chưa được rà lại trong task tài liệu này**.

| Địa bàn | QH SDĐ 2030 | Phân khu | QH chung | QH chi tiết | Ranh/góc ranh | Địa giới cũ/mới | Việc tiếp theo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Bình Dương | R | G + PDF đã giữ | G | G, độ phủ còn từng khu | L, asset 91 đơn vị lịch sử | R/R | Rà lỗ phủ, click/đo cạnh và tra quy hoạch trên các huyện; kiểm chứng bản deploy hiện tại. |
| TP.HCM cũ | R | G | G | G, không phủ liên tục | G, live theo nguồn; không có snapshot toàn thành phố | R/R | Lập ma trận coverage theo quận/phường, không suy đủ từ bbox; tối ưu cache cold/warm. |
| Hà Nội | R | R, lớp tổng Guland | — | — | M cũ / GIS `blocked_tls` | R/R | Chờ chứng chỉ cổng/API chính thức được sửa; kiểm polygon/ID thật. Guland làm sau. |
| Đồng Nai cũ | R qua provider Đồng Nai/Bình Phước | — | — | — | M: 18 tham chiếu; GIS `blocked_maintenance` | R/R | Cổng đất đai cũ đang bảo trì; không lấy Bình Phước làm độ phủ Đồng Nai cũ. Không chạy collector Guland đợt này. |
| Long An | R | — | — | — | M cũ / GIS `blocked_geometry`, WFS count có nhưng GetFeature 500 | R/R | Khôi phục geometry, không chỉ dựa schema/count. Guland làm sau. |
| Hưng Yên | R | — | — | — | — / GIS chưa xác minh đúng địa bàn cũ | R/R | DB công khai đã tìm là Thái Bình cũ; cần đúng Hưng Yên cũ. Guland làm sau. |
| Hải Phòng cũ | R | R, lớp tổng Guland | — | — | — / cổng đất đai `/og/` 404, GIS geometry chưa xác minh | R/R | Chờ route/API địa chính hoạt động; không dùng polygon quy hoạch hay Hải Dương thay thế. Guland làm sau. |
| Khánh Hòa cũ | R | R, lớp tổng Guland | — | — | **G live, verified local: 134 refs / 8 huyện; mẫu thật đủ 8** | R/R | QA trình duyệt/độ phủ, VN-2000 địa phương và release. Count 971.792 là bản ghi nguồn, chưa tải hết; tra giao QH chưa hỗ trợ. |
| Đà Nẵng cũ | R | R, lớp tổng Guland | — | — | — / GIS `blocked_upstream` 503/timeout | R/R | Kiểm lại portal/ArcGIS khi phục hồi; không nhầm Quảng Nam. Guland làm sau. |
| Lâm Đồng cũ | R | — | — | — | — / GIS `blocked_tls` | R/R | Chờ chứng chỉ portal/ArcGIS hợp lệ, rồi xác minh cadastral layer. Guland làm sau. |

“18 tham chiếu Đồng Nai cũ” là mẫu local từ đợt trước, không phải 18 đơn vị hành
chính hay 18 vùng phủ đầy đủ. Không tải/khởi động collector mới chỉ vì đọc file này.

Nguồn đối chiếu hiện trạng:

- `config/planning_landuse_areas.json` liên kết chính xác `layer_ids` sang
  `planning_landuse_2030.json`; tên provider Đồng Nai không trùng slug tỉnh.
- `config/planning_partition_reference.json` hiện chỉ có 16 lớp tổng ngoài
  HCM/BD/BRVT; không dùng số 416 đồ án lịch sử đã gỡ làm hiện trạng.
- Các GIS HCM: `planning_tiles.py`, metadata QHC/QHCT và các doc
  [phân khu](hcm-expanded-partition.md), [chung](general-planning-speed.md),
  [chi tiết](detailed-gis.md). Không khẳng định đồng loạt đúng tỷ lệ/phê duyệt.
- [Audit nguồn ranh](national-parcel-source-audit.md),
  [thu thập miễn phí](free-parcel-acquisition.md),
  [nguồn HCM mở rộng](hcm-expanded-parcels.md), `planning_parcel_catalog.py`.
- [Địa giới mới](national-administrative.md) và [cũ](legacy-administrative.md):
  dữ liệu tham khảo, ranh hành chính khác ranh địa chính và có giới hạn niên đại.

## Checklist bắt buộc cho MỖI địa bàn

Không đánh dấu địa bàn hoàn tất chỉ vì một chức năng hoặc một điểm mẫu chạy.
Tạo bằng chứng cho từng mục sau trong doc nguồn của địa bàn, rồi cập nhật hàng
tương ứng phía trên bằng ngày kiểm/SHA/đường dẫn artifact.

| Nhóm | Điều kiện nghiệm thu | Tình trạng chung hiện tại |
| --- | --- | --- |
| Ranh và góc ranh | Polygon gốc, CRS đúng, sheet/parcel ID, multipart/holes, không trace PNG, không sửa đoán; liệt kê vùng thiếu và ID bị loại | Có nền tảng HCM/Bình Dương; tỉnh khác theo ma trận |
| Tra tờ/thửa | Tỉnh/huyện/xã cũ đúng; ID không xung đột; kết quả thật và trạng thái không tìm thấy/lỗi nguồn riêng biệt | UI dùng chung đã có, backend chưa có cho mọi tỉnh |
| Tọa độ/góc ranh | WGS84, VN-2000 hệ chiếu phù hợp địa bàn; nhập nhiều điểm và OCR ảnh; kiểm thực địa/source sample | Có công cụ dùng chung, KHÔNG tự suy VN-2000 mọi tỉnh đã hỗ trợ |
| Chọn thửa | Popup cơ bản ngay, nguồn/ngày dữ liệu, marker; chiều dài cạnh/diện tích từ geometry gốc; không che dock | Có renderer dùng chung; cần QA riêng từng nguồn |
| Chi tiết quy hoạch thửa | Chỉ gọi khi người dùng yêu cầu; giao polygon thật với lớp quy hoạch, mã/chức năng, diện tích, nguồn/quyết định và unavailable riêng | HCM có; tỉnh khác chưa đủ. Kho ranh không phải kho planning offline |
| Các lớp quy hoạch | SDĐ 2030, phân khu, chung, chi tiết; bật/tắt/độ mờ; nguồn GIS/PDF; chỉ bật loại thực sự có, công khai phần thiếu | Theo ma trận; ảnh có màu không chứng minh pháp lý/đủ phủ |
| Giao thông/tầm nhìn | Kiểm tuyến thật/quy hoạch, dự thảo/phê duyệt và phạm vi; không gán lớp HCM sang tỉnh khác | Có riêng vùng HCM theo nguồn; nơi khác chưa tích hợp, chỉ bổ sung khi có nguồn thật |
| Địa giới | Cũ/mới, hover tên và zoom chọn vùng; không join mã upstream trực tiếp sang mã xã địa chính | Có lớp đăng ký cho 10 nơi; phải QA từng tỉnh |
| Tiện ích | Đo khoảng cách/đa giác tự vẽ, xóa ranh chủ động, chỉ đường, ký hiệu đất; marker tin rao ưu tiên click | Công cụ dùng chung; cần QA desktop/mobile theo tỉnh |
| Hiệu năng | Tải theo viewport, hủy cũ/newest-wins, cache versioned, geometry đo gốc riêng, private bypass; lỗi GIS không chặn snapshot | Nền tảng có; chưa có chứng nhận tải lạnh/mượt/render cho cả 10 tỉnh |
| Tính đầy đủ | Danh mục huyện/xã và đồ án cần có, mẫu kiểm phủ, lỗ trống rõ, bản cập nhật và nguồn được phép dùng | Chưa tỉnh nào được chứng nhận “đủ toàn bộ mọi lớp” bằng checklist này |
| Release | Tách code/asset local/CI/VPS/edge/browser; SHA và ngày kiểm, artifact hash, rollback | Task hiện tại chỉ lưu quyết định/tiến độ, không deploy |

Nếu nguồn thiếu, ghi `blocked_source` và lý do, ngày/URL/HTTP đã thử, khu vực
cụ thể và điều kiện mở lại; không bỏ hàng hoặc đánh dấu xong. Không đổi lớp SDĐ
thành phân khu/chung/chi tiết để lấp chỗ trống. Không ghép lại QH khác vào lớp
phân khu vì người dùng đã yêu cầu bỏ do chồng chéo. Giữ PDF/bản vẽ đã làm.

## Quy tắc tiếp tục và cập nhật

**Chỉ đạo mới nhất cho đợt ranh thửa 3–10:** dùng GIS công khai hoạt động,
không tắt xác minh TLS hoặc dùng relay vượt lỗi; phần cần thu thập Guland
để `deferred_guland`, làm trong đợt sau khi được yêu cầu. Nguồn GIS bị lỗi cũng
ghi riêng điều kiện mở lại, không coi là đã hoàn tất hoặc không có GIS.

1. Đọc file này sau `docs/maps-agent-guide.md` khi chọn tỉnh tiếp theo. Tập trung
   hàng đầu còn thiếu có nguồn khả thi; khi bị chặn, ghi lại rồi xét địa bàn kế.
2. Mỗi lần làm tỉnh nào phải cập nhật trạng thái từng nhóm: chưa làm → đang xác
   minh → local → verified → deployed, kèm nguồn và phạm vi. `registered` khác
   `verified`, `verified` khác `deployed`, và `partial` không phải `complete`.
3. Ngoài 13 địa bàn của định hướng hiện hành: **deferred expansion**. Giữ dữ liệu đã có và sửa lỗi/bảo mật,
   không xóa/tắt các lớp toàn quốc hay triển khai lại cả nước. Xin chỉ đạo mới
   khi cần mở rộng một tỉnh ngoài danh sách.
4. **Bình Phước cũ ngoài danh sách nhưng giữ công việc đã hoàn tất:** 618.053
   polygon local ở commit `20246dfb`, 615 bản ghi chưa đủ điều kiện; không tự
   mở tiếp tỉnh khác hoặc tuyên bố đã deploy. Theo dõi tại
   [free-parcel-acquisition.md](free-parcel-acquisition.md).
5. Rà lại danh sách khi có báo cáo giao dịch mới đáng tin hoặc người dùng đổi
   ưu tiên. Chỉ gọi “top 10 theo giao dịch” khi có denominator địa bàn, kỳ thống
   kê, loại giao dịch và độ phủ báo cáo so sánh được. Không tự suy từ tin rao
   RadarBDS, dữ liệu tìm kiếm, diện tích đất hay dân số.

Lần sau chỉ cần người dùng nói “làm tiếp Maps ưu tiên” thì dùng sổ này để biết
địa bàn/tính năng còn thiếu; vẫn xác minh HEAD, source và deployed SHA hiện tại.
