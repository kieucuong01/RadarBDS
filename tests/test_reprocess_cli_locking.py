from types import SimpleNamespace
from contextlib import contextmanager


def test_reprocess_cli_delegates_lock_ownership_to_pipeline(monkeypatch):
    from cleansing import reprocess
    from cli import system

    def unexpected_outer_lock(*_args, **_kwargs):
        raise AssertionError("cmd_reprocess must not acquire a second reprocess lock")

    calls = []
    monkeypatch.setattr(system, "advisory_lock", unexpected_outer_lock)
    monkeypatch.setattr(system, "init_schema", lambda: None)
    monkeypatch.setattr(
        reprocess,
        "run_full_reprocess",
        lambda **kwargs: calls.append(kwargs)
        or {
            "listings": {"new": 0, "updated": 0, "skipped": 0},
            "valuation": {"total": 0, "signals": 0, "outliers": 0},
        },
    )

    system.cmd_reprocess(
        SimpleNamespace(
            full=True,
            valuation_only=False,
            listings_only=False,
            source=None,
            since=None,
        )
    )

    assert calls == [{"source": None, "since": None, "full": True}]


def test_listings_only_cli_keeps_one_reprocess_lock(monkeypatch):
    from cleansing import reprocess
    from cli import system

    lock_events = []

    @contextmanager
    def fake_lock(name):
        lock_events.append(("enter", name))
        try:
            yield
        finally:
            lock_events.append(("exit", name))

    calls = []
    monkeypatch.setattr(system, "advisory_lock", fake_lock)
    monkeypatch.setattr(system, "init_schema", lambda: None)
    monkeypatch.setattr(
        reprocess,
        "reprocess_listings",
        lambda **kwargs: calls.append(kwargs) or {"updated": 0},
    )

    system.cmd_reprocess(
        SimpleNamespace(
            full=True,
            valuation_only=False,
            listings_only=True,
            source="facebook",
            since=None,
        )
    )

    assert lock_events == [("enter", "reprocess"), ("exit", "reprocess")]
    assert calls == [{"source": "facebook", "since": None, "full": True}]


def test_valuation_only_cli_keeps_one_reprocess_lock(monkeypatch):
    from cleansing import reprocess
    from cli import system

    lock_events = []

    @contextmanager
    def fake_lock(name):
        lock_events.append(("enter", name))
        try:
            yield
        finally:
            lock_events.append(("exit", name))

    calls = []
    monkeypatch.setattr(system, "advisory_lock", fake_lock)
    monkeypatch.setattr(system, "init_schema", lambda: None)
    monkeypatch.setattr(
        reprocess,
        "reprocess_valuation",
        lambda **kwargs: calls.append(kwargs) or {"total": 0},
    )

    system.cmd_reprocess(
        SimpleNamespace(
            full=False,
            valuation_only=True,
            listings_only=False,
            source=None,
            since=None,
        )
    )

    assert lock_events == [("enter", "reprocess"), ("exit", "reprocess")]
    assert calls == [{"incremental_ids": None}]
