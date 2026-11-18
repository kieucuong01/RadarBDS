# Monthly verifier regression fixtures

Public HTML excerpts captured on 2026-11-18 (+07) from:

- `https://radarbds.vn/bao-cao/bds-binh-duong-thang-10-2026`
- `https://radarbds.vn/bao-cao/tan-an-thang-10-2026`

Keep chart metadata/canvases, buyer summary/examples/current-listing CTA,
related reports, SEO links and ward inline filters. Omit site header/footer,
scripts and images. No generated report data or private/contact fields were
added. Ward copies in tests only substitute the report path to exercise the
same verifier loop; they do not claim to represent the other live wards.

## Root cause

Commit `c0bc6782` (2026-10-25) switched the verifier's card counter to
`buyer-example` for `data-buyer-report="v1"`, but left the master's legacy
`cards == 0` predicate. `services/report_buyer.py` intentionally provides
`examples[:6]` to **both** master and ward pages;
`templates/seo_report.html` includes `partials/report_buyer_overview.html`
unconditionally. October's master has six saved comparison examples, not
unexpected legacy signal cards. September's master has zero, so the former
September fixture did not expose this regression.

The fix applies the buyer-v1 contract only to buyer masters: 0–6 examples,
with the current-listing CTA required when examples exist. Legacy masters
still require zero signal cards. All chart/PDF/filtered CTA/SEO/child-link
checks remain intact; no template, data, privacy or small-sample gate changes.

## Important live prerequisite

At capture, neither HTML page contained a versioned PDF download link.
The fixtures preserve that absence. Positive tests explicitly append a
**test-only** PDF anchor to isolate the master-card bug. The unmodified live
fixture must still fail verification. This must not be reported as live GREEN.

The read-only patched `verify_live(10, 2026)` returned 3: all 14 URLs were 200,
charts matched, sitemap covered 14/14, but all 14 had `pdf=False`. Master had
`cards=6 cards_ok=True`, two canvases and 13 child links. Its live PDF version
was `4f5deb6878849332d9dc`; the matching file was absent from
`/opt/radar-bds/current/reports/monthly-pdf/`, where an older version
`575e5d8ed3313dbe6e4c` remained. Repair/rebuild of production PDF artifacts is
outside this verifier-only patch and requires the owner's approved release
path. Do not bypass `has_pdf`, regenerate historical reports, or use the
publisher's `--dry-run` as a read-only verifier.

## Safe execution boundary

From the isolated worktree, use the project interpreter and import only the
stdlib-only publisher module; call `verify_live`, never `main`:

```bash
/opt/radar-bds/.venv/bin/python -B -c 'import importlib.util; s=importlib.util.spec_from_file_location("monthly", "scripts/radar_monthly_report_publish.py"); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); raise SystemExit(m.verify_live(10,2026))'
```

Regression suite: `tests/test_monthly_report_publish.py` (33 cases).
Focused additional checks: pure monthly data, buyer snapshot, buyer presentation
and PDF-ordering tests. Exclude the snapshot `real_postgres` test: it creates
and inserts into DB tables. No publish/generator/build-PDF command was run.
