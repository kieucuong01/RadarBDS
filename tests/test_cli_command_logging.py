import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_crawl_daily_installs_dedicated_command_log_name():
    import radar

    assert radar._command_log_name(["radar.py", "crawl-daily"]) == "crawl-daily.log"
    assert radar._command_log_name(["radar.py", "crawl-facebook"]) == ""


def test_crawl_daily_ignores_removed_no_flags_for_stale_schedules():
    import radar

    parser = radar.build_parser()
    args = radar._parse_args(
        parser,
        ["crawl-daily", "--source", "guland", "--no-alert", "--no-retired-provider"],
    )

    assert args.cmd == "crawl-daily"
    assert args.source == "guland"
    assert args.no_alert is True


def test_crawl_daily_rejects_disabled_sources():
    import pytest
    import radar

    parser = radar.build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["crawl-daily", "--source", "batdongsan"])


def test_signal_read_model_cli_accepts_refresh_compare_and_bounded_limit():
    import radar

    args = radar.build_parser().parse_args(
        ["signal-read-model", "--refresh", "--compare", "--limit", "200"]
    )

    assert args.cmd == "signal-read-model"
    assert args.refresh is True
    assert args.compare is True
    assert args.limit == 200

    with pytest.raises(SystemExit):
        radar.build_parser().parse_args(
            ["signal-read-model", "--compare", "--limit", "1001"]
        )


def test_guland_coordinate_backfill_defaults_to_dry_run():
    import radar

    args = radar.build_parser().parse_args(["guland-coordinate-backfill"])

    assert args.cmd == "guland-coordinate-backfill"
    assert args.apply is False
    assert args.rollback_run == ""


def test_guland_coordinate_backfill_apply_and_rollback_are_mutually_exclusive():
    import pytest
    import radar

    parser = radar.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "guland-coordinate-backfill",
            "--apply",
            "--rollback-run",
            "20260730T120000Z",
        ])


def test_guland_image_backfill_defaults_to_dry_run():
    import radar

    args = radar.build_parser().parse_args(["guland-image-backfill"])

    assert args.cmd == "guland-image-backfill"
    assert args.apply is False
    assert args.recover_live_missing is True


def test_guland_image_backfill_can_include_inactive_scope():
    import radar

    args = radar.build_parser().parse_args(["guland-image-backfill", "--include-inactive"])

    assert args.include_inactive is True


def test_guland_image_backfill_has_bounded_default_limit():
    import radar

    args = radar.build_parser().parse_args(["guland-image-backfill"])
    assert args.limit == 50

    args = radar.build_parser().parse_args(
        ["guland-image-backfill", "--limit", "200"]
    )
    assert args.limit == 200

    with pytest.raises(SystemExit):
        radar.build_parser().parse_args(
            ["guland-image-backfill", "--limit", "201"]
        )


def test_guland_image_cli_forwards_the_requested_limit(monkeypatch):
    from argparse import Namespace
    from cli import guland_images

    captured = {}

    def run(**kwargs):
        captured.update(kwargs)
        return {"zero_ready_targets": 0}

    monkeypatch.setattr(guland_images, "run_guland_image_backfill", run)
    guland_images.cmd_guland_image_backfill(
        Namespace(
            apply=False,
            limit=37,
            recover_live_missing=True,
            download_recovered=True,
            include_inactive=False,
        )
    )

    assert captured["limit"] == 37


def test_guland_coordinate_cli_prints_one_json_object(monkeypatch, capsys):
    from argparse import Namespace
    from cli import guland_coordinates

    monkeypatch.setattr(
        guland_coordinates,
        "run_guland_coordinate_backfill",
        lambda **kwargs: {"eligible": 2, "valid": 1, "raw_updated": 0},
    )

    result = guland_coordinates.cmd_guland_coordinate_backfill(
        Namespace(apply=False, rollback_run="", dry_run=True)
    )
    output = capsys.readouterr().out.strip().splitlines()

    assert result["valid"] == 1
    assert len(output) == 1
    assert output[0] == '{"eligible": 2, "raw_updated": 0, "valid": 1}'
