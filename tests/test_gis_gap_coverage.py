"""Supplement genuine GIS pixels without covering existing overlays or inventing source data."""
import json

import numpy as np
import pytest
from PIL import Image
from pyproj import Transformer

from scripts.build_ben_cat_gis_partitions import digest, export_url, write_json
from scripts.build_planning_gis_coverage import build, sample_mask


def capture(tmp_path):
    extent = dict(xmin=11850000, ymin=1240000, xmax=11858000, ymax=1248000, spatialReference={'wkid': 3857})
    service = 'https://api-gisxaydung.tphcm.gov.vn/arcm/rest/services/HCM/SuDungDat_QHPK_HCM_V2/MapServer/export'
    config = dict(id='tdm-gis-supplement', title='GIS bổ sung', source_url='https://gisxaydung.tphcm.gov.vn/tracuuttqh',
                  decision='GIS coverage, legal edition unverified', notice='Native GIS coverage, reference clipping only',
                  captured_on='2026-10-27', wards=['Fixture'], extent=extent, tile_size=20, tiles=[], exclusions=[])
    for row in range(2):
        for col in range(2):
            e = dict(xmin=extent['xmin'] + col*4000, xmax=extent['xmin'] + (col+1)*4000,
                     ymin=extent['ymax'] - (row+1)*4000, ymax=extent['ymax'] - row*4000, spatialReference={'wkid': 3857})
            tag = f'{row}-{col}'
            write_json(tmp_path / (tag+'.json'), dict(width=20, height=20, extent=e))
            pixels = np.full((20,20,4), [60+row*20,100+col*20,150,255], dtype='uint8')
            if row == col == 0: pixels[10:14,10:14,3] = 0
            Image.fromarray(pixels).save(tmp_path / (tag+'.png'))
            config['tiles'].append(dict(row=row, col=col, metadata=dict(path=tag+'.json',sha256=digest(tmp_path/(tag+'.json'))),
                image=dict(path=tag+'.png',sha256=digest(tmp_path/(tag+'.png'))),
                request=export_url(service,[e[k] for k in ('xmin','ymin','xmax','ymax')],[20,20])))
    inverse = Transformer.from_crs(3857,4326,always_xy=True)
    ring=[inverse.transform(x,y) for x,y in [(11850800,1240800),(11857200,1240800),(11857200,1247200),(11850800,1247200),(11850800,1240800)]]
    write_json(tmp_path/'wards.json',dict(type='FeatureCollection',features=[dict(type='Feature',properties={'name':'Fixture'},geometry=dict(type='Polygon',coordinates=[ring]))]))
    config['geometry'] = dict(path='wards.json',sha256=digest(tmp_path/'wards.json'))
    old=np.zeros((40,40,4),dtype='uint8');old[20:30,20:30,3]=255
    Image.fromarray(old).save(tmp_path/'existing.webp',lossless=True)
    write_json(tmp_path/'existing-audit.json',dict(native_extent=extent))
    config['exclusions'].append(dict(image=dict(path='existing.webp',sha256=digest(tmp_path/'existing.webp')),
                                    audit=dict(path='existing-audit.json',sha256=digest(tmp_path/'existing-audit.json'))))
    return config


def test_supplement_uses_only_new_real_pixels_and_keeps_native_colors(tmp_path):
    config=capture(tmp_path)
    manifest=build(config,tmp_path,tmp_path/'output')
    assert manifest['theme']=='partition' and manifest['map_scale'] is None
    assert manifest['alignment_method']=='official_coordinates'
    audit=json.loads((tmp_path/'output/alignment-audit.json').read_text())
    image=np.asarray(Image.open(tmp_path/'output/overlay.webp').convert('RGBA'))
    left,top,_,_=audit['crop_pixels']
    assert image[11-top,11-left,3]==0, 'A transparent source gap stays transparent'
    assert image[25-top,25-left,3]==0, 'Previously visible GIS pixels are not overlaid twice'
    assert tuple(image[16-top,16-left])==(60,100,150,255)
    assert audit['official_plan_boundary_verified'] is False
    assert audit['coverage'][0]['after_pixels']>audit['coverage'][0]['before_pixels']


def test_mosaic_rejects_missing_shifted_or_wrong_service_tiles(tmp_path):
    config=capture(tmp_path)
    config['tiles'][0]['request']=config['tiles'][0]['request'].replace('SuDungDat_QHPK_HCM_V2','SuDungDat_QHC_HCM')
    with pytest.raises(ValueError,match='partition service'):build(config,tmp_path,tmp_path/'out')
    config=capture(tmp_path);config['tiles'].pop()
    with pytest.raises(ValueError,match='four|Four'):build(config,tmp_path,tmp_path/'out')
    config=capture(tmp_path);meta=tmp_path/'0-0.json';value=json.loads(meta.read_text());value['extent']['xmin']+=1
    write_json(meta,value);config['tiles'][0]['metadata']['sha256']=digest(meta)
    with pytest.raises(ValueError,match='grid'):build(config,tmp_path,tmp_path/'out')


def test_native_mask_sampling_does_not_stretch_outside_its_extent():
    source=np.ones((10,10),bool)
    e=dict(xmin=0,ymin=0,xmax=10,ymax=10,spatialReference={'wkid':3857})
    target=dict(e,xmax=20)
    sampled=sample_mask(source,e,target,(20,10))
    assert sampled[:,:10].all() and not sampled[:,10:].any()
