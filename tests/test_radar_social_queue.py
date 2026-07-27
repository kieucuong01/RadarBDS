import argparse
import importlib.util
from pathlib import Path


def _load_queue_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "radar_social_queue.py"
    spec = importlib.util.spec_from_file_location("radar_social_queue", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_data_status_includes_radar_domain_and_ward_filter_link():
    social_queue = _load_queue_module()
    args = argparse.Namespace(
        slug="gia-dat-tan-an-thu-dau-mot-hien-nay",
        skip_verify=True,
        platform="facebook",
        surface="page",
        page_url="https://www.facebook.com/radarbdsvn/",
        mode="publish",
        style="data_post",
    )

    item = social_queue.create(args)
    message = item["content"]["message"]
    ward_filter_link = item["content"]["ward_filter_link"]

    assert "Vào radarbds.vn → lọc phường Tân An" in message
    assert "https://radarbds.vn/?tab=signals&ward=T%C3%A2n+An" in message
    assert "utm_campaign=ward_filter" in message
    assert "utm_medium=organic_social" in message
    assert "utm_campaign=page_article" in item["content"]["link"]
    assert "Bài phân tích dữ liệu:" in message
    assert item["content"]["link"] in message
    assert ward_filter_link in message
    assert "\n        •" not in message
