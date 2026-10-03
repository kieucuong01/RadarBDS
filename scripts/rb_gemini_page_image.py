#!/usr/bin/env python3
"""Gemini Web image upgrade for Radar BDS Facebook Page Care queue items.

This is intentionally narrow: it updates an existing radar_social_queue.v1 file
with a Gemini-generated still image for the Facebook Page path only. It does not
publish, schedule cron jobs, or generate video.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
ASSET_DIR = Path("/opt/radar-bds/var/social_assets/gemini-page")
DEFAULT_CDP_URL = "http://127.0.0.1:9225"
MODEL_LABEL = "Gemini web image generation"
SCHEMA = "rb_gemini_page_image.v1"
MIN_PREFERRED_EDGE = 900


class GeminiImageError(RuntimeError):
    """Raised when Gemini Web cannot produce a usable image."""


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")[:90] or "page-care"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def image_dimensions(path: str | Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _plain(value: Any, *, limit: int = 900) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _caption_for_visual_prompt(caption: Any) -> str:
    """Use the final FB caption as meaning context, but omit raw metrics/jargon."""
    caption = _plain(caption, limit=1100)
    if not caption:
        return ""
    parts = re.split(r"(?<=[.!?。])\s+|\n+", caption)
    noisy = re.compile(
        r"\d|tr/m²|m2|m²|tỷ|%|snapshot|giá trung vị|dữ liệu 14|tin đang theo dõi|dấu hiệu đáng chú ý|mos|tab=signals",
        re.IGNORECASE,
    )
    kept = [p.strip() for p in parts if p.strip() and not noisy.search(p)]
    if not kept:
        kept = [re.sub(r"\b\d[\d.,/:-]*\b", "", caption).strip()]
    return _plain(" ".join(kept), limit=500)


def _page_context(slug: str) -> dict[str, str]:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        from config.seo_articles import SEO_ARTICLES  # pylint: disable=import-error
    except Exception:
        return {}
    page = SEO_ARTICLES.get(slug)
    if not isinstance(page, dict):
        return {}
    editorial = page.get("social_editorial") if isinstance(page.get("social_editorial"), dict) else {}
    return {
        "title": _plain(page.get("title") or page.get("hero_title")),
        "description": _plain(page.get("description") or page.get("hero_text")),
        "source_url": _plain(editorial.get("source_url") or editorial.get("url") or ""),
        "source_status": _plain(editorial.get("source_status") or editorial.get("status") or ""),
    }


def semantic_image_mode(source_title: str, description: str, caption: str, visual_style: str = "") -> str:
    """Pick infographic vs photoreal without inventing article facts."""
    text = " ".join([source_title, description, caption, visual_style]).casefold()
    photo_words = ["tin rẻ", "bất thường", "kiểm tra", "giấy tờ", "môi giới", "hẹn xem", "đường vào", "diện tích"]
    info_words = ["bảng giá", "giá rao", "khác nhau", "so sánh", "là gì", "theo dõi", "checklist", "phân biệt"]
    if any(word in text for word in photo_words) and not any(word in text for word in ["bảng giá", "giá rao khác"]):
        return "photoreal"
    if any(word in text for word in info_words):
        return "infographic"
    return "photoreal" if "buyer_checklist" in visual_style else "infographic"


def build_prompt(queue: dict[str, Any]) -> dict[str, str]:
    source = queue.get("source") if isinstance(queue.get("source"), dict) else {}
    content = queue.get("content") if isinstance(queue.get("content"), dict) else {}
    slug = _plain(source.get("slug") or "page-care")
    ctx = _page_context(slug)
    title = _plain(ctx.get("title") or source.get("title"))
    description = _caption_for_visual_prompt(ctx.get("description"))
    caption = _caption_for_visual_prompt(content.get("message"))
    old_style = _plain(content.get("visual_style"))
    mode = semantic_image_mode(title, description, caption, old_style)
    variation = int(hashlib.sha256(slug.encode("utf-8")).hexdigest()[:2], 16) % 4

    common = (
        "Create one square 1080x1080 Facebook feed image for Radar BDS, Vietnamese real-estate buyers in Bình Dương. "
        "The image must be useful and varied, not a dark template card. Use only generic, illustrative elements. "
        "Do not show a real map, legal certificate, street name, project name, broker/customer face, phone number, logo of another company, or fabricated local geography. "
        "Avoid raw analytics jargon, internal scoring names, dataset labels, pipeline labels, or internal filter names. "
        "Never invent prices, digits, percentages, numbered labels, chart values, or financial examples. All price tags must be blank. "
        "No signatures, red seals, pseudo legal certificates, brand logos or watermarks invented by you. "
        "Use a sophisticated editorial magazine aesthetic, navy/teal with warm ivory and a restrained coral accent, ample white space. "
        "Not childish clipart, not random decorative gears/clouds/plants. Keep the bottom 8 percent empty for a small external credit. "
        "Use only short Vietnamese labels strictly relevant to the source; never invent facts or numbers. " 
    )
    if mode == "infographic":
        style = [
            "clean editorial infographic, two-column comparison with hand-drawn icons",
            "bright magazine-style explainer, annotated mini cards, varied colors",
            "simple buyer education diagram with arrows and icons, warm paper background",
            "modern Vietnamese real-estate explainer graphic with checklist tiles",
        ][variation]
        instruction = (
            f"Infographic mode. Style: {style}. Show a conceptual contrast or checklist inspired by the source, with drawn houses, price tags, magnifier, notebook, and warning/help icons. "
            "Make the explanatory elements genuinely drawn, not just flat text boxes."
        )
    else:
        style = [
            "natural daylight photoreal illustration of a Vietnamese residential street",
            "photoreal buyer checklist scene with hands holding a notebook near a generic townhouse",
            "warm documentary-style illustrative photo of a couple checking notes before viewing a house",
            "realistic but clearly generic Vietnam neighborhood scene, buyer perspective",
        ][variation]
        instruction = (
            f"Style: {style}. Show a generic Vietnam residential scene suitable for a buyer checklist. "
            "No recognizable real person, no specific landmark, no license plates, no documents with readable legal text."
        )

    if mode == "photoreal":
        instruction += " Absolutely NO TEXT anywhere, no writing on notebooks, signs or tags, no blurred pseudo writing. No stylized illustrations: realistic photographic lighting and textures."
    elif "bảng giá đất" in title.casefold():
        instruction = (
            "Create a premium two-column editorial infographic that explains WHO SETS EACH PRICE, not a buying checklist. "
            "Left illustration: neutral civic building, plain blank sheet. Right illustration: generic house and blank asking-price tag. "
            "Use exactly these Vietnamese texts, with flawless diacritics, bold modern sans-serif, not script: "
            "Headline: 'BẢNG GIÁ ĐẤT ≠ GIÁ RAO BÁN'. "
            "Left label: 'Nhà nước ban hành'. Right label: 'Người bán đưa ra'. "
            "Bottom takeaway: 'Giá rao chưa phải giá chốt'. "
            "Do not add any other text, prices, digits, axes, charts or legal documents. Show a simple contrast, never a numerical relationship."
        )

    prompt = "\n".join(
        [
            common,
            instruction,
            f"Source page title: {title}",
            f"Source page description: {description}" if description else "",
            f"Final Facebook caption context, with raw metrics omitted: {caption}" if caption else "",
            "Do not claim any investment return, legal status, or real on-site evidence. The result is an AI illustration only.",
        ]
    ).strip()
    prompt = re.sub(r"\n{3,}", "\n\n", prompt)
    return {"prompt": prompt, "mode": mode, "title": title, "description": description, "slug": slug}


@contextlib.contextmanager
def _asset_lock(timeout: float = 10.0):
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = ASSET_DIR / ".gemini-page-image.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise GeminiImageError("Gemini image stage lock timeout")
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _write_textbox(page: Any, prompt: str) -> None:
    selector = '[contenteditable=true][role=textbox]'
    box = page.locator(selector).first
    box.wait_for(state="visible", timeout=25_000)
    box.click(timeout=10_000)
    try:
        box.fill(prompt, timeout=10_000)
    except Exception:
        page.evaluate(
            """(text) => {
                const el = [...document.querySelectorAll('[contenteditable=true][role=textbox]')]
                  .find(e => e.offsetWidth || e.offsetHeight || e.getClientRects().length);
                if (!el) throw new Error('Gemini textbox not found');
                el.focus(); el.textContent = text;
                el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: text}));
            }""",
            prompt,
        )


def _click_send(page: Any) -> None:
    clicked = page.evaluate(
        """() => {
            const re = /(send|submit|gửi|gởi|gửi câu lệnh|gửi tin nhắn)/i;
            const buttons = [...document.querySelectorAll('button,[role=button]')]
              .filter(b => (b.offsetWidth || b.offsetHeight || b.getClientRects().length))
              .filter(b => !b.disabled && b.getAttribute('aria-disabled') !== 'true')
              .filter(b => re.test((b.getAttribute('aria-label') || b.innerText || '').trim()));
            const btn = buttons.at(-1);
            if (!btn) return false;
            btn.click();
            return true;
        }"""
    )
    if not clicked:
        page.keyboard.press("Control+Enter")
        page.keyboard.press("Enter")


def _candidate_images(page: Any) -> list[dict[str, Any]]:
    return page.evaluate(
        """() => [...document.images].map((img, index) => {
            const r = img.getBoundingClientRect();
            return {
              index,
              src: img.currentSrc || img.src || '',
              alt: img.alt || '',
              naturalWidth: img.naturalWidth || 0,
              naturalHeight: img.naturalHeight || 0,
              width: Math.round(r.width),
              height: Math.round(r.height),
              visible: !!(r.width && r.height),
            };
        }).filter(x => x.visible && x.naturalWidth >= 512 && x.naturalHeight >= 512 && x.width >= 180 && x.height >= 180)"""
    )


def _blocking_text(page: Any) -> str:
    text = page.evaluate("() => document.body ? document.body.innerText.slice(-5000) : ''") or ""
    markers = [
        "đăng nhập", "sign in", "quota", "giới hạn", "limit reached", "không thể tạo hình ảnh",
        "can't create images", "cannot create images", "i can’t create", "i can't create",
    ]
    low = text.casefold()
    for marker in markers:
        if marker in low:
            return marker
    return ""


def _extract_image_bytes(page: Any, candidate: dict[str, Any]) -> tuple[bytes, str]:
    src = candidate.get("src") or ""
    if not src:
        raise GeminiImageError("Gemini image candidate had no src")
    try:
        payload = page.evaluate(
            """async (index) => {
                const img = document.images[index];
                if (!img || !img.naturalWidth || !img.naturalHeight) throw new Error('image not ready');
                await img.decode().catch(() => null);
                const canvas = document.createElement('canvas');
                canvas.width = img.naturalWidth;
                canvas.height = img.naturalHeight;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                const blob = await new Promise((resolve, reject) =>
                  canvas.toBlob(b => b ? resolve(b) : reject(new Error('canvas blob failed')), 'image/png'));
                const buf = await blob.arrayBuffer();
                let binary = '';
                const bytes = new Uint8Array(buf);
                const chunk = 0x8000;
                for (let i = 0; i < bytes.length; i += chunk) {
                  binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
                }
                return {b64: btoa(binary), type: blob.type || 'image/png'};
            }""",
            candidate["index"],
        )
        data = base64.b64decode(payload["b64"])
        return data, f"browser_canvas:{payload.get('type') or 'image/png'}"
    except Exception:
        pass
    try:
        payload = page.evaluate(
            """async (src) => {
                const resp = await fetch(src, {credentials: 'include'});
                if (!resp.ok) throw new Error('fetch failed ' + resp.status);
                const blob = await resp.blob();
                const buf = await blob.arrayBuffer();
                let binary = '';
                const bytes = new Uint8Array(buf);
                const chunk = 0x8000;
                for (let i = 0; i < bytes.length; i += chunk) {
                  binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
                }
                return {b64: btoa(binary), type: blob.type || ''};
            }""",
            src,
        )
        data = base64.b64decode(payload["b64"])
        return data, f"browser_fetch:{payload.get('type') or 'unknown'}"
    except Exception:
        handle = page.evaluate_handle("(index) => document.images[index]", candidate["index"])
        data = handle.as_element().screenshot(type="png")
        return data, "image_element_screenshot"


def _generate_with_gemini(prompt: str, *, cdp_url: str, timeout_seconds: int, retry: int) -> tuple[bytes, str, dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    last_error = ""
    attempts = max(1, min(2, retry + 1))
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_url, timeout=12_000)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        try:
            page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=35_000)
            page.locator('[contenteditable=true][role=textbox]').first.wait_for(state="visible", timeout=30_000)
            before = {img.get("src") for img in _candidate_images(page)}
            for attempt in range(attempts):
                attempt_prompt = prompt if attempt == 0 else prompt + "\n\nRetry once: create a visibly different version, still square and safe."
                _write_textbox(page, attempt_prompt)
                _click_send(page)
                deadline = time.monotonic() + timeout_seconds
                while time.monotonic() < deadline:
                    blocker = _blocking_text(page)
                    if blocker:
                        raise GeminiImageError(f"Gemini browser returned blocker text: {blocker}")
                    images = [img for img in _candidate_images(page) if img.get("src") not in before]
                    images.sort(key=lambda x: (x.get("naturalWidth", 0) * x.get("naturalHeight", 0), x.get("width", 0) * x.get("height", 0)), reverse=True)
                    if images:
                        data, acquisition = _extract_image_bytes(page, images[0])
                        return data, acquisition, images[0]
                    page.wait_for_timeout(1500)
                last_error = f"attempt {attempt + 1} timed out after {timeout_seconds}s"
            raise GeminiImageError(last_error or "Gemini did not return a new image")
        finally:
            with contextlib.suppress(Exception):
                page.close()
            # Do not browser.close(): this CDP session belongs to the long-lived logged-in Gemini browser.


def _compose_final(raw_path: Path, final_path: Path, *, mode: str) -> None:
    with Image.open(raw_path) as im:
        im = im.convert("RGB")
        target = 1080
        scale = max(target / im.width, target / im.height)
        resized = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        left = max(0, (resized.width - target) // 2)
        top = max(0, (resized.height - target) // 2)
        canvas = resized.crop((left, top, left + target, top + target))
    draw = ImageDraw.Draw(canvas, "RGBA")
    label = "Ảnh minh họa AI • Radar BDS" if mode == "photoreal" else "Minh họa AI • Radar BDS"
    strip_h = 50
    draw.rounded_rectangle((28, target - strip_h - 18, 570, target - 18), 12, fill=(15, 23, 42, 198))
    draw.text((44, target - strip_h - 7), label, font=_font(24, bold=True), fill=(255, 255, 255, 245))
    final_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(final_path, format="PNG", optimize=True)


def _update_queue(queue_path: Path, queue: dict[str, Any], meta: dict[str, Any]) -> None:
    content = queue.setdefault("content", {})
    old_visual_path = content.get("visual_path")
    content["visual_path"] = meta["final_image_path"]
    content["visual_prompt"] = meta["prompt"]
    content["visual_style"] = f"gemini_{meta['mode']}"
    content["gemini_image_provenance"] = meta["provenance_path"]
    editorial = content.get("editorial") if isinstance(content.get("editorial"), dict) else None
    if editorial is not None:
        visual = editorial.setdefault("visual", {})
        if isinstance(visual, dict):
            visual["path"] = meta["final_image_path"]
            visual["prompt"] = meta["prompt"]
            visual["gemini_provenance"] = meta["provenance_path"]
            visual["replaced_visual_path"] = old_visual_path
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upgrade_queue_with_gemini_image(
    queue_path: str | Path,
    *,
    cdp_url: str = DEFAULT_CDP_URL,
    timeout_seconds: int = 150,
    retry: int = 1,
    force: bool = False,
) -> dict[str, Any]:
    """Generate or reuse a Gemini image and write it into a queue JSON."""
    queue_path = Path(queue_path)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    target = queue.get("target") if isinstance(queue.get("target"), dict) else {}
    if target.get("platform") != "facebook" or target.get("surface") != "page":
        raise GeminiImageError("Gemini image upgrade is only allowed for Facebook Page queue items")

    request = build_prompt(queue)
    prompt = request["prompt"]
    source = queue.get("source") if isinstance(queue.get("source"), dict) else {}
    slug = request["slug"]
    article_date = _plain(source.get("article_date") or "unknown-date")
    fingerprint_source = json.dumps(
        {
            "schema": SCHEMA,
            "model": MODEL_LABEL,
            "slug": slug,
            "article_date": article_date,
            "mode": request["mode"],
            "prompt": prompt,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    prompt_hash = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
    stem = f"{article_date}-{_safe_slug(slug)}-{request['mode']}-{prompt_hash[:16]}"
    raw_path = ASSET_DIR / f"{stem}.raw.png"
    final_path = ASSET_DIR / f"{stem}.png"
    provenance_path = ASSET_DIR / f"{stem}.provenance.json"

    with _asset_lock():
        if force or not (final_path.exists() and provenance_path.exists()):
            data, acquisition, browser_candidate = _generate_with_gemini(
                prompt,
                cdp_url=cdp_url,
                timeout_seconds=max(30, min(150, int(timeout_seconds))),
                retry=max(0, min(1, int(retry))),
            )
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(data)
            raw_dims = image_dimensions(raw_path)
            if min(raw_dims) < MIN_PREFERRED_EDGE:
                raise GeminiImageError(f"Gemini source image too small (upscaling is not QA): {raw_dims}")
            _compose_final(raw_path, final_path, mode=request["mode"])
            final_dims = image_dimensions(final_path)
            if min(final_dims) < MIN_PREFERRED_EDGE:
                raise GeminiImageError(f"Composed Gemini image too small: {final_dims}")
            provenance = {
                "schema": SCHEMA,
                "generated_at": _now_iso(),
                "model": MODEL_LABEL,
                "cdp_url": cdp_url,
                "source_queue": str(queue_path),
                "source_slug": slug,
                "source_title": request["title"],
                "source_description": request["description"],
                "mode": request["mode"],
                "prompt_hash": prompt_hash,
                "prompt": prompt,
                "raw_image_path": str(raw_path),
                "final_image_path": str(final_path),
                "raw_acquisition": acquisition,
                "browser_candidate": browser_candidate,
                "raw_dimensions": {"width": raw_dims[0], "height": raw_dims[1]},
                "final_dimensions": {"width": final_dims[0], "height": final_dims[1]},
                "raw_sha256": _sha256_file(raw_path),
                "artifact_sha256": _sha256_file(final_path),
                "label_overlay": "Ảnh minh họa AI" if request["mode"] == "photoreal" else "Minh họa AI",
            }
            provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            if provenance.get("artifact_sha256") != _sha256_file(final_path):
                raise GeminiImageError("Cached Gemini image hash mismatch; regenerate with --force")
            if provenance.get("prompt_hash") != prompt_hash:
                raise GeminiImageError("Cached Gemini image prompt mismatch")

        meta = dict(provenance)
        meta.update(
            {
                "prompt": prompt,
                "mode": request["mode"],
                "prompt_hash": prompt_hash,
                "raw_image_path": str(raw_path),
                "final_image_path": str(final_path),
                "provenance_path": str(provenance_path),
            }
        )
        _update_queue(queue_path, queue, meta)
        return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upgrade one @rb Facebook Page queue item with a Gemini Web image")
    parser.add_argument("--queue", required=True, help="Path to radar_social_queue.v1 JSON")
    parser.add_argument("--cdp-url", default=os.environ.get("RB_GEMINI_CDP_URL", DEFAULT_CDP_URL))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("RB_GEMINI_IMAGE_TIMEOUT", "150")))
    parser.add_argument("--retry", type=int, default=int(os.environ.get("RB_GEMINI_IMAGE_RETRY", "1")))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    meta = upgrade_queue_with_gemini_image(
        args.queue,
        cdp_url=args.cdp_url,
        timeout_seconds=args.timeout,
        retry=args.retry,
        force=args.force,
    )
    print(json.dumps({"ok": True, "image": meta["final_image_path"], "provenance": meta["provenance_path"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
