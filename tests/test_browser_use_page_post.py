from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path("/opt/radar-bds/current/scripts/browser_use_page_post.py")
spec = importlib.util.spec_from_file_location("browser_use_page_post", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_extract_browser_result_uses_last_browser_json():
    stdout = "log line\n{" + '"ok": false, "verified_text": false' + "}\n" + '{"ok": true, "verified_text": true, "permalink": "https://www.facebook.com/radarbdsvn/posts/pfbid123"}\n'
    result = mod._extract_browser_result(stdout)
    assert result["ok"] is True
    assert result["permalink"].endswith("pfbid123")


@pytest.mark.parametrize(
    "permalink",
    [
        "https://www.facebook.com/radarbdsvn/posts/pfbid123",
        "https://www.facebook.com/permalink.php?story_fbid=123&id=456",
        "https://www.facebook.com/radarbdsvn?story_fbid=123&id=456",
    ],
)
def test_validate_publish_success_requires_real_facebook_permalink(permalink: str):
    record = {
        "stdout": '{"ok": true, "verified_text": true, "permalink": "' + permalink + '"}\n',
    }
    result = mod._validate_publish_success(record)
    assert result["permalink"] == permalink


def test_validate_publish_success_rejects_verified_text_without_permalink():
    record = {"stdout": '{"ok": true, "verified_text": true}\n'}
    with pytest.raises(SystemExit, match="missing valid Facebook permalink"):
        mod._validate_publish_success(record)


def test_validate_publish_success_rejects_composer_style_false_positive():
    record = {
        "stdout": '{"ok": true, "verified_text": true, "permalink": "https://www.facebook.com/radarbdsvn/"}\n'
    }
    with pytest.raises(SystemExit, match="missing valid Facebook permalink"):
        mod._validate_publish_success(record)


def test_validate_publish_success_requires_native_visual_when_queue_has_image():
    record = {
        "stdout": (
            '{"ok": true, "verified_text": true, "verified_visual": false, '
            '"permalink": "https://www.facebook.com/radarbdsvn/posts/pfbid123"}\n'
        )
    }
    with pytest.raises(SystemExit, match="native visual"):
        mod._validate_publish_success(record, require_visual=True)


def test_validate_publish_success_accepts_native_photo_permalink():
    record = {
        "stdout": (
            '{"ok": true, "verified_text": true, "verified_visual": true, '
            '"permalink": "https://www.facebook.com/radarbdsvn/posts/pfbid123", '
            '"photo_permalink": "https://www.facebook.com/photo/?fbid=456&set=a.789"}\n'
        )
    }
    result = mod._validate_publish_success(record, require_visual=True)
    assert "/photo/" in result["photo_permalink"]


def test_publish_rejects_queue_without_visual_before_browser(tmp_path, monkeypatch):
    queue_path = tmp_path / "text-only.json"
    queue_path.write_text(
        __import__("json").dumps(
            {
                "schema": "radar_social_queue.v1",
                "target": {"page_url": "https://www.facebook.com/radarbdsvn/"},
                "content": {"message": "Text-only should not publish"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "BROWSER_USE", tmp_path / "missing-browser-use")
    args = mod.argparse.Namespace(
        queue=str(queue_path),
        mode="publish",
        yes=True,
        cdp_url="http://127.0.0.1:9224",
        artifact_dir=str(tmp_path / "artifacts"),
        run_dir=str(tmp_path / "runs"),
        timeout=10,
    )
    with pytest.raises(SystemExit, match="requires a native visual"):
        mod.run(args)


def test_generated_publish_program_does_not_use_body_text_as_success_evidence(tmp_path):
    image = tmp_path / "visual.png"
    image.write_bytes(b"fake")
    queue = {
        "target": {"page_url": "https://www.facebook.com/radarbdsvn/"},
        "content": {"message": "Hook line\nBody", "visual_path": str(image)},
    }
    program = mod._program(queue, "publish", str(tmp_path / "shot.png"))
    assert "document.body.innerText" not in program
    assert "permalink" in program
    assert "href.includes('/posts/')" in program


def test_generated_publish_program_does_not_treat_generic_img_as_uploaded_visual(tmp_path):
    image = tmp_path / "visual.png"
    image.write_bytes(b"fake")
    queue = {
        "target": {"page_url": "https://www.facebook.com/radarbdsvn/"},
        "content": {"message": "Hook line\nBody", "visual_path": str(image)},
    }
    program = mod._program(queue, "publish", str(tmp_path / "shot.png"))
    assert "d.querySelector('img')" not in program
    assert 'img[src^="blob:"]' in program
    assert "photo_permalink" in program


def test_generated_publish_program_handles_inline_draft_and_exact_post_settings(tmp_path):
    image = tmp_path / "visual.png"
    image.write_bytes(b"fake")
    queue = {
        "target": {"page_url": "https://www.facebook.com/radarbdsvn/"},
        "content": {"message": "Hook line\nBody #RadarBDS", "visual_path": str(image)},
    }
    program = mod._program(queue, "publish", str(tmp_path / "shot.png"))
    compile(program, "<browser-use-program>", "exec")
    assert "inline_draft" in program
    assert "Post settings|Scheduling options|Publish now" in program
    assert "text === label" in program
    assert "Final exact Post button" in program


def test_generated_publish_program_waits_for_delayed_composer_textbox_and_has_dom_fallback(tmp_path):
    image = tmp_path / "visual.png"
    image.write_bytes(b"fake")
    queue = {
        "target": {"page_url": "https://www.facebook.com/radarbdsvn/"},
        "content": {"message": "Hook line\nBody", "visual_path": str(image)},
    }
    program = mod._program(queue, "publish", str(tmp_path / "shot.png"))
    compile(program, "<browser-use-program>", "exec")
    assert "for _ in range(12):" in program
    assert "[role=\"dialog\"] [role=\"textbox\"]" in program
    assert "textbox_point" in program


def test_generated_publish_program_never_uses_escape_after_typing_hashtags(tmp_path):
    image = tmp_path / "visual.png"
    image.write_bytes(b"fake")
    queue = {
        "target": {"page_url": "https://www.facebook.com/radarbdsvn/"},
        "content": {"message": "Hook line\n#RadarBDS", "visual_path": str(image)},
    }
    program = mod._program(queue, "publish", str(tmp_path / "shot.png"))
    compile(program, "<browser-use-program>", "exec")
    assert "if '#' in message:" not in program
    assert "press_key('Escape')" not in program.split("caption_already_present", 1)[1]
