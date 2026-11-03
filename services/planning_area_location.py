"""Resolve a browser location against the existing historic boundary snapshot."""
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata


@lru_cache(maxsize=4)
def _overview(path):
    return json.loads(Path(path).read_text(encoding='utf8'))['features']


def _name(value):
    value=unicodedata.normalize('NFKD',value.lower().replace('đ','d'))
    value=''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'^(thanh pho|thi xa|quan|huyen)\s+','',value).strip()


def resolve_area(site,latitude,longitude):
    from shapely.geometry import Point,shape
    provinces=json.loads((Path(site)/'config/planning_landuse_areas.json').read_text(encoding='utf8'))['provinces']
    point=Point(longitude,latitude);matches={}
    def covers(bounds):
        return bounds[0][0]<=latitude<=bounds[1][0] and bounds[0][1]<=longitude<=bounds[1][1]
    for province in provinces:
        path=Path(site)/'static/data/admin_vn_legacy'/province['id']/'overview.json'
        if not covers(province['bounds']) or not path.is_file():continue
        for feature in _overview(str(path)):
            props=feature['properties']
            if covers(props['bounds']) and shape(feature['geometry']).covers(point):
                name=_name(props.get('district',''))
                # Old commune snapshot predates the Thu Duc district consolidation.
                if province['id']=='hcm' and name in ('2','9','thu duc'):name='thu duc'
                districts=[d for d in province['districts'] if _name(d['name'])==name]
                matches.setdefault(province['id'],set()).add(districts[0]['id'] if len(districts)==1 else '')
    if len(matches)!=1:return {'matched':False}
    province,districts=next(iter(matches.items()))
    return dict(matched=True,province=province,district=next(iter(districts)) if len(districts)==1 else '')
