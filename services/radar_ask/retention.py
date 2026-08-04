"""Bounded, privacy-safe Radar Ask retention operations."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .repository import RadarAskRepository


logger = logging.getLogger(__name__)
BANGKOK = ZoneInfo("Asia/Bangkok")
CONTENT_RETENTION_DAYS = 90
USAGE_RETENTION_MONTHS = 13


def _bangkok_now() -> datetime:
    return datetime.now(BANGKOK)


def _subtract_months(value: datetime, months: int) -> date:
    ordinal = value.year * 12 + value.month - 1 - months
    return date(ordinal // 12, ordinal % 12 + 1, 1)


class RadarAskRetentionService:
    """Retention coordinator with one timezone-aware, injectable clock."""

    def __init__(
        self,
        *,
        repository: RadarAskRepository | None = None,
        clock: Callable[[], datetime] = _bangkok_now,
    ) -> None:
        self.repository = repository or RadarAskRepository()
        self.clock = clock

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Radar Ask retention clock must be timezone-aware")
        return value.astimezone(BANGKOK)

    def purge_expired_content(self, *, dry_run: bool = False) -> dict[str, int]:
        cutoff = self._now() - timedelta(days=CONTENT_RETENTION_DAYS)
        if dry_run:
            counts = self.repository.count_expired_content(cutoff=cutoff)
            result = {**counts, "batches": 0}
            logger.info("Radar Ask retention dry-run content cutoff=%s counts=%s", cutoff.isoformat(), result)
            return result

        totals = {"sessions": 0, "runs": 0, "messages": 0, "batches": 0}
        while batch := self.repository.purge_expired_content_batch(cutoff=cutoff):
            for key in ("sessions", "runs", "messages"):
                totals[key] += batch[key]
            totals["batches"] += 1
        logger.info("Radar Ask retention content cutoff=%s counts=%s", cutoff.isoformat(), totals)
        return totals

    def purge_expired_usage(self, *, dry_run: bool = False) -> dict[str, int]:
        # Keep exactly the current calendar month plus the preceding twelve
        # month buckets.  With a 13-month policy, August 2026 keeps
        # August 2025 through August 2026 and purges July 2025 and earlier.
        cutoff_month = _subtract_months(self._now(), USAGE_RETENTION_MONTHS - 1)
        if dry_run:
            result = self.repository.count_expired_usage(cutoff_month=cutoff_month)
            logger.info(
                "Radar Ask retention dry-run usage cutoff_month=%s counts=%s",
                cutoff_month.isoformat(),
                result,
            )
            return result

        totals = {"usage": 0, "attempts": 0, "batches": 0}
        while batch := self.repository.purge_expired_usage_batch(cutoff_month=cutoff_month):
            for key in ("usage", "attempts"):
                totals[key] += batch[key]
            totals["batches"] += 1
        logger.info(
            "Radar Ask retention usage cutoff_month=%s counts=%s",
            cutoff_month.isoformat(),
            totals,
        )
        return totals


def purge_expired_content(*, dry_run: bool = False, clock: Callable[[], datetime] = _bangkok_now) -> dict[str, int]:
    return RadarAskRetentionService(clock=clock).purge_expired_content(dry_run=dry_run)


def purge_expired_usage(*, dry_run: bool = False, clock: Callable[[], datetime] = _bangkok_now) -> dict[str, int]:
    return RadarAskRetentionService(clock=clock).purge_expired_usage(dry_run=dry_run)


def cmd_radar_ask_retention(args=None) -> None:
    """CLI adapter: it only runs local retention SQL, never a worker or provider."""
    dry_run = bool(getattr(args, "dry_run", False))
    service = RadarAskRetentionService()
    content = service.purge_expired_content(dry_run=dry_run)
    usage = service.purge_expired_usage(dry_run=dry_run)
    mode = "dry-run" if dry_run else "applied"
    print(f"Radar Ask retention {mode}: content={content} usage={usage}")


__all__ = [
    "RadarAskRetentionService",
    "cmd_radar_ask_retention",
    "purge_expired_content",
    "purge_expired_usage",
]
