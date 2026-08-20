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


@pytest.mark.parametrize("tier", ["guest", "free", "vip"])
def test_non_admin_date_range_requests_fall_back_to_three_months(monkeypatch, tier):
    import app as radar_app

    monkeypatch.setattr(radar_app, "current_tier", lambda: tier)
    with radar_app.app.test_request_context("/?date_range=all"):
        assert radar_app._request_date_range(radar_app.request) == "3m"


def test_admin_date_range_request_keeps_full_history(monkeypatch):
    import app as radar_app

    monkeypatch.setattr(radar_app, "current_tier", lambda: "admin")
    with radar_app.app.test_request_context("/?date_range=all"):
        assert radar_app._request_date_range(radar_app.request) == "all"


def test_sidebar_template_gates_long_date_ranges_to_admin():
    root = Path(__file__).resolve().parent.parent
    template = (root / "templates/index.html").read_text(encoding="utf-8")

    gate = "{% if USER_TIER == 'admin' %}"
    date_range_start = template.index('id="dateRangeFilters"')
    gated = template[template.index(gate, date_range_start):]
    gated = gated.split("{% endif %}", 1)[0]
    for value in ("6m", "1y", "all"):
        assert f'name="date_range" value="{value}"' in gated
