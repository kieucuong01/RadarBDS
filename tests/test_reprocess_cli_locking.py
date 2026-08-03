from types import SimpleNamespace


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
