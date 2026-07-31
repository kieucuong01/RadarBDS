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


def test_recheck_metadata_and_retired_guland_strength_flags_do_not_block_signal():
    from services.signal_quality import is_actionable_signal

    bare_recheck = {
        "is_signal": 1,
        "source_quality_recheck": 1,
        "source_quality_flags": "",
    }
    retired_strength_flags = {
        "is_signal": 1,
        "source_quality_recheck": 1,
        "source_quality_flags": "guland_weak_signal,guland_user_facing_risk",
    }

    assert is_actionable_signal(bare_recheck) is True
    assert is_actionable_signal(retired_strength_flags) is True


def test_actionable_sql_blocks_only_explicit_hard_quality_flags():
    from services.signal_quality import actionable_signal_sql

    sql = actionable_signal_sql("v")

    assert "ambiguous_price_text" in sql
    assert "review_bad_extraction" in sql
    assert "source_quality_recheck" not in sql
    assert "guland_weak_signal" not in sql
    assert "guland_user_facing_risk" not in sql
