"""Display windows for planning imagery; parcel/listing scope remains independent."""
import json
from pathlib import Path

LANDUSE_2030_LAYERS = tuple(json.loads(Path(__file__).with_name('planning_landuse_2030.json')
                                     .read_text(encoding='utf8'))['layers'])
BINH_DUONG_BOUNDS = [[10.75, 106.25], [11.65, 107.1]]
HCM_EXPANDED_BOUNDS = [[8.5, 106.25], [11.65, 107.65]]
PLANNING_BOUNDS = {'partition': HCM_EXPANDED_BOUNDS, 'urban_general': BINH_DUONG_BOUNDS,
                   'detailed': HCM_EXPANDED_BOUNDS}
PLANNING_REGIONS = [
    {'id': 'hcm-expanded', 'name': 'Toàn TP.HCM mới', 'bounds': HCM_EXPANDED_BOUNDS, 'max_zoom': 10},
    {'id': 'hcm-legacy', 'name': 'TP.HCM (cũ)', 'bounds': [[10.3, 106.3], [11.2, 107.05]], 'max_zoom': 12},
    {'id': 'binh-duong-legacy', 'name': 'Bình Dương (cũ)', 'bounds': BINH_DUONG_BOUNDS, 'max_zoom': 12},
    {'id': 'brvt-legacy', 'name': 'Bà Rịa–Vũng Tàu (cũ)', 'bounds': [[10.3, 107.0], [10.9, 107.65]], 'max_zoom': 12},
    {'id': 'con-dao', 'name': 'Côn Đảo', 'bounds': [[8.65, 106.56], [8.74, 106.67]], 'max_zoom': 14,
     'notice': 'Côn Đảo: phân khu có theo từng khu vực trên GIS; vùng trống cần đối chiếu hồ sơ nguồn.'},
]
