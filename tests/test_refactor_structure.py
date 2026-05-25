from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_app_routes_are_registered_from_blueprint_modules():
    expected = [
        "routes/__init__.py",
        "routes/public.py",
        "routes/auth_api.py",
        "routes/market_api.py",
        "routes/admin_api.py",
    ]
    for rel_path in expected:
        assert (ROOT / rel_path).exists(), f"missing {rel_path}"

    app_source = _read("app.py")
    assert "register_blueprints(app)" in app_source
    assert "@app.route" not in app_source


def test_index_loads_main_js_feature_files_in_dependency_order():
    html = _read("templates/index.html")
    expected_order = [
        "js/auth.js",
        "js/main/core.js",
        "js/main/filters.js",
        "js/main/signals.js",
        "js/main/modal.js",
        "js/main/market.js",
        "js/main/listings.js",
        "js/main/auth_cta.js",
        "js/main/boot.js",
    ]
    last_idx = -1
    for asset in expected_order:
        idx = html.find(asset)
        assert idx > last_idx, f"{asset} not loaded after previous feature file"
        last_idx = idx
        assert (ROOT / "static" / asset).exists(), f"missing static/{asset}"

    main_js = ROOT / "static/js/main.js"
    assert not main_js.exists() or main_js.stat().st_size < 1200


def test_index_loads_css_domain_files_in_dependency_order():
    html = _read("templates/index.html")
    expected_order = [
        "css/main/base.css",
        "css/main/layout.css",
        "css/main/filters.css",
        "css/main/cards.css",
        "css/main/modal.css",
        "css/main/market.css",
        "css/main/leads_chat.css",
        "css/auth.css",
    ]
    last_idx = -1
    for asset in expected_order:
        idx = html.find(asset)
        assert idx > last_idx, f"{asset} not loaded after previous CSS file"
        last_idx = idx
        assert (ROOT / "static" / asset).exists(), f"missing static/{asset}"
