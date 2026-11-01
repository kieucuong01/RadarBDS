"""Read-only local snapshot benchmark; never contacts a public GIS."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import math
from pathlib import Path
import statistics
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.planning_parcel_catalog import ParcelCatalog
from services.planning_parcel_tiles import CellCache, bounds, ZOOM, FIELDS, public_feature, display_features


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('catalog',type=Path)
    parser.add_argument('--requests',type=int,default=1000)
    parser.add_argument('--concurrency',type=int,default=16)
    args=parser.parse_args()
    if not 1<=args.requests<=5000 or not 1<=args.concurrency<=32:
        parser.error('Bounded local benchmark: requests <=5000, concurrency <=32')
    catalog=ParcelCatalog(args.catalog)
    box=(106.614,11.020,106.620,11.025)
    start=time.perf_counter();features,_=catalog.viewport(box)
    old_ms=(time.perf_counter()-start)*1000
    old=json.dumps(dict(type='FeatureCollection',features=features),separators=(',',':')).encode()
    def x(lon):return int((lon+180)/360*(2**ZOOM))
    def y(lat):return int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*(2**ZOOM))
    cells=[(col,row) for col in range(x(box[0]),x(box[2])+1) for row in range(y(box[3]),y(box[1])+1)]
    source_calls=0
    with tempfile.TemporaryDirectory() as directory:
        cache=CellCache(Path(directory)/'cells.sqlite')
        def load(cell):
            nonlocal source_calls
            source_calls+=1
            features,count=catalog.viewport(bounds(*cell))
            return dict(type='FeatureCollection',features=display_features([public_feature(f) for f in features],bounds(*cell)),truncated=count>1500)
        cold=time.perf_counter();sizes=[]
        for cell in cells:sizes.append(len(cache.get(str(cell),lambda cell=cell:load(cell),86400)[0]))
        cold_ms=(time.perf_counter()-cold)*1000
        def read(index):
            start=time.perf_counter()
            cache.get(str(cells[index%len(cells)]),lambda: (_ for _ in ()).throw(AssertionError('Warm miss')),86400)
            return (time.perf_counter()-start)*1000
        start=time.perf_counter()
        with ThreadPoolExecutor(args.concurrency) as pool:timings=list(pool.map(read,range(args.requests)))
        elapsed=time.perf_counter()-start
    print(json.dumps(dict(scope='local snapshot, warm cell cache; NOT 1000 simultaneous users or public edge',
        old_view_features=len(features),old_query_ms=round(old_ms,2),old_gzip_bytes=len(gzip.compress(old)),
        cells=len(cells),cold_cells_ms=round(cold_ms,2),cold_cell_gzip_bytes=sum(sizes),
        snapshot_queries=source_calls,warm_requests=args.requests,concurrency=args.concurrency,
        warm_total_seconds=round(elapsed,3),warm_p50_ms=round(statistics.median(timings),2),
        warm_p95_ms=round(sorted(timings)[int(len(timings)*.95)-1],2)),indent=2))


if __name__=='__main__':main()
