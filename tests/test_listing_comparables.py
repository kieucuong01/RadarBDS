from unittest import mock


class _Result:
    def __init__(self, *, one=None, rows=None):
        self._one = one
        self._rows = rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._rows


class _ComparableConnection:
    def __init__(self, current, candidates):
        self.current = current
        self.candidates = candidates
        self.queries = []

    def execute(self, sql, _params=None):
        self.queries.append(sql)
        if "WHERE id = ?" in sql and "FROM listings" in sql:
            return _Result(one=self.current)
        return _Result(rows=self.candidates)


def _current():
    return {
        "id": 1,
        "title": "Current listing",
        "ward": "Phú Lợi",
        "area_m2": 100.0,
        "property_type": "dat_nen",
        "tx_type": "ban",
        "road_tier": 2,
        "price_per_m2": 20.0,
    }


def _candidate(index):
    return {
        "id": index + 2,
        "title": f"Comparable {index}",
        "description": "Đất nền",
        "url": f"https://source.example/{index}",
        "ward": "Phú Lợi",
        "price_ty": 2.0,
        "area_m2": 100.0 + index,
        "frontage_m": 5.0,
        "depth_m": 20.0,
        "actual_ppm2": 20.0,
        "price_per_m2": 20.0,
        "property_type": "dat_nen",
        "road_tier": 2,
        "road_name": "ĐX 43",
        "road_type": "duong_nhua",
        "road_width_m": 6.0,
        "tho_cu_m2": 60.0,
        "tho_cu_ratio": 0.6,
        "posted_at": "2026-07-29",
        "crawled_at": "2026-07-29",
        "source": "facebook",
        "is_hot": 0,
        "price_dropped": 0,
        "suspicious_bait": 0,
        "price_drop_pct": None,
        "price_first_ty": None,
        "duplicate_of_id": None,
        "fair_ppm2": 30.0,
        "fair_ppm2_old": 30.0,
        "fair_ppm2_new": None,
        "mos_pct": 33.3,
        "mos_pct_old": 33.3,
        "mos_pct_new": None,
        "fair_ppm2_display": 30.0,
        "mos_pct_display": 33.3,
        "signal_model": "display_mos",
        "signal_score": 70,
        "trust_tier": "candidate_signal",
        "trust_score": 0,
        "legal_status": "unverified",
        "legal_flags": "",
        "source_quality_flags": "",
        "source_quality_recheck": 0,
        "has_legal_doc_image": 0,
        "has_so": 1,
        "is_fresh_locked": 0,
        "primary_local_path": f"data/images/thumbs/{index}.webp",
        "primary_img_url": "",
        "image_count": 1,
    }


def test_comparable_service_returns_full_redacted_signal_cards_with_cap():
    from services.listing_comparables import load_listing_comparables

    conn = _ComparableConnection(_current(), [_candidate(i) for i in range(20)])
    with mock.patch(
        "services.listing_comparables.resolve_image_url",
        side_effect=lambda local, _remote: f"/{local}" if local else "",
    ):
        items = load_listing_comparables(conn, 1, tier="guest", limit=99)

    assert len(items) == 18
    assert items[0]["id"] != 1
    assert items[0]["detail_url"] == f"/listing/{items[0]['id']}"
    assert items[0]["primary_img"].endswith("/0.webp")
    assert items[0]["fair_ppm2_display"] == 30.0
    assert items[0]["mos_pct_display"] == 33.3
    assert items[0]["url"] is None
    assert "latest_valuation" in "\n".join(conn.queries)
    assert "listing_images" in "\n".join(conn.queries)


def test_comparable_service_preserves_admin_source_boundary():
    from services.listing_comparables import load_listing_comparables

    conn = _ComparableConnection(_current(), [_candidate(0)])
    with mock.patch("services.listing_comparables.resolve_image_url", return_value=""):
        items = load_listing_comparables(conn, 1, tier="admin", limit=18)

    assert items[0]["url"] == "https://source.example/0"
    assert items[0]["detail_url"] == "/listing/2"


def test_comparison_uses_observed_asking_prices_and_lists_the_lot_differences():
    from services.listing_comparables import load_listing_comparison

    subject = dict(_current(), road_tier=1, tho_cu_m2=80)
    rows = [dict(_candidate(i), price_per_m2=price, actual_ppm2=999,
                 road_tier=3, last_seen_at="2026-11-21T21:30:00+00:00")
            for i, price in enumerate([13, 16, 22, 30, 85])]
    result = load_listing_comparison(_ComparableConnection(subject, rows), 1, "guest")
    assert "5 tin dưới đây: 22 triệu/m²" in result["comparison_summary"]
    first = result["comps"][0]
    assert first["asking_ppm2"] == 13
    assert first["observed_at_label"] == "22/11/2026 04:30"
    assert "hẻm xe hơi (lô đang xem: mặt tiền)" in first["comparison_note"]
    assert "Thổ cư ít hơn 20 m²" in first["comparison_note"]


def test_small_and_empty_comparisons_explain_available_evidence():
    from services.listing_comparables import load_listing_comparison

    row = dict(_candidate(0), crawled_at=None, posted_at="2026-11-21")
    result = load_listing_comparison(_ComparableConnection(_current(), [row]), 1, "guest")
    assert "Chỉ có 1 tin rao" in result["comparison_summary"]
    assert "Trung vị" not in result["comparison_summary"]
    assert result["comps"][0]["observed_at_label"] is None
    assert "Chưa đủ dữ liệu đối chiếu thổ cư" in result["comps"][0]["comparison_note"]
    conn = _ComparableConnection(dict(_current(), tx_type="thue"), [row])
    empty = load_listing_comparison(conn, 1, "guest")
    assert not empty["comps"] and "Chưa có tin rao" in empty["comparison_summary"]
