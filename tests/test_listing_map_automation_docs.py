from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_map_automation_runbook_has_required_commands_and_stop_gates():
    text = (
        ROOT / "docs" / "listing_map_registry_automation.md"
    ).read_text(encoding="utf-8")

    required = (
        "map-location-research-queue",
        "map-location-ingest-evidence",
        "--apply",
        "build_listing_location_registry.py",
        "map-locations --full --dry-run",
        "map-locations --full",
        "deploy_production.ps1",
        "confidence >= 0.90",
        "CAPTCHA",
        "không cần người dùng duyệt",
    )
    for value in required:
        assert value in text
