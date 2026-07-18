from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_reprocess_has_no_gemini_mutation_path():
    text = (ROOT / "cleansing" / "reprocess.py").read_text(encoding="utf-8")
    cli = (ROOT / "cli" / "system.py").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "use_gemini" not in text
    assert "enrich_listings_with_gemini" not in text
    assert "gemini" not in cli.lower()
    assert "google-generativeai" not in requirements
    assert not (ROOT / "cleansing" / "gemini_enricher.py").exists()


def test_legacy_market_data_loader_is_removed():
    market_data = (ROOT / "services" / "market_data.py").read_text(encoding="utf-8")
    app = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "def load_data(" not in market_data
    assert "load_data" not in app.split("from services.market_data import", 1)[1].split("\n", 1)[0]
