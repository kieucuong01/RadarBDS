import pytest
from PIL import Image, ImageDraw

pytest.importorskip('cv2', reason='Optional local operator image-analysis dependency')

from scripts.create_parcel_candidate_points import candidate_points


def tile(tmp_path, x, image):
    path = tmp_path/f'{x}.png'
    image.save(path)
    return dict(url=f'https://s3.hn-1.cloud.cmctelecom.vn/guland9/qh-dong-nai/thuadat/18/{x}/122963.png', file=str(path))


def test_closed_region_yields_an_interior_lookup_point_not_a_traced_polygon(tmp_path):
    image = Image.new('RGBA', (256, 256))
    ImageDraw.Draw(image).rectangle((40, 50, 160, 190), outline=(0, 197, 255, 255), width=2)
    seeds = candidate_points([tile(tmp_path, 209111, image)])
    assert len(seeds) == 1
    seed = seeds[0]
    assert seed['seed_only'] is True
    assert 40 < seed['pixel_x'] < 160 and 50 < seed['pixel_y'] < 190
    assert 106 < seed['lng'] < 108 and 10 < seed['lat'] < 13
    assert 'geometry' not in seed and 'points' not in seed


def test_mosaic_finds_regions_crossing_the_internal_tile_seam(tmp_path):
    image = Image.new('RGBA', (512, 256))
    ImageDraw.Draw(image).rectangle((210, 40, 310, 190), outline=(0, 197, 255, 255), width=2)
    seeds = candidate_points([tile(tmp_path, 209111, image.crop((0, 0, 256, 256))),
                              tile(tmp_path, 209112, image.crop((256, 0, 512, 256)))])
    assert len(seeds) == 1


def test_open_regions_at_outer_border_are_not_called_complete_parcels(tmp_path):
    image = Image.new('RGBA', (256, 256))
    ImageDraw.Draw(image).rectangle((-10, 40, 150, 190), outline=(0, 197, 255, 255), width=2)
    assert candidate_points([tile(tmp_path, 209111, image)]) == []


def test_missing_or_duplicate_tiles_fail_without_hallucinating_a_grid(tmp_path):
    image = Image.new('RGBA', (256, 256))
    first = tile(tmp_path, 209111, image)
    with pytest.raises(ValueError):
        candidate_points([first, first])
    with pytest.raises(ValueError):
        candidate_points([first, tile(tmp_path, 209113, image)])
