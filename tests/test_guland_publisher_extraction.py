from unittest import mock
import json
import pytest

from crawler.guland_pw import GulandCrawler
from db.listings import upsert_listing
from db.schema import init_schema
from db.connection import get_conn
from services.guland_publisher_activity import validated_raw_publisher_fields


@pytest.mark.parametrize('fresh_count', [6, None])
@pytest.mark.parametrize('separate_time', [True, False, None])
def test_verified_price_refresh_updates_only_fresh_portfolio_timestamp(fresh_count, separate_time):
    from services.guland_reconciliation import ExistingGulandSnapshot
    old = '2026-10-01T00:00:00+07:00'
    snapshot = ExistingGulandSnapshot(1, 1, 'https://guland.vn/post/test-123', '123', 2.0, old, 'active')
    raw = {'publisher_other_listing_count': 468, 'publisher_identity_checked_at': old}
    if separate_time:
        raw['publisher_portfolio_checked_at'] = old
    elif separate_time is None:
        raw.pop('publisher_identity_checked_at')
    crawler = GulandCrawler()
    fields = {} if fresh_count is None else {'publisher_other_listing_count': fresh_count}
    with mock.patch('crawler.guland_pw.get_conn') as conn, mock.patch('crawler.guland_pw.validated_raw_publisher_fields', return_value=fields), mock.patch.object(crawler, '_refresh_changed_record', return_value=1) as publish:
        conn.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {'raw_json': json.dumps(raw)}
        crawler._refresh_verified_price(snapshot, {}, 1.9)
    result = publish.call_args.args[1]
    if fresh_count is None:
        if separate_time is None:
            assert 'publisher_other_listing_count' not in result
        else:
            assert result['publisher_portfolio_checked_at'] == old
            assert result['publisher_other_listing_count'] == 468
    else:
        assert result['publisher_portfolio_checked_at'] != old
        assert result['publisher_other_listing_count'] == 6


def _card(token: str = "12345") -> dict[str, object]:
    return {
        "url": f"https://guland.vn/post/publisher-test-{token}",
        "source_list_url": (
            "https://guland.vn/mua-ban-dat-tho-cu-"
            "phuong-tan-an-thanh-pho-thu-dau-mot-binh-duong"
        ),
        "post_id": token,
        "title": "Bán đất Tân An",
        "price_raw": "2 tỷ",
        "area_raw": "100 m²",
        "pm2_raw": "20 tr/m²",
        "date_raw": "Hôm nay",
    }


def test_listing_contact_phone_beats_footer_hotline():
    detail = {
        "description": "Bán đất",
        "publisher_phone_candidate": "0912345678",
        "publisher_phone_scope": "listing_contact",
        "page_global_phone": "0983284379",
    }

    raw = validated_raw_publisher_fields(detail, secret="s" * 64)

    assert raw["publisher_phone"] == "0912345678"
    assert raw["publisher_identity_status"] == "identified"


def test_unscoped_phone_never_populates_contact_phone():
    detail = {
        "description": "Không có số liên hệ",
        "publisher_phone_candidate": "0983284379",
        "publisher_phone_scope": "footer",
    }

    raw = validated_raw_publisher_fields(detail, secret="s" * 64)

    assert raw["publisher_identity_status"] == "unknown"
    assert not raw.get("publisher_phone")


def test_build_record_uses_only_validated_publisher_contact():
    crawler = GulandCrawler()
    detail = {
        "description": "Bán đất",
        "publisher_phone_candidate": "0912345678",
        "publisher_phone_scope": "listing_contact",
        "page_global_phone": "0983284379",
    }
    validated = validated_raw_publisher_fields(detail, secret="s" * 64)

    with mock.patch(
        "crawler.guland_pw.validated_raw_publisher_fields",
        return_value=validated,
        create=True,
    ):
        record = crawler._build_record(_card(), detail)

    assert record["contact_phone"] == "0912345678"
    assert record["publisher_phone"] == "0912345678"
    assert record["_publisher_contact_checked"] is True
    assert record["publisher_identity_checked_at"]


def test_build_record_does_not_copy_legacy_page_global_phone():
    crawler = GulandCrawler()
    detail = {
        "description": "Không có số liên hệ",
        "contact_phone": "0983284379",
        "publisher_phone_candidate": "0983284379",
        "publisher_phone_scope": "footer",
        "page_global_phone": "0983284379",
    }
    validated = validated_raw_publisher_fields(detail, secret="s" * 64)

    with mock.patch(
        "crawler.guland_pw.validated_raw_publisher_fields",
        return_value=validated,
        create=True,
    ):
        record = crawler._build_record(_card("12346"), detail)

    assert record["contact_phone"] == ""
    assert record["_publisher_contact_checked"] is True


def test_checked_guland_update_clears_hotline_but_facebook_is_preserved():
    init_schema()
    guland_url = "https://guland.vn/post/checked-contact-test-991001"
    facebook_url = "https://facebook.com/checked-contact-test-991002"
    listing_ids = []
    try:
        for source, url in (("guland", guland_url), ("facebook", facebook_url)):
            listing_id, _ = upsert_listing(
                {
                    "source": source,
                    "source_id": url.rsplit("-", 1)[-1],
                    "url": url,
                    "title": "Checked contact test",
                    "description": "",
                    "price_ty": 2.0,
                    "price_per_m2": 20.0,
                    "area_m2": 100.0,
                    "property_type": "dat_nen",
                    "contact_phone": "0983284379",
                }
            )
            listing_ids.append(listing_id)

        for source, url in (("guland", guland_url), ("facebook", facebook_url)):
            upsert_listing(
                {
                    "source": source,
                    "source_id": url.rsplit("-", 1)[-1],
                    "url": url,
                    "title": "Checked contact test",
                    "description": "",
                    "price_ty": 2.0,
                    "price_per_m2": 20.0,
                    "area_m2": 100.0,
                    "property_type": "dat_nen",
                    "contact_phone": None,
                    "_publisher_contact_checked": True,
                }
            )

        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT source, contact_phone
                FROM listings WHERE id IN (?, ?)
                ORDER BY source
                """,
                listing_ids,
            ).fetchall()

        contacts = {row["source"]: row["contact_phone"] for row in rows}
        assert contacts["guland"] in (None, "")
        assert contacts["facebook"] == "0983284379"
    finally:
        if listing_ids:
            with get_conn() as conn:
                conn.execute(
                    "DELETE FROM listings WHERE id IN (?, ?)",
                    listing_ids,
                )
