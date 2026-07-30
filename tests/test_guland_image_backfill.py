from services.guland_image_backfill import (
    GulandImageRow,
    _build_thumbnail_repairs,
    _image_urls_from_raw,
    _primary_image_rows,
    _thumb_key_for_image_key,
)


def test_thumb_key_for_image_key_uses_existing_image_stem():
    assert (
        _thumb_key_for_image_key("data/images/45567_0.jpg")
        == "data/images/thumbs/45567_0.webp"
    )


def test_build_thumbnail_repairs_requires_original_and_missing_thumb():
    rows = [
        GulandImageRow(
            image_id=1,
            listing_id=10,
            img_url="https://cdn.guland.vn/a.jpg",
            img_order=0,
            local_path="data/images/10_0.jpg",
        ),
        GulandImageRow(
            image_id=2,
            listing_id=20,
            img_url="https://cdn.guland.vn/b.jpg",
            img_order=0,
            local_path="data/images/20_0.jpg",
        ),
        GulandImageRow(
            image_id=3,
            listing_id=30,
            img_url="https://cdn.guland.vn/c.jpg",
            img_order=0,
            local_path="NOT_FOUND",
        ),
    ]
    keys = {
        "data/images/10_0.jpg",
        "data/images/20_0.jpg",
        "data/images/thumbs/20_0.webp",
    }

    repairs, missing_original = _build_thumbnail_repairs(rows, keys)

    assert [r.image_id for r in repairs] == [1]
    assert missing_original == []


def test_primary_image_rows_keeps_one_lowest_order_image_per_listing():
    rows = [
        GulandImageRow(2, 10, "https://cdn.guland.vn/b.jpg", 1, "data/images/10_1.jpg"),
        GulandImageRow(1, 10, "https://cdn.guland.vn/a.jpg", 0, "data/images/10_0.jpg"),
        GulandImageRow(3, 20, "https://cdn.guland.vn/c.jpg", 0, "data/images/20_0.jpg"),
    ]

    assert [row.image_id for row in _primary_image_rows(rows)] == [1, 3]


def test_image_urls_from_raw_accepts_guland_image_fields_and_dedupes():
    raw = {
        "imgs": ["https://cdn.guland.vn/a.jpg", "https://cdn.guland.vn/a.jpg"],
        "img_urls": ["https://cdn.guland.vn/b.jpg"],
        "images": [{"url": "https://cdn.guland.vn/c.jpg"}],
    }

    assert _image_urls_from_raw(raw) == [
        "https://cdn.guland.vn/a.jpg",
        "https://cdn.guland.vn/b.jpg",
        "https://cdn.guland.vn/c.jpg",
    ]
