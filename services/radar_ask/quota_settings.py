"""Admin-configurable daily question limits for Radar Ask."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.connection import PgConnection, get_conn


DEFAULT_FREE_DAILY_LIMIT = 5
DEFAULT_VIP_DAILY_LIMIT = 20
MAX_CONFIGURABLE_DAILY_LIMIT = 1000
CONFIGURABLE_TIERS = frozenset({"free", "vip"})


class RadarAskQuotaSettingsError(ValueError):
    """Raised when an admin submits an unsafe quota setting."""


@dataclass(frozen=True)
class RadarAskQuotaSettings:
    free_daily_limit: int = DEFAULT_FREE_DAILY_LIMIT
    vip_daily_limit: int = DEFAULT_VIP_DAILY_LIMIT

    def limit_for_tier(self, tier: str) -> int | None:
        if tier == "admin":
            return None
        if tier == "free":
            return self.free_daily_limit
        if tier == "vip":
            return self.vip_daily_limit
        raise ValueError("unknown Radar Ask tier")

    def as_payload(self) -> dict[str, Any]:
        return {
            "daily_limits": {
                "free": self.free_daily_limit,
                "vip": self.vip_daily_limit,
            },
            "admin_unlimited": True,
            "max_daily_limit": MAX_CONFIGURABLE_DAILY_LIMIT,
        }


def _parse_limit(value: Any, *, tier: str) -> int:
    if isinstance(value, bool):
        raise RadarAskQuotaSettingsError("invalid_daily_limit")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RadarAskQuotaSettingsError("invalid_daily_limit") from exc
    if parsed != value and not (isinstance(value, str) and value.strip() == str(parsed)):
        raise RadarAskQuotaSettingsError("invalid_daily_limit")
    if not 0 <= parsed <= MAX_CONFIGURABLE_DAILY_LIMIT:
        raise RadarAskQuotaSettingsError("invalid_daily_limit")
    if tier not in CONFIGURABLE_TIERS:
        raise RadarAskQuotaSettingsError("invalid_daily_limit")
    return parsed


def _settings_from_rows(rows: list[Any]) -> RadarAskQuotaSettings:
    limits = {
        "free": DEFAULT_FREE_DAILY_LIMIT,
        "vip": DEFAULT_VIP_DAILY_LIMIT,
    }
    for row in rows:
        tier = str(row["tier"])
        if tier in CONFIGURABLE_TIERS:
            limits[tier] = _parse_limit(row["daily_limit"], tier=tier)
    return RadarAskQuotaSettings(
        free_daily_limit=limits["free"],
        vip_daily_limit=limits["vip"],
    )


def ensure_radar_ask_quota_settings_table(conn: PgConnection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS radar_ask_quota_settings (
            tier        TEXT PRIMARY KEY CHECK (tier IN ('free', 'vip')),
            daily_limit INTEGER NOT NULL CHECK (daily_limit BETWEEN 0 AND 1000),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_by TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        INSERT INTO radar_ask_quota_settings (tier, daily_limit, updated_by)
        VALUES ('free', 5, 'schema-default'), ('vip', 20, 'schema-default')
        ON CONFLICT (tier) DO NOTHING
        """
    )


def load_radar_ask_quota_settings(conn: PgConnection | None = None) -> RadarAskQuotaSettings:
    """Load quota settings, falling back to product defaults if rows are absent."""
    if conn is None:
        with get_conn() as owned_conn:
            return load_radar_ask_quota_settings(owned_conn)
    ensure_radar_ask_quota_settings_table(conn)
    rows = conn.execute(
        """
        SELECT tier, daily_limit
        FROM radar_ask_quota_settings
        WHERE tier IN ('free', 'vip')
        """
    ).fetchall()
    return _settings_from_rows(rows)


def save_radar_ask_quota_settings(
    *,
    free_daily_limit: Any,
    vip_daily_limit: Any,
    updated_by: str = "",
    conn: PgConnection | None = None,
) -> RadarAskQuotaSettings:
    """Persist Free/VIP daily limits. Use 0 to lock a tier; admin is unlimited."""
    free_limit = _parse_limit(free_daily_limit, tier="free")
    vip_limit = _parse_limit(vip_daily_limit, tier="vip")
    actor = str(updated_by or "")[:120]
    if conn is None:
        with get_conn() as owned_conn:
            return save_radar_ask_quota_settings(
                free_daily_limit=free_limit,
                vip_daily_limit=vip_limit,
                updated_by=actor,
                conn=owned_conn,
            )
    ensure_radar_ask_quota_settings_table(conn)
    for tier, limit in (("free", free_limit), ("vip", vip_limit)):
        conn.execute(
            """
            INSERT INTO radar_ask_quota_settings (tier, daily_limit, updated_by)
            VALUES (?, ?, ?)
            ON CONFLICT (tier) DO UPDATE
            SET daily_limit=EXCLUDED.daily_limit,
                updated_by=EXCLUDED.updated_by,
                updated_at=NOW()
            """,
            (tier, limit, actor),
        )
    return RadarAskQuotaSettings(
        free_daily_limit=free_limit,
        vip_daily_limit=vip_limit,
    )


__all__ = [
    "CONFIGURABLE_TIERS",
    "DEFAULT_FREE_DAILY_LIMIT",
    "DEFAULT_VIP_DAILY_LIMIT",
    "MAX_CONFIGURABLE_DAILY_LIMIT",
    "RadarAskQuotaSettings",
    "RadarAskQuotaSettingsError",
    "ensure_radar_ask_quota_settings_table",
    "load_radar_ask_quota_settings",
    "save_radar_ask_quota_settings",
]
