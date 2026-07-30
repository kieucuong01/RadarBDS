"""PostgreSQL repository for Facebook crawl broker profile configuration."""
from __future__ import annotations

from typing import Any, Callable

from db.connection import get_conn


def _normalize_profiles(profiles) -> list[dict]:
    from services.admin_quality import normalize_facebook_profiles

    return normalize_facebook_profiles(profiles)


def _row_dict(row: Any) -> dict:
    return dict(row.items()) if hasattr(row, "items") else dict(row)


def _row_value(row: Any | None, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if hasattr(row, "get"):
        return row.get(key, default)
    values = _row_dict(row)
    return values.get(key, default)


def _bool_value(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _profile_from_row(row: Any) -> dict:
    values = _row_dict(row)
    daily_limit = int(values.get("daily_limit") or 20)
    return {
        "city": str(values.get("city") or "").strip(),
        "url": str(values.get("url") or "").strip(),
        "broker_name": str(values.get("broker_name") or "").strip(),
        "tier": daily_limit,
        "daily_limit": daily_limit,
        "range_days": int(values.get("range_days") or 7),
        "crawl_every_days": int(values.get("crawl_every_days") or 1),
        "active": _bool_value(values.get("active"), True),
    }


def read_profile_config(
    *,
    conn_factory: Callable = get_conn,
) -> list[dict]:
    """Read Facebook crawl profile config from PostgreSQL."""
    with conn_factory() as conn:
        rows = conn.execute(
            """
            SELECT city, url, broker_name, daily_limit, range_days,
                   crawl_every_days, active
            FROM facebook_crawl_profiles
            ORDER BY active DESC, city, broker_name, url
            """
        ).fetchall()
    profiles = [_profile_from_row(row) for row in rows]
    return _normalize_profiles(profiles)


def write_profile_config(
    profiles: list[dict],
    *,
    conn_factory: Callable = get_conn,
    updated_by: str = "",
) -> list[dict]:
    """Replace the stored profile config with a normalized admin submission."""
    cleaned = _normalize_profiles(profiles)
    with conn_factory() as conn:
        conn.execute("DELETE FROM facebook_crawl_profiles")
        for profile in cleaned:
            conn.execute(
                """
                INSERT INTO facebook_crawl_profiles (
                    url, city, broker_name, daily_limit, range_days,
                    crawl_every_days, active, updated_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile["url"],
                    profile.get("city") or "",
                    profile.get("broker_name") or "",
                    int(profile.get("daily_limit") or profile.get("tier") or 20),
                    int(profile.get("range_days") or 7),
                    int(profile.get("crawl_every_days") or 1),
                    profile.get("active", True) is not False,
                    str(updated_by or "")[:200],
                ),
            )
    return cleaned
