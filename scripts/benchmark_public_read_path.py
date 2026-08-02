"""Safe cold/warm timing for Radar BDS public read endpoints.

The utility intentionally discards response bodies and never sends or prints
cookies. Run it from localhost or a controlled operator host.
"""

from __future__ import annotations

import argparse
import http.client
import json
import time
from urllib.parse import urlsplit


DEFAULT_PATHS = (
    "/",
    "/api/signals?limit=30&include_total=0",
    "/api/signals?source=facebook&limit=30&include_total=0",
    "/api/signals?source=guland&limit=30&include_total=0",
    "/api/listings?date_range=3m&sort_by=date&sort_dir=desc&page=1&limit=50",
    "/api/counts",
    "/api/dashboard",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure cold and warm Radar BDS public read paths.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:5000",
        help="Origin only; defaults to the local Flask listener.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="Samples per cold/warm mode (1-100).",
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="Public path to time; repeat this option for multiple paths.",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    return parser


def _target(base_url: str):
    target = urlsplit(base_url)
    if target.scheme not in {"http", "https"} or not target.hostname:
        raise ValueError("--base-url must be an http(s) origin")
    if target.username or target.password or target.query or target.fragment:
        raise ValueError("--base-url must not contain credentials/query/fragment")
    return target


def _connection_for(target, timeout: float):
    cls = (
        http.client.HTTPSConnection
        if target.scheme == "https"
        else http.client.HTTPConnection
    )
    return cls(target.hostname, target.port, timeout=timeout)


def _request_path(target, path: str) -> str:
    normalized = path if path.startswith("/") else "/" + path
    base_path = target.path.rstrip("/")
    return (base_path + normalized) or "/"


def _sample(conn, path: str, *, mode: str, sample: int) -> dict:
    started = time.perf_counter()
    conn.request(
        "GET",
        path,
        headers={
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.1",
            "User-Agent": "RadarBDS-PublicRead-Benchmark/1.0",
            "Connection": "keep-alive" if mode == "warm" else "close",
        },
    )
    response = conn.getresponse()
    ttfb_ms = (time.perf_counter() - started) * 1000
    body = response.read()
    total_ms = (time.perf_counter() - started) * 1000
    return {
        "mode": mode,
        "path": path,
        "sample": sample,
        "status": int(response.status),
        "ttfb_ms": round(ttfb_ms, 2),
        "total_ms": round(total_ms, 2),
        "bytes": len(body),
    }


def _emit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    repeat = min(max(int(args.repeat), 1), 100)
    timeout = min(max(float(args.timeout), 0.1), 120.0)
    try:
        target = _target(args.base_url)
    except ValueError as exc:
        print(f"benchmark configuration error: {exc}")
        return 2

    paths = tuple(args.paths or DEFAULT_PATHS)
    failed = False
    for raw_path in paths:
        path = _request_path(target, str(raw_path))
        for sample_number in range(1, repeat + 1):
            conn = _connection_for(target, timeout)
            try:
                result = _sample(
                    conn,
                    path,
                    mode="cold",
                    sample=sample_number,
                )
                _emit(result)
                failed = failed or not 200 <= result["status"] < 300
            except (OSError, TimeoutError, http.client.HTTPException) as exc:
                _emit(
                    {
                        "mode": "cold",
                        "path": path,
                        "sample": sample_number,
                        "error": type(exc).__name__,
                    }
                )
                failed = True
            finally:
                conn.close()

        warm_conn = _connection_for(target, timeout)
        try:
            for sample_number in range(1, repeat + 1):
                try:
                    result = _sample(
                        warm_conn,
                        path,
                        mode="warm",
                        sample=sample_number,
                    )
                    _emit(result)
                    failed = failed or not 200 <= result["status"] < 300
                except (OSError, TimeoutError, http.client.HTTPException) as exc:
                    _emit(
                        {
                            "mode": "warm",
                            "path": path,
                            "sample": sample_number,
                            "error": type(exc).__name__,
                        }
                    )
                    failed = True
                    break
        finally:
            warm_conn.close()

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
