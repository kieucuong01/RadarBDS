# Kiểm duyệt nguồn lớp quy hoạch trên bản đồ tin rao

**Ngày kiểm duyệt:** 2026-07-29
**Trạng thái phát hành:** `release_blocked`

## Phạm vi và điều kiện chấp nhận

Radar BDS chỉ phát hành một lớp quy hoạch khi đồng thời xác minh được cơ quan
công bố, quyết định phê duyệt đang có hiệu lực, bản đồ đủ tỷ lệ và chú giải,
nguồn tải công khai ổn định, tính cập nhật, SHA-256 của bản gốc và quyền lưu trữ
raster dẫn xuất có ghi nguồn. URL có thể truy cập không tự động đồng nghĩa với
quyền sao chép hoặc tái phân phối.

Không dùng dữ liệu hình học từ website thương mại, tài liệu lấy ý kiến/dự thảo,
API cần token bảo vệ hoặc endpoint xác thực không được công bố.

## Kết quả bốn hiện vật bắt buộc

| ID hiện vật | Nguồn chính thức đã kiểm tra | Hồ sơ phê duyệt và bản đồ | Quyền tái sử dụng | SHA-256 nguồn | Trạng thái |
|---|---|---|---|---|---|
| `land-use-thu-dau-mot` | Báo cáo KHSDĐ 2023 trên cổng Thủ Dầu Một xác nhận Quyết định 04/QĐ-UBND ngày 05/01/2022 phê duyệt QHSDĐ đến 2030 | Chưa tìm thấy bản đồ hoàn chỉnh, chú giải và tệp đính kèm ổn định trên trang công bố chính thức; kết quả bản đồ khác nằm trong `/van-ban-du-thao/` hoặc website thương mại nên bị loại | Chưa có điều khoản hoặc văn bản cho phép Radar BDS lưu trữ raster dẫn xuất | Không tính vì chưa có bản gốc được chấp nhận | `blocked_missing_official_map_and_reuse_right` |
| `land-use-ben-cat` | [Công bố QHSDĐ đến 2030 của Bến Cát](https://bencat.binhduong.gov.vn/cong-khai-thong-tin/quy-hoach-su-dung-dat-den-nam-2030-thi-xa-ben-cat) ngày 20/01/2022 | Trang công bố liệt kê quyết định, báo cáo và bản đồ tỷ lệ 1/25.000; chưa xác minh được toàn bộ legend/tệp gốc ổn định và chưa hoàn tất kiểm tra các điều chỉnh mới hơn | Trang công bố không nêu quyền tạo và lưu trữ raster dẫn xuất; chưa có văn bản cho phép | Không tính vì nguồn chưa đạt cổng quyền sử dụng | `blocked_missing_reuse_right_and_currency_proof` |
| `construction-thu-dau-mot` | Tài liệu chính thức tìm thấy về điều chỉnh QHC đến 2040 nằm trong `/van-ban-du-thao/`; hồ sơ 2024 nói đang chờ lập QHC đến 2045 theo nhiệm vụ tại Quyết định 1498/QĐ-TTg ngày 30/11/2023 | Quyết định 1702/QĐ-UBND ngày 26/06/2012 là đồ án cũ; tài liệu sau đó là nhiệm vụ, dự thảo hoặc điều chỉnh cục bộ, chưa phải một bộ bản đồ mới được duyệt bao phủ đầy đủ khu vực hỗ trợ | Không đánh giá quyền vì chưa có hiện vật chính thức đang hiệu lực đáp ứng phạm vi | Không tính vì chưa có bản gốc được chấp nhận | `blocked_no_current_approved_full_plan` |
| `construction-ben-cat` | [Công bố QHC Bến Cát đến 2040](https://bencat.binhduong.gov.vn/cong-khai-thong-tin/quy-hoach-chung-thi-xa-ben-cat-den-nam-2040) ngày 06/09/2022 | Trang xác nhận UBND tỉnh đã phê duyệt nhưng chỉ liệt kê tệp quyết định; chưa có một bản đồ tổng thể kèm legend/tỷ lệ đủ để dựng overlay toàn vùng. Các đồ án phân khu 1/2.000 công bố năm 2023 chỉ bao phủ một số phường, không thay thế hiện vật toàn Bến Cát | Chưa có điều khoản hoặc văn bản cho phép lưu trữ raster dẫn xuất | Không tính vì chưa có bản gốc bản đồ và quyền được chấp nhận | `blocked_missing_map_sheet_legend_and_reuse_right` |

## Các ứng viên đã loại

- Tài liệu Thủ Dầu Một dưới đường dẫn `/van-ban-du-thao/`: đây là nhiệm vụ,
  hồ sơ lấy ý kiến hoặc báo cáo điều chỉnh, không phải hiện vật phê duyệt cuối
  cùng theo cổng phát hành.
- Báo cáo điều chỉnh cục bộ năm 2024 của Thủ Dầu Một: chính tài liệu cho biết
  đang chờ lập đồ án QHC đến 2045; không thể dùng như bản đồ toàn khu vực.
- Các thông báo điều chỉnh kế hoạch sử dụng đất Bến Cát năm 2024 và thông báo
  lập điều chỉnh giai đoạn 2026–2030: không phải bản đồ QHSDĐ 2030 hợp nhất đã
  phê duyệt kèm quyền tái sử dụng.
- [Các quy hoạch phân khu Bến Cát tỷ lệ 1/2.000](https://bencat.binhduong.gov.vn/cong-khai-thong-tin/quy-hoach-phan-khu-ty-le-12000-cac-phuong-tren-dia-ban-thi-xa-ben-cat-den-nam-2040):
  có các quyết định riêng cho năm phường nhưng không phủ toàn bộ phạm vi Bến
  Cát mà sản phẩm yêu cầu.
- [Cổng GIS xây dựng TP.HCM](https://gisxaydung.tphcm.gov.vn/tracuuttqh):
  được [Sở Quy hoạch – Kiến trúc TP.HCM giới thiệu](https://qhkt.hochiminhcity.gov.vn/tai-lieu-hop/huong-dan-gisxaydung-3627.html)
  như cổng tra cứu chính thức sau hợp nhất. Chưa có tài liệu công khai chỉ ra
  đúng bốn lớp tải xuống, quyết định tương ứng và API không cần token. Dòng bản
  quyền cho phép phát hành lại thông tin trên website khi ghi nguồn chưa được
  coi là quyền tạo/tự lưu trữ raster dẫn xuất từ bản đồ.
- Mọi bản đồ chỉ xuất hiện trên website thương mại: loại vì không phải nguồn
  hình học chính thức và không có quyền tái phân phối.

## Điều kiện để gỡ chặn

Mỗi hiện vật cần được bổ sung một URL chính thức ổn định đến đúng bản đồ đã
phê duyệt (đủ tỷ lệ và legend), số/ngày quyết định, bằng chứng đây là phiên bản
đang có hiệu lực, cùng điều khoản rõ ràng hoặc văn bản của cơ quan sở hữu cho
phép Radar BDS tạo và phục vụ raster dẫn xuất có ghi nguồn. Sau đó mới tải bản
gốc vào vùng `.local`, tính SHA-256, tạo điểm khống chế và chạy cổng sai số/căn
chỉnh trước khi thêm công tắc quy hoạch vào giao diện.

Theo cổng phát hành hiện tại, kế hoạch triển khai lớp quy hoạch dừng tại tài
liệu kiểm duyệt và validator. Không tạo manifest công khai, WebP, control point
hay điều khiển UI cho đến khi đủ cả bốn hiện vật.
