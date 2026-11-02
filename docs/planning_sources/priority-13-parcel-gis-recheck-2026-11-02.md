# Rà lại GIS ranh thửa của 13 thị trường ưu tiên

Ngày kiểm: 02/11/2026, sau release `b59294a6`. Phạm vi tỉnh **cũ** trong
[hồ sơ 13 thị trường](maps-priority-13-2026-11-02.md). Yêu cầu: bổ sung nơi
chưa tích hợp mà GIS công khai thực sự trả được polygon địa chính.

## Kết quả

**Chưa xác minh được provider mới đủ điều kiện trong đợt này.** Không đổi code
ranh hoặc bật lựa chọn không có dữ liệu. Không thu thập Guland. Điều này không
có nghĩa các tỉnh còn thiếu không có CSDL/GIS; chỉ các đầu mối đã kiểm chưa
đạt điều kiện tích hợp. Không dùng đồ án quy hoạch hay địa giới thay ranh thửa.

| Địa bàn cũ | Kết quả và bước tiếp tục |
| --- | --- |
| Bình Dương | Provider/snapshot hiện có; không thêm provider trùng. Không kiểm lại toàn bộ thửa trong đợt này. |
| TP.HCM | Provider GIS hiện có; không tuyên bố phủ kín từ registry. |
| Hà Nội | `blocked_tls`: curl/Schannel xác minh HTTPS tại https://quyhoach.hanoi.gov.vn/ báo `SEC_E_CERT_EXPIRED`. Chờ chứng chỉ/endpoint polygon hợp lệ. |
| Đồng Nai | `blocked_maintenance`: https://datdai.stnmt.dongnai.gov.vn/ HTTP 200 nhưng body “Hệ thống đang bảo trì”. Giữ kết quả kiểm 11 huyện và phạm vi Bình Phước ở [audit Đồng Nai](dongnai-priority-review-2026-11-02.md); không kiểm lại 11 huyện lần này. |
| Long An | `blocked_geometry`: WFS Tây Ninh `cite:thuadat_chauthanh4326` trả HTTP 200 cho hits; mẫu GetFeature geometry-only `count=1`, JSON vẫn HTTP 500, body `Error fetching data from GeoServer`. Cần source sửa truy vấn hình học; chưa có adapter. |
| BRVT | Dùng provider HCM mở rộng hiện có; không kiểm từng huyện/đảo lần này. Không thêm nguồn giả cho Côn Đảo. |
| Hưng Yên | `unverified_historic_scope`: https://gisdata.hungyen.gov.vn/quyhoachv4.aspx?orgcode=thaibinhcsdl HTTP 200, vẫn đầu mối `thaibinhcsdl`; chưa xác minh polygon đúng Hưng Yên cũ. |
| Hải Phòng | `unverified_geometry`: portal và `/assets/appconfig.json` HTTP 200. Cấu hình `haiphongsxd/qhxd_tt16_bxd` có API quy hoạch theo điểm, đồ án và DVHC; không thấy API tra thửa/polygon địa chính trong cấu hình đang dùng. Mã frontend có thành phần dùng chung về thửa không chứng minh tenant đã có dữ liệu. Cần API địa chính thực tế, không suy từ template. |
| Đà Nẵng | `blocked_upstream`: https://gisportal.danang.gov.vn/server/rest/services?f=pjson HTTP 503. Đầu mối đất đai https://ttdd.tnmt.danang.gov.vn/ được cơ quan thành phố công bố nhưng HTTPS hiện báo `SEC_E_CERT_EXPIRED`. |
| Khánh Hòa | `existing_provider_live_sample_verified`: query layer 8 trả HTTP 200, một feature có `geometry.rings` và thuộc tính tờ/thửa. Adapter đã có trong HEAD triển khai; không phải provider mới. Không kiểm toàn bộ 134 tham chiếu, UI hay tra giao quy hoạch ở đợt này. |
| Bắc Ninh | `unverified_historic_scope`: https://gis.bacninh.gov.vn/QuyHoach/ và `assets/appconfig.json` HTTP 200, cấu hình ghi rõ **“Cung cấp quy hoạch xây dựng tỉnh Bắc Giang”**; HTML còn dẫn `gis.bacgiang.gov.vn`. Không gán dữ liệu này cho Bắc Ninh cũ. Đầu mối cũ `https://sxd.gis.bacninh.gov.vn/` timeout sau 20 giây; cần nguồn đúng địa bàn và mẫu polygon+ID. |
| Quảng Ninh | `not_found_verified_endpoint`: rà tìm kiếm nguồn công khai và https://investinquangninh.vn/vi/thong-tin-quy-hoach (HTTP 200) chỉ xác minh được đầu mối hồ sơ/ảnh quy hoạch, chưa có endpoint polygon địa chính. Việc tỉnh xây dựng/đồng bộ CSDL không chứng minh mở API công khai. Tiếp tục từ nguồn do Sở/Văn phòng đăng ký đất đai công bố. |
| Lâm Đồng | `blocked_tls`: https://quyhoach.lamdong.gov.vn/ vẫn `SEC_E_CERT_EXPIRED`. Không tắt xác minh TLS để kích hoạt adapter. |

## Truy vấn và bằng chứng có thể lặp lại

- Long An hits: `https://geo.tayninh.gov.vn/geoserver/wfs?service=WFS&version=2.0.0&request=GetFeature&typeNames=cite:thuadat_chauthanh4326&resultType=hits`.
- Long An geometry: cùng service/type, `count=1&outputFormat=application/json&propertyName=geom`, bỏ `resultType=hits`. Đây là kiểm bổ sung; các biến thể JSON/GML/POST đã có ở [audit trước](priority-gis-parcels-2026-11-02.md).
- Khánh Hòa: `/arcgis/rest/services/Base/DiaChinh/MapServer/8/query`,
  `where=1=1`, `resultRecordCount=1`, `returnGeometry=true`, `outSR=4326`;
  chỉ `OBJECTID,So_To,So_Thua,Dien_Tich,MaXa,MaHuyen,TenPhuong,TenHuyen`.
- Chẩn đoán cục bộ ignored: `.local/priority-gis-recheck-20261102/`, gồm
  trạng thái HTTP/TLS, HTML/config công khai và mẫu Khánh Hòa không có chủ đất.
  Không commit bundle/config bên thứ ba hoặc khóa có sẵn trong frontend nguồn.
- [Cơ quan Đà Nẵng công bố cổng đất đai](https://www.investdanang.gov.vn/vi/web/guest/chi-tiet-tin-tuc?dinhdanh=1407846).
- [GIS Bắc Ninh công khai](https://gis.bacninh.gov.vn/QuyHoach/), cần kiểm địa bàn tenant như trên.

## Điều kiện bật nguồn mới

Phải có mẫu polygon gốc hợp lệ, số tờ/thửa, đúng tỉnh/huyện cũ; kiểm search,
point và viewport; chỉ allowlist field không có thông tin chủ đất, CRS rõ ràng,
namespace ID riêng, giới hạn tải/cache/cancellation. Nối vào renderer và popup
hiện có. Nếu chỉ tra được qua Guland thì ghi `deferred_guland`, chưa thu thập.
Đợt này chỉ cập nhật hồ sơ nguồn; không có thay đổi chức năng cần deploy.
