"""Opt-in loopback runner; never imported by the production app entry point."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

from flask import abort, jsonify, request, send_file

ROOT = Path(__file__).resolve().parents[1]
FILES = ('overlay.webp', 'legend.webp')
CATALOG_PATH = ROOT / 'config/ben_cat_planning_catalog.json'


def read_manifest(directory, expected_id='thoi-hoa-2909-qh01'):
    payload = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if payload.get('id') != expected_id or payload.get('status') != 'local_experiment':
        raise ValueError('Unknown pilot manifest')
    bounds = payload['bounds']
    if len(bounds) != 2 or any(len(point) != 2 for point in bounds):
        raise ValueError('Invalid bounds')
    south, west, north, east = [float(v) for point in bounds for v in point]
    if not all(math.isfinite(v) for v in (south, west, north, east)) or not (
        10.75 <= south < north <= 11.65 and 106.25 <= west < east <= 107.10
    ):
        raise ValueError('Bounds outside supported area')
    required_files = FILES if payload.get('legend_available', True) else ('overlay.webp',)
    for name in required_files:
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != payload['artifacts'][name]:
            raise ValueError('Artifact hash mismatch')
    return payload


def install_pilot(app, directory=None):
    directory = Path(directory or ROOT / '.local/planning-ben-cat').resolve()
    catalog = json.loads(CATALOG_PATH.read_text(encoding='utf8'))['layers']
    layers = {layer['id']: layer for layer in catalog}

    def layer_folder(layer):
        relative = layer.get('artifact_dir', '' if layer['slug'] == 'thoi-hoa' else layer['slug'])
        folder = (directory / relative).resolve()
        if not folder.is_relative_to(directory):
            raise ValueError('Artifact folder outside pilot directory')
        return folder

    @app.get('/local-planning/catalog.json')
    def planning_catalog():
        result = []
        native = app.extensions.get('planning_native_layers', [])
        for layer in catalog:
            item = {k: layer[k] for k in ('id', 'name', 'status', 'decision', 'source_url')}
            item['city'] = layer.get('city', 'Bến Cát')
            item.update({key: layer[key] for key in ('theme', 'source', 'area_id', 'scope', 'notice') if key in layer})
            item['message'] = layer.get('message', '')
            if layer['status'] == 'overlay_ready':
                try:
                    item['manifest'] = read_manifest(layer_folder(layer), layer['id'])
                except (OSError, ValueError, KeyError, TypeError, IndexError):
                    item.update(status='artifact_unavailable', message='Lớp phủ chưa sẵn sàng hoặc không khớp kiểm tra dữ liệu.')
            elif layer['status'] == 'document_only':
                item['preview_url'] = '/local-planning/' + layer['id'] + '/preview.webp'
            result.append(item)
            if native and item.get('source') == 'gis':
                item['inspection_only'] = True
        result.extend(native)
        from config.planning_regions import LANDUSE_2030_LAYERS, VISION_100_LAYERS, TRANSPORT_LAYERS, ADMINISTRATIVE_LAYERS
        result.extend((*LANDUSE_2030_LAYERS, *VISION_100_LAYERS, *TRANSPORT_LAYERS, *ADMINISTRATIVE_LAYERS))
        return jsonify(layers=result)

    @app.get('/local-planning/<layer_id>/<name>')
    def layer_asset(layer_id, name):
        layer = layers.get(layer_id)
        if not layer:
            abort(404)
        try:
            folder = layer_folder(layer)
            if layer['status'] == 'overlay_ready' and name in FILES:
                payload = read_manifest(folder, layer_id)
                if name == 'legend.webp' and not payload.get('legend_available', True):
                    abort(404)
            elif layer['status'] == 'document_only' and name == 'preview.webp':
                hashes = json.loads((directory / 'documents.json').read_text(encoding='utf8'))
                if hashlib.sha256((folder / name).read_bytes()).hexdigest() != hashes[layer_id]:
                    raise ValueError('Preview hash mismatch')
            else:
                abort(404)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return jsonify(error='Bản vẽ chưa sẵn sàng hoặc không khớp kiểm tra dữ liệu.'), 503
        return send_file(folder / name, mimetype='image/webp', conditional=False)

    @app.before_request
    def loopback_only():
        # Do not trust a reverse proxy or a rebinding Host on this local runner.
        if (request.remote_addr not in ('127.0.0.1', '::1')
            or request.host.split(':')[0] not in ('localhost', '127.0.0.1')
            or any(request.headers.get(h) for h in ('Forwarded', 'X-Forwarded-For', 'X-Forwarded-Host'))):
            abort(404)

    @app.context_processor
    def pilot_context():
        return {'planning_pilot_enabled': True, 'planning_overlay_config': None}

    def private_pilot(response):
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers.pop('X-Radar-Public-Cache', None)
        response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    # Flask executes these hooks in reverse registration order. Run last so
    # the main app's immutable static-asset policy cannot cache a local pilot.
    app.after_request_funcs.setdefault(None, []).insert(0, private_pilot)

    @app.get('/local-planning/<name>')
    def planning_asset(name):
        if name not in (*FILES, 'manifest.json'):
            abort(404)
        try:
            payload = read_manifest(directory)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            return jsonify(error='Bản đồ thử chưa sẵn sàng hoặc không khớp kiểm tra dữ liệu.'), 503
        if name == 'manifest.json':
            return jsonify(payload)
        return send_file(directory / name, mimetype='image/webp', conditional=False)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    import app as app_module

    install_pilot(app_module.app)
    from services.planning_tiles import install_tiles
    install_tiles(app_module.app, ROOT / '.local/planning-gis-tiles')
    parcel_directory = ROOT / '.local/planning-parcels-tan-an'
    parcel_catalog = ROOT / '.local/planning-parcels/parcels.sqlite'
    if parcel_catalog.is_file():
        from services.planning_parcel_catalog import install_catalog
        install_catalog(app_module.app, parcel_catalog, expanded=True)
    elif (parcel_directory / 'parcels.geojson').is_file():
        from services.planning_parcels import install_parcel_pilot
        install_parcel_pilot(app_module.app, parcel_directory)
    app_module.app.run(host='127.0.0.1', port=5055, debug=False, use_reloader=False)
