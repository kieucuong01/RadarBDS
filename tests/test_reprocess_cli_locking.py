from types import SimpleNamespace
from contextlib import contextmanager

import pytest


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


def test_raw_ids_cli_runs_complete_targeted_pipeline(monkeypatch):
    import radar
    from cleansing import reprocess
    from cli import system

    args = radar.build_parser().parse_args(["reprocess", "--raw-ids", "17", "18"])
    calls = []
    monkeypatch.setattr(system, "init_schema", lambda: None)
    monkeypatch.setattr(reprocess, "run_targeted_reprocess", lambda ids: calls.append(ids) or {})
    system.cmd_reprocess(args)
    assert calls == [[17, 18]]


@pytest.mark.parametrize("options", [
    ["--raw-ids", "0"], ["--raw-ids", "-1"],
    ["--raw-ids", "17", "--full"],
    ["--raw-ids", "17", "--source", "facebook"],
    ["--raw-ids", "17", "--since", "2026-11-01"],
    ["--raw-ids", "17", "--listings-only"],
    ["--raw-ids", "17", "--valuation-only"],
])
def test_raw_ids_cli_rejects_invalid_or_conflicting_scope_before_db(monkeypatch, options):
    import radar
    from cli import system

    def unexpected_schema():
        raise AssertionError("Invalid scope must be rejected before DB writes")

    monkeypatch.setattr(system, "init_schema", unexpected_schema)
    with pytest.raises(SystemExit):
        system.cmd_reprocess(radar.build_parser().parse_args(["reprocess", *options]))
