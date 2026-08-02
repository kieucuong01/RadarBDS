import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path("scripts/load/aggregate_k6_shards.py")
BASE_URL = "https://radarbds.vn"
STAGE = "default-1000"
RUN_ID = "run-1-default-1000"
VU_START_EPOCH = 1_800_000_000


def _write_shard(
    root: Path,
    shard: int,
    *,
    scenario: str = "default",
    stage: str = STAGE,
    run_id: str = RUN_ID,
    base_url: str = BASE_URL,
    expected_shards: int = 2,
    vus: int = 500,
    p95: float = 500.0,
    p99: float = 900.0,
    failed_passes: int = 10,
    failed_fails: int = 9990,
    check_passes: int = 29970,
    check_fails: int = 30,
    requests: int = 10000,
    hit: int = 9990,
    miss: int = 10,
    stale: int = 0,
    bypass: int = 0,
    unknown: int = 0,
    edge_error: int = 0,
    origin_error: int = 0,
    transport_error: int = 0,
    cdn_hit: int | None = None,
    cdn_miss: int | None = None,
    cdn_stale: int = 0,
    cdn_bypass: int = 0,
    cdn_unknown: int = 0,
    cdn_error: int = 0,
    require_cdn: bool = True,
    omit_zero_counters: bool = False,
    exit_code: int = 0,
    crossed_threshold: bool = False,
    vu_start_epoch: int = VU_START_EPOCH,
    vu_start_count: int | None = None,
    vu_start_min_ms: float | None = None,
    vu_start_max_ms: float | None = None,
) -> None:
    if cdn_hit is None:
        cdn_hit = hit
    if cdn_miss is None:
        cdn_miss = miss
    if vu_start_count is None:
        vu_start_count = vus
    if vu_start_min_ms is None:
        vu_start_min_ms = vu_start_epoch * 1000 + 100
    if vu_start_max_ms is None:
        vu_start_max_ms = vu_start_epoch * 1000 + 900
    folder = root / f"shard-{shard}"
    folder.mkdir(parents=True)
    metadata = {
        "scenario": scenario,
        "stage": stage,
        "run_id": run_id,
        "base_url": base_url,
        "shard": shard,
        "expected_shards": expected_shards,
        "vus": vus,
        "require_cdn": require_cdn,
        "vu_start_epoch": vu_start_epoch,
        "k6_exit_code": exit_code,
    }
    summary = {
        "metrics": {
            "http_req_duration": {
                "p(95)": p95,
                "p(99)": p99,
                "thresholds": {
                    "p(95)<1000": crossed_threshold,
                    "p(99)<2000": crossed_threshold,
                },
            },
            "http_req_failed": {
                "passes": failed_passes,
                "fails": failed_fails,
                "value": failed_passes / (failed_passes + failed_fails),
                "thresholds": {"rate<0.005": crossed_threshold},
            },
            "checks": {
                "passes": check_passes,
                "fails": check_fails,
                "value": check_passes / (check_passes + check_fails),
                "thresholds": {"rate>0.995": crossed_threshold},
            },
            "http_reqs": {"count": requests},
            "radar_edge_hit": {"count": hit},
            "radar_edge_miss": {"count": miss},
            "radar_edge_stale": {"count": stale},
            "radar_edge_bypass": {"count": bypass},
            "radar_edge_unknown": {"count": unknown},
            "radar_edge_error": {"count": edge_error},
            "radar_origin_error": {"count": origin_error},
            "radar_transport_error": {"count": transport_error},
            "radar_cdn_hit": {"count": cdn_hit},
            "radar_cdn_miss": {"count": cdn_miss},
            "radar_cdn_stale": {"count": cdn_stale},
            "radar_cdn_bypass": {"count": cdn_bypass},
            "radar_cdn_unknown": {"count": cdn_unknown},
            "radar_cdn_error": {"count": cdn_error},
            "radar_vu_started_at_ms": {
                "count": vu_start_count,
                "min": vu_start_min_ms,
                "max": vu_start_max_ms,
            },
        }
    }
    if omit_zero_counters:
        summary["metrics"] = {
            name: metric
            for name, metric in summary["metrics"].items()
            if metric.get("count") != 0
        }
    (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (folder / "summary.json").write_text(json.dumps(summary), encoding="utf-8")


def _run(root: Path, output: Path, *, scenario: str = "default") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input-dir",
            str(root),
            "--expected-shards",
            "2",
            "--scenario",
            scenario,
            "--stage",
            STAGE,
            "--run-id",
            RUN_ID,
            "--base-url",
            BASE_URL,
            "--require-cdn",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_valid_shards_are_summed_and_use_conservative_max_percentiles(tmp_path: Path):
    _write_shard(tmp_path, 0, p95=420.0, p99=810.0, requests=10000, hit=9990)
    _write_shard(tmp_path, 1, p95=640.0, p99=1200.0, requests=12000, hit=11980, miss=20)
    output = tmp_path / "aggregate.json"

    completed = _run(tmp_path, output)

    assert completed.returncode == 0, completed.stderr
    aggregate = json.loads(output.read_text("utf-8"))
    assert aggregate["status"] == "passed"
    assert aggregate["total_vus"] == 1000
    assert aggregate["http_reqs"] == 22000
    assert aggregate["max_shard_p95_ms"] == 640.0
    assert aggregate["max_shard_p99_ms"] == 1200.0
    assert aggregate["edge"] == {
        "radar_edge_hit": 21970,
        "radar_edge_miss": 30,
        "radar_edge_stale": 0,
        "radar_edge_bypass": 0,
        "radar_edge_unknown": 0,
        "radar_edge_error": 0,
    }
    assert aggregate["cdn"] == {
        "radar_cdn_hit": 21970,
        "radar_cdn_miss": 30,
        "radar_cdn_stale": 0,
        "radar_cdn_bypass": 0,
        "radar_cdn_unknown": 0,
        "radar_cdn_error": 0,
    }
    assert aggregate["origin_errors"] == 0
    assert aggregate["planned_vu_start_epoch"] == VU_START_EPOCH
    assert aggregate["earliest_vu_start_ms"] == VU_START_EPOCH * 1000 + 100
    assert aggregate["latest_vu_start_ms"] == VU_START_EPOCH * 1000 + 900
    assert aggregate["vu_start_skew_ms"] == 800
    assert "stage_status=passed" in completed.stdout


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"missing": True}, "Missing shard directory"),
        ({"run_id": "wrong"}, "metadata run_id mismatch"),
        ({"exit_code": 99}, "k6 exit code"),
        ({"crossed_threshold": True}, "crossed threshold"),
        ({"bypass": 1}, "edge bypass"),
        ({"unknown": 1}, "unknown edge"),
        ({"cdn_bypass": 1}, "cdn bypass"),
        ({"cdn_unknown": 1}, "unknown cdn"),
        ({"cdn_hit": 0, "cdn_stale": 0}, "cdn hit or stale"),
        ({"require_cdn": False}, "metadata require_cdn mismatch"),
        ({"vu_start_epoch": VU_START_EPOCH + 1}, "vu_start_epoch mismatch"),
        ({"vu_start_count": 499}, "vu start samples"),
        ({"vu_start_min_ms": VU_START_EPOCH * 1000 - 1_001}, "preceded"),
        ({"vu_start_max_ms": VU_START_EPOCH * 1000 + 10_001}, "vu start deadline"),
        ({"p95": 1000.0}, "p95"),
        ({"p99": 2000.0}, "p99"),
        ({"failed_passes": 50, "failed_fails": 9950}, "failure rate"),
        ({"check_passes": 9950, "check_fails": 50}, "check rate"),
    ],
)
def test_invalid_or_incomplete_shards_fail_closed(tmp_path: Path, mutation: dict, message: str):
    _write_shard(tmp_path, 0)
    if not mutation.get("missing"):
        _write_shard(tmp_path, 1, **mutation)
    output = tmp_path / "aggregate.json"

    completed = _run(tmp_path, output)

    assert completed.returncode != 0
    assert message.lower() in completed.stderr.lower()
    assert not output.exists()


def test_mixed_scenario_uses_1500ms_p95_limit(tmp_path: Path):
    _write_shard(tmp_path, 0, scenario="mixed", stage=STAGE, p95=1499.9)
    _write_shard(tmp_path, 1, scenario="mixed", stage=STAGE, p95=1500.0)

    completed = _run(tmp_path, tmp_path / "aggregate.json", scenario="mixed")

    assert completed.returncode != 0
    assert "p95" in completed.stderr.lower()


def test_zero_value_counter_metrics_may_be_omitted_by_k6(tmp_path: Path):
    _write_shard(tmp_path, 0, omit_zero_counters=True)
    _write_shard(tmp_path, 1, omit_zero_counters=True)

    completed = _run(tmp_path, tmp_path / "aggregate.json")

    assert completed.returncode == 0, completed.stderr


def test_cdn_errors_are_governed_by_failure_threshold_not_unknown_gate(tmp_path: Path):
    for shard in range(2):
        _write_shard(
            tmp_path,
            shard,
            requests=1000,
            hit=998,
            miss=0,
            edge_error=1,
            transport_error=1,
            cdn_hit=998,
            cdn_miss=0,
            cdn_error=1,
            failed_passes=2,
            failed_fails=998,
            check_passes=3990,
            check_fails=10,
        )

    output = tmp_path / "aggregate.json"
    completed = _run(tmp_path, output)

    assert completed.returncode == 0, completed.stderr
    aggregate = json.loads(output.read_text("utf-8"))
    assert aggregate["failure_rate"] == 0.002
    assert aggregate["edge"]["radar_edge_error"] == 2
    assert aggregate["cdn"]["radar_cdn_error"] == 2
    assert aggregate["transport_errors"] == 2


def test_origin_errors_are_governed_by_failure_threshold_not_unknown_gate(
    tmp_path: Path,
):
    for shard in range(2):
        _write_shard(
            tmp_path,
            shard,
            requests=1000,
            hit=999,
            miss=0,
            origin_error=1,
            cdn_hit=999,
            cdn_miss=0,
            failed_passes=1,
            failed_fails=999,
            check_passes=3995,
            check_fails=5,
        )

    output = tmp_path / "aggregate.json"
    completed = _run(tmp_path, output)

    assert completed.returncode == 0, completed.stderr
    aggregate = json.loads(output.read_text("utf-8"))
    assert aggregate["failure_rate"] == 0.001
    assert aggregate["origin_errors"] == 2
    assert aggregate["edge"]["radar_edge_unknown"] == 0
    assert aggregate["cdn"]["radar_cdn_unknown"] == 0
