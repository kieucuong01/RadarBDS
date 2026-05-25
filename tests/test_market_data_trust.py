import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_signal_score_sort_prioritizes_verified_trust_before_raw_signal_score():
    from services.market_data import _signal_sort_sql

    sql = _signal_sort_sql("score_desc")

    assert sql.index("trust_score") < sql.index("signal_score")
    assert "trust_tier" in sql
    assert "has_legal_doc" in sql
    assert "ocr_extracted" not in sql
    assert "legal_verified_signal" not in sql
