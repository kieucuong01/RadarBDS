"""Local Apify token pool with masked admin output and monthly usage tracking."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4


TOKEN_PATH = Path(__file__).resolve().parent.parent / "data" / "apify_tokens.json"
DEFAULT_MONTHLY_QUOTA = 950
_LOCK = threading.Lock()


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _mask_token(token: str) -> str:
    if not token:
        return ""
    if len(token) <= 10:
        return token[:2] + "..." + token[-2:]
    return token[:8] + "..." + token[-6:]


def _read_raw() -> dict:
    if not TOKEN_PATH.exists():
        return {"tokens": []}
    try:
        data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"tokens": []}
    if isinstance(data, list):
        return {"tokens": data}
    if not isinstance(data, dict):
        return {"tokens": []}
    data.setdefault("tokens", [])
    return data


def _write_raw(data: dict) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _normalize_token(raw: dict, reset_month: bool = True) -> dict:
    current_month = _month_key()
    month = raw.get("month") or current_month
    used = int(raw.get("used_this_month") or 0)
    if reset_month and month != current_month:
        month = current_month
        used = 0
    quota = max(1, int(raw.get("monthly_quota") or DEFAULT_MONTHLY_QUOTA))
    token = (raw.get("token") or "").strip()
    return {
        "id": raw.get("id") or uuid4().hex[:12],
        "label": (raw.get("label") or "").strip() or f"Apify {_mask_token(token)}",
        "token": token,
        "monthly_quota": quota,
        "used_this_month": max(0, used),
        "month": month,
        "active": raw.get("active", True) is not False,
        "created_at": raw.get("created_at") or _now_iso(),
        "last_used_at": raw.get("last_used_at"),
        "last_error": raw.get("last_error"),
    }


def has_configured_tokens() -> bool:
    with _LOCK:
        tokens = [_normalize_token(t) for t in _read_raw().get("tokens", []) if isinstance(t, dict)]
        changed = tokens != _read_raw().get("tokens", [])
        if changed:
            _write_raw({"tokens": tokens})
    return any(t["active"] and t["token"] for t in tokens)


def list_tokens_public() -> list[dict]:
    with _LOCK:
        data = _read_raw()
        tokens = [_normalize_token(t) for t in data.get("tokens", []) if isinstance(t, dict)]
        _write_raw({"tokens": tokens})
    items = []
    for token in tokens:
        remaining = max(0, token["monthly_quota"] - token["used_this_month"])
        items.append({
            "id": token["id"],
            "label": token["label"],
            "token_mask": _mask_token(token["token"]),
            "monthly_quota": token["monthly_quota"],
            "used_this_month": token["used_this_month"],
            "remaining": remaining,
            "month": token["month"],
            "active": token["active"],
            "last_used_at": token.get("last_used_at"),
            "last_error": token.get("last_error"),
        })
    return items


def upsert_token(payload: dict) -> list[dict]:
    token_id = (payload.get("id") or "").strip()
    label = (payload.get("label") or "").strip()
    token_value = (payload.get("token") or "").strip()
    quota = max(1, int(payload.get("monthly_quota") or DEFAULT_MONTHLY_QUOTA))
    active = payload.get("active", True) is not False
    if not token_id and not token_value:
        raise ValueError("token_required")

    with _LOCK:
        data = _read_raw()
        tokens = [_normalize_token(t) for t in data.get("tokens", []) if isinstance(t, dict)]
        idx = next((i for i, t in enumerate(tokens) if t["id"] == token_id), None)
        if idx is None:
            if any(t["token"] == token_value for t in tokens):
                raise ValueError("duplicate_token")
            tokens.append(_normalize_token({
                "label": label,
                "token": token_value,
                "monthly_quota": quota,
                "active": active,
            }, reset_month=False))
        else:
            current = tokens[idx]
            if token_value:
                current["token"] = token_value
            current["label"] = label or current["label"]
            current["monthly_quota"] = quota
            current["active"] = active
            current["last_error"] = None
            tokens[idx] = _normalize_token(current, reset_month=False)
        _write_raw({"tokens": tokens})
    return list_tokens_public()


def delete_token(token_id: str) -> bool:
    with _LOCK:
        tokens = [_normalize_token(t) for t in _read_raw().get("tokens", []) if isinstance(t, dict)]
        kept = [t for t in tokens if t["id"] != token_id]
        _write_raw({"tokens": kept})
    return len(kept) != len(tokens)


def reset_token_usage(token_id: str) -> bool:
    with _LOCK:
        tokens = [_normalize_token(t) for t in _read_raw().get("tokens", []) if isinstance(t, dict)]
        changed = False
        for token in tokens:
            if token["id"] == token_id:
                token["used_this_month"] = 0
                token["month"] = _month_key()
                token["last_error"] = None
                changed = True
        _write_raw({"tokens": tokens})
    return changed


def acquire_token(required_posts: int = 1, exclude_ids: Optional[set[str]] = None) -> dict:
    exclude_ids = exclude_ids or set()
    required_posts = max(1, int(required_posts or 1))
    with _LOCK:
        data = _read_raw()
        tokens = [_normalize_token(t) for t in data.get("tokens", []) if isinstance(t, dict)]
        _write_raw({"tokens": tokens})

    candidates = []
    for token in tokens:
        remaining = token["monthly_quota"] - token["used_this_month"]
        if token["active"] and token["token"] and token["id"] not in exclude_ids and remaining > 0:
            candidates.append((remaining, token))
    if candidates:
        enough = [item for item in candidates if item[0] >= required_posts]
        chosen = max(enough or candidates, key=lambda item: item[0])[1]
        if chosen["monthly_quota"] - chosen["used_this_month"] < required_posts:
            raise RuntimeError("Tat ca APIFY_TOKEN khong du quota cho request hien tai.")
        return dict(chosen)

    env_token = (os.getenv("APIFY_TOKEN") or "").strip()
    if env_token and "env" not in exclude_ids:
        return {
            "id": "env",
            "label": "APIFY_TOKEN env",
            "token": env_token,
            "monthly_quota": 0,
            "used_this_month": 0,
            "month": _month_key(),
            "active": True,
        }
    raise RuntimeError("Khong co APIFY_TOKEN active. Them token trong Admin > Facebook Crawl.")


def record_usage(token_id: Optional[str], posts_used: int) -> None:
    if not token_id or token_id == "env":
        return
    posts_used = max(0, int(posts_used or 0))
    with _LOCK:
        tokens = [_normalize_token(t) for t in _read_raw().get("tokens", []) if isinstance(t, dict)]
        for token in tokens:
            if token["id"] == token_id:
                token["used_this_month"] += posts_used
                token["last_used_at"] = _now_iso()
                if token["used_this_month"] >= token["monthly_quota"]:
                    token["used_this_month"] = token["monthly_quota"]
                    token["active"] = False
                    token["last_error"] = "monthly_quota_reached"
                else:
                    token["last_error"] = None
        _write_raw({"tokens": tokens})


def mark_error(token_id: Optional[str], message: str) -> None:
    if not token_id or token_id == "env":
        return
    with _LOCK:
        tokens = [_normalize_token(t) for t in _read_raw().get("tokens", []) if isinstance(t, dict)]
        for token in tokens:
            if token["id"] == token_id:
                token["last_error"] = str(message)[:240]
        _write_raw({"tokens": tokens})


def mark_limit_exhausted(token_id: Optional[str], message: str) -> None:
    if not token_id or token_id == "env":
        return
    with _LOCK:
        tokens = [_normalize_token(t) for t in _read_raw().get("tokens", []) if isinstance(t, dict)]
        for token in tokens:
            if token["id"] == token_id:
                token["used_this_month"] = token["monthly_quota"]
                token["active"] = False
                token["last_used_at"] = _now_iso()
                token["last_error"] = (str(message) or "monthly_limit_reached")[:240]
        _write_raw({"tokens": tokens})
