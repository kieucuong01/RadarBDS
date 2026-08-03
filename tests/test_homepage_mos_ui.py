import re
from unittest import mock

import pytest


@pytest.mark.parametrize(
    ("tier", "locked"),
    [
        ("guest", True),
        ("free", True),
        ("vip", False),
        ("admin", False),
    ],
)
def test_rendered_homepage_mos_control_matches_tier(tier, locked):
    import app as app_module

    app_module.app.config.update(TESTING=True)
    with (
        mock.patch.object(app_module, "current_tier", return_value=tier),
        mock.patch.object(app_module, "current_user", return_value=None),
    ):
        response = app_module.app.test_client().get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    slider = re.search(r'<input[^>]+id="mosSlider"[^>]*>', html, re.S)
    assert slider is not None
    assert 'value="15"' in slider.group(0)
    assert ("disabled" in slider.group(0)) is locked
    assert re.search(r'id="mosValue">\s*15\s*</span>', html)
