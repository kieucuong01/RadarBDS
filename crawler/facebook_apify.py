"""
FacebookApifyCrawler — crawl posts Facebook qua Apify actor.

Actor mặc định: apify/facebook-posts-scraper
- Không cần browser, không cần cookies
- Full mode  : lấy tối đa MAX_POSTS_FULL bài / profile (lần đầu cào)
- Incremental: lấy INCR_FETCH bài rồi lọc chỉ giữ bài trong 24h qua

Output mỗi post (tương thích build_record trong facebook_chrome.py):
  url, post_id, text, date_raw, seller_name, profile_url, imgs
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Actor mặc định — có thể override qua env APIFY_ACTOR
DEFAULT_ACTOR = "apify/facebook-posts-scraper"

# Số bài fetch mỗi profile
MAX_POSTS_FULL = 100   # full mode: lần đầu cào
INCR_FETCH     = 30    # incremental: fetch rồi lọc ra bài trong 72h (3 ngày = chu kỳ scheduler)
INCR_HOURS     = 72    # phải khớp với --every N của schedule-setup

# Danh sách profiles mặc định
PROFILES_FILE = Path(__file__).parent.parent / "data" / "facebook_profiles.json"


_TIER_STR_MAP = {"high": 40, "medium": 20, "low": 10}
_DEFAULT_TIER = 20


def _coerce_tier(raw) -> int:
    """tier có thể là int (số bài fetch) hoặc string cũ ('high'/'medium'/'low')."""
    if isinstance(raw, int):
        return raw if raw > 0 else _DEFAULT_TIER
    if isinstance(raw, str):
        key = raw.strip().lower()
        if key in _TIER_STR_MAP:
            print(f"[facebook] WARN: tier='{raw}' (legacy string) -> int={_TIER_STR_MAP[key]}. Hãy update JSON.")
            return _TIER_STR_MAP[key]
        try:
            n = int(key)
            return n if n > 0 else _DEFAULT_TIER
        except ValueError:
            print(f"[facebook] WARN: tier='{raw}' không parse được -> default={_DEFAULT_TIER}")
            return _DEFAULT_TIER
    return _DEFAULT_TIER


def load_profiles(path: str | Path = PROFILES_FILE, area_filter: Optional[str] = None) -> list[dict]:
    """Đọc danh sách profiles từ JSON file. Trả về list of dicts.

    Schema mới:
      {"city": [{"url": "...", "broker_name": "...", "tier": <int>}]}
    Backward compat: tier string 'high'/'medium'/'low' → tự convert sang int.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Không tìm thấy file profiles: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))

    def _build(item, area):
        if isinstance(item, str):
            return {
                "url": item.strip(),
                "tier": _DEFAULT_TIER,
                "broker_name": None,
                "default_area": area,
            }
        if isinstance(item, dict):
            return {
                "url": (item.get("url") or "").strip(),
                "tier": _coerce_tier(item.get("tier")),
                "broker_name": (item.get("broker_name") or "").strip() or None,
                "default_area": area,
            }
        return None

    profiles = []
    if isinstance(data, list):
        for item in data:
            rec = _build(item, None)
            if rec:
                profiles.append(rec)
    elif isinstance(data, dict):
        for area_name, items in data.items():
            if area_filter and area_filter.lower() != area_name.lower():
                continue
            for item in items:
                rec = _build(item, area_name)
                if rec:
                    profiles.append(rec)
    return [p for p in profiles if p["url"]]


class FacebookApifyCrawler:
    """Crawl Facebook posts dùng Apify actor API."""

    def __init__(self, token: Optional[str] = None, actor: Optional[str] = None):
        self.token = token or os.getenv("APIFY_TOKEN") or ""
        self.actor = actor or os.getenv("APIFY_ACTOR") or DEFAULT_ACTOR
        if not self.token:
            raise RuntimeError(
                "Thieu APIFY_TOKEN. Them vao .env:\n  APIFY_TOKEN=apify_api_xxxxxx\n"
                "Dang ky tai: https://apify.com/"
            )
        # Import lazy de khong loi import neu chua cai
        from apify_client import ApifyClient  # noqa: PLC0415
        self._client = ApifyClient(self.token)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def crawl_all(
        self,
        profiles: list[dict],
        mode: str = "full",
        limit_override: Optional[int] = None,
    ) -> list[dict]:
        """
        Crawl nhieu profiles trong cac batch chia theo tier.
        """
        if not profiles:
            print("[facebook-apify] Khong co profile nao de crawl.")
            return []

        from collections import defaultdict

        # Quy per_profile cuối cùng cho từng profile
        def _per_profile(p: dict) -> int:
            if limit_override:
                return int(limit_override)
            base = int(p.get("tier") or _DEFAULT_TIER)
            if mode == "full":
                return max(base, MAX_POSTS_FULL)
            return base

        # Gom profiles có cùng per_profile vào một batch (giảm số Apify calls)
        by_limit = defaultdict(list)
        for p in profiles:
            by_limit[_per_profile(p)].append(p)

        adapted_all = []

        for per_profile, batch_profiles in by_limit.items():
            total_limit = per_profile * len(batch_profiles)
            urls = [p["url"] for p in batch_profiles]
            run_input = {
                "startUrls": [{"url": u} for u in urls],
                "resultsLimit": total_limit,
            }

            print(
                f"[facebook-apify] Batch limit={per_profile}/profile | "
                f"{len(urls)} profiles | total={total_limit} | mode={mode}"
            )

            try:
                run = self._client.actor(self.actor).call(run_input=run_input)
            except Exception as exc:
                msg = str(exc)
                if "401" in msg or "Unauthorized" in msg:
                    raise RuntimeError("APIFY_TOKEN khong hop le. Kiem tra lai.") from exc
                if "402" in msg or "Payment" in msg:
                    raise RuntimeError("Het Apify credits. Nap them hoac giam --limit.") from exc
                raise

            items = list(self._client.dataset(run["defaultDatasetId"]).iterate_items())
            print(f"[facebook-apify] Nhan duoc {len(items)} raw items (limit={per_profile}/profile).")

            for item in items:
                post = self._adapt(item)
                if post:
                    input_url = item.get("inputUrl", "")
                    for p in batch_profiles:
                        if input_url and p["url"] in input_url:
                            post["default_area"] = p.get("default_area")
                            post["broker_name"] = p.get("broker_name")
                            break
                    adapted_all.append(post)

        # Incremental filter
        if mode == "incremental":
            cutoff = datetime.now(timezone.utc) - timedelta(hours=INCR_HOURS)
            before = len(adapted_all)
            adapted_all = [p for p in adapted_all if self._is_within_24h(p["date_raw"], cutoff)]
            print(
                f"[facebook-apify] Incremental filter: {before} -> {len(adapted_all)} bai ({INCR_HOURS}h)"
            )

        return adapted_all

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _adapt(self, item: dict) -> Optional[dict]:
        """
        Chuyen Apify output -> format chuan cua pipeline.
        Tra ve None neu khong lay duoc text.

        Dict tra ve co them key "_apify_raw" chua toan bo raw item tu Apify —
        dung de luu vao raw_json trong DB (khong bi mat data goc).
        """
        text = (
            item.get("text")          # apify/facebook-posts-scraper dung 'text'
            or item.get("message")    # fallback ten cu
            or item.get("postText")
            or ""
        ).strip()

        if not text:
            return None  # bo qua bai khong co text (anh/video khong caption)

        url = (
            item.get("url")
            or item.get("facebookUrl")
            or item.get("postUrl")
            or item.get("link")
            or ""
        ).strip()

        post_id = (
            item.get("postId")
            or item.get("facebookId")
            or item.get("id")
            or ""
        )

        # Timestamp: Unix int hoac ISO string
        ts = (
            item.get("timestamp")    # Apify tra ve Unix int
            or item.get("time")
            or item.get("createdTime")
            or item.get("date")
            or ""
        )
        if isinstance(ts, int):
            from datetime import datetime, timezone as _tz
            date_raw = datetime.fromtimestamp(ts, tz=_tz.utc).isoformat()[:19]
        elif ts:
            date_raw = str(ts)[:19]
        else:
            date_raw = ""

        # Author/seller — Apify dung 'user' hoac 'pageName'
        user = item.get("user") or {}
        seller_name = (
            (user.get("name") if isinstance(user, dict) else str(user))
            or item.get("pageName")
            or item.get("profileName")
            or ""
        )
        profile_url = (
            (user.get("url") or user.get("link") if isinstance(user, dict) else "")
            or item.get("inputUrl")
            or ""
        )

        # Images — extract tu media[] (co ca anh va video)
        imgs = self._extract_images(item.get("media") or [])

        return {
            "url":         url,
            "post_id":     str(post_id),
            "text":        text,
            "date_raw":    date_raw,
            "seller_name": seller_name,
            "profile_url": profile_url,
            "imgs":        imgs,
            # Luu toan bo raw Apify item de khong mat data goc
            "_apify_raw":  item,
        }

    @staticmethod
    def _extract_images(media: list) -> list[str]:
        """
        Extract danh sach URL anh tu Apify media[].
        Uu tien photo_image.uri (full size), fallback thumbnail.
        Loai bo video thumbnails neu co the.
        """
        urls = []
        for m in media:
            if not isinstance(m, dict):
                continue
            typename = m.get("__typename", "") or m.get("__isMedia", "")
            # Lay full-size url neu la anh
            photo_img = m.get("photo_image") or {}
            full_uri  = photo_img.get("uri") if isinstance(photo_img, dict) else ""
            thumb     = m.get("thumbnail") or ""
            url       = (full_uri or thumb or "").strip()
            if url:
                urls.append(url)
        return urls

    @staticmethod
    def _is_within_24h(date_raw: str, cutoff: datetime) -> bool:
        """
        Tra True neu date_raw >= cutoff.
        date_raw: ISO string "2026-04-25T08:30:00" hoac "2026-04-25"
        Neu khong parse duoc -> giu lai (an toan hon la bo mat bai).
        """
        if not date_raw:
            return True
        try:
            # Them UTC neu khong co timezone
            s = date_raw.replace("Z", "+00:00")
            if "+" not in s and len(s) <= 10:
                s += "T00:00:00+00:00"
            elif "+" not in s:
                s += "+00:00"
            dt = datetime.fromisoformat(s)
            return dt >= cutoff
        except Exception:
            return True
