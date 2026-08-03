import uuid

from db.connection import get_conn
from db.listings import canonical_image_asset_key, sync_listing_images


def _create_listing(source: str) -> tuple[int, str]:
    token = uuid.uuid4().hex
    url = f"https://example.test/{source}/{token}"
    with get_conn() as conn:
        listing_id = conn.execute(
            """
            INSERT INTO listings (
                source, source_id, url, title, area, ward, property_type,
                tx_type, price_ty, price_per_m2, area_m2, crawled_at
            )
            VALUES (?, ?, ?, 'Tin anh', 'Tan An', 'Tan An', 'dat_nen',
                    'ban', 1.0, 10.0, 100.0, datetime('now'))
            """,
            (source, f"{source}-{token}", url),
        ).lastrowid
    return listing_id, url


def _delete_listing(listing_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM listings WHERE id=?", (listing_id,))


def _rows(listing_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, img_url, img_order, local_path
            FROM listing_images
            WHERE listing_id=?
            ORDER BY img_order, id
            """,
            (listing_id,),
        ).fetchall()
    return [dict(row.items()) for row in rows]


def test_asset_identity_drops_volatile_query_but_not_path():
    first = "https://scontent.xx.fbcdn.net/v/t39/photo-a.jpg?stp=old&token=1"
    rotated = "https://scontent.xx.fbcdn.net/v/t39/photo-a.jpg?stp=new&token=2"
    changed = "https://scontent.xx.fbcdn.net/v/t39/photo-b.jpg?token=2"

    assert canonical_image_asset_key(first) == canonical_image_asset_key(rotated)
    assert canonical_image_asset_key(first) != canonical_image_asset_key(changed)


def test_facebook_signed_url_rotation_keeps_one_ready_slot():
    listing_id, _ = _create_listing("facebook")
    first = "https://scontent.xx.fbcdn.net/v/t39/photo-a.jpg?token=old"
    rotated = "https://scontent.xx.fbcdn.net/v/t39/photo-a.jpg?token=new"
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO listing_images
                    (listing_id, img_url, img_order, local_path)
                VALUES (?, ?, 0, 'data/images/existing.jpg')
                """,
                (listing_id, first),
            )

        stats = sync_listing_images(listing_id, [rotated], source="facebook")

        assert stats["reset"] == 0
        assert _rows(listing_id) == [
            {
                "id": _rows(listing_id)[0]["id"],
                "img_url": rotated,
                "img_order": 0,
                "local_path": "data/images/existing.jpg",
            }
        ]
    finally:
        _delete_listing(listing_id)


def test_facebook_changed_asset_resets_download_and_collapses_slot_duplicates():
    listing_id, _ = _create_listing("facebook")
    changed = "https://scontent.xx.fbcdn.net/v/t39/photo-new.jpg?token=2"
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO listing_images
                    (listing_id, img_url, img_order, local_path)
                VALUES (?, 'https://scontent.xx.fbcdn.net/v/t39/old-a.jpg', 0,
                        'data/images/old-a.jpg')
                """,
                (listing_id,),
            )
            conn.execute(
                """
                INSERT INTO listing_images
                    (listing_id, img_url, img_order, local_path)
                VALUES (?, 'https://scontent.xx.fbcdn.net/v/t39/old-b.jpg', 0,
                        'NOT_FOUND')
                """,
                (listing_id,),
            )

        stats = sync_listing_images(listing_id, [changed], source="facebook")

        rows = _rows(listing_id)
        assert stats["removed"] == 1
        assert stats["reset"] == 1
        assert len(rows) == 1
        assert rows[0]["img_url"] == changed
        assert rows[0]["local_path"] is None
    finally:
        _delete_listing(listing_id)


def test_partial_facebook_observation_does_not_delete_unobserved_trailing_slot():
    listing_id, _ = _create_listing("facebook")
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order)
                VALUES (?, 'https://scontent.test/old-cover.jpg', 0)
                """,
                (listing_id,),
            )
            conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order)
                VALUES (?, 'https://scontent.test/second.jpg', 1)
                """,
                (listing_id,),
            )

        sync_listing_images(
            listing_id,
            ["https://scontent.test/new-cover.jpg"],
            source="facebook",
        )

        assert [row["img_order"] for row in _rows(listing_id)] == [0, 1]
    finally:
        _delete_listing(listing_id)


def test_facebook_exact_url_moving_slots_does_not_hit_unique_constraint():
    listing_id, _ = _create_listing("facebook")
    moved = "https://scontent.test/moved.jpg?token=same"
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO listing_images (listing_id, img_url, img_order)
                VALUES (?, 'https://scontent.test/old-cover.jpg', 0)
                """,
                (listing_id,),
            )
            conn.execute(
                """
                INSERT INTO listing_images
                    (listing_id, img_url, img_order, local_path)
                VALUES (?, ?, 1, 'data/images/moved.jpg')
                """,
                (listing_id, moved),
            )

        stats = sync_listing_images(listing_id, [moved], source="facebook")

        rows = _rows(listing_id)
        assert stats["removed"] == 1
        assert len(rows) == 1
        assert rows[0]["img_url"] == moved
        assert rows[0]["img_order"] == 0
        assert rows[0]["local_path"] == "data/images/moved.jpg"
    finally:
        _delete_listing(listing_id)


def test_guland_keeps_url_identity_instead_of_collapsing_same_order():
    listing_id, _ = _create_listing("guland")
    try:
        sync_listing_images(
            listing_id,
            [
                "https://bizcdn.guland.vn/posts/1/a.jpg",
                "https://bizcdn.guland.vn/posts/1/b.jpg",
            ],
            source="guland",
        )
        sync_listing_images(
            listing_id,
            ["https://bizcdn.guland.vn/posts/1/c.jpg"],
            source="guland",
        )

        assert [row["img_url"] for row in _rows(listing_id)] == [
            "https://bizcdn.guland.vn/posts/1/a.jpg",
            "https://bizcdn.guland.vn/posts/1/c.jpg",
            "https://bizcdn.guland.vn/posts/1/b.jpg",
        ]
    finally:
        _delete_listing(listing_id)
