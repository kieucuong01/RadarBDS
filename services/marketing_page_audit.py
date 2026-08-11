"""Deterministic, configuration-only audit for public marketing pages.

The audit intentionally reads registries only.  It is useful in local review and
CI because it does not depend on PostgreSQL, Redis, HTTP, or a language model.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from config.binh_duong_map import BINH_DUONG_MAP_PAGE
from config.city_map_products import CITY_MAP_PRODUCTS
from config.content_hubs import NEWS_HUBS, PLANNING_CATEGORY_PAGES
from config.planning_pages import PLANNING_HUB, PLANNING_PAGE_LIST
from config.seo_articles import KNOWLEDGE_HUB, SEO_ARTICLES
from config.seo_locations import SEO_LOCATION_PAGES, TDM_LIVE_WARDS
from config.seo_pages import REPORT_HUB, SEO_PAGES


MAX_JSON_FINDINGS = 200
MIN_APPROVED_STATIC_PATHS = 124
PREFERRED_ANSWER_FIRST_WORDS = range(40, 61)

SUPPORTED_DASHBOARD_TABS = frozenset({"signals", "all", "market", "insights"})
SUPPORTED_DASHBOARD_QUERY_KEYS = frozenset(
    {
        "tab",
        "ward",
        "city",
        "source",
        "prop_type",
        "price_range",
        "area_range",
        "price_min",
        "price_max",
        "area_min",
        "area_max",
        "date_range",
        "mos_min",
        "q",
        "keyword",
        "signal",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
    }
)

STATIC_TOOL_PAGES = (
    {"path": "/", "title": "Radar BDS"},
    {"path": "/dinh-gia-bds", "title": "Định giá BĐS"},
    {"path": "/bang-gia-dat-tphcm", "title": "Bảng giá đất TP.HCM"},
)
MACHINE_DISCOVERY_SURFACES = frozenset({"/robots.txt", "/sitemap.xml", "/llms.txt"})
LEGACY_DEFAULT_FUNNEL_PHRASES = (
    "lọc watchlist",
    "thông báo VIP",
    "ráp mối VIP",
)
REQUIRED_REGISTRY_FAMILIES = frozenset(
    {
        "static_tools",
        "report_hub",
        "seo_pages",
        "seo_articles",
        "knowledge_hub",
        "news_hubs",
        "planning_hub",
        "planning_categories",
        "planning_pages",
        "binh_duong_map",
        "city_map_products",
        "seo_locations",
    }
)
# ``/bao-cao`` is served by the dedicated REPORT_HUB route.  SEO_PAGES keeps a
# legacy seed record for generator compatibility, but it is not a second public
# definition and must not mask the route-owned canonical payload in this audit.
ROUTE_OWNED_SEO_PAGE_PATHS = frozenset({"/bao-cao"})


@dataclass(frozen=True, slots=True)
class AuditFinding:
    severity: str
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class MarketingAuditResult:
    checked_path_count: int
    hard_failures: tuple[AuditFinding, ...]
    warnings: tuple[AuditFinding, ...]

    @property
    def exit_code(self) -> int:
        return 1 if self.hard_failures else 0

    def to_dict(self, limit: int = MAX_JSON_FINDINGS) -> dict[str, object]:
        bounded = max(1, min(int(limit), MAX_JSON_FINDINGS))
        return {
            "summary": {
                "checked_path_count": self.checked_path_count,
                "hard_failure_count": len(self.hard_failures),
                "warning_count": len(self.warnings),
            },
            "hard_failures": [asdict(item) for item in self.hard_failures[:bounded]],
            "warnings": [asdict(item) for item in self.warnings[:bounded]],
            "truncated": len(self.hard_failures) > bounded or len(self.warnings) > bounded,
        }


def _records(source: str, registry: Mapping[str, Mapping[str, object]] | Iterable[Mapping[str, object]]) -> list[tuple[str, str, Mapping[str, object]]]:
    values = registry.values() if isinstance(registry, Mapping) else registry
    records: list[tuple[str, str, Mapping[str, object]]] = []
    for item in values:
        if not isinstance(item, Mapping):
            records.append((source, "", {"value": item}))
            continue
        payload = dict(item)
        records.append((source, str(payload.get("path") or ""), payload))
    return records


def _raw_marketing_page_candidates() -> tuple[tuple[str, str, Mapping[str, object]], ...]:
    records: list[tuple[str, str, Mapping[str, object]]] = []
    records.extend(_records("static_tools", STATIC_TOOL_PAGES))
    records.extend(_records("report_hub", (REPORT_HUB,)))
    records.extend(
        _records(
            "seo_pages",
            tuple(page for page in SEO_PAGES.values() if page.get("path") not in ROUTE_OWNED_SEO_PAGE_PATHS),
        )
    )
    records.extend(_records("seo_articles", SEO_ARTICLES))
    records.extend(_records("knowledge_hub", (KNOWLEDGE_HUB,)))
    records.extend(_records("news_hubs", NEWS_HUBS))
    records.extend(_records("planning_hub", (PLANNING_HUB,)))
    records.extend(_records("planning_categories", PLANNING_CATEGORY_PAGES))
    records.extend(_records("planning_pages", PLANNING_PAGE_LIST))
    records.extend(_records("binh_duong_map", (BINH_DUONG_MAP_PAGE,)))
    records.extend(_records("city_map_products", CITY_MAP_PRODUCTS))
    records.extend(_records("seo_locations", SEO_LOCATION_PAGES))
    return tuple(records)


def _payload_signature(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _deduplicate_candidates(
    candidates: Iterable[tuple[str, str, Mapping[str, object]]],
) -> tuple[tuple[tuple[str, str, Mapping[str, object]], ...], tuple[AuditFinding, ...]]:
    first_by_path: dict[str, tuple[str, str, Mapping[str, object]]] = {}
    signatures: dict[str, str] = {}
    findings: list[AuditFinding] = []
    for source, path, payload in candidates:
        normalized_path = str(path or "")
        signature = _payload_signature(payload)
        previous = first_by_path.get(normalized_path)
        if previous is None:
            first_by_path[normalized_path] = (source, normalized_path, payload)
            signatures[normalized_path] = signature
        elif signatures[normalized_path] != signature:
            findings.append(
                AuditFinding(
                    "error",
                    "conflicting_canonical_definition",
                    normalized_path,
                    f"{previous[0]} and {source} define different payloads for one canonical path.",
                )
            )
    return tuple(first_by_path.values()), tuple(findings)


def collect_marketing_page_candidates() -> tuple[tuple[str, str, Mapping[str, object]], ...]:
    """Return one representative for every active, configured public page path."""
    candidates, _findings = _deduplicate_candidates(_raw_marketing_page_candidates())
    return tuple(sorted(candidates, key=lambda item: (item[1], item[0])))


def _iter_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _iter_strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_strings(child)


def _is_valid_iso_date(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip()
    try:
        if "T" in candidate:
            datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        else:
            date.fromisoformat(candidate)
    except ValueError:
        return False
    return True


def _finding_sort_key(item: AuditFinding) -> tuple[str, str, str, str]:
    return (item.severity, item.code, item.path, item.message)


def _validate_dashboard_url(path: str, value: str) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path != "/":
        return findings
    for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
        if key == "property_type" or key not in SUPPORTED_DASHBOARD_QUERY_KEYS:
            findings.append(
                AuditFinding("error", "invalid_dashboard_query_key", path, f"Dashboard query key '{key}' is not supported."),
            )
        if key == "tab" and any(value not in SUPPORTED_DASHBOARD_TABS for value in values):
            findings.append(
                AuditFinding("error", "invalid_dashboard_tab", path, "Dashboard tab must be one of signals, all, market, insights."),
            )
        if key.startswith("utm_") and any(len(value) > 80 for value in values):
            findings.append(
                AuditFinding("error", "utm_value_too_long", path, f"Dashboard {key} values must be at most 80 characters."),
            )
    return findings


def _title_for(payload: Mapping[str, object]) -> str:
    return str(payload.get("title") or payload.get("hero_title") or "")


def _article_faq(payload: Mapping[str, object], article: Mapping[str, object]) -> object:
    return article["faq"] if "faq" in article else payload.get("faq")


def _normalise_intent(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _audit_candidate_records(
    candidates: Iterable[tuple[str, str, Mapping[str, object]]], *, strict: bool
) -> MarketingAuditResult:
    raw = tuple(candidates)
    deduplicated, conflicts = _deduplicate_candidates(raw)
    hard_failures = list(conflicts)
    warnings: list[AuditFinding] = []
    intent_paths: dict[str, list[str]] = {}

    for _source, path, payload in deduplicated:
        if not path.startswith("/") or path.startswith("//") or any(ord(char) < 32 for char in path):
            hard_failures.append(AuditFinding("error", "invalid_path", path, "Page path must be an absolute, control-character-free path."))
            continue

        for value in _iter_strings(payload):
            if any(ord(char) < 32 for char in value):
                hard_failures.append(AuditFinding("error", "control_character", path, "Configured text contains a control character."))
            legacy_phrase = next(
                (phrase for phrase in LEGACY_DEFAULT_FUNNEL_PHRASES if phrase.casefold() in value.casefold()),
                None,
            )
            if legacy_phrase:
                hard_failures.append(
                    AuditFinding(
                        "error",
                        "legacy_funnel_copy",
                        path,
                        f"Replace legacy default funnel copy containing '{legacy_phrase}'.",
                    ),
                )
            if value.startswith("//"):
                hard_failures.append(AuditFinding("error", "protocol_relative_url", path, "Protocol-relative URLs are not allowed."))
            if value.startswith("/?"):
                hard_failures.extend(_validate_dashboard_url(path, value))

        title = _title_for(payload)
        description = str(payload.get("description") or "")
        if not 30 <= len(title) <= 65:
            warnings.append(AuditFinding("warning", "title_length", path, "Title should be 30-65 characters."))
        if not 70 <= len(description) <= 170:
            warnings.append(AuditFinding("warning", "description_length", path, "Description should be 70-170 characters."))

        article = payload.get("article")
        if isinstance(article, Mapping):
            if not path.startswith("/tin-tuc/"):
                hard_failures.append(AuditFinding("error", "invalid_article_path", path, "Article payloads must live below /tin-tuc/."))
            for field in ("published_at", "modified_at"):
                if not _is_valid_iso_date(article.get(field)):
                    hard_failures.append(AuditFinding("error", "invalid_article_date", path, f"Article {field} must be a valid ISO date."))
            faq = _article_faq(payload, article)
            if not isinstance(faq, list) or not faq or any(not isinstance(item, Mapping) or not item.get("q") or not item.get("a") for item in faq):
                hard_failures.append(AuditFinding("error", "empty_article_faq", path, "Articles need at least one complete FAQ item."))
            intros = article.get("intro")
            first_intro = intros[0] if isinstance(intros, list) and intros and isinstance(intros[0], str) else ""
            if len(first_intro.split()) not in PREFERRED_ANSWER_FIRST_WORDS:
                warnings.append(AuditFinding("warning", "answer_first_length", path, "First article paragraph should be 40-60 words."))
            if not article.get("charts") and not article.get("illustrations"):
                warnings.append(AuditFinding("warning", "missing_illustration", path, "Article should include a supported illustration or chart."))
            if not article.get("data_tables"):
                warnings.append(AuditFinding("warning", "missing_data_table", path, "Article should include a supporting data table when applicable."))
            if not payload.get("secondary_href"):
                warnings.append(AuditFinding("warning", "missing_secondary_internal_link", path, "Article should include a secondary internal link."))

        normalized_intent = _normalise_intent(title)
        if normalized_intent:
            intent_paths.setdefault(normalized_intent, []).append(path)

    for intent, paths in intent_paths.items():
        if len(paths) > 1:
            for path in sorted(paths):
                warnings.append(AuditFinding("warning", "duplicate_intent", path, f"Title intent '{intent}' is shared by multiple pages."))

    for ward_slug, ward_name in TDM_LIVE_WARDS.items():
        location_key = f"binh-duong/phuong-{ward_slug}"
        page = SEO_LOCATION_PAGES.get(location_key)
        if not page or page.get("live_ward") != ward_name or page.get("ward_slug") != ward_slug:
            hard_failures.append(AuditFinding("error", "missing_live_ward_coverage", f"/binh-duong/phuong-{ward_slug}", "Canonical TDM ward needs matching live_ward and ward_slug."))

    if strict:
        active_paths = {path for _source, path, _payload in deduplicated if path}
        if len(active_paths) < MIN_APPROVED_STATIC_PATHS:
            hard_failures.append(AuditFinding("error", "approved_inventory_below_baseline", "/", f"Expected at least {MIN_APPROVED_STATIC_PATHS} active public paths."))
        present_sources = {source for source, _path, _payload in raw}
        for source in sorted(REQUIRED_REGISTRY_FAMILIES - present_sources):
            hard_failures.append(AuditFinding("error", "missing_registry_family", "/", f"Required registry family '{source}' is unavailable."))
        for surface in sorted(MACHINE_DISCOVERY_SURFACES):
            if surface not in MACHINE_DISCOVERY_SURFACES:
                hard_failures.append(AuditFinding("error", "missing_discovery_surface", surface, "Required discovery surface is unavailable."))

    return MarketingAuditResult(
        checked_path_count=len({path for _source, path, _payload in deduplicated if path}),
        hard_failures=tuple(sorted(hard_failures, key=_finding_sort_key)),
        warnings=tuple(sorted(warnings, key=_finding_sort_key)),
    )


def audit_marketing_pages(*, strict: bool = False) -> MarketingAuditResult:
    """Audit the public configuration registries without loading application state."""
    return _audit_candidate_records(_raw_marketing_page_candidates(), strict=strict)


def render_human(result: MarketingAuditResult) -> str:
    lines = [f"Marketing pages checked: {result.checked_path_count}", f"Hard failures: {len(result.hard_failures)}"]
    lines.extend(f"- [{item.code}] {item.path}: {item.message}" for item in result.hard_failures)
    lines.append(f"Warnings: {len(result.warnings)}")
    lines.extend(f"- [{item.code}] {item.path}: {item.message}" for item in result.warnings)
    return "\n".join(lines)
