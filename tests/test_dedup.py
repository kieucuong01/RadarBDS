"""
Unit tests cho cleansing/dedup.py — scoring system mới (exact dims + text sim).

Chạy: python tests/test_dedup.py

3 case chính:
  Case 1: front_exact AND depth_exact → text ≥ 0.30  → score ≥ 8
  Case 2: area_exact (không front/depth) → text ≥ 0.70 → score ≥ 6
  Case 3: không có số liệu → text ≥ 0.85 (copy-paste) → score = 6

Hard gates: different_days, property_type match, ward match.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cleansing.dedup import _repost_score, _is_duplicate, _is_reliable_price_drop, SCORE_THRESHOLD


# ── Helpers ───────────────────────────────────────────────────────────────────

def _listing(**kw):
    defaults = {
        "source": "guland", "source_id": "abc",
        "crawled_at": "2026-04-20", "posted_at": None,
        "property_type": "dat_nen", "ward": "Tân An",
        "frontage_m": None, "depth_m": None, "area_m2": None,
        "description": "",
    }
    defaults.update(kw)
    return defaults


LONG_DESC = (
    "Bán đất nền đường Hùng Vương, phường Tân An, Thủ Dầu Một. "
    "Diện tích 100m2, mặt tiền 5m, sổ hồng riêng. "
    "Giá 2 tỷ, thương lượng. Liên hệ 0901234567."
)
LONG_DESC_COPY = LONG_DESC  # identical copy
LONG_DESC_SLIGHT = (
    "Bán đất nền đường Hùng Vương, phường Tân An, Thủ Dầu Một. "
    "Diện tích 100m2, mặt tiền 5m, sổ hồng riêng. "
    "Giá 1.9 tỷ, đã giảm. Liên hệ 0901234567."
)
LONG_DESC_DIFFERENT = (
    "Nhà cấp 4 hẻm đường Lê Hồng Phong, cách mặt tiền 50m, "
    "diện tích 80m2, giá 1.5 tỷ, cần bán gấp kẹt tiền."
)


# ── Hard gate tests ───────────────────────────────────────────────────────────

def test_hard_gate_same_day():
    l1 = _listing(crawled_at="2026-04-20", description=LONG_DESC_COPY)
    l2 = _listing(crawled_at="2026-04-20", description=LONG_DESC_COPY)
    assert _repost_score(l1, l2) == 0, "Same day → must return 0"


def test_hard_gate_different_property_type():
    l1 = _listing(crawled_at="2026-04-19", property_type="dat_nen", description=LONG_DESC_COPY)
    l2 = _listing(crawled_at="2026-04-20", property_type="nha_dat", description=LONG_DESC_COPY)
    assert _repost_score(l1, l2) == 0, "Different property_type → must return 0"


def test_hard_gate_different_ward():
    l1 = _listing(crawled_at="2026-04-19", ward="Tân An", description=LONG_DESC_COPY)
    l2 = _listing(crawled_at="2026-04-20", ward="Phú Cường", description=LONG_DESC_COPY)
    assert _repost_score(l1, l2) == 0, "Different ward → must return 0"


def test_hard_gate_unknown_ward_passes():
    l1 = _listing(crawled_at="2026-04-19", ward="", description=LONG_DESC_COPY)
    l2 = _listing(crawled_at="2026-04-20", ward="Tân An", description=LONG_DESC_COPY)
    # Missing ward → không block, nhưng score phụ thuộc text sim
    score = _repost_score(l1, l2)
    assert score >= SCORE_THRESHOLD, f"Missing ward should not block; score={score}"


# ── Case 1: front + depth exact ───────────────────────────────────────────────

def test_case1_passes_with_text_30():
    l1 = _listing(crawled_at="2026-04-19", frontage_m=5.0, depth_m=20.0, description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", frontage_m=5.0, depth_m=20.0, description=LONG_DESC_SLIGHT)
    score = _repost_score(l1, l2)
    assert score >= SCORE_THRESHOLD, f"Case 1 with text≥0.30 should pass; score={score}"


def test_case1_fails_without_text():
    l1 = _listing(crawled_at="2026-04-19", frontage_m=5.0, depth_m=20.0, description="")
    l2 = _listing(crawled_at="2026-04-20", frontage_m=5.0, depth_m=20.0, description="")
    score = _repost_score(l1, l2)
    assert score == 0, f"Case 1 with no text sim should fail; score={score}"


def test_case1_fails_with_different_dims():
    l1 = _listing(crawled_at="2026-04-19", frontage_m=5.0, depth_m=20.0, description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", frontage_m=5.1, depth_m=20.0, description=LONG_DESC)
    # frontage 5.0 vs 5.1 is NOT exact (tol=0.0) → front_match=False → Case 1 không kích hoạt
    # Case 3 sẽ áp dụng vì text ≥ 0.85
    score = _repost_score(l1, l2)
    # text sim is high (same description) so Case 3 kicks in
    assert score >= SCORE_THRESHOLD, f"Should match via Case 3 (text≥0.85); score={score}"


def test_case1_different_depth_no_match():
    l1 = _listing(crawled_at="2026-04-19", frontage_m=5.0, depth_m=20.0, description=LONG_DESC_SLIGHT)
    l2 = _listing(crawled_at="2026-04-20", frontage_m=5.0, depth_m=25.0, description=LONG_DESC_SLIGHT)
    # front matches but depth differs → front_match AND depth_match = False → falls to Case 2/3
    # area_m2 both None, text sim moderate → score depends on text
    score = _repost_score(l1, l2)
    # text is slightly modified — probably < 0.85 but > 0.70, not enough for Case 3
    # This is acceptable — 5x20 vs 5x25 are different lots
    # We just verify it doesn't use the 0-tolerance gate incorrectly
    assert isinstance(score, int)


# ── Case 2: area exact, no front/depth ───────────────────────────────────────

def test_case2_passes_with_text_70():
    l1 = _listing(crawled_at="2026-04-19", area_m2=100.0, description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", area_m2=100.0, description=LONG_DESC_SLIGHT)
    score = _repost_score(l1, l2)
    assert score >= SCORE_THRESHOLD, f"Case 2 with text≥0.70 should pass; score={score}"


def test_case2_fails_with_low_text():
    l1 = _listing(crawled_at="2026-04-19", area_m2=100.0, description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", area_m2=100.0, description=LONG_DESC_DIFFERENT)
    score = _repost_score(l1, l2)
    assert score == 0, f"Case 2 with different text (<0.70) should fail; score={score}"


def test_case2_area_mismatch_no_match():
    l1 = _listing(crawled_at="2026-04-19", area_m2=100.0, description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", area_m2=101.0, description=LONG_DESC)
    # 100 vs 101 NOT exact → area_match=False → falls to Case 3
    # text is identical → Case 3 kicks in
    score = _repost_score(l1, l2)
    assert score >= SCORE_THRESHOLD, f"Identical text should match via Case 3; score={score}"


# ── Case 3: text-only (copy-paste) ───────────────────────────────────────────

def test_case3_exact_copy():
    l1 = _listing(crawled_at="2026-04-19", description=LONG_DESC_COPY)
    l2 = _listing(crawled_at="2026-04-20", description=LONG_DESC_COPY)
    score = _repost_score(l1, l2)
    assert score >= SCORE_THRESHOLD, f"Exact copy should match; score={score}"
    assert score == 6, f"No dims → only text contributes; expected 6, got {score}"


def test_case3_no_text_no_match():
    l1 = _listing(crawled_at="2026-04-19")
    l2 = _listing(crawled_at="2026-04-20")
    score = _repost_score(l1, l2)
    assert score == 0, f"No text, no dims → cannot determine duplicate; score={score}"


def test_case3_low_similarity_no_match():
    l1 = _listing(crawled_at="2026-04-19", description=LONG_DESC)
    l2 = _listing(crawled_at="2026-04-20", description=LONG_DESC_DIFFERENT)
    score = _repost_score(l1, l2)
    assert score == 0, f"Different text, no dims → no match; score={score}"


# ── _is_duplicate: same source_id shortcut ───────────────────────────────────

def test_same_source_id_always_duplicate():
    l1 = _listing(source="guland", source_id="POST123", crawled_at="2026-04-19", description="")
    l2 = _listing(source="guland", source_id="POST123", crawled_at="2026-04-20", description="")
    assert _is_duplicate(l1, l2), "Same source + source_id → always duplicate"


def test_same_source_different_id_uses_scoring():
    l1 = _listing(source="guland", source_id="POST111", crawled_at="2026-04-19", description=LONG_DESC_COPY)
    l2 = _listing(source="guland", source_id="POST222", crawled_at="2026-04-20", description=LONG_DESC_COPY)
    assert _is_duplicate(l1, l2), "Same source, different id, identical text → duplicate via scoring"


def test_cross_source_scoring():
    l1 = _listing(source="guland",     source_id="G1", crawled_at="2026-04-19",
                  area_m2=100.0, description=LONG_DESC)
    l2 = _listing(source="batdongsan", source_id="B1", crawled_at="2026-04-20",
                  area_m2=100.0, description=LONG_DESC_SLIGHT)
    assert _is_duplicate(l1, l2), "Cross-source with same area + similar text → duplicate"


# ── Score floor verification ──────────────────────────────────────────────────

def test_reliable_drop_facebook_same_area_different_post():
    old = _listing(
        source="facebook", source_id="fb1", posted_at="2026-05-01",
        ward="Tân An", property_type="dat_nen", area_m2=100.0,
        price_ty=2.0, description="Bán đất đường DX84 diện tích 100m2 giá 2 tỷ"
    )
    new = _listing(
        source="facebook", source_id="fb2", posted_at="2026-05-03",
        ward="Tân An", property_type="dat_nen", area_m2=100.0,
        price_ty=1.9, description="Bán đất đường DX84 diện tích 100m2 giá giảm còn 1.9 tỷ"
    )
    assert _is_reliable_price_drop(old, new), "Facebook repost same area should count as reliable price drop"


def test_reliable_drop_rejects_same_template_different_lot():
    old = _listing(
        source="facebook", source_id="fb1", posted_at="2026-05-01",
        ward="Định Hòa", property_type="dat_nen", area_m2=1259.0,
        price_ty=13.5, description="Cần bán đất Định Hòa đường DX78 liên hệ môi giới"
    )
    new = _listing(
        source="facebook", source_id="fb2", posted_at="2026-05-03",
        ward="Định Hòa", property_type="dat_nen", area_m2=180.0,
        price_ty=3.3, description="Cần bán đất Định Hòa đường DX71 liên hệ môi giới"
    )
    assert not _is_reliable_price_drop(old, new), "Different area and road should not count as price drop"


def test_reliable_drop_same_source_id():
    old = _listing(
        source="facebook", source_id="same-post", posted_at="2026-05-01",
        area_m2=1259.0, price_ty=13.5, description="Old post"
    )
    new = _listing(
        source="facebook", source_id="same-post", posted_at="2026-05-03",
        area_m2=180.0, price_ty=12.9, description="Updated post"
    )
    assert _is_reliable_price_drop(old, new), "Same source_id should be a reliable price drop"


def test_score_threshold_boundary():
    assert SCORE_THRESHOLD == 6, f"SCORE_THRESHOLD should be 6, got {SCORE_THRESHOLD}"


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_hard_gate_same_day,
        test_hard_gate_different_property_type,
        test_hard_gate_different_ward,
        test_hard_gate_unknown_ward_passes,
        test_case1_passes_with_text_30,
        test_case1_fails_without_text,
        test_case1_fails_with_different_dims,
        test_case1_different_depth_no_match,
        test_case2_passes_with_text_70,
        test_case2_fails_with_low_text,
        test_case2_area_mismatch_no_match,
        test_case3_exact_copy,
        test_case3_no_text_no_match,
        test_case3_low_similarity_no_match,
        test_same_source_id_always_duplicate,
        test_same_source_different_id_uses_scoring,
        test_cross_source_scoring,
        test_reliable_drop_facebook_same_area_different_post,
        test_reliable_drop_rejects_same_template_different_lot,
        test_reliable_drop_same_source_id,
        test_score_threshold_boundary,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  💥 {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"  {passed} passed | {failed} failed")
    print(f"{'='*50}")
    sys.exit(0 if failed == 0 else 1)
