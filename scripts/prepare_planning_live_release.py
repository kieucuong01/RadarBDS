"""Package only verified public parcel/grid assets; no raw source captures or tokens."""
import argparse
from hashlib import file_digest
import json
from pathlib import Path
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify',action='store_true',help='Verify installed assets before enabling production')
    args=parser.parse_args()
    from services.planning_live import validate_assets
    if args.verify:
        folder,config=validate_assets(ROOT,verify_hashes=True)
        print('Verified planning release',config['release'],config['areas'],'areas',config['count'],'parcels')
        return
    from services.planning_assets import release_id
    from services.planning_parcel_catalog import ParcelCatalog
    from services.planning_tiles import METADATA_SERVICES,validate_grid
    sources={'parcels.sqlite':ROOT/'.local/planning-parcels/parcels.sqlite',
        **{f'metadata/{name}.json':ROOT/'.local/planning-gis-tiles/metadata'/f'{name}.json' for name in METADATA_SERVICES}}
    files={}
    for name,path in sources.items():
        if name!='parcels.sqlite':validate_grid(json.loads(path.read_text(encoding='utf8')))
        with path.open('rb') as stream: digest=file_digest(stream,'sha256').hexdigest()
        files[name]={'sha256':digest,'bytes':path.stat().st_size}
    catalog=ParcelCatalog(sources['parcels.sqlite'])
    from config.planning_parcels import PARCEL_AREAS
    assert {a['area_id'] for a in catalog.areas}=={a['code'] for a in PARCEL_AREAS}
    config={'release':release_id(files),'files':files,'areas':len(catalog.areas),
            'count':sum(a['count'] for a in catalog.areas)}
    target=ROOT/'.local/planning-releases'/f"{config['release']}.tar.gz"
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix('.download')
    with tarfile.open(temporary,'w:gz',compresslevel=3) as archive:
        for name,path in sources.items():
            archive.add(path,arcname=config['release']+'/'+name,recursive=False)
    temporary.replace(target)
    (ROOT/'config/planning_live_release.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf8')
    print('Packaged',config['release'],config['areas'],'areas',config['count'],'parcels',
          target.stat().st_size,'compressed bytes',flush=True)
    print(target,flush=True)


if __name__=='__main__':main()
