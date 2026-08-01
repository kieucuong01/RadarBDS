"""Best-effort, no-credential warming for a bounded public route set."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROUTE_CONFIG = PROJECT_ROOT / "config" / "public_cache_warm_routes.json"
ALLOWED_PATHS = frozenset(
    {"/", "/api/signals", "/api/counts", "/api/dashboard"}
)
MAX_ROUTES = 20
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _validated_base_url(base_url: str) -> str:
    text = str(base_url or "").strip()
    parsed = urlsplit(text)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("invalid public prewarm base URL")
    return text.rstrip("/")


def _validated_routes(routes) -> tuple[str, ...]:
    values = tuple(str(route or "").strip() for route in routes)
    if len(values) > MAX_ROUTES:
        raise ValueError("public prewarm supports at most 20 routes")
    normalized: list[str] = []
    for route in values:
        parsed = urlsplit(route)
        if (
            not route.startswith("/")
            or route.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ALLOWED_PATHS
        ):
            raise ValueError("invalid public prewarm route")
        normalized.append(route)
    return tuple(dict.fromkeys(normalized))


def prewarm_public_routes(
    base_url: str,
    routes,
    timeout_seconds: float = 5.0,
) -> dict:
    base = _validated_base_url(base_url)
    validated = _validated_routes(routes)
    result = {
        "attempted": len(validated),
        "succeeded": 0,
        "failed": 0,
        "routes": [],
    }
    for route in validated:
        request = Request(
            urljoin(f"{base}/", route.lstrip("/")),
            headers={"User-Agent": "RadarBDS-Prewarm/1.0"},
        )
        route_status: int | str
        try:
            with urlopen(request, timeout=float(timeout_seconds)) as response:
                status = int(
                    getattr(response, "status", None)
                    or response.getcode()
                )
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                route_status = "body_too_large"
                result["failed"] += 1
            elif 200 <= status < 400:
                route_status = status
                result["succeeded"] += 1
            else:
                route_status = f"http_{status}"
                result["failed"] += 1
        except Exception as exc:
            route_status = f"error:{type(exc).__name__}"
            result["failed"] += 1
        result["routes"].append({"path": route, "status": route_status})
        logger.info("Public prewarm path=%s status=%s", route, route_status)
    return result


def prewarm_configured_routes(
    config_path: str | Path = DEFAULT_ROUTE_CONFIG,
) -> dict:
    routes = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(routes, list):
        raise ValueError("public prewarm route config must be a list")
    return prewarm_public_routes(
        os.getenv(
            "RADAR_PUBLIC_PREWARM_URL", "http://127.0.0.1:5000"
        ),
        routes,
    )
