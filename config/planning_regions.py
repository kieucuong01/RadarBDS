"""Display windows for planning imagery; parcel/listing scope remains independent."""
import json
from pathlib import Path

LANDUSE_2030_LAYERS = tuple(json.loads(Path(__file__).with_name('planning_landuse_2030.json')
                                     .read_text(encoding='utf8'))['layers'])
VISION_100_LAYERS = tuple(json.loads(Path(__file__).with_name('planning_vision_100.json')
                                   .read_text(encoding='utf8'))['layers'])
TRANSPORT_LAYERS = tuple(json.loads(Path(__file__).with_name('planning_transport.json')
                                  .read_text(encoding='utf8'))['layers'])
ADMINISTRATIVE_LAYERS = tuple(json.loads(Path(__file__).with_name('planning_administrative.json')
                                       .read_text(encoding='utf8'))['layers']) + tuple(
    json.loads(Path(__file__).with_name('planning_administrative_legacy.json').read_text(encoding='utf8'))['layers'])
LANDUSE_AREAS = tuple(p for p in json.loads(Path(__file__).with_name('planning_landuse_areas.json')
                                          .read_text(encoding='utf8'))['provinces']
                      if any(layer['id'] in p['layer_ids'] and layer['status'] == 'overlay_ready'
                             for layer in LANDUSE_2030_LAYERS))
LANDUSE_SOURCE_RULES = {
    layer['id']: {key:layer['manifest'][key] for key in (
        'tile_template','bounds','min_zoom','max_zoom','tile_size',
        'min_native_zoom','max_native_zoom','coverage_windows') if key in layer['manifest']}
    for layer in LANDUSE_2030_LAYERS
}
LANDUSE_PUBLIC_AREAS = tuple(
    {**p,'districts':[{key:d[key] for key in ('id','name','bounds')} for d in p['districts']]}
    for p in LANDUSE_AREAS
)
BINH_DUONG_BOUNDS = [[10.75, 106.25], [11.65, 107.1]]
HCM_EXPANDED_BOUNDS = [[8.5, 106.25], [11.65, 107.65]]
DONG_NAI_EXPANDED_BOUNDS = [[10.49, 106.39], [12.33, 107.60]]
PLANNING_BOUNDS = {'partition': HCM_EXPANDED_BOUNDS, 'urban_general': HCM_EXPANDED_BOUNDS,
                   'detailed': HCM_EXPANDED_BOUNDS}
PLANNING_REGIONS = [
    {'id':'tay-ninh-legacy','name':'Tây Ninh (cũ)',
     'bounds':[[10.962,105.809],[11.780,106.493]],'max_zoom':11,
     'notice':'Tây Ninh cũ: QH SDĐ 2030 tham khảo; ranh thửa chưa tích hợp cho khu vực này.'},
    {'id':'long-an-legacy','name':'Long An (cũ)',
     'bounds':[[10.395,105.498],[11.032,106.749]],'max_zoom':11,
     'notice':'Long An cũ, thuộc Tây Ninh mới: QH SDĐ 2030 tham khảo; ranh thửa chưa tích hợp cho khu vực này.'},
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
PLANNING_REGIONS.extend(
    {'id':p['region_id'],'name':p['name']+' (cũ)',
     'bounds':p.get('focus_bounds',p['bounds']),'max_zoom':13,
     'notice':'QH SDĐ 2030 tham khảo; dữ liệu ranh thửa và các loại quy hoạch khác chưa được tích hợp cho địa bàn này.'}
    for p in LANDUSE_AREAS if p['region_id'] not in {r['id'] for r in PLANNING_REGIONS}
)
