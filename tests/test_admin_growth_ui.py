from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_growth_admin_ui_contract():
    template = (ROOT / "templates" / "admin_control_room.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "css" / "admin.css").read_text(encoding="utf-8")

    for marker in (
        'id="panel-growth"',
        'data-panel-slug="tang-truong"',
        'id="growthAnchor"',
        'id="growthIncludeGuland"',
        'id="growthSourceChart"',
        'id="growthUniqueChart"',
        'id="growthDropChart"',
        'id="growthUserChart"',
        'id="growthTableBody"',
        "chart.js@4.4.4",
    ):
        assert marker in template
    assert "growth: 'tang-truong'" in script
    assert template.index('id="panel-infra"') < template.index('id="panel-growth"') < template.index('id="panel-users"')
    assert template.index("chart.js@4.4.4") < template.index("js/admin.js")
    assert template.index("chart.js@4.4.4") > template.index("</main>")
    user_select = template[template.index('id="userTierFilter"'):template.index('id="userTable"', template.index('id="userTierFilter"'))]
    assert "chart.js@4.4.4" not in user_select
    assert "admin-v46-facebook-broker-governance" in template
    assert "/admin/api/growth?period=" in script
    assert "include_guland=" in script
    assert "prefers-reduced-motion" in script
    assert "Đăng ký · toàn hệ thống" in script
    assert ".growth-kpis" in styles
    assert "@media (max-width: 600px)" in styles

