from pathlib import Path


def test_runtime_code_does_not_use_deprecated_datetime_utcnow():
    root = Path(__file__).resolve().parent.parent
    scan_targets = [
        root / "app.py",
        root / "alerts",
        root / "analytics",
        root / "cleansing",
        root / "cli",
        root / "config",
        root / "crawler",
        root / "db",
        root / "routes",
        root / "scripts",
        root / "services",
    ]
    offenders = []
    for target in scan_targets:
        files = [target] if target.is_file() else target.rglob("*.py")
        for path in files:
            text = path.read_text(encoding="utf-8")
            if "datetime.utcnow(" in text:
                offenders.append(path.relative_to(root).as_posix())

    assert offenders == []
