"""Verify bounded traffic-page visibility and aggregate optional GSC exports."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from typing import Callable, Mapping
from urllib import robotparser
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.traffic_priority import active_traffic_priority_pages


@dataclass(frozen=True, slots=True)
class FetchedResponse:
    status: int
    headers: Mapping[str, str]
    body: str


@dataclass(frozen=True, slots=True)
class VisibilityFinding:
    status: str
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class VisibilityReport:
    findings: tuple[VisibilityFinding, ...]

    @property
    def failures(self) -> tuple[VisibilityFinding, ...]:
        return tuple(item for item in self.findings if item.status == "fail")

    @property
    def unknowns(self) -> tuple[VisibilityFinding, ...]:
        return tuple(item for item in self.findings if item.status == "unknown")

    @property
    def passes(self) -> tuple[VisibilityFinding, ...]:
        return tuple(item for item in self.findings if item.status == "pass")

    def to_dict(self) -> dict[str, object]:
        return {
            "summary": {
                "pass": len(self.passes),
                "fail": len(self.failures),
                "unknown": len(self.unknowns),
            },
            "findings": [asdict(item) for item in self.findings],
        }


@dataclass(frozen=True, slots=True)
class GscRow:
    query: str
    page: str
    clicks: int
    impressions: int
    ctr: float
    position: float
    dashboard_clicks: int | None = None


class _SeoHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonicals: list[str] = []
        self.robot_directives: list[str] = []
        self.h1_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {str(key).casefold(): str(value or "") for key, value in attrs}
        normalized_tag = tag.casefold()
        if normalized_tag == "h1":
            self.h1_count += 1
        elif normalized_tag == "link":
            rel = {item.casefold() for item in values.get("rel", "").split()}
            if "canonical" in rel and values.get("href"):
                self.canonicals.append(values["href"])
        elif normalized_tag == "meta":
            name = values.get("name", "").casefold()
            if name in {"robots", "googlebot"}:
                self.robot_directives.append(values.get("content", ""))


Fetcher = Callable[[str, float], FetchedResponse]


def _fetch(url: str, timeout: float) -> FetchedResponse:
    request = Request(url, headers={"User-Agent": "RadarBDS-Traffic-Visibility/1.0"})
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return FetchedResponse(
            status=int(response.status),
            headers={key.casefold(): value for key, value in response.headers.items()},
            body=response.read().decode(charset, errors="replace"),
        )


def _finding(status: str, code: str, path: str, message: str) -> VisibilityFinding:
    return VisibilityFinding(status=status, code=code, path=path, message=message)


def _fetch_or_unknown(
    fetcher: Fetcher,
    url: str,
    path: str,
    timeout: float,
    findings: list[VisibilityFinding],
) -> FetchedResponse | None:
    try:
        return fetcher(url, timeout)
    except Exception as exc:  # Network and injected transport errors are external state.
        findings.append(
            _finding("unknown", "fetch_unknown", path, f"Fetch unavailable: {type(exc).__name__}.")
        )
        return None


def _sitemap_paths(xml_body: str) -> set[str]:
    root = ET.fromstring(xml_body)
    paths: set[str] = set()
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "loc" or not element.text:
            continue
        parsed = urlsplit(element.text.strip())
        path = unquote(parsed.path or "/")
        paths.add(path.rstrip("/") or "/")
    return paths


def _has_noindex(value: str) -> bool:
    directives = {
        item.strip().casefold()
        for item in str(value or "").replace(";", ",").split(",")
    }
    return "noindex" in directives or "none" in directives


def verify_visibility(
    base_url: str,
    *,
    fetcher: Fetcher | None = None,
    timeout: float = 10.0,
) -> VisibilityReport:
    origin = str(base_url or "").rstrip("/")
    if not origin.startswith(("http://", "https://")):
        raise ValueError("base_url must be an absolute HTTP(S) origin")
    bounded_timeout = max(0.1, min(float(timeout), 60.0))
    transport = fetcher or _fetch
    pages = active_traffic_priority_pages()
    findings: list[VisibilityFinding] = []

    robots_path = "/robots.txt"
    robots_url = f"{origin}{robots_path}"
    robots_response = _fetch_or_unknown(
        transport, robots_url, robots_path, bounded_timeout, findings
    )
    if robots_response is not None:
        if robots_response.status != 200:
            findings.append(_finding("fail", "robots_status", robots_path, "robots.txt must return HTTP 200."))
        else:
            expected_sitemap = f"{origin}/sitemap.xml"
            sitemap_lines = [
                line.split(":", 1)[1].strip()
                for line in robots_response.body.splitlines()
                if line.casefold().startswith("sitemap:")
            ]
            if expected_sitemap not in sitemap_lines:
                findings.append(_finding("fail", "robots_sitemap", robots_path, "robots.txt must name the canonical sitemap."))
            else:
                findings.append(_finding("pass", "robots_sitemap", robots_path, "Canonical sitemap is declared."))
            parser = robotparser.RobotFileParser()
            parser.set_url(robots_url)
            parser.parse(robots_response.body.splitlines())
            for page in pages:
                if not parser.can_fetch("*", f"{origin}{page.path}"):
                    findings.append(_finding("fail", "robots_disallow", page.path, "Priority path is disallowed by robots.txt."))

    sitemap_path = "/sitemap.xml"
    sitemap_response = _fetch_or_unknown(
        transport,
        f"{origin}{sitemap_path}",
        sitemap_path,
        bounded_timeout,
        findings,
    )
    sitemap_paths: set[str] | None = None
    if sitemap_response is not None:
        if sitemap_response.status != 200:
            findings.append(_finding("fail", "sitemap_status", sitemap_path, "sitemap.xml must return HTTP 200."))
        else:
            try:
                sitemap_paths = _sitemap_paths(sitemap_response.body)
            except ET.ParseError:
                findings.append(_finding("fail", "sitemap_xml", sitemap_path, "sitemap.xml is not valid XML."))
            if sitemap_paths is not None:
                for page in pages:
                    if page.path not in sitemap_paths:
                        findings.append(_finding("fail", "sitemap_missing_path", page.path, "Priority path is absent from sitemap.xml."))

    for page in pages:
        path = page.path
        expected_url = f"{origin}{path if path != '/' else '/'}"
        response = _fetch_or_unknown(
            transport,
            expected_url,
            path,
            bounded_timeout,
            findings,
        )
        if response is None:
            continue
        if response.status != 200:
            findings.append(_finding("fail", "page_status", path, f"Priority page returned HTTP {response.status}."))
            continue

        headers = {str(key).casefold(): str(value) for key, value in response.headers.items()}
        if _has_noindex(headers.get("x-robots-tag", "")):
            findings.append(_finding("fail", "x_robots_noindex", path, "X-Robots-Tag blocks indexing."))

        parser = _SeoHtmlParser()
        parser.feed(response.body)
        if any(_has_noindex(value) for value in parser.robot_directives):
            findings.append(_finding("fail", "meta_robots_noindex", path, "Meta robots blocks indexing."))
        if parser.canonicals != [expected_url]:
            findings.append(_finding("fail", "canonical_mismatch", path, "Page needs exactly one clean self-canonical."))
        if parser.h1_count != 1:
            findings.append(_finding("fail", "h1_count", path, "Page needs exactly one H1."))
        if not any(item.path == path and item.status == "fail" for item in findings):
            findings.append(_finding("pass", "page_visible", path, "Status, indexability, canonical, and H1 checks passed."))

    return VisibilityReport(tuple(findings))


HEADER_ALIASES = {
    "query": {"query", "top queries", "truy vấn", "cụm từ tìm kiếm"},
    "page": {"page", "top pages", "trang"},
    "clicks": {"clicks", "lượt nhấp"},
    "impressions": {"impressions", "lượt hiển thị"},
    "ctr": {"ctr"},
    "position": {"position", "vị trí"},
}


def _header_key(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _number(value: object) -> float:
    text = str(value or "").strip().replace("\u00a0", "").replace(" ", "")
    text = text.removesuffix("%")
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    return float(text or 0)


def _canonical_priority_path(value: str) -> str | None:
    parsed = urlsplit(str(value or "").strip())
    path = unquote(parsed.path or "/")
    normalized = path.rstrip("/") or "/"
    active = {page.path for page in active_traffic_priority_pages()}
    return normalized if normalized in active else None


def aggregate_gsc_csv(path: Path) -> tuple[GscRow, ...]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        normalized = {_header_key(name): name for name in fieldnames}
        columns: dict[str, str] = {}
        for target, aliases in HEADER_ALIASES.items():
            source = next((normalized[alias] for alias in aliases if alias in normalized), None)
            if source is None:
                raise ValueError(f"GSC CSV is missing the {target} column")
            columns[target] = source

        totals: dict[tuple[str, str], dict[str, float]] = {}
        for raw in reader:
            canonical = _canonical_priority_path(str(raw.get(columns["page"]) or ""))
            if canonical is None:
                continue
            query = str(raw.get(columns["query"]) or "").strip()
            key = (query, canonical)
            clicks = int(round(_number(raw.get(columns["clicks"]))))
            impressions = int(round(_number(raw.get(columns["impressions"]))))
            position = _number(raw.get(columns["position"]))
            bucket = totals.setdefault(
                key,
                {"clicks": 0.0, "impressions": 0.0, "position_weight": 0.0, "weight": 0.0},
            )
            weight = float(impressions if impressions > 0 else 1)
            bucket["clicks"] += clicks
            bucket["impressions"] += impressions
            bucket["position_weight"] += position * weight
            bucket["weight"] += weight

    return tuple(
        GscRow(
            query=query,
            page=page,
            clicks=int(values["clicks"]),
            impressions=int(values["impressions"]),
            ctr=(values["clicks"] / values["impressions"] if values["impressions"] else 0.0),
            position=(values["position_weight"] / values["weight"] if values["weight"] else 0.0),
            dashboard_clicks=None,
        )
        for (query, page), values in sorted(totals.items(), key=lambda item: (item[0][1], item[0][0]))
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Radar BDS priority traffic visibility")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--gsc-csv", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args(argv)

    report = verify_visibility(args.base_url, timeout=args.timeout)
    gsc_rows = aggregate_gsc_csv(args.gsc_csv) if args.gsc_csv else ()
    payload = report.to_dict()
    payload["gsc"] = {
        "status": "available" if args.gsc_csv else "unknown",
        "rows": [asdict(row) for row in gsc_rows],
        "dashboard_clicks": "unknown",
    }
    if args.as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        summary = payload["summary"]
        print(
            f"Visibility pass={summary['pass']} fail={summary['fail']} unknown={summary['unknown']}"
        )
        for finding in report.failures + report.unknowns:
            print(f"- [{finding.status}:{finding.code}] {finding.path}: {finding.message}")
        print(f"GSC rows: {len(gsc_rows) if args.gsc_csv else 'unknown'}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
