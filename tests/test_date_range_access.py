import pytest
from pathlib import Path


def test_date_range_options_are_limited_for_non_admin_tiers():
    from services import market_data

    public = ("1w", "1m", "3m")
    assert market_data.date_range_options_for_tier("guest") == public
    assert market_data.date_range_options_for_tier("free") == public
    assert market_data.date_range_options_for_tier("vip") == public
    assert market_data.date_range_options_for_tier("admin") == (
        "1w",
        "1m",
        "3m",
        "6m",
        "1y",
        "all",
    )


def test_guland_source_is_available_only_to_admins():
    from services import market_data

    assert market_data.normalize_sources_for_tier(None, "guest") == ["facebook"]
    assert market_data.normalize_sources_for_tier(["guland"], "free") == ["facebook"]
    assert market_data.normalize_sources_for_tier(["facebook", "guland"], "vip") == ["facebook"]
    assert market_data.normalize_sources_for_tier(None, "admin") == ["facebook", "guland"]
    assert market_data.normalize_sources_for_tier(["guland"], "admin") == ["guland"]


@pytest.mark.parametrize("tier", ["guest", "free", "vip"])
def test_non_admin_date_range_defaults_to_one_month_and_restricts_admin_ranges(monkeypatch, tier):
    import app as radar_app

    monkeypatch.setattr(radar_app, "current_tier", lambda: tier)
    with radar_app.app.test_request_context("/"):
        assert radar_app._request_date_range(radar_app.request) == "1m"
    with radar_app.app.test_request_context("/?date_range=all"):
        assert radar_app._request_date_range(radar_app.request) == "1m"
    with radar_app.app.test_request_context("/?date_range=3m"):
        assert radar_app._request_date_range(radar_app.request) == "3m"


def test_admin_date_range_request_keeps_full_history(monkeypatch):
    import app as radar_app

    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    with radar_app.app.test_request_context("/?date_range=all"):
        assert radar_app._request_date_range(radar_app.request) == "all"


def test_admin_date_range_defaults_to_one_month(monkeypatch):
    import app as radar_app

    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    with radar_app.app.test_request_context("/"):
        assert radar_app._request_date_range(radar_app.request) == "1m"


def test_sidebar_template_gates_long_date_ranges_to_admin():
    root = Path(__file__).resolve().parent.parent
    template = (root / "templates/index.html").read_text(encoding="utf-8")

    gate = "{% if USER_TIER == 'admin' %}"
    date_range_start = template.index('id="dateRangeFilters"')
    gated = template[template.index(gate, date_range_start):]
    gated = gated.split("{% endif %}", 1)[0]
    for value in ("6m", "1y", "all"):
        assert f'name="date_range" value="{value}"' in gated


def test_sidebar_template_defaults_to_one_month_and_gates_source_filter_to_admin():
    root = Path(__file__).resolve().parent.parent
    template = (root / "templates/index.html").read_text(encoding="utf-8")

    assert 'name="date_range" value="1m" checked' in template
    assert 'name="date_range" value="3m" checked' not in template
    source_start = template.index('id="sourceFilters"')
    admin_gate = template.rfind("{% if USER_TIER == 'admin' %}", 0, source_start)
    assert admin_gate >= 0
    assert template.index("{% endif %}", source_start) < template.index('id="dateRangeFilters"')
