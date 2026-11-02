from copy import deepcopy
import json
import math

from flask import Flask
import pytest

from services.planning_khanh_hoa_parcels import KhanhHoaParcels, KhanhHoaGIS, QUERY, SOURCE, FIELDS, ID_OFFSET
from services.planning_dongnai_parcels import RegionalParcels


class Source:
    def __init__(self):
        self.calls = []
        self.data = dict(spatialReference=dict(wkid=4326), features=[dict(
            attributes=dict(OBJECTID=7, So_To='1', So_Thua='14', Dien_Tich=120,
                MaXa='22465', MaHuyen='570            ', TenPhuong='Cam An Bắc', TenHuyen='Cam Lâm',
                Chu_SD1='PRIVATE OWNER', DiaChi_CSD='PRIVATE ADDRESS'),
            geometry=dict(rings=[[[109.08,12.02],[109.081,12.02],[109.081,12.021],
                                  [109.08,12.021],[109.08,12.02]]]))])

    def request(self, path, *, params):
        assert path == QUERY and params['outFields'] == FIELDS
        assert 'Chu_SD' not in params['outFields'] and 'DiaChi' not in params['outFields']
        self.calls.append(params)
        return deepcopy(self.data)


def test_safe_fields_source_projection_namespace_and_exact_search():
    source = Source();provider = KhanhHoaParcels(client=source)
    feature = provider.search('kh-570-22465', '1', '14')['features'][0]
    assert feature['id'] == ID_OFFSET+7
    assert feature['properties']['source'] == SOURCE
    assert feature['properties']['source_id'] == 7
    assert feature['properties']['province'] == 'khanh-hoa'
    assert feature['geometry']['coordinates'][0][1] == [109.081,12.02]
    assert 'PRIVATE' not in json.dumps(feature)
    assert "So_To = '1' AND So_Thua = '14'" in source.calls[0]['where']
    assert source.calls[0]['outSR'] == 4326
    assert provider.feature(ID_OFFSET+7, 'kh-570-22465') == feature
    assert len(source.calls) == 1


def test_actual_feature_query_removes_namespace_and_quotes_search_literals():
    source = Source();provider = KhanhHoaParcels(client=source)
    assert provider.feature(ID_OFFSET+7)['id'] == ID_OFFSET+7
    assert source.calls[-1]['where'].endswith('OBJECTID = 7')
    source.data['features'][0]['attributes']['So_Thua'] = "14' AND 1=1"
    provider.search('kh-570-22465', '1', "14' AND 1=1")
    assert "So_Thua = '14'' AND 1=1'" in source.calls[-1]['where']


@pytest.mark.parametrize('change', ['wrong_name','unknown_area','null_area','invalid_polygon'])
def test_unverified_localities_and_invalid_geometry_are_excluded(change):
    source = Source();row = source.data['features'][0]
    if change=='wrong_name':row['attributes']['TenHuyen']='Cam Ranh'
    if change=='unknown_area':row['attributes']['MaXa']='99999'
    if change=='null_area':row['attributes']['MaHuyen']=None
    if change=='invalid_polygon':row['geometry']['rings'][0][1]=[0,0]
    result = KhanhHoaParcels(client=source).viewport((109.079,12.019,109.082,12.022))
    assert not result['features'] and result['excluded_count']==1


def test_crs_ignored_search_and_foreign_area_fail_closed():
    source = Source();source.data['spatialReference']['wkid']=3405
    with pytest.raises(ValueError,match='coordinate system'):
        KhanhHoaParcels(client=source).search('kh-570-22465','1','14')
    source.data['spatialReference']['wkid']=4326
    provider=KhanhHoaParcels(client=source)
    with pytest.raises(ValueError,match='ignored exact'):
        provider.search('kh-570-22465','1','99999')
    with pytest.raises(ValueError,match='Unsupported'):
        provider.search('bp-689-25201','1','14')


def test_point_requires_polygon_coverage_and_bbox_accepts_only_bounded_region():
    provider = KhanhHoaParcels(client=Source())
    assert provider.point(109.0805,12.0205)['features'][0]['id']==ID_OFFSET+7
    with pytest.raises(ValueError,match='ignored coordinate'):
        provider.point(109.082,12.022)
    from services.planning_parcels import parcel_bbox
    assert parcel_bbox('109.079,12.019,109.082,12.022',expanded=True,
                       coverage_bounds=RegionalParcels.coverage_bounds)[0]==109.079
    with pytest.raises(ValueError):
        parcel_bbox('109.079,12.019,109.082,12.022',expanded=True)
    with pytest.raises(ValueError):
        parcel_bbox('109.07,12.01,109.15,12.09',expanded=True,coverage_bounds=RegionalParcels.coverage_bounds)


def test_regions_cells_and_planning_never_mix_provider_ids(tmp_path,monkeypatch):
    from services.planning_parcels import PublicGIS,install_planning_lookup
    from services.planning_dongnai_info import DongNaiPlanning
    from services.planning_parcel_tiles import install
    def forbidden(*args,**kwargs):raise AssertionError('Khánh Hòa cannot use HCM/Bình Phước object IDs')
    monkeypatch.setattr(PublicGIS,'request',forbidden)
    monkeypatch.setattr(DongNaiPlanning,'lookup',forbidden)
    kh=KhanhHoaParcels(client=Source());regional=RegionalParcels(khanhhoa=kh)
    feature=regional.search('kh-570-22465','1','14')['features'][0]
    assert regional.feature(feature['id'])==feature
    assert regional.point(109.0805,12.0205)['features']==[feature]
    class Catalog:
        areas=[]
        def feature(self,*args):return None
        def viewport(self,*args):return [],0
    app=Flask(__name__);install(app,Catalog(),regional,tmp_path,'kh-test')
    install_planning_lookup(app,lambda identifier:regional.feature(identifier))
    c=app.test_client();x=int((109.0805+180)/360*2**17)
    y=int((1-math.asinh(math.tan(math.radians(12.0205)))/math.pi)/2*2**17)
    cell=c.get(f'/api/planning/parcel-cells/kh-test/live/{x}/{y}.json')
    assert cell.status_code==200 and cell.json['features'][0]['properties']['source']==SOURCE
    original=c.get(f'/api/planning/parcel-original/kh-test/{ID_OFFSET+7}.json')
    assert original.json['geometry']==feature['geometry']
    result=c.get(f'/local-planning/parcels/{ID_OFFSET+7}/planning.json')
    assert result.status_code==200 and result.json['planning_available'] is False
    assert result.json['plans']==[] and result.json['source']==SOURCE


def test_client_rejects_unregistered_endpoints_and_private_field_requests():
    with pytest.raises(ValueError):KhanhHoaGIS().request('/admin',params={})
    with pytest.raises(ValueError):KhanhHoaGIS().request(QUERY,params={'outFields':'*'})
    with pytest.raises(ValueError):KhanhHoaGIS().request(QUERY,params={'where':'1=1'})


def test_reference_capture_rejects_truncation_and_ambiguous_code():
    from scripts.capture_khanh_hoa_parcel_areas import references
    with pytest.raises(ValueError):references(dict(features=[{}],exceededTransferLimit=True))
    attrs=dict(MaXa='22465',MaHuyen='570            ',TenPhuong='Cam An Bắc',TenHuyen='Cam Lâm')
    with pytest.raises(ValueError,match='Ambiguous'):
        references(dict(features=[dict(attributes=attrs),dict(attributes=attrs)]))
