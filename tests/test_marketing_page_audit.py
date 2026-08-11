from __future__ import annotations

import json

from config.seo_locations import TDM_LIVE_WARDS
from scripts.audit_marketing_pages import main
from services.marketing_page_audit import (
    AuditFinding,
    MarketingAuditResult,
    _audit_candidate_records,
    _deduplicate_candidates,
    collect_marketing_page_candidates,
    render_human,
)


def test_real_registry_inventory_preserves_approved_baseline():
    candidates = collect_marketing_page_candidates()
    paths = {path for _source, path, _payload in candidates}

    assert len(paths) >= 124
    assert {"/", "/bao-cao", "/tin-tuc", "/ban-do-binh-duong"} <= paths
    assert "/dinh-gia-bds" in paths
    assert "/bang-gia-dat-tphcm" in paths


def test_canonical_ward_registry_has_all_thirteen_wards():
    assert len(TDM_LIVE_WARDS) == 13
    assert TDM_LIVE_WARDS["phu-tan"] == "Phú Tân"
    assert TDM_LIVE_WARDS["hiep-thanh"] == "Hiệp Thành"


def test_identical_aliases_are_deduplicated_but_conflicts_are_hard_failures():
    candidates = (
        ("one", "/same", {"path": "/same", "title": "Same"}),
        ("two", "/same", {"path": "/same", "title": "Same"}),
        ("three", "/same", {"path": "/same", "title": "Different"}),
    )

    deduplicated, findings = _deduplicate_candidates(candidates)

    assert len(deduplicated) == 1
    assert [item.code for item in findings] == ["conflicting_canonical_definition"]


def test_dashboard_contract_and_article_boundaries_are_hard_failures():
    candidates = (
        (
            "fixture",
            "/tin-tuc/example",
            {
                "path": "/tin-tuc/example",
                "title": "A sufficiently sized title for this fixture page",
                "description": "A description long enough to avoid the metadata warning for this deterministic fixture.",
                "primary_href": "/?tab=other&property_type=dat_nen&bad=1",
                "article": {
                    "published_at": "2026-02-30",
                    "modified_at": "not-a-date",
                    "intro": ["too short"],
                    "faq": [],
                },
            },
        ),
    )

    result = _audit_candidate_records(candidates, strict=False)
    codes = {item.code for item in result.hard_failures}

    assert {"invalid_dashboard_tab", "invalid_dashboard_query_key", "invalid_article_date", "empty_article_faq"} <= codes
    assert "answer_first_length" in {item.code for item in result.warnings}


def test_warning_only_result_exits_zero():
    result = MarketingAuditResult(
        checked_path_count=1,
        hard_failures=(),
        warnings=(AuditFinding("warning", "title_length", "/x", "short"),),
    )

    assert result.exit_code == 0
    assert "Warnings: 1" in render_human(result)


def test_hard_failure_exits_nonzero_and_json_is_bounded():
    result = MarketingAuditResult(
        checked_path_count=1,
        hard_failures=(AuditFinding("error", "invalid_tab", "/x", "bad"),),
        warnings=(AuditFinding("warning", "title_length", "/x", "short"),),
    )

    assert result.exit_code == 1
    payload = result.to_dict(limit=0)
    assert payload["summary"]["hard_failure_count"] == 1
    assert json.dumps(payload, ensure_ascii=False)
    assert payload["hard_failures"] == [{"severity": "error", "code": "invalid_tab", "path": "/x", "message": "bad"}]


def test_cli_supports_bounded_json_output(capsys):
    exit_code = main(["--json", "--limit", "1"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert len(payload["hard_failures"]) <= 1
    assert payload["summary"]["checked_path_count"] >= 124
