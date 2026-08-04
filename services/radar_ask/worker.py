"""Bounded PostgreSQL worker for queued Radar Ask Deep research runs."""
from __future__ import annotations

import logging
import os
import signal
import socket
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import datetime, timezone
from threading import Event
from time import monotonic
from typing import Callable
from uuid import uuid4

from .burst import get_burst_limiter
from .config import RadarAskSettings
from .contracts import ProviderUsage
from .limits import RadarAskLimitService
from .orchestrator import OrchestratorDependencies, execute_leased_run
from .provider import DeepSeekProvider
from .registry import DEFAULT_TOOL_REGISTRY
from .repository import InvalidRunTransition, RadarAskRepository
from .routing import route_question


LOGGER = logging.getLogger(__name__)
DEFAULT_LEASE_SECONDS = 90
DEFAULT_POLL_SECONDS = 1.0


class RadarAskWorkerDisabled(RuntimeError):
    """Raised when the worker is started while Radar Ask is feature-off."""


def _default_worker_id() -> str:
    host = socket.gethostname().strip()[:48] or "radar"
    return f"{host}:{os.getpid()}:{uuid4().hex[:12]}"


def build_worker_dependencies(
    settings: RadarAskSettings | None = None,
) -> OrchestratorDependencies:
    """Build isolated worker dependencies with the Deep 60-second HTTP timeout."""
    active = settings or RadarAskSettings.from_env()
    provider_settings = replace(
        active,
        provider_timeout_seconds=active.deep_timeout_seconds,
    )
    return OrchestratorDependencies(
        settings=active,
        repository=RadarAskRepository(),
        limits=RadarAskLimitService(settings=active),
        burst=get_burst_limiter(),
        router=route_question,
        registry=DEFAULT_TOOL_REGISTRY,
        provider=DeepSeekProvider(settings=provider_settings),
        clock=lambda: datetime.now(timezone.utc),
    )


class RadarAskWorker:
    """Lease Deep runs and execute at a bounded process-level concurrency."""

    def __init__(
        self,
        *,
        dependencies: OrchestratorDependencies,
        worker_id: str | None = None,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        execute_fn: Callable[..., object] = execute_leased_run,
        monotonic_fn: Callable[[], float] = monotonic,
    ):
        if not 1 <= int(lease_seconds) <= 300:
            raise ValueError("lease_seconds must be between 1 and 300")
        if not 0.01 <= float(poll_seconds) <= 60:
            raise ValueError("poll_seconds must be between 0.01 and 60")
        self.dependencies = dependencies
        self.worker_id = worker_id or _default_worker_id()
        self.lease_seconds = int(lease_seconds)
        self.poll_seconds = float(poll_seconds)
        self.execute_fn = execute_fn
        self._monotonic = monotonic_fn
        self._stop = Event()

    def request_stop(self, *_args) -> None:
        """Stop new leasing; already leased work is drained before return."""
        self._stop.set()

    def _require_enabled(self) -> None:
        if not self.dependencies.settings.enabled:
            raise RadarAskWorkerDisabled("Radar Ask worker refuses while feature is disabled")

    def _execute_owned(
        self,
        run,
        *,
        deadline: float | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> object | None:
        try:
            return self.execute_fn(
                run,
                worker_id=self.worker_id,
                dependencies=self.dependencies,
                lease_seconds=self.lease_seconds,
                deadline=deadline,
                cancelled=cancelled,
                monotonic_fn=self._monotonic,
            )
        except InvalidRunTransition:
            LOGGER.warning("Radar Ask lease ownership changed for run %s", run.id)
            return None
        except Exception:
            LOGGER.exception("Radar Ask Deep execution failed for run %s", run.id)
            try:
                return self.dependencies.repository.fail_leased_run(
                    run.id,
                    worker_id=self.worker_id,
                    outcome="database_failure",
                    error_code="worker_execution_failed",
                    retryable=True,
                    reservation_id=run.reservation_id,
                    usage=ProviderUsage(),
                    lease_seconds=self.lease_seconds,
                )
            except InvalidRunTransition:
                return None

    def run_once(self) -> object | None:
        """Recover stale work, lease at most one run, and execute it synchronously."""
        self._require_enabled()
        self.dependencies.repository.recover_expired_leases(
            lease_seconds=self.lease_seconds
        )
        if self._stop.is_set():
            return None
        run = self.dependencies.repository.lease_next_run(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
        )
        if run is None:
            return None
        cancelled = Event()
        deadline = self._monotonic() + float(self.dependencies.settings.deep_timeout_seconds)
        return self._execute_owned(run, deadline=deadline, cancelled=cancelled.is_set)

    def run_forever(self) -> None:
        """Run until SIGTERM/request_stop, renewing active leases while they drain."""
        self._require_enabled()
        self.dependencies.repository.recover_expired_leases(
            lease_seconds=self.lease_seconds
        )
        concurrency = max(1, min(int(self.dependencies.settings.worker_concurrency), 8))
        renew_interval = max(1.0, self.lease_seconds / 3)
        next_renewal = self._monotonic() + renew_interval
        recovery_interval = max(5.0, min(30.0, self.poll_seconds * 10))
        next_recovery = self._monotonic() + recovery_interval
        active: dict[Future, tuple[object, Event, float]] = {}

        executor = ThreadPoolExecutor(
            max_workers=concurrency,
            thread_name_prefix="radar-ask-deep",
        )
        try:
            while active or not self._stop.is_set():
                if not self._stop.is_set() and self._monotonic() >= next_recovery:
                    self.dependencies.repository.recover_expired_leases(
                        lease_seconds=self.lease_seconds
                    )
                    next_recovery = self._monotonic() + recovery_interval
                done = {future for future in active if future.done()}
                for future in done:
                    active.pop(future)
                    try:
                        future.result()
                    except Exception:
                        LOGGER.exception("Radar Ask worker future ended unexpectedly")

                while not self._stop.is_set() and len(active) < concurrency:
                    run = self.dependencies.repository.lease_next_run(
                        worker_id=self.worker_id,
                        lease_seconds=self.lease_seconds,
                    )
                    if run is None:
                        break
                    cancelled = Event()
                    deadline = self._monotonic() + float(
                        self.dependencies.settings.deep_timeout_seconds
                    )
                    future = executor.submit(
                        self._execute_owned,
                        run,
                        deadline=deadline,
                        cancelled=cancelled.is_set,
                    )
                    active[future] = (run, cancelled, deadline)

                if not active:
                    if self._stop.wait(self.poll_seconds):
                        break
                    continue

                now = self._monotonic()
                if now >= next_renewal:
                    for run, cancelled, _deadline in list(active.values()):
                        try:
                            self.dependencies.repository.renew_lease(
                                run.id,
                                worker_id=self.worker_id,
                                lease_seconds=self.lease_seconds,
                            )
                        except InvalidRunTransition:
                            LOGGER.warning("Radar Ask lease renewal lost for run %s", run.id)
                            cancelled.set()
                    next_renewal = now + renew_interval

                for _run, cancelled, deadline in active.values():
                    if now >= deadline:
                        cancelled.set()

                if self._stop.is_set() and active:
                    final_deadline = max(deadline for _run, _cancelled, deadline in active.values())
                    if now >= final_deadline:
                        for _run, cancelled, _deadline in active.values():
                            cancelled.set()
                        break

                timeout = min(
                    self.poll_seconds,
                    max(0.01, next_renewal - self._monotonic()),
                )
                wait(active, timeout=timeout, return_when=FIRST_COMPLETED)
        finally:
            for _run, cancelled, _deadline in active.values():
                cancelled.set()
            executor.shutdown(wait=False, cancel_futures=True)


def cmd_radar_ask_worker(_args=None) -> None:
    """CLI adapter that installs graceful process stop handlers."""
    dependencies = build_worker_dependencies()
    worker = RadarAskWorker(dependencies=dependencies)
    worker._require_enabled()
    signal.signal(signal.SIGTERM, worker.request_stop)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, worker.request_stop)
    worker.run_forever()


__all__ = [
    "RadarAskWorker",
    "RadarAskWorkerDisabled",
    "build_worker_dependencies",
    "cmd_radar_ask_worker",
]
