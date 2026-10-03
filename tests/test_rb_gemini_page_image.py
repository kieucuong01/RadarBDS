from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path("/opt/radar-bds/current/scripts/rb_gemini_page_image.py")
spec = importlib.util.spec_from_file_location("rb_gemini_page_image", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _queue(slug: str, title: str, caption: str, visual_style: str = "") -> dict:
    return {
        "schema": "radar_social_queue.v1",
        "source": {"slug": slug, "title": title, "article_date": "2026-09-12"},
        "target": {"platform": "facebook", "surface": "page"},
        "content": {"message": caption, "visual_style": visual_style},
    }


def test_semantic_mode_chooses_infographic_for_price_table_article():
    request = mod.build_prompt(
        _queue(
            "bang-gia-dat-va-gia-rao-khac-nhau-the-nao",
            "Bảng giá đất và giá rao khác nhau thế nào?",
            "Bài giải thích vì sao không nên lấy bảng giá làm giá chủ phải bán.",
        )
    )

    assert request["mode"] == "infographic"
    assert "infographic" in request["prompt"].casefold()
    assert "MOS" not in request["prompt"]
    assert "tab=signals" not in request["prompt"]


def test_semantic_mode_chooses_photoreal_for_buyer_checklist_article():
    request = mod.build_prompt(
        _queue(
            "tin-re-bat-thuong-binh-duong-can-kiem-tra-gi",
            "Tin rẻ bất thường ở Bình Dương: 5 điểm cần kiểm tra trước khi gọi môi giới",
            "Trước khi gọi môi giới, kiểm tra đường vào, giấy tờ và diện tích mô tả.",
            "buyer_checklist",
        )
    )

    assert request["mode"] == "photoreal"
    assert "generic Vietnam residential scene" in request["prompt"]
    assert "AI illustration only" in request["prompt"]


def test_update_queue_writes_visual_and_provenance(tmp_path):
    queue_path = tmp_path / "queue.json"
    data = _queue("abc", "Tiêu đề", "Caption")
    data["content"]["visual_path"] = "/old.png"
    data["content"]["editorial"] = {"visual": {"path": "/old.png", "prompt": "old"}}
    queue_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    meta = {
        "final_image_path": "/new.png",
        "prompt": "gemini prompt",
        "mode": "infographic",
        "provenance_path": "/new.provenance.json",
    }
    mod._update_queue(queue_path, data, meta)

    updated = json.loads(queue_path.read_text(encoding="utf-8"))
    assert updated["content"]["visual_path"] == "/new.png"
    assert updated["content"]["visual_style"] == "gemini_infographic"
    assert updated["content"]["gemini_image_provenance"] == "/new.provenance.json"
    assert updated["content"]["editorial"]["visual"]["replaced_visual_path"] == "/old.png"


def test_caption_context_omits_raw_metrics_for_visual_prompt():
    text = (
        "Phú Lợi hay Hiệp An nếu đang xem nhà đất? "
        "Dữ liệu 14 ngày: Phú Lợi 76 tin, Hiệp An 96 tin. "
        "Đây là dữ liệu để lọc ban đầu, không phải kết luận nên mua."
    )

    cleaned = mod._caption_for_visual_prompt(text)

    assert "76" not in cleaned
    assert "96" not in cleaned
    assert "Dữ liệu 14" not in cleaned
    assert "Phú Lợi hay Hiệp An" in cleaned
    assert "không phải kết luận nên mua" in cleaned


def test_prompt_bans_invented_prices_and_keeps_specific_price_table_meaning():
    request = mod.build_prompt(_queue(
        "bang-gia-dat-va-gia-rao-khac-nhau-the-nao",
        "Bảng giá đất và giá rao khác nhau thế nào?", "Phân biệt hai loại giá."))
    assert "Never invent prices, digits" in request["prompt"]
    assert "Nhà nước ban hành" in request["prompt"]
    assert "Người bán đưa ra" in request["prompt"]
    assert "Giá rao chưa phải giá chốt" in request["prompt"]


def test_generation_failure_leaves_queue_unmodified(tmp_path, monkeypatch):
    import pytest
    queue_path = tmp_path / "queue.json"
    original = json.dumps(_queue("custom-checklist", "Kiểm tra nhà trước khi mua", "Hỏi giấy tờ."))
    queue_path.write_text(original)
    monkeypatch.setattr(mod, "ASSET_DIR", tmp_path / "assets")
    def blocked(*args, **kwargs):
        raise mod.GeminiImageError("quota")
    monkeypatch.setattr(mod, "_generate_with_gemini", blocked)
    with pytest.raises(mod.GeminiImageError, match="quota"):
        mod.upgrade_queue_with_gemini_image(queue_path)
    assert queue_path.read_text() == original


def test_low_resolution_is_rejected_before_upscale(tmp_path, monkeypatch):
    import io
    import pytest
    from PIL import Image
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(_queue("tiny-image", "Kiểm tra nhà", "Kiểm tra nhà.")))
    raw = io.BytesIO()
    Image.new("RGB", (512, 512)).save(raw, format="PNG")
    monkeypatch.setattr(mod, "ASSET_DIR", tmp_path / "assets")
    monkeypatch.setattr(mod, "_generate_with_gemini", lambda *a, **kw: (raw.getvalue(), "unit-test", {}))
    with pytest.raises(mod.GeminiImageError, match="source image too small"):
        mod.upgrade_queue_with_gemini_image(queue_path)

