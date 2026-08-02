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
