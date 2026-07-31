import pytest

from services.guland_image_backfill import (
    GulandImageRow,
    GulandRawImageTarget,
    _bounded_zero_ready_targets,
    _build_thumbnail_repairs,
    _image_urls_from_raw,
    _primary_image_rows,
    _ready_listing_ids,
    _thumb_key_for_image_key,
    run_guland_image_backfill,
    validate_backfill_limit,
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


def test_ready_listing_requires_original_and_thumbnail_in_s3():
    rows = [
        GulandImageRow(1, 10, "https://cdn/a.jpg", 0, ""),
        GulandImageRow(2, 20, "https://cdn/b.jpg", 0, "NOT_FOUND"),
        GulandImageRow(3, 30, "https://cdn/c.jpg", 0, "data/images/30.jpg"),
        GulandImageRow(4, 40, "https://cdn/d.jpg", 0, "data/images/40.jpg"),
        GulandImageRow(5, 50, "https://cdn/e.jpg", 0, "data/images/50.jpg"),
    ]
    keys = {
        "data/images/40.jpg",
        "data/images/50.jpg",
        "data/images/thumbs/50.webp",
    }

    assert _ready_listing_ids(rows, keys, s3_enabled=True) == {50}
    assert _ready_listing_ids(rows, set(), s3_enabled=False) == {30, 40, 50}


def test_zero_ready_scope_includes_existing_rows_and_is_bounded_deterministically():
    targets = [
        GulandRawImageTarget(30, 300, "https://guland.vn/post/30", {}, 4),
        GulandRawImageTarget(10, 100, "https://guland.vn/post/10", {}, 0),
        GulandRawImageTarget(20, 200, "https://guland.vn/post/20", {}, 2),
    ]

    selected = _bounded_zero_ready_targets(
        targets,
        ready_listing_ids={30},
        limit=2,
    )

    assert [target.listing_id for target in selected] == [10, 20]
    assert [target.existing_image_rows for target in selected] == [0, 2]


def test_backfill_limit_is_strictly_bounded():
    assert validate_backfill_limit(1) == 1
    assert validate_backfill_limit(200) == 200

    for value in (0, 201):
        try:
            validate_backfill_limit(value)
        except ValueError as exc:
            assert "between 1 and 200" in str(exc)
        else:
            raise AssertionError(f"expected invalid limit: {value}")


def test_zero_ready_dry_run_reports_scope_without_mutation(monkeypatch):
    import services.guland_image_backfill as service

    image_url = "https://bizcdn.guland.vn/posts/10/a.jpg"
    rows = [GulandImageRow(1, 10, image_url, 0, "NOT_FOUND")]
    targets = [
        GulandRawImageTarget(
            10,
            100,
            "https://guland.vn/post/a-10",
            {"imgs": [image_url]},
            1,
        )
    ]
    monkeypatch.setattr(service, "_load_guland_images", lambda **_kwargs: (rows, targets))
    monkeypatch.setattr(service, "s3_image_storage_enabled", lambda: False)
    monkeypatch.setattr(
        service,
        "_fetch_live_image_map",
        lambda _targets: {10: [image_url]},
    )

    def refuse_mutation(*_args, **_kwargs):
        raise AssertionError("dry-run attempted a mutation")

    monkeypatch.setattr(service, "_apply_raw_image_recovery", refuse_mutation)
    monkeypatch.setattr(service, "_reset_image_rows_by_id", refuse_mutation)
    monkeypatch.setattr(service, "_reset_live_not_found_rows", refuse_mutation)

    stats = run_guland_image_backfill(apply=False, limit=1)

    assert stats["zero_row_targets"] == 0
    assert stats["zero_ready_targets"] == 1
    assert stats["live_checked_targets"] == 1
    assert stats["live_recoverable_targets"] == 1
    assert stats["retry_rows_reset"] == 0


def test_zero_ready_apply_resets_live_not_found_and_targets_download(
    monkeypatch,
):
    import cleansing.download_images as downloader
    import services.guland_image_backfill as service

    image_url = "https://bizcdn.guland.vn/posts/10/a.jpg"
    rows = [GulandImageRow(1, 10, image_url, 0, "NOT_FOUND")]
    targets = [
        GulandRawImageTarget(
            10,
            100,
            "https://guland.vn/post/a-10",
            {"imgs": [image_url]},
            1,
        )
    ]
    monkeypatch.setattr(service, "_load_guland_images", lambda **_kwargs: (rows, targets))
    monkeypatch.setattr(service, "s3_image_storage_enabled", lambda: False)
    monkeypatch.setattr(
        service,
        "_fetch_live_image_map",
        lambda _targets: {10: [image_url]},
    )
    monkeypatch.setattr(
        service,
        "_apply_raw_image_recovery",
        lambda *_args, **_kwargs: (0, 0, [10]),
    )
    monkeypatch.setattr(service, "_reset_image_rows_by_id", lambda _ids: 0)
    monkeypatch.setattr(
        service,
        "_reset_live_not_found_rows",
        lambda _images: 1,
    )
    monkeypatch.setattr(
        downloader,
        "download_images",
        lambda *, limit, listing_ids: len(listing_ids),
    )

    stats = run_guland_image_backfill(apply=True, limit=1)

    assert stats["retry_rows_reset"] == 1
    assert stats["recovered_images_downloaded"] == 1
