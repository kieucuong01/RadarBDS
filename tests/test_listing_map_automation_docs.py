from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_auto_registry_runtime_geometry_dependency_is_pinned():
    requirements = (
        ROOT / "requirements.txt"
    ).read_text(encoding="utf-8").splitlines()

    assert "shapely==2.1.2" in requirements


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
        "production-queue.json",
        "map-location-research-queue --limit 50",
    )
    for value in required:
        assert value in text
