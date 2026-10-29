"""Display windows for planning imagery; parcel/listing scope remains independent."""
import json
from pathlib import Path

LANDUSE_2030_LAYERS = tuple(json.loads(Path(__file__).with_name('planning_landuse_2030.json')
                                     .read_text(encoding='utf8'))['layers'])
BINH_DUONG_BOUNDS = [[10.75, 106.25], [11.65, 107.1]]
HCM_EXPANDED_BOUNDS = [[8.5, 106.25], [11.65, 107.65]]
DONG_NAI_EXPANDED_BOUNDS = [[10.49, 106.39], [12.33, 107.60]]
PLANNING_BOUNDS = {'partition': HCM_EXPANDED_BOUNDS, 'urban_general': HCM_EXPANDED_BOUNDS,
                   'detailed': HCM_EXPANDED_BOUNDS}
PLANNING_REGIONS = [
    {'id': 'dong-nai-expanded', 'name': 'Đồng Nai mới (gồm Bình Phước cũ)',
     'bounds': DONG_NAI_EXPANDED_BOUNDS, 'max_zoom': 10,
     'notice': 'Đồng Nai mới: bật QH 2030 để xem dữ liệu Đồng Nai và Bình Phước cũ. Ranh thửa chưa được tích hợp cho địa bàn này.'},
    {'id': 'dong-nai-legacy', 'name': 'Đồng Nai (cũ)',
     'bounds': [[10.49,106.72],[11.59,107.60]], 'max_zoom': 11,
     'notice': 'Đồng Nai cũ: bật QH 2030 để xem bản đồ sử dụng đất tham khảo.'},
    {'id': 'binh-phuoc-legacy', 'name': 'Bình Phước (cũ)',
     'bounds': [[11.31,106.39],[12.33,107.43]], 'max_zoom': 11,
     'notice': 'Bình Phước cũ: bật QH 2030 để xem bản đồ sử dụng đất tham khảo.'},
    {'id': 'hcm-expanded', 'name': 'Toàn TP.HCM mới', 'bounds': HCM_EXPANDED_BOUNDS, 'max_zoom': 10},
    {'id': 'hcm-legacy', 'name': 'TP.HCM (cũ)', 'bounds': [[10.3, 106.3], [11.2, 107.05]], 'max_zoom': 12},
    {'id': 'binh-duong-legacy', 'name': 'Bình Dương (cũ)', 'bounds': BINH_DUONG_BOUNDS, 'max_zoom': 12},
    {'id': 'brvt-legacy', 'name': 'Bà Rịa–Vũng Tàu (cũ)', 'bounds': [[10.3, 107.0], [10.9, 107.65]], 'max_zoom': 12},
    {'id': 'con-dao', 'name': 'Côn Đảo', 'bounds': [[8.65, 106.56], [8.74, 106.67]], 'max_zoom': 14,
     'notice': 'Côn Đảo: phân khu có theo từng khu vực trên GIS; vùng trống cần đối chiếu hồ sơ nguồn.'},
]
