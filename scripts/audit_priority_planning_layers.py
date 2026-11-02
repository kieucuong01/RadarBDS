"""Bounded raster samples for 13 historic markets; never a coverage certificate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PRIORITY = ('binh-duong','hcm','ha-noi','dong-nai','long-an','brvt','hung-yen',
            'hai-phong','da-nang','khanh-hoa','bac-ninh','quang-ninh','lam-dong')
FILES = ('planning_landuse_2030','planning_partition_reference','planning_general_reference','planning_construction')

def tile(point, z):
    lat, lng = point
    return int((lng+180)/360*2**z), int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*2**z)

def sample_point(samples, bounds, focus):
    def inside(point):
        return bounds[0][0]<=point[0]<=bounds[1][0] and bounds[0][1]<=point[1]<=bounds[1][1]
    positive=[s for s in samples if isinstance(s,dict) and s.get('point') and s.get('positive',True)
              and str(s.get('status',200))=='200' and inside(s['point'])]
    if positive:return max(positive,key=lambda s:s.get('z',0))['point'],'previous_positive_sample'
    center=[(focus[0][0]+focus[1][0])/2,(focus[0][1]+focus[1][1])/2]
    if not inside(center):center=[(bounds[0][0]+bounds[1][0])/2,(bounds[0][1]+bounds[1][1])/2]
    return center,'focus_midpoint_with_layer_membership'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--catalog-file',type=Path)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    provinces=json.loads((ROOT/'config/planning_landuse_areas.json').read_text(encoding='utf8'))['provinces']
    audits={}
    for f in FILES:
        for p in json.loads((ROOT/'config'/f'{f}_audit.json').read_text(encoding='utf8'))['provinces']:
            audits[f,p['province']]=p
    jobs=[];inventory=[]
    for province in provinces:
        if province['id'] not in PRIORITY:continue
        for f in FILES:
            for layer in json.loads((ROOT/'config'/f'{f}.json').read_text(encoding='utf8'))['layers']:
                matches=layer['id'] in province['layer_ids'] if f=='planning_landuse_2030' else province['id'] in layer.get('coverage_provinces',[])
                if not matches:continue
                m=layer['manifest'];audit=audits.get((f,province['id']),{})
                samples=audit.get('samples',audit.get('controls',[]))
                samples=samples if isinstance(samples,list) else audit.get('controls',[])
                b=m['bounds']
                focus=m.get('focus_bounds',province.get('focus_bounds',b))
                point,basis=sample_point(samples,b,focus)
                low=m.get('min_native_zoom',m.get('min_zoom',8));high=min(16,m.get('max_native_zoom',m.get('max_zoom',18)))
                row={'province':province['id'],'layer':layer['id'],'theme':layer['theme'],'source_url':layer['source_url'],'template':m['tile_template'],'low_zoom':low,'high_zoom':high,'sample_point':point,'point_basis':basis,'zoom_below_native':'overview' if m.get('overview') else 'native_minimum_guard'}
                inventory.append(row)
                for z in sorted(set([low,high])):
                    x,y=tile(point,z);url=m['tile_template'].replace('{z}',str(z)).replace('{x}',str(x)).replace('{y}',str(y))
                    jobs.append({**row,'z':z,'x':x,'y':y,'url':url})
    if args.catalog_file:
        catalog=json.loads(args.catalog_file.read_text(encoding='utf8'))['layers']
        for layer in catalog:
            m=layer.get('manifest',{})
            if not m.get('source_tiles'):continue
            for province,point in [('binh-duong',[11.022086,106.617125]),('hcm',[10.7769,106.7009]),('brvt',[10.411,107.136])]:
                row={'province':province,'layer':layer['id'],'theme':layer['theme'],'source_url':layer['source_url'],'template':m['source_tiles']['primary'],'low_zoom':12,'high_zoom':16,'sample_point':point,'point_basis':'named_city_sample','zoom_below_native':'native_minimum_guard'}
                inventory.append(row)
                for z in [12,16]:
                    x,y=tile(point,z);url=row['template'].replace('{z}',str(z)).replace('{x}',str(x)).replace('{y}',str(y))
                    jobs.append({**row,'z':z,'x':x,'y':y,'url':url})
    def check(job):
        result={**job}
        try:
            with requests.get(job['url'],timeout=(5,15),stream=True,allow_redirects=False) as r:
                result['status']=r.status_code;r.raise_for_status()
                if r.status_code!=200:raise ValueError('Unexpected redirect')
                data=bytearray()
                for part in r.iter_content(65536):
                    data.extend(part)
                    if len(data)>8_000_000:raise ValueError('Oversized image')
            image=Image.open(BytesIO(data))
            if max(image.size)>2048:raise ValueError('Unexpected image size')
            image.load();rgba=image.convert('RGBA')
            alpha=rgba.getchannel('A');bbox=alpha.getbbox()
            result.update(size=list(image.size),bytes=len(data),sha256=sha256(data).hexdigest(),alpha_bbox=bbox,nonempty=bbox is not None)
            (args.output/f"{job['province']}-{job['layer']}-{job['z']}.png").write_bytes(data)
        except Exception as e:result['error']=str(e)[:300]
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(check,jobs))
    report={'scope':list(PRIORITY),'method':'two bounded point samples per registered reference layer, not full coverage','inventory':inventory,'samples':results}
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'layers':len(inventory),'samples':len(results),'nonempty':sum(r.get('nonempty',False) for r in results),'errors':sum('error' in r for r in results),'empty':sum(r.get('nonempty') is False for r in results)}))

if __name__=='__main__':main()
