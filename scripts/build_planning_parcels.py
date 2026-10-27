"""Capture all supported historic wards, then publish a local spatial asset index."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    from config.planning_parcels import PARCEL_AREAS
    from services.planning_parcels import capture, PublicGIS
    from services.planning_parcel_catalog import build_catalog
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--index-only',action='store_true')
    args = parser.parse_args()
    directory = ROOT/'.local/planning-parcels'
    directory.mkdir(exist_ok=True)
    client = PublicGIS()
    if not args.index_only:
        for area in PARCEL_AREAS:
            folder = directory/area['code']
            ready = False
            if not args.refresh and (folder/'metadata.json').is_file() and (folder/'parcels.geojson').is_file():
                metadata = json.loads((folder/'metadata.json').read_text(encoding='utf8'))
                where = "MaPhuongXa = '%s' AND MaQuanHuyen = '%s'"%(area['code'],area['district'])
                current = client.request('/rest/thua-dat/query',params={'f':'json','where':where,'returnCountOnly':'true'})['count']
                ready = (metadata['source_count'] == current and
                         metadata['sha256'] == sha256((folder/'parcels.geojson').read_bytes()).hexdigest())
            if ready:
                print('Verified previous capture:',area['ward'],flush=True)
            else:
                capture(folder,client=client,area=area)
    path = build_catalog(directory,PARCEL_AREAS)
    print('Complete spatial catalogue:',path,flush=True)


if __name__ == '__main__':
    main()
