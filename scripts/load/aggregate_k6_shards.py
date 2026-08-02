#!/usr/bin/env python3
"""Fail-closed aggregation for synchronized Radar BDS k6 shards."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any


EDGE_METRICS = (
    "radar_edge_hit",
    "radar_edge_miss",
    "radar_edge_stale",
    "radar_edge_bypass",
    "radar_edge_unknown",
    "radar_edge_error",
)
CDN_METRICS = (
    "radar_cdn_hit",
    "radar_cdn_miss",
    "radar_cdn_stale",
    "radar_cdn_bypass",
    "radar_cdn_unknown",
    "radar_cdn_error",
)


class AggregationError(ValueError):
    """Raised when shard evidence is incomplete or violates a gate."""


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AggregationError(f"{label} must be a JSON object")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AggregationError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise AggregationError(f"{label} must be a finite non-negative number")
    return result


def _integer(value: Any, label: str) -> int:
    numeric = _number(value, label)
    if not numeric.is_integer():
        raise AggregationError(f"{label} must be an integer")
    return int(numeric)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        return _object(json.loads(path.read_text(encoding="utf-8")), label)
    except FileNotFoundError as exc:
        raise AggregationError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AggregationError(f"Invalid {label}: {path}: {exc}") from exc


def _metric(summary: dict[str, Any], name: str) -> dict[str, Any]:
    metrics = _object(summary.get("metrics"), "summary metrics")
    if name not in metrics:
        raise AggregationError(f"Missing metric: {name}")
    return _object(metrics[name], f"metric {name}")


def _metric_number(summary: dict[str, Any], metric_name: str, field: str) -> float:
    metric = _metric(summary, metric_name)
    if field not in metric:
        raise AggregationError(f"Missing metric field: {metric_name}.{field}")
    return _number(metric[field], f"{metric_name}.{field}")


def _metric_count(summary: dict[str, Any], metric_name: str) -> int:
    return _integer(_metric_number(summary, metric_name, "count"), f"{metric_name}.count")


def _optional_metric_count(summary: dict[str, Any], metric_name: str) -> int:
    metrics = _object(summary.get("metrics"), "summary metrics")
    if metric_name not in metrics:
        return 0
    return _integer(
        _metric_number(summary, metric_name, "count"), f"{metric_name}.count"
    )


def _rate_counts(summary: dict[str, Any], metric_name: str) -> tuple[int, int]:
    metric = _metric(summary, metric_name)
    passes = _integer(metric.get("passes"), f"{metric_name}.passes")
    fails = _integer(metric.get("fails"), f"{metric_name}.fails")
    if passes + fails <= 0:
        raise AggregationError(f"{metric_name} has no samples")
    return passes, fails


def _require_thresholds_not_crossed(summary: dict[str, Any], metric_name: str) -> None:
    thresholds = _object(_metric(summary, metric_name).get("thresholds"), f"{metric_name}.thresholds")
    if not thresholds:
        raise AggregationError(f"Missing threshold results for {metric_name}")
    for expression, crossed in thresholds.items():
        if not isinstance(crossed, bool):
            raise AggregationError(f"Threshold result must be boolean: {metric_name} {expression}")
        if crossed:
            raise AggregationError(f"Shard crossed threshold: {metric_name} {expression}")


def _metadata_value(metadata: dict[str, Any], name: str, expected: Any) -> None:
    actual = metadata.get(name)
    if actual != expected or type(actual) is not type(expected):
        raise AggregationError(
            f"Metadata {name} mismatch: expected {expected!r}, got {actual!r}"
        )


def aggregate(args: argparse.Namespace) -> dict[str, Any]:
    if args.expected_shards < 1:
        raise AggregationError("expected_shards must be at least 1")

    summaries: list[dict[str, Any]] = []
    metadata_rows: list[dict[str, Any]] = []
    planned_vu_start_epoch: int | None = None
    earliest_vu_starts: list[float] = []
    latest_vu_starts: list[float] = []
    for shard in range(args.expected_shards):
        shard_dir = args.input_dir / f"shard-{shard}"
        if not shard_dir.is_dir():
            raise AggregationError(f"Missing shard directory: {shard_dir}")
        metadata = _read_json(shard_dir / "metadata.json", "shard metadata")
        summary = _read_json(shard_dir / "summary.json", "shard summary")

        for field, expected in (
            ("scenario", args.scenario),
            ("stage", args.stage),
            ("run_id", args.run_id),
            ("base_url", args.base_url),
            ("shard", shard),
            ("expected_shards", args.expected_shards),
            ("require_cdn", args.require_cdn),
        ):
            _metadata_value(metadata, field, expected)

        vus = _integer(metadata.get("vus"), "metadata vus")
        if vus < 1:
            raise AggregationError("metadata vus must be at least 1")
        shard_vu_start_epoch = _integer(
            metadata.get("vu_start_epoch"), "metadata vu_start_epoch"
        )
        if planned_vu_start_epoch is None:
            planned_vu_start_epoch = shard_vu_start_epoch
        elif shard_vu_start_epoch != planned_vu_start_epoch:
            raise AggregationError(
                "Metadata vu_start_epoch mismatch: "
                f"expected {planned_vu_start_epoch}, got {shard_vu_start_epoch}"
            )
        exit_code = _integer(metadata.get("k6_exit_code"), "metadata k6_exit_code")
        if exit_code != 0:
            raise AggregationError(f"Shard {shard} k6 exit code was {exit_code}")

        for metric_name in ("http_req_duration", "http_req_failed", "checks"):
            _require_thresholds_not_crossed(summary, metric_name)

        p95 = _metric_number(summary, "http_req_duration", "p(95)")
        p99 = _metric_number(summary, "http_req_duration", "p(99)")
        p95_limit = 1500.0 if args.scenario == "mixed" else 1000.0
        if p95 >= p95_limit:
            raise AggregationError(
                f"Shard {shard} p95 {p95:.3f}ms is not below {p95_limit:.0f}ms"
            )
        if p99 >= 2000.0:
            raise AggregationError(
                f"Shard {shard} p99 {p99:.3f}ms is not below 2000ms"
            )

        failed_true, failed_false = _rate_counts(summary, "http_req_failed")
        failure_rate = failed_true / (failed_true + failed_false)
        if failure_rate >= 0.005:
            raise AggregationError(
                f"Shard {shard} failure rate {failure_rate:.6f} is not below 0.005"
            )
        check_passes, check_fails = _rate_counts(summary, "checks")
        check_rate = check_passes / (check_passes + check_fails)
        if check_rate <= 0.995:
            raise AggregationError(
                f"Shard {shard} check rate {check_rate:.6f} is not above 0.995"
            )

        vu_start_samples = _metric_count(summary, "radar_vu_started_at_ms")
        if vu_start_samples != vus:
            raise AggregationError(
                f"Shard {shard} VU start samples {vu_start_samples} did not match {vus} VUs"
            )
        earliest_vu_start = _metric_number(summary, "radar_vu_started_at_ms", "min")
        latest_vu_start = _metric_number(summary, "radar_vu_started_at_ms", "max")
        planned_vu_start_ms = shard_vu_start_epoch * 1000
        if earliest_vu_start < planned_vu_start_ms - 1000:
            raise AggregationError(
                f"Shard {shard} VU start preceded the planned epoch"
            )
        if latest_vu_start > planned_vu_start_ms + 10_000:
            raise AggregationError(
                f"Shard {shard} VU start deadline exceeded by "
                f"{latest_vu_start - planned_vu_start_ms:.0f}ms"
            )
        earliest_vu_starts.append(earliest_vu_start)
        latest_vu_starts.append(latest_vu_start)

        bypass = _optional_metric_count(summary, "radar_edge_bypass")
        if bypass:
            raise AggregationError(f"Shard {shard} edge bypass count was {bypass}")
        unknown = _optional_metric_count(summary, "radar_edge_unknown")
        if unknown:
            raise AggregationError(f"Shard {shard} unknown edge count was {unknown}")
        edge_public = sum(
            _optional_metric_count(summary, name)
            for name in ("radar_edge_hit", "radar_edge_miss", "radar_edge_stale")
        )
        if edge_public <= 0:
            raise AggregationError(f"Shard {shard} has no public origin edge evidence")

        if args.require_cdn:
            cdn_bypass = _optional_metric_count(summary, "radar_cdn_bypass")
            if cdn_bypass:
                raise AggregationError(
                    f"Shard {shard} CDN bypass count was {cdn_bypass}"
                )
            cdn_unknown = _optional_metric_count(summary, "radar_cdn_unknown")
            if cdn_unknown:
                raise AggregationError(
                    f"Shard {shard} unknown CDN count was {cdn_unknown}"
                )
            cdn_hot = sum(
                _optional_metric_count(summary, name)
                for name in ("radar_cdn_hit", "radar_cdn_stale")
            )
            if cdn_hot <= 0:
                raise AggregationError(
                    f"Shard {shard} has no CDN HIT or stale evidence"
                )

        metadata_rows.append(metadata)
        summaries.append(summary)

    failure_true = sum(_rate_counts(item, "http_req_failed")[0] for item in summaries)
    failure_false = sum(_rate_counts(item, "http_req_failed")[1] for item in summaries)
    check_passes = sum(_rate_counts(item, "checks")[0] for item in summaries)
    check_fails = sum(_rate_counts(item, "checks")[1] for item in summaries)
    aggregate_result = {
        "status": "passed",
        "scenario": args.scenario,
        "stage": args.stage,
        "run_id": args.run_id,
        "base_url": args.base_url,
        "require_cdn": args.require_cdn,
        "expected_shards": args.expected_shards,
        "total_vus": sum(_integer(item["vus"], "metadata vus") for item in metadata_rows),
        "http_reqs": sum(_metric_count(item, "http_reqs") for item in summaries),
        "max_shard_p95_ms": max(
            _metric_number(item, "http_req_duration", "p(95)") for item in summaries
        ),
        "max_shard_p99_ms": max(
            _metric_number(item, "http_req_duration", "p(99)") for item in summaries
        ),
        "failure_rate": failure_true / (failure_true + failure_false),
        "check_rate": check_passes / (check_passes + check_fails),
        "edge": {
            name: sum(_optional_metric_count(item, name) for item in summaries)
            for name in EDGE_METRICS
        },
        "cdn": {
            name: sum(_optional_metric_count(item, name) for item in summaries)
            for name in CDN_METRICS
        },
        "transport_errors": sum(
            _optional_metric_count(item, "radar_transport_error")
            for item in summaries
        ),
        "origin_errors": sum(
            _optional_metric_count(item, "radar_origin_error")
            for item in summaries
        ),
        "planned_vu_start_epoch": planned_vu_start_epoch,
        "earliest_vu_start_ms": min(earliest_vu_starts),
        "latest_vu_start_ms": max(latest_vu_starts),
        "vu_start_skew_ms": max(latest_vu_starts) - min(earliest_vu_starts),
    }
    return aggregate_result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--expected-shards", type=int, required=True)
    parser.add_argument("--scenario", choices=("default", "mixed"), required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-url", choices=("https://radarbds.vn",), required=True)
    parser.add_argument("--require-cdn", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = aggregate(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(f"{args.output.name}.{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.output)
    except (AggregationError, OSError) as exc:
        print(f"aggregation_error={exc}", file=sys.stderr)
        return 1

    print("stage_status=passed")
    print(f"stage={result['stage']}")
    print(f"total_vus={result['total_vus']}")
    print(f"http_reqs={result['http_reqs']}")
    print(f"max_shard_p95_ms={result['max_shard_p95_ms']:.3f}")
    print(f"max_shard_p99_ms={result['max_shard_p99_ms']:.3f}")
    print(f"failure_rate={result['failure_rate']:.6f}")
    print(f"check_rate={result['check_rate']:.6f}")
    print(f"vu_start_skew_ms={result['vu_start_skew_ms']:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
