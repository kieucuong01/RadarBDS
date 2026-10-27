"""Verify public GIS native grid metadata before enabling local planning tile routes."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    import requests
    from services.planning_tiles import METADATA_SERVICES,HEADERS,API,validate_grid,NativeGISTiles
    directory=ROOT/'.local/planning-gis-tiles/metadata'
    captures={}
    session=requests.Session();session.trust_env=False;session.headers.update(HEADERS)
    for theme,service in METADATA_SERVICES.items():
        response=NativeGISTiles._public_get(session,API+'/arcm/rest/services/HCM/'+service+'/MapServer',
                                           params={'f':'json'})
        response.raise_for_status()
        if len(response.content)>2_000_000:raise ValueError('Unexpected GIS metadata size')
        data=response.json();validate_grid(data);captures[theme]=data
    directory.mkdir(parents=True,exist_ok=True)
    for theme,data in captures.items():
        target=directory/f'{theme}.json';temporary=directory/f'{theme}.download'
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(target)
        print('Verified native grid:',theme,flush=True)


if __name__=='__main__':main()
