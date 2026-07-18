from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_standard_deploy_rolls_back_and_installs_dependencies_before_restart():
    script = (ROOT / "scripts" / "deploy_production.ps1").read_text(encoding="utf-8")

    assert "rollback_to_before" in script
    assert "trap 'rollback_to_before' ERR" in script
    assert "pip install -r requirements.txt" in script
    assert script.index("pip install -r requirements.txt") < script.rindex("sudo systemctl restart radar-bds.service")


def test_bundle_fallback_rolls_back_and_installs_dependencies_before_restart():
    script = (ROOT / "scripts" / "ship_production.ps1").read_text(encoding="utf-8")

    assert "rollback_to_before" in script
    assert "trap 'rollback_to_before' ERR" in script
    assert "pip install -r requirements.txt" in script
    assert script.index("pip install -r requirements.txt") < script.rindex("sudo systemctl restart radar-bds.service")
