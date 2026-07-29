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


def test_data_status_includes_radar_domain_and_ward_filter_link(tmp_path):
    social_queue = _load_queue_module()
    social_queue.ASSET_DIR = tmp_path
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


def _queue_args(slug, style="data_post"):
    return argparse.Namespace(
        slug=slug,
        skip_verify=True,
        platform="facebook",
        surface="page",
        page_url="https://www.facebook.com/radarbdsvn/",
        mode="publish",
        style=style,
    )


def test_visual_style_metadata_for_comparison_article(tmp_path):
    social_queue = _load_queue_module()
    social_queue.ASSET_DIR = tmp_path

    item = social_queue.create(_queue_args("phu-tan-hay-phu-my-loc-gia-theo-phuong"))
    content = item["content"]

    assert content["visual_style"] == "ward_compare"
    assert "maximum 2 key metrics" in content["visual_prompt"]
    assert "no long paragraph" in content["visual_prompt"]
    assert Path(content["visual_path"]).exists()


def test_visual_style_variants_for_budget_and_risk_articles():
    social_queue = _load_queue_module()

    assert social_queue._visual_kind(
        "nha-dat-thu-dau-mot-duoi-3-ty-phuong-nao-nhieu-lua-chon",
        {"title": "Nhà đất Thủ Dầu Một dưới 3 tỷ: phường nào còn nhiều lựa chọn?"},
    ) == "budget_filter"
    assert social_queue._visual_kind(
        "tin-re-bat-thuong-binh-duong-can-kiem-tra-gi",
        {"title": "Tin rẻ bất thường Bình Dương cần kiểm tra gì?"},
    ) == "risk_checklist"


def test_ward_price_uses_classic_visual_style_prompt_and_asset(tmp_path):
    social_queue = _load_queue_module()
    social_queue.ASSET_DIR = tmp_path

    item = social_queue.create(_queue_args("gia-dat-phu-tan-hien-bao-nhieu"))
    content = item["content"]

    assert content["visual_style"] == "ward_price"
    assert "classic ward price card" in content["visual_prompt"]
    assert "ĐANG SO GIÁ PHÚ TÂN?" in content["visual_prompt"]
    assert Path(content["visual_path"]).exists()

