"""Production serves only the validated, versioned planning snapshot, never local sources."""
import json

import pytest

from scripts.build_planning_release import build_release
from services.planning_assets import load_release


def inputs(tmp_path):
    import hashlib
    root=tmp_path/'capture';root.mkdir()
    layer=root/'ward';layer.mkdir()
    (layer/'overlay.webp').write_bytes(b'public-map-image')
    manifest=dict(id='ward-gis',status='local_experiment',title='GIS',notice='Source edition unverified',
        bounds=[[11,106.6],[11.1,106.7]],legend_available=False,source_kind='official_gis',
        alignment_method='official_coordinates',map_scale=2000,captured_on='2026-10-27',
        internal_path='private-capture-path',artifacts={'overlay.webp':hashlib.sha256(b'public-map-image').hexdigest()})
    (layer/'manifest.json').write_text(json.dumps(manifest))
    (layer/'original.pdf').write_bytes(b'not-for-public-bundle')
    catalog=tmp_path/'catalog.json'
    catalog.write_text(json.dumps({'layers':[dict(id='ward-gis',name='Ward',slug='ward',city='Thủ Dầu Một',
        theme='partition',source='gis',scope='area',area_id='ward',status='overlay_ready',decision='GIS',
        source_url='https://gisxaydung.tphcm.gov.vn/tracuuttqh',artifact_dir='ward')]}))
    return root,catalog


def test_release_is_deterministic_sanitized_and_immutable(tmp_path):
    root,catalog=inputs(tmp_path)
    output=tmp_path/'site/static/maps/planning/overlays'
    release=build_release(catalog,root,output)
    assert release==build_release(catalog,root,output)
    directory=output/release['release']
    public=json.loads((directory/'catalog.json').read_text())
    item=public['layers'][0]
    assert item['manifest']['status']=='reference_overlay'
    assert 'artifact_dir' not in item and 'internal_path' not in item['manifest']
    assert sorted(p.name for p in (directory/'ward-gis').iterdir())==['overlay.webp']
    config=tmp_path/'site/config/planning_release.json';config.parent.mkdir()
    config.write_text(json.dumps(release))
    active=load_release(tmp_path/'site')
    assert active['catalogUrl'].endswith('/'+release['release']+'/catalog.json')
    assert active['assetBase'].startswith('/static/maps/planning/overlays/')
    (directory/'ward-gis/overlay.webp').write_bytes(b'changed')
    assert load_release(tmp_path/'site') is None
    with pytest.raises(ValueError,match='existing|Existing|immutable'):
        build_release(catalog,root,output)


def test_release_rejects_source_escape_and_invalid_capture(tmp_path):
    root,catalog=inputs(tmp_path)
    data=json.loads(catalog.read_text());data['layers'][0]['artifact_dir']='../escape'
    catalog.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='outside|escape'):
        build_release(catalog,root,tmp_path/'out')
    assert load_release(tmp_path/'missing-site') is None


def test_runtime_rejects_release_paths_outside_allowlisted_public_images(tmp_path):
    config=tmp_path/'config';config.mkdir()
    (config/'planning_release.json').write_text(json.dumps(dict(release='../private',files={})))
    assert load_release(tmp_path) is None
