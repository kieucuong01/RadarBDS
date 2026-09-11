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
        skip_verify=False,
        source_http_status=200,
        platform="facebook",
        surface="page",
        page_url="https://www.facebook.com/radarbdsvn/",
        mode="publish",
        style="data_post",
    )

    item = social_queue.create(args)
    message = item["content"]["message"]
    self_comment = item["content"]["self_comment"]

    # New contract: the caption stands alone; the Radar link lives in the
    # self-comment with attribution, never as raw URL text inside the caption.
    assert item["content"]["generated_by"] == "rb_social_editorial"
    assert message.strip()
    assert "utm_medium=pinned_comment" in self_comment
    assert "utm_campaign=" in self_comment
    assert "radarbds.vn" in self_comment
    assert "utm_campaign=page_article" in item["content"]["link"]
    assert item["content"]["link"] not in message
    assert "\n        •" not in message


def _queue_args(slug, style="data_post"):
    # New contract: publish mode requires a verified source HTTP status.
    return argparse.Namespace(
        slug=slug,
        skip_verify=False,
        source_http_status=200,
        platform="facebook",
        surface="page",
        page_url="https://www.facebook.com/radarbdsvn/",
        mode="publish",
        style=style,
    )


def test_editorial_contract_replaces_legacy_ward_card_copy(tmp_path):
    """Legacy ward-card assertions are obsolete: captions are editorial now."""
    social_queue = _load_queue_module()
    social_queue.ASSET_DIR = tmp_path

    item = social_queue.create(_queue_args("gia-dat-phu-tan-hien-bao-nhieu"))
    content = item["content"]

    assert content["generated_by"] == "rb_social_editorial"
    editorial = content["editorial"]
    assert editorial["status"] == "ready"
    assert editorial["pillar"] in {"radar_insight", "radar_howto", "buyer_checklist"}
    message = content["message"]
    # Reader-facing text must not carry raw ratios, sample sizes or jargon.
    for forbidden in ("14/432", "trung vị", "Số liệu đang ghi nhận", "property_type"):
        assert forbidden not in message
    assert message.strip()
    assert Path(content["visual_path"]).exists()


def test_legacy_visual_kind_helpers_still_supported():
    social_queue = _load_queue_module()

    assert social_queue._visual_kind(
        "nha-dat-thu-dau-mot-duoi-3-ty-phuong-nao-nhieu-lua-chon",
        {"title": "Nhà đất Thủ Dầu Một dưới 3 tỷ: phường nào còn nhiều lựa chọn?"},
    ) == "budget_filter"
    assert social_queue._visual_kind(
        "tin-re-bat-thuong-binh-duong-can-kiem-tra-gi",
        {"title": "Tin rẻ bất thường Bình Dương cần kiểm tra gì?"},
    ) == "risk_checklist"

