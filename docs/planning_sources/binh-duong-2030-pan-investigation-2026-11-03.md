# Điều tra kéo SDĐ2030 Bình Dương so với phân khu — 03/11/2026

## Cập nhật triển khai nhãn theo vùng nhìn

`referenceBranding` dùng cùng helper cắt polygon để kiểm giao với viewport thật,
chỉ tạo nhãn sau khi bật lớp và khi footprint có diện tích giao vùng nhìn.
SVG giữ hệ tọa độ/ma trận gốc nhưng cắt viewBox và bounds về viewport cộng
128 CSS px mỗi phía. Surface nhãn vì vậy không vượt kích thước màn hình cộng
256 px mỗi chiều; không còn image overlay địa lý hàng chục nghìn px.
Nhãn cập nhật tại `moveend`, giữ nguyên opacity, xóa listener/overlay khi tắt lớp.
Trong lúc kéo, nhãn hiện có đi theo bản đồ; nhãn mới xuất hiện khi kéo kết thúc.

Đo lại cùng harness, vị trí, opacity, 10 lần kéo và CPU slowdown 4× ở zoom
14/16/18: p95 rAF đều khoảng **16.8 ms**, **0 khoảng khung hình >50 ms**, không
long task. Zoom14 còn 1 SVG 946×510 CSS px; zoom16/18 không tạo nhãn ngoài
viewport (trước đây luôn có 4 SVG). Tất cả tile đã tải xong trong lần đo.
Evidence ignored: `.local/landuse-pan-investigation-deep-labels/results.json`.
Baseline cũng chưa tái hiện lag, nên không suy ra mức tăng FPS hoặc kết luận
đã hết lag trên điện thoại thật. Chưa cần thêm cache ảnh/giải mã từ kết quả này.

Test riêng `tests/js/planning_reference_labels.test.cjs` kiểm polygon thật thay
vì bbox, viewBox hữu hạn, giữ ma trận, opacity, pan ra/vào và bật/tắt không sót
listener. Overlay/native runtime qua. Asset version `viewport-labels-20261103`;
thay đổi vẫn local, chưa commit/deploy.

Chrome đối chiếu riêng nhãn thật tại tâm footprint, zoom14/18: không có pixel
khác quá 16/255 giữa ảnh trước/sau trong viewport 1100×700. Ở zoom18, nhãn
đang thấy chỉ còn 1356×956 CSS px thay cho overlay 19840×20864; 3 nhãn ngoài
màn hình không được tạo. Zoom và remove/add giữ opacity 0.3, không page error.
Evidence `.local/landuse-pan-investigation-deep-labels/label-check.json` và
`label-{old,new,diff}-z{14,18}.png`. Đây vẫn là Chrome headless, không phải
điện thoại thật hoặc phép đo bộ nhớ GPU.

## Cập nhật triển khai mục1

Theo chỉ đạo tiếp theo, đã sửa `referenceClipPath`: giữ bbox làm lọc nhanh,
sau đó Sutherland–Hodgman cắt footprint polygon về ô0..256 qua4 cạnh. Chỉ
tạo CSSpath khi polygon sau cắt có diện tích dương; không còn dùng bbox làm
điều kiện cuối. Không thêm cache/dependency: footprint chỉ là các đa giác nhỏ
đã review; chưa đo được nhu cầu cache mới. Phần SVG nhãn được sửa ở bước tiếp theo bên trên.

Kiểm: tile giao một phần/hoàn toàn, footprint nằm trong ô, chỉ chạm cạnh/góc,
và các tile thật Bình Dương bbox-positive nhưng polygon-negative đều qua.
Đối chiếu Shapely trên342 ô ởzoom8/11/14/17: sai khác vùng cắt tối đa0.141px²
do CSSpath giữ rounding0.001px như cũ. Script ignored `.local/check-clip-geometry.py`.

Chrome harness zoom18 cùng vị trí/opacity: **8 tile, clip-path8→0**, nhãn SVG
giữ nguyên. p95 rAF vẫn16.8ms,0 longtask; baseline chưa lag nên **chưa chứng
minh tăng FPS**. Evidence `.local/landuse-pan-investigation-deep-patched/results.json`.
Overlay/native runtime, asset-version test và JS syntax qua. Bump overlay asset
`tile-polygon-clip-20261103` là version của bước này, sau đó thay bằng version nhãn bên trên.

## Điều tra trước khi sửa

Yêu cầu: tìm nguyên nhân và đề xuất, chưa sửa renderer trong đợt này. Giữ
nguyên phần góc ranh/CRS đang dirty từ task trước; không commit/deploy.

## Đối chứng chạy thật

Chrome desktop headless,1100×700,DPR1,CPU slowdown4×. Leaflet1.9.4 và ba module
renderer hiện đang phục vụ từ radarbds.vn. Trang harness được fulfill local
trong browser dưới origin radarbds.vn, không xuất bản trang mới lên server.
Cùng vị trí Tân An **11.022086,106.617125**, opacity50%, zoom14/16/18; chỉ1
planning layer, không tin rao/admin/base map. Mỗi mode chờ5s rồi10 drag120px,
15 mouse steps/drag, ngắt120ms. Tắt inertia,fade và zoom animation để cô lập
renderer; đây không phải trải nghiệm app đầy đủ hoặc máy người dùng.

Modes: SDĐ2030 nguyên bản; SDĐ với4 annotation SVG display:none chỉ trong
harness; phân khu canvas gateway-first. Không thay nguồn/định dạng/chính sách
cache thật. Ởzoom18 kiểm8/8 SDĐ img complete và24/24 PK canvas transport=gateway.
Chưa đo CPU/GPU memory thật, cold-network hoặc throughput tuyến ảnh.

Tất cả9 mode (3 zoom ×3 mode) đều p95 rAF khoảng16.8ms,0 frame interval>50ms,
0 long task trong drag phase. **Chưa tái hiện lag của người dùng.** Việc ẩn nhãn
không cho thấy cải thiện đo được trong môi trường này; không thể khẳng định
SVG là nguyên nhân duy nhất hay cam kết FPS sau sửa từ các con số trên.

Evidence ignored: `.local/compare-landuse-pan.py`,
`.local/landuse-pan-investigation/results.json`,
`.local/landuse-pan-investigation-deep/results.json`,
`.local/landuse-pan-investigation-deep/geometry-check.json`.

## Khác biệt có bằng chứng

1. `referenceClipPath` trong `planning_overlay.js` biến đổi4 ring nhãn rồi
   kiểm **bbox ring** với ô256. Ring nghiêng có bbox lớn, nên nhiều ô không
   giao polygon thật vẫn nhận CSSclip-path. Phân khu GIS không qua bước này.
   Tại viewportzoom16:24 ô tính theo khung nhìn,18 bbox-positive nhưng0 giao
   polygon thật (kiểm Shapely). Với **8 ô thực tế đã tải tại zoom18** (native17
   overzoom),8 có CSSclip-path nhưng **0 giao polygon thật**. Đây là công việc
   render thừa được chứng minh, chưa phải chứng minh nó gây toàn bộ lag.
2. `referenceBranding` tạo và add cả4 `L.imageOverlay` SVG, không lọc theo
   viewport. Zoom16 có SVG4960×5216 và5632×1040 CSSpx; zoom18 lên19840×20864
   và22528×4160. Ba bbox nằm ngoài viewport; bbox SVG thứ nhất phủ viewport
   nhưng polygon thực nằm ngoài các tile đã kiểm. Culling chỉ bằng bbox vẫn
   giữ nhãn không cần. Đây là kích thước CSS, **không phải số MB GPU đã cấp**.
3. Phân khu dùng canvas256 và cache composite hoàn tất tối đa64 ô/180s.
   SDĐ reference dùng img và browser HTTP cache, không có cùng decoded/canvas
   cache JS. Tái tạo img không tự chứng minh tải lại byte qua mạng; cần đo
   cache-hit/decode riêng. Cả hai đã dùng scheduler4 nên giới hạn request
   không giải quyết được phần CSSclip/SVG khi kéo.
4. Khác biệt không phải mặc định tải63 tỉnh: `wantedItems` ràng SDĐ theo
   selectedProvince.layer_ids, BD chỉ1 provider. Catalog/source lookup cũng
   dùng chung cho cả hai theme. Không gán triệu chứng cho tải toàn quốc khi
   chưa có request evidence như vậy.

## Đề xuất theo thứ tự

1. **Sửa kiểm giao thật** giữa polygon annotation với tile, chỉ gắnclip-path
   khi polygon giao có diện tích. Clip ring về biên0..256 trước khi tạo path;
   giữ nguyên vùng cần cắt/hiển thị, test tile nằm trong/ngoài/qua biên, vòng
   nghiêng và trường hợp phủ kín. Cache hình học theo source/z/x/y có giới hạn.
   Đây là sửa tối thiểu cho lỗi đã chứng minh; không đổi chất lượng ảnh.
2. **Không gắn SVG địa lý khổng lồ cho nhãn ngoài vùng nhìn**. Tối thiểu cull
   theo polygon thật với viewport và padding; hướng bền hơn là render nhãn
   theo ô hữu hạn, giữ nội dung/nguồn và không tạo surface hàng chục nghìn px.
   Kiểm alignment/opacity/zoom lifecycle trước phát hành.
3. Sau đó đo A/B đầy đủ app trên Chrome có tăng tốc GPU và máy người dùng,
   cùng camera/opacity/mạng; record render/raster/composite và kéo có inertia.
   Nếu còn chậm mới thêm cache ảnh SDĐ hữu hạn/giảm decode hoặc pipeline
   raster có cache. Không mặc định nén mất dữ liệu hay hạ độ nét để che lỗi.

Nguyên nhân khả nghi nhất: **pipeline cắt/nhãn riêng của SDĐ2030**, có xử lý
thừa thật; chưa xác nhận root cause duy nhất của lag cảm nhận. Cần thêm thông
tin vị trí/zoom/máy cụ thể nếu sau sửa vẫn không tái hiện. Không cần hỏi mật
khẩu hoặc dùng cookie nguồn để chạy đối chứng.
