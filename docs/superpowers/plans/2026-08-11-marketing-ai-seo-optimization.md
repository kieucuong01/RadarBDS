# Marketing and AI SEO Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every public Radar BDS marketing page easier to discover, cite, trust, and convert while preserving the filtered-dashboard-to-signal funnel.

**Architecture:** Treat the existing config registries as the content source of truth, add a deterministic config-only audit layer, and centralize public trust/entity context before rendering it through existing templates. Keep live ward hydration fail-open, derive AI discovery from the same registries, and make only eight bounded content edits after shared-system correctness is green.

**Tech Stack:** Python 3.12, Flask, Jinja2, vanilla JavaScript, JSON-LD, pytest, PowerShell, Graphify

## Global Constraints

- Preserve the funnel `SEO / social / AI assistant -> exact public page -> filtered dashboard -> signal card -> contact or lead CTA`.
- Preserve every existing public route and self-canonical; the approved 124-URL inventory is a minimum protected baseline, not a ceiling for the daily publisher.
- Do not create thin pages, invent market evidence, or make watchlist, Telegram, or VIP upgrade the default public promise.
- `TDC` and `TDC Phú Chánh` continue to resolve through `Phú Tân`; `KDC Hiệp Thành` continues to resolve through `Hiệp Thành`.
- Live snapshot failures remain fail-open and must not substitute generated numbers or a false current-data claim.
- Add only schema fields supported by visible content; do not add ratings, reviews, people, credentials, or unsupported claims.
- Keep the permissive wildcard robots policy unchanged.
- The audit is config-only by default and never requires PostgreSQL, Redis, production HTTP, or an external LLM.
- Warnings never cause a non-zero audit exit; only hard failures do.
- Do not change crawl, normalization, valuation, deduplication, database schema, auth, Facebook/admin, or Telegram delivery code.
- Preserve unrelated workspace work. Use `superpowers:using-git-worktrees` before execution and stage only paths named by the current task.
- Do not push or deploy a branch that carries unrelated commits. Release only through `scripts/deploy_production.ps1` after a clean branch-topology check.
- A timeout is unverified, not a pass. Production completion requires deployed revision evidence plus public HTTP, sitemap, JSON-LD, and browser checks.

---

## File Structure

- Create `services/marketing_page_audit.py`: registry inventory, dashboard-link validation, hard-failure/warning model, bounded JSON output, and human rendering.
- Create `scripts/audit_marketing_pages.py`: thin CLI around the pure audit service.
- Create `tests/test_marketing_page_audit.py`: audit unit tests, real-registry contract tests, and CLI exit/output tests.
- Create `services/public_marketing.py`: truthful visible trust context plus stable Organization/WebSite entity nodes and references.
- Create `templates/partials/seo_trust.html`: one accessible visible trust panel with optional rows.
- Create `tests/test_public_marketing_trust.py`: rendered trust and schema contracts across page types.
- Modify `config/seo_locations.py`: one canonical 13-ward mapping and the five missing live ward fields.
- Modify `config/seo_articles.py`: two broken dashboard URLs and eight bounded answer-first introductions.
- Modify `config/seo_pages.py`: remove legacy default watchlist/VIP marketing copy from existing pages.
- Modify `app.py`: consume the canonical ward map, decorate page trust context, normalize schema entities, generate bounded `llms.txt`, and include `/llms.txt` in the sitemap.
- Modify `templates/seo_article.html`, `templates/seo_landing.html`, `templates/seo_report.html`, `templates/seo_report_hub.html`, `templates/seo_knowledge_hub.html`, `templates/news_portal.html`, and `templates/public_content_hub.html`: visible trust and matching JSON-LD.
- Modify `templates/valuation_tool.html` and `templates/tphcm_land_price_tool.html`: stable language/entity references only; visible source/method content stays unchanged.
- Modify `static/css/seo.css`: responsive trust-panel styles.
- Modify `scripts/generate_monthly_report.py` and `scripts/enhance_monthly_report_rich.py`: future-safe funnel copy.
- Modify `tests/test_public_seo.py`, `tests/test_traffic_seo_aio.py`, `tests/test_planning_pages.py`, `tests/test_city_map_product_pages.py`, `tests/test_thu_dau_mot_map_product_page.py`, `tests/test_valuation_tool_ui.py`, and `tests/test_tphcm_land_price_tool.py`: rendered route, discovery, and schema regression coverage.
- Modify `docs/growth_marketing_workflow.md`: durable audit/release command and hard-failure versus warning semantics.

### Task 1: Build the deterministic marketing-page audit

**Files:**
- Create: `services/marketing_page_audit.py`
- Create: `scripts/audit_marketing_pages.py`
- Create: `tests/test_marketing_page_audit.py`
- Modify: `config/seo_locations.py:1-9`

**Interfaces:**
- Produces: `TDM_LIVE_WARDS: Mapping[str, str]`, keyed by the 13 canonical ward slugs.
- Produces: `AuditFinding(severity: str, code: str, path: str, message: str)`.
- Produces: `MarketingAuditResult(checked_path_count: int, hard_failures: tuple[AuditFinding, ...], warnings: tuple[AuditFinding, ...])`.
- Produces: `collect_marketing_page_candidates() -> tuple[tuple[str, str, Mapping[str, object]], ...]` where each tuple is `(source, path, payload)`.
- Produces: `audit_marketing_pages(*, strict: bool = False) -> MarketingAuditResult`.
- Produces: `render_human(result: MarketingAuditResult) -> str` and `result.to_dict(limit: int = 200) -> dict[str, object]`.
- Guarantees: identical registry aliases are deduplicated; only conflicting definitions are hard failures.

- [ ] **Step 1: Add the canonical 13-ward constant and failing inventory tests**

Add this immutable mapping to `config/seo_locations.py` without yet changing the five page definitions:

```python
from types import MappingProxyType

TDM_LIVE_WARDS = MappingProxyType({
    "tan-an": "Tân An",
    "hiep-an": "Hiệp An",
    "tuong-binh-hiep": "Tương Bình Hiệp",
    "dinh-hoa": "Định Hòa",
    "chanh-my": "Chánh Mỹ",
    "phu-my": "Phú Mỹ",
    "phu-cuong": "Phú Cường",
    "phu-hoa": "Phú Hòa",
    "phu-loi": "Phú Lợi",
    "hiep-thanh": "Hiệp Thành",
    "chanh-nghia": "Chánh Nghĩa",
    "phu-tan": "Phú Tân",
    "hoa-phu": "Hòa Phú",
})
```

Write tests that import the not-yet-created audit service and assert the inventory includes all registry families, deduplicates `/bao-cao` and location aliases, and protects at least 124 unique active paths:

```python
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
```

- [ ] **Step 2: Run the new tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_marketing_page_audit.py -q`

Expected: import failure for `services.marketing_page_audit`.

- [ ] **Step 3: Implement immutable findings and bounded results**

Use dataclasses and fixed limits:

```python
from dataclasses import asdict, dataclass

MAX_JSON_FINDINGS = 200
MIN_APPROVED_STATIC_PATHS = 124

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
```

Sort findings by `(severity, code, path, message)` before constructing the result so human and JSON runs are deterministic.

- [ ] **Step 4: Implement registry collection and conflict-safe deduplication**

Import only config modules. Collect:

```python
STATIC_TOOL_PAGES = (
    {"path": "/", "title": "Radar BDS"},
    {"path": "/dinh-gia-bds", "title": "Định giá BĐS"},
    {"path": "/bang-gia-dat-tphcm", "title": "Bảng giá đất TP.HCM"},
)
```

Then add `REPORT_HUB`, `SEO_PAGES`, `SEO_ARTICLES`, `/tin-tuc`, `NEWS_HUBS`, `PLANNING_HUB`, `PLANNING_CATEGORY_PAGES`, `PLANNING_PAGE_LIST`, `BINH_DUONG_MAP_PAGE`, and `CITY_MAP_PRODUCTS`. Keep both source records for duplicated aliases. Compare duplicate payloads using a stable JSON signature with `ensure_ascii=False`, `sort_keys=True`, and `default=str`; emit `conflicting_canonical_definition` only when the same path has different signatures. Identical aliases remain one checked path.

- [ ] **Step 5: Implement hard checks and warnings**

Use these exact dashboard constants:

```python
SUPPORTED_DASHBOARD_TABS = frozenset({"signals", "all", "market", "insights"})
SUPPORTED_DASHBOARD_QUERY_KEYS = frozenset({
    "tab", "ward", "city", "source", "prop_type",
    "price_range", "area_range", "price_min", "price_max",
    "area_min", "area_max", "date_range", "mos_min",
    "q", "keyword", "signal", "utm_source", "utm_medium",
    "utm_campaign", "utm_content", "utm_term",
})
PREFERRED_ANSWER_FIRST_WORDS = range(40, 61)
```

Walk every nested string value in each payload. Validate only root-dashboard links beginning with `/?`. Parse with `urllib.parse.urlsplit` and `parse_qs`; hard-fail unknown keys, unsupported `tab`, any `property_type` key, protocol-relative values, control characters, or UTM values longer than 80 characters. Hard-fail missing/invalid path, article paths outside `/tin-tuc/`, invalid ISO `published_at`/`modified_at`, empty article FAQ or missing `q`/`a`, and any missing member of `TDM_LIVE_WARDS` in location coverage. In strict mode, hard-fail if the deduplicated inventory is below 124 or a required registry family is absent.

Emit warnings for title length outside 30-65 characters, description length outside 70-170 characters, first intro outside 40-60 whitespace-delimited words, missing illustration/data table/secondary internal link, and normalized duplicate title/intent candidates. Duplicate intent is warning-only.

- [ ] **Step 6: Add fixture-level tests for every severity boundary**

Test identical aliases, conflicting aliases, invalid query key, bad tab, malformed date, empty FAQ, metadata warning, intro warning, and JSON truncation. Verify warnings keep exit code zero:

```python
def test_warning_only_result_exits_zero():
    result = MarketingAuditResult(
        checked_path_count=1,
        hard_failures=(),
        warnings=(AuditFinding("warning", "title_length", "/x", "short"),),
    )
    assert result.exit_code == 0

def test_hard_failure_exits_nonzero():
    result = MarketingAuditResult(
        checked_path_count=1,
        hard_failures=(AuditFinding("error", "invalid_tab", "/x", "bad"),),
        warnings=(),
    )
    assert result.exit_code == 1
```

- [ ] **Step 7: Implement the thin CLI and test human/JSON modes**

The script must add the project root to `sys.path`, parse only `--json`, `--strict`, and `--limit`, print UTF-8, and return `result.exit_code`:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Radar BDS marketing pages")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)
    result = audit_marketing_pages(strict=args.strict)
    output = (
        json.dumps(result.to_dict(args.limit), ensure_ascii=False, indent=2)
        if args.as_json
        else render_human(result)
    )
    print(output)
    return result.exit_code
```

CLI tests call `main([...])` directly and assert bounded valid JSON. Do not spawn a subprocess in unit tests.

- [ ] **Step 8: Run GREEN tests, capture the expected repository findings, and commit**

```powershell
& $py -X utf8 -m pytest tests\test_marketing_page_audit.py -q
& $py -X utf8 scripts\audit_marketing_pages.py --strict
git add config/seo_locations.py services/marketing_page_audit.py scripts/audit_marketing_pages.py tests/test_marketing_page_audit.py
git commit -m "feat: add deterministic marketing page audit"
```

Expected: unit tests pass; the real strict audit exits non-zero only for the known CTA/live-ward hard failures that Tasks 2-3 will remove. Record the exact finding codes in the implementation log.

### Task 2: Repair CTA contracts and remove legacy default funnel copy

**Files:**
- Modify: `config/seo_articles.py:4579,7780-7787`
- Modify: `config/seo_pages.py:395,6046-10817`
- Modify: `scripts/generate_monthly_report.py:232-245`
- Modify: `scripts/enhance_monthly_report_rich.py:414-431`
- Modify: `templates/seo_report.html:264-320`
- Modify: `tests/test_marketing_page_audit.py`
- Modify: `tests/test_monthly_report_data.py`
- Modify: `tests/test_public_seo.py`

**Interfaces:**
- Consumes: Task 1 dashboard-link validator.
- Produces: all configured root-dashboard CTAs use supported keys and tab values.
- Guarantees: generated monthly reports say `lọc signal`/`xem tin phù hợp`, never `lọc watchlist` or default VIP/Telegram promises.

- [ ] **Step 1: Add failing real-registry and rendered-copy tests**

```python
def test_real_marketing_ctas_have_no_contract_failures():
    result = audit_marketing_pages(strict=False)
    forbidden = {"invalid_dashboard_query_key", "invalid_dashboard_tab"}
    assert not [item for item in result.hard_failures if item.code in forbidden]

def test_public_report_copy_uses_contact_funnel_not_vip_matching():
    html = radar_app.app.test_client().get("/bao-cao/phu-my-thang-07-2026").get_data(as_text=True)
    assert "Ráp mối VIP" not in html
    assert "Xem tin phù hợp" in html
```

Add generator source assertions for the absence of `lọc watchlist`, `thông báo VIP`, and `Ráp mối VIP` in public report/config/template files.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_marketing_page_audit.py tests\test_monthly_report_data.py tests\test_public_seo.py -q`

Expected: failures identify the two broken article URLs and legacy report copy.

- [ ] **Step 3: Fix the two live article links exactly**

Apply these replacements in `config/seo_articles.py`:

```python
"primary_href": "/?ward=Định%20Hòa&tab=signals"
```

and for both the page-level and final CTA:

```python
"/?tab=signals&prop_type=dat_nen&utm_source=seo&utm_medium=article&utm_campaign=land_under20"
```

Do not alter the canonical paths, UTM values, titles, or body copy in this step.

- [ ] **Step 4: Replace legacy default funnel language**

Use these canonical replacements:

```text
Mở dashboard để lọc watchlist -> Mở dashboard để lọc signal
Đưa tin sạch, MOS tốt và phù hợp bộ lọc lên dashboard hoặc thông báo VIP.
-> Đưa tin sạch, MOS tốt và phù hợp bộ lọc lên dashboard để người dùng xem và liên hệ.
▱ ⚡ Ráp mối VIP -> Xem tin phù hợp
```

Update the existing July report entries in `config/seo_pages.py`, the base generator, and the rich enhancer so regenerated pages cannot restore old language. Preserve lead forms and listing-detail links.

- [ ] **Step 5: Run GREEN tests and the audit CTA slice**

```powershell
& $py -X utf8 -m pytest tests\test_marketing_page_audit.py tests\test_monthly_report_data.py tests\test_public_seo.py -q
& $py -X utf8 scripts\audit_marketing_pages.py --json --limit 200
```

Expected: no `invalid_dashboard_query_key`, `invalid_dashboard_tab`, or `legacy_funnel_copy` hard finding; live-ward findings remain until Task 3.

- [ ] **Step 6: Commit CTA and generator corrections**

```powershell
git add config/seo_articles.py config/seo_pages.py scripts/generate_monthly_report.py scripts/enhance_monthly_report_rich.py templates/seo_report.html tests/test_marketing_page_audit.py tests/test_monthly_report_data.py tests/test_public_seo.py
git commit -m "fix: align marketing CTAs with signal funnel"
```

### Task 3: Extend live location coverage to all 13 Thủ Dầu Một wards

**Files:**
- Modify: `config/seo_locations.py:118-204`
- Modify: `app.py:81-98,2793-2808,3836-3843,3898-3902`
- Modify: `tests/test_traffic_seo_aio.py:7-184`
- Modify: `tests/test_marketing_page_audit.py`

**Interfaces:**
- Consumes: `TDM_LIVE_WARDS` from Task 1.
- Produces: every canonical TDM ward page has `live_ward` and `ward_slug`.
- Produces: `_PRIORITY_TDM_WARDS` is removed; redirects and `llms.txt` read the shared mapping.
- Preserves: `_build_live_location_snapshot(page: dict) -> dict` and its bounded fail-open behavior.

- [ ] **Step 1: Parameterize failing coverage and fail-open tests**

Replace the duplicated eight-ward test constant with the config mapping and assert all 13 definitions hydrate:

```python
from config.seo_locations import SEO_LOCATION_PAGES, TDM_LIVE_WARDS

def test_all_thirteen_tdm_pages_have_live_contract():
    for slug, ward in TDM_LIVE_WARDS.items():
        page = SEO_LOCATION_PAGES[f"binh-duong/phuong-{slug}"]
        assert page["live_ward"] == ward
        assert page["ward_slug"] == slug

def test_new_live_ward_degrades_without_database(monkeypatch):
    monkeypatch.setattr(radar_app, "load_dashboard_summary", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    response = radar_app.app.test_client().get("/binh-duong/phuong-phu-tan")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Dữ liệu trực tiếp tạm thời chưa khả dụng" in html
    assert not any(item.get("@type") == "Dataset" for item in _json_ld_graph(html))
```

Also expand redirect tests to all 13 canonical slugs and keep query-string preservation.

- [ ] **Step 2: Run tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_traffic_seo_aio.py tests\test_marketing_page_audit.py -q`

Expected: five missing `live_ward`/`ward_slug` pairs and five missing natural redirects.

- [ ] **Step 3: Add the five missing location fields**

Set these exact pairs in `LOCATION_DEFINITIONS`:

```python
{"slug": "phuong-tuong-binh-hiep", "live_ward": "Tương Bình Hiệp", "ward_slug": "tuong-binh-hiep"}
{"slug": "phuong-chanh-my", "live_ward": "Chánh Mỹ", "ward_slug": "chanh-my"}
{"slug": "phuong-phu-cuong", "live_ward": "Phú Cường", "ward_slug": "phu-cuong"}
{"slug": "phuong-phu-tan", "live_ward": "Phú Tân", "ward_slug": "phu-tan"}
{"slug": "phuong-hoa-phu", "live_ward": "Hòa Phú", "ward_slug": "hoa-phu"}
```

Insert the fields into the existing dictionaries; do not replace their curated context, intent, watch, or related lists.

- [ ] **Step 4: Make app redirects and discovery consume the shared mapping**

Import `TDM_LIVE_WARDS` in `app.py`, delete `_PRIORITY_TDM_WARDS`, use `TDM_LIVE_WARDS` in `seo_tdm_ward_redirect()` and the ward loop in `llms_txt()`. Do not touch `_REPORT_TDM_WARDS` in this task because it also encodes report-city classification.

- [ ] **Step 5: Verify live and fail-open behavior for old and new wards**

Run the parameterized tests with patched payloads. Assert the loader receives `wards=["Phú Tân"]` and that the rendered dashboard URL is `/?tab=signals&ward=Ph%C3%BA+T%C3%A2n`. Add explicit assertions that no code/config change introduced `TDC` as a separate public ward or `KDC Hiệp Thành` as a separate market.

- [ ] **Step 6: Run GREEN tests, strict audit, and commit**

```powershell
& $py -X utf8 -m pytest tests\test_traffic_seo_aio.py tests\test_marketing_page_audit.py -q
& $py -X utf8 scripts\audit_marketing_pages.py --strict
git add config/seo_locations.py app.py tests/test_traffic_seo_aio.py tests/test_marketing_page_audit.py
git commit -m "feat: cover all TDM ward landing snapshots"
```

Expected: strict audit has zero hard failures; metadata and content-quality warnings may remain.

### Task 4: Add one truthful visible trust contract

**Files:**
- Create: `services/public_marketing.py`
- Create: `templates/partials/seo_trust.html`
- Create: `tests/test_public_marketing_trust.py`
- Modify: `app.py:3156-3229,3335-3415,3490-3668,3846-3865`
- Modify: `templates/seo_article.html:11-25`
- Modify: `templates/seo_landing.html:156-240`
- Modify: `templates/seo_report.html:27-55`
- Modify: `templates/seo_report_hub.html:1-65`
- Modify: `templates/seo_knowledge_hub.html:8-50`
- Modify: `templates/news_portal.html`
- Modify: `templates/public_content_hub.html`
- Modify: `static/css/seo.css:2863-2900`

**Interfaces:**
- Produces: `build_trust_context(page: Mapping[str, object], *, page_type: str) -> dict[str, str]`.
- Trust keys: `owner_name`, `owner_url`, `published_at`, `modified_at`, `source_label`, `method_label`, `method_url`, `caveat`.
- Guarantees: empty optional values are omitted and a failed live snapshot never claims a current snapshot date.

- [ ] **Step 1: Write failing pure and rendered trust tests**

```python
def test_failed_live_snapshot_omits_false_update_date():
    page = {"variant": "location", "live_snapshot": {"available": False}}
    trust = build_trust_context(page, page_type="location")
    assert "modified_at" not in trust
    assert "tạm thời chưa khả dụng" in trust["source_label"]

@pytest.mark.parametrize("path, marker", [
    ("/tin-tuc/gia-rao-khac-gia-giao-dich-the-nao", "Nhóm dữ liệu Radar BDS"),
    ("/bao-cao/bds-binh-duong-thang-07-2026", "Phương pháp và giới hạn"),
    ("/binh-duong/phuong-hiep-thanh", "Nguồn dữ liệu"),
    ("/tin-tuc/du-lieu-radarbds", "Thông tin biên tập"),
])
def test_public_page_types_render_truthful_trust(path, marker):
    html = radar_app.app.test_client().get(path).get_data(as_text=True)
    assert 'class="seo-trust-panel"' in html
    assert marker in html
    assert "Nhóm dữ liệu Radar BDS" in html
```

Add negative assertions that planning/map pages keep their existing source sections and do not render a second `.seo-trust-panel`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_public_marketing_trust.py -q`

Expected: import failure and missing trust panel.

- [ ] **Step 3: Implement the pure trust builder**

Use truthful fixed identity and page-owned dates:

```python
EDITORIAL_OWNER_NAME = "Nhóm dữ liệu Radar BDS"
EDITORIAL_OWNER_URL = "/san-deal-bds"
DEFAULT_CAVEAT = (
    "Dữ liệu dùng để sàng lọc ban đầu, không thay thế kiểm tra thực địa, "
    "quy hoạch, pháp lý hoặc định giá chính thức."
)

def build_trust_context(page, *, page_type):
    article = page.get("article") or {}
    report = page.get("report") or {}
    snapshot = page.get("live_snapshot") or {}
    values = {
        "owner_name": EDITORIAL_OWNER_NAME,
        "owner_url": EDITORIAL_OWNER_URL,
        "published_at": str(article.get("published_at") or report.get("published_at") or ""),
        "modified_at": str(
            article.get("modified_at")
            or report.get("data_as_of")
            or page.get("latest_modified_at")
            or page.get("updated_at")
            or ""
        ),
        "method_label": "Cách Radar BDS lọc và đối chiếu dữ liệu",
        "method_url": "/san-deal-bds",
        "caveat": DEFAULT_CAVEAT,
    }
    if page_type == "location":
        values["modified_at"] = str(snapshot.get("updated_iso") or "") if snapshot.get("available") else ""
        values["source_label"] = (
            "Tin rao công khai Radar BDS đang theo dõi."
            if snapshot.get("available")
            else "Dữ liệu trực tiếp tạm thời chưa khả dụng; trang giữ nội dung phương pháp thường trực."
        )
    elif page_type == "report":
        values["source_label"] = str(report.get("source_note") or "Dữ liệu Radar BDS đã sàng lọc.")
    else:
        values["source_label"] = str(page.get("source_note") or "Nội dung và dữ liệu biên tập bởi Radar BDS.")
    return {key: value for key, value in values.items() if value}
```

Do not synthesize dates from `datetime.now()` in this service.

- [ ] **Step 4: Decorate only eligible page families in app routes**

Add a small helper in `app.py`:

```python
def _with_public_trust(page: dict, page_type: str) -> dict:
    page["trust"] = build_trust_context(page, page_type=page_type)
    return page
```

Call it after live/report hydration and before `render_template()` for articles, reports, locations, report hub, knowledge/news hub, news portal, and public-content hubs. Before decorating a hub, set `latest_modified_at` from the maximum truthful child `modified_at`, `updated_at`, or report `published_at`; leave it empty when the collection is empty. Do not attach it to planning detail/hub/category, Bình Dương map, or city-map product routes because those already render stronger source/method sections.

- [ ] **Step 5: Implement the accessible partial and include it once**

```html
{% if page.trust %}
<aside class="seo-trust-panel" aria-label="Thông tin biên tập và nguồn dữ liệu">
  <p class="seo-eyebrow">Thông tin biên tập</p>
  <dl>
    <div><dt>Biên tập</dt><dd><a href="{{ page.trust.owner_url }}">{{ page.trust.owner_name }}</a></dd></div>
    {% if page.trust.published_at %}<div><dt>Xuất bản</dt><dd><time datetime="{{ page.trust.published_at }}">{{ page.trust.published_at }}</time></dd></div>{% endif %}
    {% if page.trust.modified_at %}<div><dt>Cập nhật</dt><dd><time datetime="{{ page.trust.modified_at }}">{{ page.trust.modified_at }}</time></dd></div>{% endif %}
    {% if page.trust.source_label %}<div><dt>Nguồn dữ liệu</dt><dd>{{ page.trust.source_label }}</dd></div>{% endif %}
  </dl>
  <p><a href="{{ page.trust.method_url }}">{{ page.trust.method_label }}</a></p>
  <p class="seo-trust-caveat">{{ page.trust.caveat }}</p>
</aside>
{% endif %}
```

Place it below the page header/hero and above the main data/body section. For report detail, keep the existing full method section; the partial supplies owner/date/source summary only.

- [ ] **Step 6: Style the panel without changing existing layout contracts**

Add one neutral bordered panel using existing CSS variables, a wrapping `dl` grid, 14px body text, visible focus state, and a single-column mobile rule below 768px. Do not add icons, animation, or new fonts.

- [ ] **Step 7: Run rendered trust tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_public_marketing_trust.py tests\test_public_seo.py tests\test_public_content_hubs.py -q
git add services/public_marketing.py templates/partials/seo_trust.html app.py templates/seo_article.html templates/seo_landing.html templates/seo_report.html templates/seo_report_hub.html templates/seo_knowledge_hub.html templates/news_portal.html templates/public_content_hub.html static/css/seo.css tests/test_public_marketing_trust.py tests/test_public_seo.py tests/test_public_content_hubs.py
git commit -m "feat: add truthful public trust context"
```

### Task 5: Normalize stable entity and JSON-LD contracts

**Files:**
- Modify: `services/public_marketing.py`
- Modify: `app.py:1800-1875,2066-2445,2702-2746,3156-3229,3335-3415,3490-3518,3693-3724,3846-3865`
- Modify: `templates/seo_article.html:183-213`
- Modify: `templates/seo_landing.html:38-151`
- Modify: `templates/seo_report.html:363-385`
- Modify: `templates/seo_report_hub.html:159-172`
- Modify: `templates/seo_knowledge_hub.html:188-203`
- Modify: `templates/valuation_tool.html:23-91`
- Modify: `templates/tphcm_land_price_tool.html:18-29`
- Modify: `tests/test_public_marketing_trust.py`
- Modify: `tests/test_planning_pages.py`
- Modify: `tests/test_city_map_product_pages.py`
- Modify: `tests/test_thu_dau_mot_map_product_page.py`
- Modify: `tests/test_valuation_tool_ui.py`
- Modify: `tests/test_tphcm_land_price_tool.py`

**Interfaces:**
- Produces: `build_public_entities(base_url: str) -> dict[str, dict[str, object]]`.
- Entity keys: `organization`, `website`, `organization_ref`, `website_ref`.
- Stable IDs: `https://radarbds.vn/#organization` and `https://radarbds.vn/#website`.
- Guarantees: page/article/report nodes use `inLanguage: vi-VN`; visible dates and FAQ remain authoritative.

- [ ] **Step 1: Write failing entity and representative schema tests**

Parse every JSON-LD script as JSON and cover article, report, location, hub, planning detail, Bình Dương map, city-map product, valuation tool, and TP.HCM land-price tool:

```python
def assert_stable_public_entities(graph):
    by_id = {item.get("@id"): item for item in graph if item.get("@id")}
    assert "https://radarbds.vn/#organization" in by_id
    assert "https://radarbds.vn/#website" in by_id
    assert by_id["https://radarbds.vn/#organization"]["url"] == "https://radarbds.vn/"

def test_article_schema_matches_visible_trust():
    html = client.get("/tin-tuc/gia-rao-khac-gia-giao-dich-the-nao").get_data(as_text=True)
    graph = _json_ld_graph(html)
    article = next(item for item in graph if item.get("@type") == "BlogPosting")
    assert article["inLanguage"] == "vi-VN"
    assert article["author"] == {"@id": "https://radarbds.vn/#organization"}
    assert article["publisher"] == {"@id": "https://radarbds.vn/#organization"}
    assert article["dateModified"] in html
    assert_stable_public_entities(graph)
```

For FAQ pages, compare schema question/answer text to visible HTML. For fail-open locations, assert no Dataset node. Assert no AggregateRating, Review, Person, or invented credentials anywhere in the sampled graphs.

- [ ] **Step 2: Run representative tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_public_marketing_trust.py tests\test_planning_pages.py tests\test_city_map_product_pages.py tests\test_valuation_tool_ui.py tests\test_tphcm_land_price_tool.py -q`

Expected: stable entity IDs/language are missing from at least the article, report, hub, and tools.

- [ ] **Step 3: Add the shared entity builder**

```python
PUBLIC_LANGUAGE = "vi-VN"

def build_public_entities(base_url: str) -> dict[str, dict[str, object]]:
    root = f"{str(base_url).rstrip('/')}/"
    organization_id = f"{root}#organization"
    website_id = f"{root}#website"
    return {
        "organization": {
            "@type": "Organization",
            "@id": organization_id,
            "name": "Radar BDS",
            "url": root,
            "logo": {"@type": "ImageObject", "url": f"{root}static/images/app-icon-512.png"},
        },
        "website": {
            "@type": "WebSite",
            "@id": website_id,
            "name": "Radar BDS",
            "url": root,
            "inLanguage": PUBLIC_LANGUAGE,
            "publisher": {"@id": organization_id},
        },
        "organization_ref": {"@id": organization_id},
        "website_ref": {"@id": website_id},
    }
```

Return fresh dictionaries per call; do not expose a mutable module singleton.

- [ ] **Step 4: Wire entity context into template-rendered schemas**

Pass `public_entities=build_public_entities(PUBLIC_BASE_URL)` to eligible templates, including the valuation and TP.HCM land-price routes near `app.py:1800-1875`. In each JSON-LD graph:

- append `public_entities.organization` and `public_entities.website` once;
- add `inLanguage: "vi-VN"` to BlogPosting, Article, Report, WebPage, CollectionPage, Dataset, and WebApplication nodes where relevant;
- use `organization_ref` for author/publisher/creator/provider;
- use `website_ref` for `isPartOf`;
- preserve visible `datePublished`, `dateModified`, FAQ text, Dataset values, and all canonical URLs.

Do not change schema types or add schema fields that lack visible support.

- [ ] **Step 5: Normalize app-built graphs with the same entities**

Add `_public_schema_graph(*nodes: dict) -> dict` in `app.py`:

```python
def _public_schema_graph(*nodes: dict) -> dict:
    entities = build_public_entities(PUBLIC_BASE_URL)
    return {
        "@context": "https://schema.org",
        "@graph": [*nodes, entities["organization"], entities["website"]],
    }
```

Use it in `_planning_hub_schema`, `_planning_detail_schema`, `_binh_duong_map_schema`, `city_map_product_schema`, category/collection schema, and legal document graph. Add `inLanguage` to their public content nodes and replace inline Radar BDS Organization/WebSite objects with stable references. Keep the GovernmentOrganization author on Legislation unchanged.

- [ ] **Step 6: Run all schema tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_public_marketing_trust.py tests\test_public_seo.py tests\test_planning_pages.py tests\test_city_map_product_pages.py tests\test_thu_dau_mot_map_product_page.py tests\test_valuation_tool_ui.py tests\test_tphcm_land_price_tool.py -q
git add services/public_marketing.py app.py templates/seo_article.html templates/seo_landing.html templates/seo_report.html templates/seo_report_hub.html templates/seo_knowledge_hub.html templates/valuation_tool.html templates/tphcm_land_price_tool.html tests/test_public_marketing_trust.py tests/test_public_seo.py tests/test_planning_pages.py tests/test_city_map_product_pages.py tests/test_thu_dau_mot_map_product_page.py tests/test_valuation_tool_ui.py tests/test_tphcm_land_price_tool.py
git commit -m "feat: unify public entity schema"
```

### Task 6: Generate bounded AI discovery from registries

**Files:**
- Modify: `app.py:2967-2993,3898-4079`
- Modify: `tests/test_traffic_seo_aio.py:151-184`
- Modify: `tests/test_public_seo.py:44-65`
- Modify: `tests/test_marketing_page_audit.py`

**Interfaces:**
- Produces: `_llms_priority_reports(limit: int = 8) -> list[dict]`.
- Produces: `_llms_priority_articles(limit: int = 12) -> list[dict]`.
- `/llms.txt` includes all 13 canonical wards, at most 8 current reports, and at most 12 priority articles.
- `/sitemap.xml` includes `/llms.txt` exactly once and never includes `/agent/site.json` or `/agent/openapi.json`.

- [ ] **Step 1: Add failing bounded discovery tests**

```python
def test_llms_has_all_wards_and_bounded_current_content():
    body = radar_app.app.test_client().get("/llms.txt").get_data(as_text=True)
    for slug in TDM_LIVE_WARDS:
        assert f"https://radarbds.vn/binh-duong/phuong-{slug}" in body
    report_block = body.split("## Báo cáo mới", 1)[1].split("## Bài phân tích ưu tiên", 1)[0]
    article_block = body.split("## Bài phân tích ưu tiên", 1)[1].split("##", 1)[0]
    assert report_block.count("\n-") <= 8
    assert article_block.count("\n-") <= 12

def test_sitemap_contains_llms_but_not_agent_json():
    sitemap = radar_app.app.test_client().get("/sitemap.xml").get_data(as_text=True)
    assert sitemap.count("<loc>https://radarbds.vn/llms.txt</loc>") == 1
    assert "/agent/site.json" not in sitemap
    assert "/agent/openapi.json" not in sitemap
```

Also assert the newest publishable report and newest article appear, output is stable across two calls, and no live counts such as `204 tin` leak into `llms.txt`.

- [ ] **Step 2: Run tests and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_traffic_seo_aio.py tests\test_public_seo.py tests\test_marketing_page_audit.py -q`

Expected: missing bounded report/article sections and missing sitemap `/llms.txt`.

- [ ] **Step 3: Implement deterministic bounded selectors**

```python
def _llms_priority_reports(limit: int = 8) -> list[dict]:
    bounded = max(1, min(int(limit), 20))
    return sorted(_published_report_pages(), key=_report_sort_key, reverse=True)[:bounded]

def _llms_priority_articles(limit: int = 12) -> list[dict]:
    bounded = max(1, min(int(limit), 30))
    articles = [dict(page) for page in SEO_ARTICLES.values() if str(page.get("path") or "").startswith("/tin-tuc/")]
    return sorted(
        articles,
        key=lambda page: (
            int(page.get("ai_priority") or 0),
            str((page.get("article") or {}).get("modified_at") or ""),
            str((page.get("article") or {}).get("published_at") or ""),
            str(page.get("path") or ""),
        ),
        reverse=True,
    )[:bounded]
```

Render their `hero_title` and canonical `_public_url(path)` into two named sections. Generate ward lines from `TDM_LIVE_WARDS`. Keep agent JSON links in the AI-agent section only.

- [ ] **Step 4: Add `/llms.txt` as a web discovery document**

Add a page record to the sitemap candidate list:

```python
{"path": "/llms.txt", "updated_at": max(news_lastmod, content_lastmod.get("radar_article", ""))}
```

Let existing `seen_paths` dedupe it. Do not add JSON endpoints or API URLs to the sitemap. Keep robots unchanged.

- [ ] **Step 5: Extend audit coverage for discovery documents**

The strict audit must require `/llms.txt`, `/robots.txt`, and `/sitemap.xml` as machine surfaces in its summary while keeping them outside the active 124-page baseline count. Add a rendered sitemap test as the authoritative proof that every active registry path plus `/llms.txt` is present exactly once.

- [ ] **Step 6: Run GREEN tests and commit**

```powershell
& $py -X utf8 -m pytest tests\test_traffic_seo_aio.py tests\test_public_seo.py tests\test_marketing_page_audit.py -q
git add app.py tests/test_traffic_seo_aio.py tests/test_public_seo.py tests/test_marketing_page_audit.py
git commit -m "feat: generate bounded AI discovery links"
```

### Task 7: Tighten the eight selected answer-first introductions

**Files:**
- Modify: `config/seo_articles.py:8973-12600`
- Modify: `tests/test_marketing_page_audit.py`
- Modify: `tests/test_public_seo.py`

**Interfaces:**
- Consumes: Task 1 preferred first-paragraph range of 40-60 words.
- Produces: exactly eight selected current article intros in that range.
- Preserves: article canonical paths, dates, verified figures, caveats, sections, FAQ, tables, charts, and CTAs.

- [ ] **Step 1: Add a failing exact-slug content test**

```python
ANSWER_FIRST_REWRITE_SLUGS = (
    "duoi-3-ty-nen-xem-hiep-thanh-hay-phu-tan-truoc",
    "dinh-hoa-hay-hiep-thanh-nen-xem-khu-nao-truoc",
    "hiep-thanh-hay-tan-an-nen-xem-khu-nao-truoc",
    "tan-an-hay-phu-hoa-nen-xem-khu-nao-truoc",
    "bang-gia-dat-va-gia-rao-khac-nhau-the-nao",
    "dat-nen-duoi-3-ty-phu-tan-hay-phu-my-con-nhieu-lua-chon-hon",
    "duoi-3-ty-nen-xem-phu-tan-hay-dinh-hoa-truoc",
    "phu-loi-hay-hiep-thanh-nen-loc-dat-nen-hay-nha-dat-truoc",
)

def test_selected_answer_first_intros_are_bounded():
    assert len(ANSWER_FIRST_REWRITE_SLUGS) == 8
    for slug in ANSWER_FIRST_REWRITE_SLUGS:
        first = SEO_ARTICLES[slug]["article"]["intro"][0]
        assert 40 <= len(first.split()) <= 60
```

Snapshot each article's path, published/modified dates, numerical tokens, and remaining section/FAQ counts before editing; assert those values do not change.

- [ ] **Step 2: Run the exact test and verify RED**

Run: `& $py -X utf8 -m pytest tests\test_marketing_page_audit.py::test_selected_answer_first_intros_are_bounded -q`

Expected: all or some selected paragraphs exceed 60 words.

- [ ] **Step 3: Replace the eight first paragraphs with approved bounded copy**

Use these exact replacements, one per slug in the same order as the test set:

```text
Với ngân sách dưới 3 tỷ, nên mở Phú Tân trước khi tìm đất nền; nếu ưu tiên nhà xây sẵn, hãy xem Hiệp Thành song song. Dữ liệu Radar BDS cho thấy Phú Tân có nguồn đất nền dưới 3 tỷ dày hơn, còn Hiệp Thành nhỉnh hơn về số tin nhà đất cùng ngân sách.

Nếu cần nhiều lựa chọn và ngân sách dễ thở hơn, nên mở Định Hòa trước; nếu muốn xem thêm nhà đất ở mặt bằng giá cao hơn, hãy so song song với Hiệp Thành. Kết luận chỉ có ý nghĩa khi tách riêng đất nền và nhà đất.

Nếu cần nhiều lựa chọn, nên mở Tân An trước; nếu ưu tiên tin đáng kiểm tra hoặc đất nền có giá/m² thấp hơn, hãy xem Hiệp Thành song song. Dữ liệu là giá rao Facebook Radar BDS theo dõi ngày 01/08/2026, không phải giá giao dịch.

Nếu cần nguồn hàng dày, giá mềm và lọc nhanh dưới 4 tỷ, nên mở Tân An trước; nếu muốn xem khu có nhịp giá và nguồn nhà đất cao hơn, hãy mở Phú Hòa sau. Dữ liệu là giá rao Facebook Radar BDS theo dõi ngày 05/08/2026.

Bảng giá đất thấp hơn giá rao thị trường không phải lỗi dữ liệu: bảng giá là mốc nhà nước, còn giá rao là mức người bán đang chào. Khi lọc tin Bình Dương, nên ưu tiên giá rao cùng phường, cùng loại hình và dùng bảng giá như một lớp tham chiếu pháp lý.

Nếu lọc đất nền dưới 3 tỷ giữa Phú Tân và Phú Mỹ, nên mở Phú Tân trước. Dữ liệu Radar BDS ngày 07/08/2026 ghi nhận 299 tin phù hợp tại Phú Tân và 210 tin tại Phú Mỹ. Đây là giá rao Facebook công khai, không phải giá chốt giao dịch.

Với trần 3 tỷ, nên mở Định Hòa trước để có nhiều lựa chọn hơn, rồi xem Phú Tân khi muốn soi nhóm đất nền đáng chú ý. Dữ liệu trong bài là giá rao Facebook Radar BDS theo dõi ngày 08/08/2026, không phải giá chốt giao dịch.

Nếu ưu tiên đất nền, nên mở Phú Lợi trước; nếu tìm nhà đất dưới 4 tỷ, nên mở Hiệp Thành trước. Dữ liệu Radar BDS ngày 09/08/2026 cho thấy khác biệt chính giữa hai phường nằm ở cơ cấu loại hình và số tin còn trong vùng ngân sách phổ biến.
```

Do not edit title/description outliers or merge/redirect suspected duplicate-intent pages without Search Console query evidence.

- [ ] **Step 4: Verify content invariants and warning-only audit behavior**

```powershell
& $py -X utf8 -m pytest tests\test_marketing_page_audit.py tests\test_public_seo.py -q
& $py -X utf8 scripts\audit_marketing_pages.py --strict
```

Expected: eight selected intro tests pass; remaining metadata/duplicate-intent findings are warnings; audit exits zero.

- [ ] **Step 5: Commit bounded content changes**

```powershell
git add config/seo_articles.py tests/test_marketing_page_audit.py tests/test_public_seo.py
git commit -m "content: tighten answer-first article intros"
```

### Task 8: Document, verify, release safely, and prove production

**Files:**
- Modify: `docs/growth_marketing_workflow.md`
- Verify only: all scoped implementation files from Tasks 1-7

**Interfaces:**
- Produces: a repeatable local audit command and a release evidence record.
- Guarantees: no completion claim without scoped tests, clean Git topology, deployed revision, and public proof.

- [ ] **Step 1: Document the durable audit contract**

Add this workflow block to `docs/growth_marketing_workflow.md`:

```powershell
& $py -X utf8 scripts\audit_marketing_pages.py --strict
& $py -X utf8 scripts\audit_marketing_pages.py --json --limit 200
```

Document that hard failures are canonical/query/date/FAQ/sitemap/schema/live-ward contract breaches; metadata length, answer-first length, duplicate intent, and optional visual/link gaps are warnings. State that config-only audit does not prove production indexing, rankings, or traffic.

- [ ] **Step 2: Run syntax and focused audit checks**

```powershell
& $py -X utf8 -m py_compile app.py services\marketing_page_audit.py services\public_marketing.py scripts\audit_marketing_pages.py scripts\generate_monthly_report.py scripts\enhance_monthly_report_rich.py config\seo_articles.py config\seo_locations.py config\seo_pages.py
node --check static\js\main.js
& $py -X utf8 scripts\audit_marketing_pages.py --strict
& $py -X utf8 scripts\audit_marketing_pages.py --json --limit 200
```

Expected: compilation/syntax pass, both audit modes report zero hard failures, JSON parses, warnings remain bounded.

- [ ] **Step 3: Run the existing 152-test marketing matrix plus new tests**

```powershell
& $py -X utf8 -m pytest tests\test_public_seo.py tests\test_public_content_hubs.py tests\test_traffic_seo_aio.py tests\test_planning_pages.py tests\test_city_map_product_pages.py tests\test_thu_dau_mot_map_product_page.py tests\test_valuation_tool_ui.py tests\test_tphcm_land_price_tool.py tests\test_marketing_page_audit.py tests\test_public_marketing_trust.py -q
```

Expected: all existing 152 tests and all new audit/trust tests pass. Report the new total from pytest output; do not reuse the old count as the result.

- [ ] **Step 4: Render representative pages and parse every JSON-LD block**

Use the Flask test client for `/`, one core landing, one old live ward, one newly live ward, report hub/detail, news hub/article, planning hub/detail, Bình Dương map, one city-map product, valuation tool, TP.HCM land-price tool, and a legal-document detail fixture. Assert HTTP 200, one self-canonical, visible H1, no unsupported CTA query, and valid JSON for every `application/ld+json` block.

- [ ] **Step 5: Refresh structural evidence after code changes**

```powershell
graphify update .
graphify query "marketing SEO pages trust schema sitemap llms"
```

Treat this as structural evidence only. Verify every important relationship against imports/tests already run.

- [ ] **Step 6: Run Git scope checks and commit documentation**

```powershell
git diff --check
git status --short
git add docs/growth_marketing_workflow.md
git diff --cached --name-only
git commit -m "docs: add marketing AI SEO audit workflow"
```

Expected staged output before commit: exactly `docs/growth_marketing_workflow.md`. Leave `.playwright-cli/` and all unrelated files untouched.

- [ ] **Step 7: Verify clean release topology before any push**

Fetch without merging, then inspect exact commits:

```powershell
git fetch origin
git log --oneline --decorate origin/main..HEAD
git diff --name-status origin/main...HEAD
```

Proceed only when the branch contains the approved design/plan and Tasks 1-8 changes, with no Facebook/admin/unrelated files. If not clean, stop and report the exact commits/files; do not push, stash, reset, or rebase user-owned work into the release.

- [ ] **Step 8: Push and deploy only after the release gate is authorized and clean**

```powershell
git push -u origin codex/marketing-ai-seo
.\scripts\deploy_production.ps1
```

If production deploys from `main`, integrate the verified scoped branch using the repository's approved merge flow, rerun Steps 2-4 on the integrated SHA, then invoke the wrapper. Do not manually reproduce the wrapper's remote commands.

- [ ] **Step 9: Verify all public sitemap URLs and representative browser behavior**

After deploy, fetch `https://radarbds.vn/sitemap.xml`, parse every `<loc>`, and require HTTP 200 for every sitemap URL. Separately verify:

```text
/robots.txt
/llms.txt
/agent/site.json
/agent/openapi.json
/tin-tuc/gia-dat-dinh-hoa-thu-dau-mot-cap-nhat-thang-7-2026
/tin-tuc/dat-nen-thu-dau-mot-duoi-20-trieu-m2-con-o-phuong-nao
/binh-duong/phuong-phu-tan
/bao-cao/bds-binh-duong-thang-07-2026
/quy-hoach-binh-duong
/ban-do-thu-dau-mot
/dinh-gia-bds
/bang-gia-dat-tphcm
```

For representative HTML pages, assert deployed self-canonical, trust panel where expected, valid JSON-LD, all 13 ward links in `llms.txt`, `/llms.txt` exactly once in sitemap, and agent JSON absent from sitemap. Use a real browser at desktop and mobile widths to click the two repaired article CTAs and confirm the dashboard opens the Signals tab with `ward=Định Hòa` or `prop_type=dat_nen` hydrated. Check console for errors.

- [ ] **Step 10: Record honest completion evidence**

Report local test totals, audit summary, pushed branch/SHA, deployed release/SHA, sitemap URL count, failed URL count, representative schema types, CTA browser results, and any skipped/unverified gates separately. Do not claim indexing/ranking gains without Search Console/Bing evidence.

---

## Final Acceptance Checklist

- [ ] At least the approved 124 static marketing paths remain represented; valid daily-publisher additions are allowed.
- [ ] No marketing CTA uses `property_type=` or an unsupported `tab` value.
- [ ] All 13 canonical Thủ Dầu Một ward pages use the bounded live/fail-open contract.
- [ ] Public page types display truthful editorial/update/source/method information without duplicating stronger map/planning source sections.
- [ ] All sampled JSON-LD parses, uses stable Radar BDS entity IDs, declares `vi-VN`, and matches visible dates/FAQ/source claims.
- [ ] `/llms.txt` contains all 13 wards plus bounded current reports/articles and appears once in sitemap.
- [ ] Agent JSON stays linked from `llms.txt` and remains outside sitemap.
- [ ] Audit exits zero with no hard failures; warnings remain visible and bounded.
- [ ] Eight selected answer-first intros are 40-60 words with figures, dates, and caveats preserved.
- [ ] Existing marketing matrix and all new tests pass.
- [ ] Unrelated workspace files and commits remain untouched.
- [ ] Production success is supported by deployed revision, all-sitemap HTTP proof, parsed schema, and browser CTA checks.
