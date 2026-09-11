#!/usr/bin/env python3
"""Auto-post the latest Radar BDS social queue item to the Facebook Page.

Cron-safe wrapper:
1. Ensure the dedicated browser-use Chrome/CDP worker is reachable.
2. Create a `radar_social_queue.v1` JSON for the latest `/tin-tuc` article.
3. Publish to the Radar BDS Facebook Page via `scripts/browser_use_page_post.py`.
4. Record a lightweight posted-state key to avoid duplicate reposts.

No passwords, cookies, or Facebook credentials are read or written here. The
script relies on the already-authenticated Chrome profile at
`/home/hermesops/.browser-profiles/radar-social/chrome-profile`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path("/opt/radar-bds/current")
QUEUE_SCRIPT = REPO / "scripts/radar_social_queue.py"
POST_SCRIPT = REPO / "scripts/browser_use_page_post.py"
CDP_URL = "http://127.0.0.1:9224"
STATE_PATH = Path("/opt/radar-bds/var/social_queue/posted_slugs.json")
# Use a dedicated Hermes-owned queue dir for auto-posting. The SEO publisher can
# create same-day queue files in /opt/radar-bds/var/social_queue as the `radar`
# user; overwriting those from Hermes cron causes PermissionError.
QUEUE_DIR = Path("/opt/radar-bds/var/social_queue/autopost")
RUN_DIR = Path("/opt/radar-bds/var/browser_use_runs")


def log(message: str) -> None:
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def cdp_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=4) as resp:  # noqa: S310 - localhost only
            return resp.status == 200
    except Exception:
        return False


def ensure_browser() -> None:
    if cdp_ready():
        log("Chrome CDP already reachable at 127.0.0.1:9224")
        return
    raise SystemExit(
        "Radar Social Chrome CDP unavailable; cron wrapper must restore radar-social-browser.service first"
    )


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"posted": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("posted"), dict):
            raise ValueError("expected posted object")
        return data
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Cannot read posted state; refusing a possible duplicate: {exc}") from exc


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


def valid_facebook_permalink(url: str) -> bool:
    return bool(
        isinstance(url, str)
        and url.startswith("https://www.facebook.com/")
        and ("/posts/" in url or "/permalink.php" in url or "story_fbid=" in url)
    )


def valid_facebook_photo_permalink(url: str) -> bool:
    return bool(
        isinstance(url, str)
        and url.startswith("https://www.facebook.com/")
        and ("/photo/" in url or "/photo.php" in url)
    )


def posted_today(posted: dict, today: dt.date | None = None) -> tuple[bool, dict | None]:
    today = today or dt.datetime.now().astimezone().date()
    for item in posted.values():
        item = item if isinstance(item, dict) else {}
        raw_browser_result = item.get("browser_result")
        browser_result: dict = raw_browser_result if isinstance(raw_browser_result, dict) else {}
        stamp = str(item.get("posted_at") or "")
        post_url = str(item.get("post_url") or browser_result.get("permalink") or "")
        photo_url = str(item.get("photo_url") or browser_result.get("photo_permalink") or "")
        verified_text = item.get("verified_text", browser_result.get("verified_text"))
        verified_visual = item.get("verified_visual", browser_result.get("verified_visual"))
        if (
            stamp[:10] == today.isoformat()
            and valid_facebook_permalink(post_url)
            and bool(verified_text)
            and bool(verified_visual)
            and valid_facebook_photo_permalink(photo_url)
        ):
            return True, item
    return False, None


def parse_post_wrapper_stdout(stdout: str) -> dict:
    try:
        data = json.loads((stdout or "").strip())
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Publish wrapper returned 0 but stdout was not JSON: {exc}") from exc
    browser_result = data.get("browser_result") if isinstance(data, dict) else None
    if not isinstance(browser_result, dict) or browser_result.get("ok") is not True:
        raise SystemExit(f"Post wrapper missing browser_result.ok=true: {str(stdout)[-1000:]}")
    if not valid_facebook_permalink(str(browser_result.get("permalink") or "")):
        raise SystemExit(f"Publish wrapper missing verified permalink: {str(stdout)[-1000:]}")
    if (
        not browser_result.get("verified_text")
        or not browser_result.get("verified_visual")
        or not valid_facebook_photo_permalink(str(browser_result.get("photo_permalink") or ""))
    ):
        raise SystemExit(f"Publish wrapper missing verified native visual: {str(stdout)[-1000:]}")
    if not browser_result.get("verified_comment"):
        browser_result["comment_warning"] = "Radar BDS self-comment was not verified; post KPI still counts because permalink/native visual are verified."
    return data


def article_candidates() -> list[tuple[str, str]]:
    """Newest /tin-tuc article slugs with their publish/modified dates."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from config.seo_articles import SEO_ARTICLES  # pylint: disable=import-error

    candidates: list[tuple[str, str]] = []
    for slug, page in SEO_ARTICLES.items():
        if not isinstance(page, dict) or not str(page.get("path", "")).startswith("/tin-tuc/"):
            continue
        article = page.get("article") or {}
        article_date = str(article.get("modified_at") or article.get("published_at") or "unknown-date")
        candidates.append((article_date, str(slug)))
    return sorted(candidates, reverse=True)


def create_queue(slug: str = "latest", *, style: str = "data_post", preview: bool = False) -> Path:
    output_dir = Path("/opt/radar-bds/var/social_preview") if preview else QUEUE_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(QUEUE_SCRIPT), "--slug", slug, "--mode", "review" if preview else "publish", "--style", style, "--out-dir", str(output_dir)]
    proc = subprocess.run(cmd, cwd=str(REPO), text=True, capture_output=True, timeout=60, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"Queue creation failed for slug={slug} style={style}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    first = (proc.stdout.strip().splitlines() or [""])[0]
    path = Path(first)
    if not path.exists():
        raise SystemExit(f"Queue script did not return an existing file. Output:\n{proc.stdout}")
    log(f"Queue created: {path} · style={style}")
    return path


def page_care_style_for_date(day: dt.date | None = None) -> str:
    """Rotate caption style so the Page does not sound identical each run."""
    day = day or dt.datetime.now().astimezone().date()
    # Mon/Wed/Fri keep article-specific hooks; Tue/Thu use a market-pulse voice.
    return "market_pulse" if day.weekday() in {1, 3} else "data_post"


def was_slug_posted(slug: str, posted: dict) -> bool:
    """Only real published records count; review previews are not history."""
    for key, entry in posted.items():
        if not isinstance(entry, dict):
            continue
        if (entry.get("slug") or key.rsplit(":", 1)[0]) != slug:
            continue
        if entry.get("post_url") or entry.get("posted_at"):
            return True
    return False


def refresh_preview_artifacts(slug: str) -> int:
    """Rebuild existing review previews for a slug from current code.

    Preview JSON files are review-only scratch artifacts, never publish history.
    Without this, a preview written before a code fix keeps showing the old
    caption/visual metadata and hides the fix. Returns files refreshed.
    """
    import subprocess as _sp
    preview_dir = Path("/opt/radar-bds/var/social_preview")
    if not preview_dir.is_dir():
        return 0
    refreshed = 0
    cmd = [sys.executable, str(QUEUE_SCRIPT), "--slug", slug, "--mode", "review", "--style", "data_post", "--out-dir", str(preview_dir)]
    proc = _sp.run(cmd, cwd=str(REPO), text=True, capture_output=True, timeout=60, check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        refreshed += 1
    return refreshed


def rank_editorial_candidates(rows: list[dict], recent: list[dict]) -> list[dict]:
    """Prefer a different, underrepresented pillar; never repeat a recent angle.

    recent is newest first. If no source-qualified angle survives, return no
    candidate rather than a generic filler post. Publication frequency unchanged.
    """
    from collections import Counter
    used = {r.get("topic") for r in recent[:6] if r.get("topic")}
    counts = Counter(r.get("pillar") for r in recent[:10])
    last = recent[0].get("pillar") if recent else None
    eligible = [r for r in rows if r.get("topic") not in used]
    eligible.sort(key=lambda r: (r.get("date", ""), r["slug"]), reverse=True)
    eligible.sort(key=lambda r: (r.get("pillar") == last, counts[r.get("pillar")]))
    return eligible


def editorial_candidates(posted: dict) -> list[dict]:
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from config.seo_articles import SEO_ARTICLES
    from scripts.rb_social_editorial import build_editorial
    rows = []
    recent = []
    for key, entry in sorted(posted.items(), key=lambda x: x[1].get("posted_at", ""), reverse=True)[:10]:
        slug = entry.get("slug") or key.rsplit(":", 1)[0]
        if entry.get("editorial_pillar"):
            recent.append({"pillar": entry["editorial_pillar"], "topic": entry.get("editorial_topic")})
        elif slug in SEO_ARTICLES:
            draft = build_editorial(SEO_ARTICLES[slug], "", slug, make_visual=False)
            recent.append({"pillar": draft["pillar"], "topic": draft["metadata"]["topic"]})
    from collections import Counter
    pillar_seen = Counter(r.get("pillar") for r in recent[:10])
    rows = []
    for article_date, slug in article_candidates():
        if was_slug_posted(slug, posted):
            continue
        page = SEO_ARTICLES[slug]
        draft = build_editorial(page, "https://radarbds.vn" + page["path"], slug, make_visual=False)
        if draft["status"] != "ready":
            continue
        rows.append({"date": article_date, "slug": slug, "pillar": draft["pillar"], "topic": draft["metadata"]["topic"]})
    # rank_editorial_candidates drops any topic already used recently. That guard
    # is meant to stop repeating the *same angle*, not to starve the queue when a
    # whole pillar family shares one generic topic label. On starvation, rank by
    # pillar balance and recency instead of returning nothing.
    ranked = rank_editorial_candidates(rows, recent)
    if ranked:
        return ranked
    fallback = sorted(rows, key=lambda r: (pillar_seen[r["pillar"]], r["date"], r["slug"]))
    return fallback


def create_unposted_queue(posted: dict, *, preview: bool = False) -> Path:
    """Choose a new editorial angle with a real source, then verify and render."""
    for row in editorial_candidates(posted):
        try:
            return create_queue(row["slug"], style="data_post", preview=preview)
        except SystemExit as exc:
            # One dead/blocked article must not cause publishing stale content.
            log(f"Skip blocked editorial candidate {row['slug']}: {exc}")
    raise SystemExit("No source-qualified, non-repeating editorial candidate; no post made")


def queue_key(queue_path: Path) -> tuple[str, str, str]:
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    source = data.get("source", {})
    slug = str(source.get("slug") or queue_path.stem)
    article_date = str(source.get("article_date") or "unknown-date")
    key = f"{slug}:{article_date}"
    url = str(source.get("url") or "")
    return key, slug, url


def publish(queue_path: Path) -> dict:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    # Visual uploads + Facebook async publish can exceed 4 minutes. Keep the
    # wrapper timeout above the browser worker timeout so the worker can return
    # verification output instead of being killed after a successful post.
    cmd = [str(POST_SCRIPT), "--queue", str(queue_path), "--mode", "publish", "--yes", "--timeout", "420"]
    proc = subprocess.run(cmd, cwd=str(REPO), text=True, capture_output=True, timeout=500, check=False)
    record = {
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-3000:],
        "stderr_tail": proc.stderr[-3000:],
    }
    if proc.returncode != 0:
        raise SystemExit(
            "Facebook Page publish failed\n"
            f"STDOUT:\n{proc.stdout[-3000:]}\nSTDERR:\n{proc.stderr[-3000:]}"
        )
    wrapper_record = parse_post_wrapper_stdout(proc.stdout)
    browser_result = wrapper_record["browser_result"]
    record["post_url"] = browser_result["permalink"]
    record["browser_result"] = browser_result
    record["screenshot"] = wrapper_record.get("screenshot")
    return record


def main(argv: list[str] | None = None) -> int:
    state = load_state()
    posted = state.setdefault("posted", {})
    import argparse as _argparse
    ap = _argparse.ArgumentParser(description="Radar BDS Page Care auto-post")
    ap.add_argument("--preview", action="store_true", help="Build review-only preview artifacts; never touch the browser or the Page.")
    args = ap.parse_args(argv)
    if args.preview:
        os.chdir(REPO)
        queue_path = create_unposted_queue(posted, preview=True)
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        content = data.get("content") or {}
        editorial = data.get("editorial") or {}
        print("## @rb Facebook Page Care — PREVIEW (no publish)")
        print(f"- Pillar: {(editorial.get('metadata') or {}).get('pillar') or content.get('visual_style')}")
        print(f"- Queue: {queue_path}")
        print(f"- Source: {data.get('source', {}).get('url')} (HTTP {data.get('source', {}).get('http_status')}, ngày dữ liệu {data.get('source', {}).get('article_date')})")
        print(f"- Visual: {content.get('visual_path')}")
        print(f"- Self-comment: {content.get('self_comment')}")
        print("- Caption:")
        print(content.get("message"))
        return 0
    already_done, done_item = posted_today(posted)
    if already_done:
        post_url = done_item.get("post_url") or ((done_item.get("browser_result") or {}).get("permalink"))
        print("## @rb Daily Facebook Page Care")
        print("- KPI hôm nay: ĐẠT")
        print(f"- Published Page post: already posted today: {post_url}")
        if done_item.get("queue"):
            print(f"- Source queue/article: {done_item.get('queue')}")
        if done_item.get("visual"):
            print(f"- Visual: {done_item.get('visual')}")
        print("- Verification: posted_slugs.json has today's verified text + native visual + Facebook permalinks")
        return 0

    # Only touch the browser and queue directories when a publish is actually due.
    # A recovery rerun after today's KPI is already met must remain a safe no-op
    # even if the CDP service is temporarily unavailable.
    os.chdir(REPO)
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    ensure_browser()
    queue_path = create_unposted_queue(posted)
    key, slug, url = queue_key(queue_path)
    if key in posted:
        raise SystemExit(f"Internal dedupe error: selected already-posted queue {key}")
    log(f"Publishing social item: {key}")
    data = json.loads(queue_path.read_text(encoding="utf-8"))
    content = data.get("content") or {}
    result = publish(queue_path)
    browser_result = result.get("browser_result") or {}
    posted[key] = {
        "slug": slug,
        "url": url,
        "queue": str(queue_path),
        "style": content.get("style"),
        "visual_style": content.get("visual_style"),
        "editorial_pillar": (data.get("editorial") or {}).get("metadata", {}).get("pillar"),
        "editorial_topic": (data.get("editorial") or {}).get("metadata", {}).get("topic"),
        "posted_at": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds"),
        "post_url": result.get("post_url"),
        "photo_url": browser_result.get("photo_permalink"),
        "verified_text": bool(browser_result.get("verified_text")),
        "verified_visual": bool(browser_result.get("verified_visual")),
        "verified_comment": bool(browser_result.get("verified_comment")),
        "comment_needle": browser_result.get("comment_needle"),
        "screenshot": result.get("screenshot"),
        "browser_result": browser_result,
        "result": result,
    }
    save_state(state)
    print("## @rb Daily Facebook Page Care")
    print("- KPI hôm nay: ĐẠT")
    print(f"- Published Page post: {result.get('post_url')}")
    print(f"- Source queue/article: {queue_path} → {url}")
    print(f"- Visual: {content.get('visual_path') or content.get('image_path') or ''} · {content.get('visual_style') or 'legacy'}")
    print(f"- Caption style: {content.get('style')} · visual={content.get('visual_style')}")
    print(f"- Caption angle: {str(content.get('message') or '').splitlines()[0][:160]}")
    if browser_result.get("verified_comment"):
        print(f"- Self-comment: verified with Radar BDS link · {browser_result.get('comment_needle') or ''}")
    else:
        print(f"- Self-comment: ⚠️ chưa verify được; post vẫn đã lên Page · {browser_result.get('comment_warning') or browser_result.get('comment_needle') or ''}")
    print("- Verification: browser_result ok=true + verified_text=true + verified_visual=true + valid post/photo permalinks; self-comment is best-effort")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
