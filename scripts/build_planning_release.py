"""Package only validated display images and a sanitized catalog for production."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.run_planning_pilot import read_manifest
from services.planning_assets import release_id

PUBLIC_FIELDS = ('id','title','bounds','notice','decision','map_scale','captured_on','source_url',
                 'source_kind','alignment_method','check_max_m','check_count','legend_available','attribution')


def build_release(catalog_path, source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    catalog = json.loads(Path(catalog_path).read_text(encoding='utf8'))['layers']
    if not 1 <= len(catalog) <= 64:
        raise ValueError('Invalid catalog size')
    rows, images, ids = [], {}, set()
    for layer in catalog:
        identity = layer['id']
        if not re.fullmatch(r'[a-z0-9-]+', identity) or identity in ids:
            raise ValueError('Invalid or duplicate layer ID')
        ids.add(identity)
        item = {k:layer[k] for k in ('id','name','city','theme','source','scope','area_id','status','decision','source_url','message','notice') if k in layer}
        if layer['status'] == 'overlay_ready':
            relative = layer.get('artifact_dir', '' if layer['slug']=='thoi-hoa' else layer['slug'])
            directory = (source/relative).resolve()
            if not directory.is_relative_to(source):
                raise ValueError('Capture folder outside source directory')
            manifest = read_manifest(directory, identity)
            item['manifest'] = {k:manifest[k] for k in PUBLIC_FIELDS if k in manifest}
            item['manifest']['status'] = 'reference_overlay'
            for name in ('overlay.webp', 'legend.webp') if manifest.get('legend_available', True) else ('overlay.webp',):
                images[identity+'/'+name] = (directory/name).read_bytes()
        elif layer['status'] == 'document_only':
            item.update(status='source_unavailable', message='Mở hồ sơ gốc để xem tài liệu này.')
        rows.append(item)
    payloads = {'catalog.json':(json.dumps({'layers':rows}, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode('utf8'), **images}
    files = {name:hashlib.sha256(data).hexdigest() for name,data in sorted(payloads.items())}
    version = release_id(files)
    destination = output/version
    if destination.exists():
        actual = {p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.rglob('*') if p.is_file()}
        if actual != files:
            raise ValueError('Existing immutable release differs from its expected files')
    else:
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.staging-', dir=output) as temporary:
            stage = Path(temporary)
            for name,data in payloads.items():
                path = stage/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
            stage.replace(destination)
    return {'version':1, 'release':version, 'files':files, 'layer_count':len(rows), 'image_count':len(images)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=ROOT/'config/ben_cat_planning_catalog.json')
    parser.add_argument('--source', type=Path, default=ROOT/'.local/planning-ben-cat')
    parser.add_argument('--output', type=Path, default=ROOT/'static/maps/planning/overlays')
    parser.add_argument('--release-config', type=Path, default=ROOT/'config/planning_release.json')
    args = parser.parse_args()
    result = build_release(args.catalog, args.source, args.output)
    args.release_config.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n', encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='files'}))
