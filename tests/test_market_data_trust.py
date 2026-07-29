import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_signal_score_sort_does_not_prioritize_image_legal_trust_while_disabled():
    from services.market_data import _signal_sort_sql

    sql = _signal_sort_sql("score_desc")

    assert "signal_score" in sql
    assert "trust_score" not in sql
    assert "trust_tier" not in sql
    assert "has_legal_doc" not in sql
    assert "ocr_extracted" not in sql
    assert "legal_verified_signal" not in sql


def test_fatal_quality_flag_is_not_actionable_but_low_confidence_remains_visible():
    from services.signal_quality import is_actionable_signal

    fatal = {
        "is_signal": 1,
        "source_quality_recheck": 1,
        "source_quality_flags": "ambiguous_price_text",
    }
    low_confidence = {
        "is_signal": 1,
        "source_quality_recheck": 1,
        "source_quality_flags": "low_segment_confidence",
    }

    assert is_actionable_signal(fatal) is False
    assert is_actionable_signal(low_confidence) is True
