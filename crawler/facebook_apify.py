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

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from db import facebook_profiles as db_facebook_profiles

# Actor mặc định — có thể override qua env APIFY_ACTOR
DEFAULT_ACTOR = "apify/facebook-posts-scraper"

# Số bài fetch mỗi profile
MAX_POSTS_FULL = 100   # full mode: lần đầu cào
INCR_FETCH     = 30    # incremental: fetch rồi lọc ra bài trong 72h (3 ngày = chu kỳ scheduler)
INCR_HOURS     = 72    # phải khớp với --every N của schedule-setup

# Danh sách profiles mặc định
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


def _coerce_crawl_every_days(raw) -> int:
    try:
        cadence = int(raw)
    except (TypeError, ValueError):
        return 1
    return cadence if cadence in {1, 3, 7} else 1


def profile_due_on(profile: dict, on_date: date | None = None) -> bool:
    """Spread 3/7-day profiles across stable calendar buckets by URL."""
    cadence = _coerce_crawl_every_days(profile.get("crawl_every_days"))
    if cadence == 1:
        return True
    day = on_date or datetime.now(timezone.utc).date()
    url = (profile.get("url") or "").strip().encode("utf-8")
    bucket = int.from_bytes(hashlib.sha256(url).digest()[:4], "big") % cadence
    return day.toordinal() % cadence == bucket


def profiles_due_on(profiles: list[dict], on_date: date | None = None) -> list[dict]:
    return [profile for profile in profiles if profile_due_on(profile, on_date)]


def _is_apify_limit_error(message: str) -> bool:
    text = (message or "").lower()
    limit_markers = [
        "402",
        "payment",
        "monthly",
        "quota",
        "usage limit",
        "remaining usage",
        "limit exceeded",
        "exceed your remaining",
        "not enough credits",
        "insufficient credits",
        "credit limit",
        "paid plan",
        "billing/subscription",
        "upgrade",
    ]
    return any(marker in text for marker in limit_markers)


def load_profiles(path: str | Path | None = None, area_filter: Optional[str] = None) -> list[dict]:
    """Đọc danh sách profiles từ JSON file. Trả về list of dicts.

    Schema mới:
      {"city": [{"url": "...", "broker_name": "...", "tier": <int>}]}
    Backward compat: tier string 'high'/'medium'/'low' → tự convert sang int.
    """
    if path is None:
        from services.admin_quality import normalize_facebook_profile_url

        db_profiles = db_facebook_profiles.read_profile_config()
        profiles = []
        for item in db_profiles:
            if item.get("active", True) is False:
                continue
            area = (item.get("city") or "").strip() or None
            if area_filter and (area or "").lower() != area_filter.lower():
                continue
            profiles.append({
                "url": normalize_facebook_profile_url(item.get("url")),
                "tier": _coerce_tier(item.get("daily_limit", item.get("tier"))),
                "broker_name": (item.get("broker_name") or "").strip() or None,
                "default_area": area,
                "crawl_every_days": _coerce_crawl_every_days(item.get("crawl_every_days")),
            })
        profiles = [profile for profile in profiles if profile["url"]]
        return profiles
        return profiles

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
                "crawl_every_days": 1,
            }
        if isinstance(item, dict):
            if item.get("active", True) is False:
                return None
            return {
                "url": (item.get("url") or "").strip(),
                "tier": _coerce_tier(item.get("daily_limit", item.get("tier"))),
                "broker_name": (item.get("broker_name") or "").strip() or None,
                "default_area": area,
                "crawl_every_days": _coerce_crawl_every_days(item.get("crawl_every_days")),
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
        from crawler.apify_token_pool import has_configured_tokens

        self.token = token or ""
        self._use_token_pool = token is None and has_configured_tokens()
        if not self._use_token_pool:
            self.token = self.token or os.getenv("APIFY_TOKEN") or ""
        self.actor = actor or os.getenv("APIFY_ACTOR") or DEFAULT_ACTOR
        if not self.token and not self._use_token_pool:
            raise RuntimeError(
                "Thieu APIFY_TOKEN. Them vao .env:\n  APIFY_TOKEN=apify_api_xxxxxx\n"
                "Dang ky tai: https://apify.com/"
            )
        # Import lazy de khong loi import neu chua cai
        from apify_client import ApifyClient  # noqa: PLC0415
        self._client_cls = ApifyClient
        self._client = None if self._use_token_pool else ApifyClient(self.token)

    @staticmethod
    def _token_remaining(token_rec: dict) -> int:
        return max(
            0,
            int(token_rec.get("monthly_quota") or 0)
            - int(token_rec.get("used_this_month") or 0),
        )

    @staticmethod
    def _new_run_report() -> dict:
        return {
            "partial": False,
            "messages": [],
            "completed_profiles": 0,
            "unattempted_profiles": 0,
            "actor_runs": 0,
        }

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
        self.last_run_report = self._new_run_report()
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

        unusable_token_ids: set[str] = set()

        for per_profile, batch_profiles in by_limit.items():
            pending = list(batch_profiles)

            while pending:
                if not self._use_token_pool:
                    chunk = pending
                    token_rec = None
                else:
                    from crawler.apify_token_pool import acquire_token

                    try:
                        token_rec = acquire_token(
                            required_posts=per_profile,
                            exclude_ids=unusable_token_ids,
                        )
                    except RuntimeError:
                        unattempted = len(pending)
                        event = (
                            f"limit={per_profile}: {unattempted} profile(s) unattempted "
                            "because no token has enough quota"
                        )
                        self.last_run_report["partial"] = True
                        self.last_run_report["unattempted_profiles"] += unattempted
                        self.last_run_report["messages"].append(event)
                        print(f"[facebook-apify] {event}")
                        break
                    if token_rec["id"] == "env":
                        chunk_size = len(pending)
                    else:
                        chunk_size = min(
                            len(pending),
                            self._token_remaining(token_rec) // per_profile,
                        )
                    chunk = pending[:chunk_size]

                expected_total = per_profile * len(chunk)
                run_input = {
                    "startUrls": [{"url": profile["url"]} for profile in chunk],
                    "resultsLimit": per_profile,
                }
                token_label = token_rec["label"] if token_rec else "APIFY_TOKEN"
                print(
                    f"[facebook-apify] Sub-batch limit={per_profile}/profile | "
                    f"profiles={len(chunk)} | expected_max={expected_total} | "
                    f"token={token_label} | mode={mode}"
                )

                try:
                    items = self._run_actor(
                        run_input,
                        required_posts=expected_total,
                        token_rec=token_rec,
                    )
                except Exception as exc:
                    msg = str(exc)
                    if token_rec and _is_apify_limit_error(msg):
                        unusable_token_ids.add(token_rec["id"])
                        event = (
                            f"Token {token_rec['label']} exhausted by provider; "
                            "remaining=0; rotating"
                        )
                        self.last_run_report["messages"].append(event)
                        print(f"[facebook-apify] {event}")
                        continue
                    if "401" in msg or "Unauthorized" in msg:
                        if token_rec:
                            unusable_token_ids.add(token_rec["id"])
                            event = (
                                f"Token {token_rec['label']} rejected authentication; rotating"
                            )
                            self.last_run_report["messages"].append(event)
                            print(f"[facebook-apify] {event}")
                            continue
                        raise RuntimeError("APIFY_TOKEN khong hop le. Kiem tra lai.") from exc
                    if "402" in msg or "Payment" in msg:
                        raise RuntimeError("Het Apify credits. Nap them hoac giam --limit.") from exc
                    raise

                print(
                    f"[facebook-apify] Nhan duoc {len(items)} raw items "
                    f"(limit={per_profile}/profile, expected_max={expected_total})."
                )

                limited_items = self._limit_items_per_profile(items, chunk, per_profile)
                if len(limited_items) < len(items):
                    print(
                        f"[facebook-apify] Clamp actor overfetch: {len(items)} -> {len(limited_items)} "
                        f"items theo limit/profile."
                    )

                for item, profile in limited_items:
                    post = self._adapt(item)
                    if post:
                        if profile:
                            post["default_area"] = profile.get("default_area")
                            post["broker_name"] = profile.get("broker_name")
                        adapted_all.append(post)

                pending = pending[len(chunk):]
                self.last_run_report["completed_profiles"] += len(chunk)
                self.last_run_report["actor_runs"] += 1

        # Incremental filter
        if mode == "incremental":
            cutoff = datetime.now(timezone.utc) - timedelta(hours=INCR_HOURS)
            before = len(adapted_all)
            adapted_all = [p for p in adapted_all if self._is_within_24h(p["date_raw"], cutoff)]
            print(
                f"[facebook-apify] Incremental filter: {before} -> {len(adapted_all)} bai ({INCR_HOURS}h)"
            )

        return adapted_all

    def _run_actor(
        self,
        run_input: dict,
        required_posts: int,
        token_rec: Optional[dict] = None,
    ) -> list[dict]:
        if not self._use_token_pool:
            run = self._client.actor(self.actor).call(run_input=run_input)
            return list(self._client.dataset(run["defaultDatasetId"]).iterate_items())

        from crawler.apify_token_pool import (
            acquire_token,
            mark_error,
            mark_limit_exhausted,
            record_usage,
        )

        if token_rec is None:
            excluded: set[str] = set()
            last_error = None
            for _ in range(5):
                selected = acquire_token(
                    required_posts=required_posts,
                    exclude_ids=excluded,
                )
                try:
                    return self._run_actor(
                        run_input,
                        required_posts=required_posts,
                        token_rec=selected,
                    )
                except Exception as exc:
                    last_error = exc
                    msg = str(exc)
                    if _is_apify_limit_error(msg) or "401" in msg or "Unauthorized" in msg:
                        excluded.add(selected["id"])
                        continue
                    raise
            raise last_error or RuntimeError("Khong chon duoc APIFY_TOKEN kha dung.")

        client = self._client_cls(token_rec["token"])
        try:
            print(f"[facebook-apify] Dung token {token_rec['label']} cho limit={required_posts}")
            run = client.actor(self.actor).call(run_input=run_input)
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            record_usage(token_rec["id"], len(items))
            return items
        except Exception as exc:
            msg = str(exc)
            if _is_apify_limit_error(msg):
                mark_limit_exhausted(token_rec["id"], msg)
            else:
                mark_error(token_rec["id"], msg)
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _profile_key(url: str) -> str:
        return (url or "").strip().rstrip("/").lower()

    @classmethod
    def _match_profile(cls, input_url: str, profiles: list[dict]) -> Optional[dict]:
        key = cls._profile_key(input_url)
        if not key:
            return None
        for profile in profiles:
            profile_key = cls._profile_key(profile.get("url") or "")
            if profile_key and (profile_key in key or key in profile_key):
                return profile
        return None

    @classmethod
    def _limit_items_per_profile(
        cls,
        items: list[dict],
        profiles: list[dict],
        per_profile: int,
    ) -> list[tuple[dict, Optional[dict]]]:
        counts: dict[str, int] = {}
        limited: list[tuple[dict, Optional[dict]]] = []
        unknown_budget = per_profile * len(profiles)

        for item in items:
            profile = cls._match_profile(str(item.get("inputUrl") or ""), profiles)
            if profile:
                key = cls._profile_key(profile.get("url") or "")
                current = counts.get(key, 0)
                if current >= per_profile:
                    continue
                counts[key] = current + 1
                limited.append((item, profile))
            elif unknown_budget > 0:
                # Keep a bounded fallback for actor outputs missing inputUrl.
                unknown_budget -= 1
                limited.append((item, None))

        return limited

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
