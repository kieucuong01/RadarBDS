"""Capture the 168 public post-2025 HCM administrative units for viewport rendering."""
import argparse
from datetime import date
import json
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform
from shapely.strtree import STRtree

from services.planning_parcels import API, PublicGIS, esri_geometry

SOURCE='https://gisxaydung.tphcm.gov.vn/tracuuttqh'
QUERY=API+'/arcgis/rest/services/HCM/HanhChinhXa/FeatureServer/0/query'


def write_json(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf8')


def capture(output,source_file=None):
    if source_file:
        data=json.loads(source_file.read_text(encoding='utf8'))
    else:
        client=PublicGIS();client.guest()
        response=client.session.get(QUERY,params={'f':'json','where':'1=1','returnCountOnly':'true'},timeout=(5,25))
        response.raise_for_status();assert response.json().get('count')==168
        response=client.session.get(QUERY,params={'f':'json','where':'1=1',
            'outFields':'OBJECTID,TenXa,MaPhuongXa,TenTinhCu,TenHuyenCu','outSR':4326,
            'returnGeometry':'true','resultRecordCount':1000,'orderByFields':'OBJECTID ASC'},timeout=(5,40))
        response.raise_for_status();data=response.json()
    assert not data.get('error') and not data.get('exceededTransferLimit')
    assert data['spatialReference']['wkid']==4326 and len(data['features'])==168
    rows=sorted(data['features'],key=lambda r:r['attributes']['MaPhuongXa'])
    assert len({r['attributes']['MaPhuongXa'] for r in rows})==168
    geometries=[shape(esri_geometry(r['geometry']['rings'])) for r in rows]
    return write_snapshot(output,rows,geometries,{'source_url':SOURCE,'source_service':'HanhChinhXa/FeatureServer/0',
        'reference_url':'https://diaocthongthai.com/ban-do-tp-hcm-new-2025/'})


def write_snapshot(output,rows,geometries,provenance):
    assert all(g.is_valid and not g.is_empty and g.geom_type in ('Polygon','MultiPolygon') for g in geometries)
    tree=STRtree(geometries);colours=[];overview=[]
    to_metres=Transformer.from_crs(4326,3857,always_xy=True).transform
    to_wgs=Transformer.from_crs(3857,4326,always_xy=True).transform
    output.mkdir(parents=True,exist_ok=True)
    for i,(row,geometry) in enumerate(zip(rows,geometries)):
        a=row['attributes'];code=a['MaPhuongXa']
        assert len(code)==5 and code.isdecimal()
        neighbours={colours[int(j)] for j in tree.query(geometry,predicate='intersects') if j<i}
        colour=next(c for c in range(8) if c not in neighbours);colours.append(colour)
        largest=max(geometry.geoms,key=lambda g:g.area) if geometry.geom_type=='MultiPolygon' else geometry
        label=largest.representative_point();assert geometry.contains(label)
        west,south,east,north=geometry.bounds
        properties={'code':code,'name':a['TenXa'],'source_id':a['OBJECTID'],
            'former_province':a['TenTinhCu'],'bounds':[[south,west],[north,east]],
            'label':[label.y,label.x],'colour':colour}
        full={'type':'Feature','properties':properties,'geometry':mapping(geometry)}
        write_json(output/(code+'.json'),full)
        # Overview only: <=10 m simplification in Mercator; full source geometry at zoom 13+.
        metric=transform(to_metres,geometry)
        tolerance=10
        for _ in range(4):
            candidate=metric.simplify(tolerance,preserve_topology=True)
            if metric.hausdorff_distance(candidate)<=10:break
            tolerance/=2
        else:raise ValueError('Overview exceeds display tolerance')
        simplified=transform(to_wgs,candidate)
        def rounded(value):
            if isinstance(value,(list,tuple)):return [rounded(v) for v in value]
            return round(value,7)
        simplified_json=mapping(simplified);simplified_json['coordinates']=rounded(simplified_json['coordinates'])
        # Rounding can close very narrow rings; preserve precision rather than repair the boundary.
        if not shape(simplified_json).is_valid:
            simplified_json=mapping(simplified)
        if not shape(simplified_json).is_valid:
            simplified_json=mapping(geometry)
        overview.append({'type':'Feature','properties':properties,'geometry':simplified_json})
    bounds=[[min(f['properties']['bounds'][0][0] for f in overview),min(f['properties']['bounds'][0][1] for f in overview)],
            [max(f['properties']['bounds'][1][0] for f in overview),max(f['properties']['bounds'][1][1] for f in overview)]]
    write_json(output/'overview.json',{'type':'FeatureCollection','source_checked_on':date.today().isoformat(),
        **provenance,
        'detail_min_zoom':13,'overview_simplification_metres':10,'bounds':bounds,'features':overview})
    print(json.dumps({'units':len(overview),'overview_bytes':(output/'overview.json').stat().st_size,
                      'detail_bytes':sum((output/(f['properties']['code']+'.json')).stat().st_size for f in overview),'bounds':bounds}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('static/data/admin_hcm_2025'))
    parser.add_argument('--source-file',type=Path)
    args=parser.parse_args();capture(args.output,args.source_file)
