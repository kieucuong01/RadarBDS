import sys
import subprocess
import platform
import json
from pathlib import Path
from db.connection import advisory_lock, get_conn
from db.schema import init_schema

def cmd_reprocess(args):
    return _cmd_reprocess(args)


def cmd_integrity_report(args):
    """Print the read-only extraction/valuation integrity comparison."""
    from services import extraction_integrity_report

    report = extraction_integrity_report.build_integrity_report(
        limit=getattr(args, "limit", None),
    )
    if getattr(args, "as_json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for key, value in report.items():
            rendered = (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list))
                else value
            )
            print(f"{key}: {rendered}")
    return report


_SIGNAL_READ_MODEL_COMPARE_CASES = (
    ("default", {}),
    ("facebook", {"sources": ["facebook"]}),
    ("guland", {"sources": ["guland"]}),
    ("ward_tan_an", {"wards": ["Tan An"]}),
    ("property_dat_nen", {"prop_types": ["dat_nen"]}),
    ("mos_20", {"mos_min": 20}),
    ("price_drops", {"only_drops": True}),
    ("mos_desc", {"sort": "mos_desc"}),
    ("score_desc", {"sort": "score_desc"}),
)

_LISTING_READ_MODEL_COMPARE_CASES = (
    ("default_3m", {"date_range": "3m"}),
    ("facebook", {"sources": ["facebook"], "date_range": "3m"}),
    ("guland", {"sources": ["guland"], "date_range": "3m"}),
    ("ward_tan_an", {"wards": ["Tan An"], "date_range": "3m"}),
    (
        "property_dat_nen",
        {"prop_types": ["dat_nen"], "date_range": "3m"},
    ),
    ("price_drops", {"only_drops": True, "date_range": "3m"}),
    ("complete", {"complete_only": True, "date_range": "3m"}),
    (
        "area_range",
        {"area_min": 60, "area_max": 200, "date_range": "3m"},
    ),
    (
        "price_range",
        {"price_min": 1, "price_max": 5, "date_range": "3m"},
    ),
    ("keyword", {"keyword": "duong", "date_range": "3m"}),
    ("date_all", {"date_range": "all"}),
    (
        "area_asc",
        {"sort_by": "area", "sort_dir": "asc", "date_range": "3m"},
    ),
    (
        "price_desc",
        {"sort_by": "price", "sort_dir": "desc", "date_range": "3m"},
    ),
    (
        "price_m2_asc",
        {
            "sort_by": "price_m2",
            "sort_dir": "asc",
            "date_range": "3m",
        },
    ),
    (
        "fair_desc",
        {"sort_by": "fair", "sort_dir": "desc", "date_range": "3m"},
    ),
    (
        "ward_asc",
        {"sort_by": "ward", "sort_dir": "asc", "date_range": "3m"},
    ),
    (
        "prop_type_asc",
        {
            "sort_by": "prop_type",
            "sort_dir": "asc",
            "date_range": "3m",
        },
    ),
    ("page_2", {"page": 2, "limit": 50, "date_range": "3m"}),
    (
        "guland_admin_override",
        {
            "sources": ["guland"],
            "include_guland_high_activity": True,
            "date_range": "3m",
        },
    ),
)


def _collect_signal_page(loader, *, limit: int, tier: str, case: dict):
    page_size = min(max(limit, 1), 100)
    collected = []
    page = 1
    while len(collected) < limit:
        payload = loader(
            None,
            tier=tier,
            page=page,
            limit=page_size,
            include_total=False,
            **case,
        )
        batch = payload["signals"]
        collected.extend(batch)
        if not payload["has_more"] or not batch:
            break
        page += 1
    return collected[:limit]


def compare_signal_read_model(limit: int = 200) -> dict:
    from services.market_data import _load_signals_legacy
    from services.signal_read_model import load_signals_from_read_model

    bounded_limit = min(max(int(limit), 1), 1000)
    differences = []
    compared_cases = 0
    for tier in ("guest", "free", "vip", "admin"):
        for case_name, case in _SIGNAL_READ_MODEL_COMPARE_CASES:
            compared_cases += 1
            legacy = _collect_signal_page(
                _load_signals_legacy,
                limit=bounded_limit,
                tier=tier,
                case=case,
            )
            read_model = _collect_signal_page(
                load_signals_from_read_model,
                limit=bounded_limit,
                tier=tier,
                case=case,
            )
            legacy_ids = [int(row["id"]) for row in legacy]
            read_model_ids = [int(row["id"]) for row in read_model]
            legacy_by_id = {int(row["id"]): row for row in legacy}
            read_model_by_id = {int(row["id"]): row for row in read_model}
            common_ids = set(legacy_by_id) & set(read_model_by_id)
            differing_fields = sorted(
                {
                    field
                    for listing_id in common_ids
                    for field in (
                        set(legacy_by_id[listing_id])
                        | set(read_model_by_id[listing_id])
                    )
                    if legacy_by_id[listing_id].get(field)
                    != read_model_by_id[listing_id].get(field)
                }
            )
            if legacy_ids != read_model_ids or differing_fields:
                differences.append(
                    {
                        "case": case_name,
                        "tier": tier,
                        "legacy_count": len(legacy_ids),
                        "read_model_count": len(read_model_ids),
                        "legacy_only_ids": sorted(
                            set(legacy_ids) - set(read_model_ids)
                        ),
                        "read_model_only_ids": sorted(
                            set(read_model_ids) - set(legacy_ids)
                        ),
                        "order_mismatch": legacy_ids != read_model_ids,
                        "field_names": differing_fields,
                    }
                )
    return {
        "status": "ok" if not differences else "mismatch",
        "compared_cases": compared_cases,
        "limit": bounded_limit,
        "difference_count": len(differences),
        "differences": differences,
    }


def _collect_listing_page(loader, *, limit: int, tier: str, case: dict):
    bounded_limit = min(max(int(limit), 1), 1000)
    start_page = max(int(case.get("page", 1)), 1)
    page_size = min(max(int(case.get("limit", 100)), 1), 100)
    target_rows = page_size if "page" in case else bounded_limit
    call_case = {
        key: value
        for key, value in case.items()
        if key not in {"page", "limit"}
    }
    collected = []
    first_meta = None
    page = start_page
    while len(collected) < target_rows:
        payload = loader(
            None,
            tier=tier,
            page=page,
            limit=min(page_size, target_rows - len(collected)),
            **call_case,
        )
        if first_meta is None:
            first_meta = {
                key: payload.get(key)
                for key in (
                    "total",
                    "page",
                    "limit",
                    "pages",
                    "has_more",
                    "tier",
                )
            }
        batch = list(payload.get("listings") or ())
        collected.extend(batch)
        if not payload.get("has_more") or not batch or "page" in case:
            break
        page += 1
    return {"rows": collected[:target_rows], "meta": first_meta or {}}


def compare_listing_read_model(limit: int = 200) -> dict:
    """Compare listing feeds while retaining only non-sensitive diagnostics."""
    from services.listing_feed import (
        _load_listing_feed_legacy,
        load_listings_from_read_model,
    )

    bounded_limit = min(max(int(limit), 1), 1000)
    differences = []
    compared_cases = 0
    for tier in ("guest", "free", "vip", "admin"):
        for case_name, case in _LISTING_READ_MODEL_COMPARE_CASES:
            compared_cases += 1
            legacy = _collect_listing_page(
                _load_listing_feed_legacy,
                limit=bounded_limit,
                tier=tier,
                case=case,
            )
            read_model = _collect_listing_page(
                load_listings_from_read_model,
                limit=bounded_limit,
                tier=tier,
                case=case,
            )
            legacy_rows = legacy["rows"]
            read_model_rows = read_model["rows"]
            legacy_ids = [int(row["id"]) for row in legacy_rows]
            read_model_ids = [int(row["id"]) for row in read_model_rows]
            legacy_by_id = {int(row["id"]): row for row in legacy_rows}
            read_model_by_id = {
                int(row["id"]): row for row in read_model_rows
            }
            common_ids = set(legacy_by_id) & set(read_model_by_id)
            differing_fields = sorted(
                {
                    field
                    for listing_id in common_ids
                    for field in (
                        set(legacy_by_id[listing_id])
                        | set(read_model_by_id[listing_id])
                    )
                    if legacy_by_id[listing_id].get(field)
                    != read_model_by_id[listing_id].get(field)
                }
            )
            differing_metadata_fields = sorted(
                key
                for key in set(legacy["meta"]) | set(read_model["meta"])
                if legacy["meta"].get(key) != read_model["meta"].get(key)
            )
            if (
                legacy_ids != read_model_ids
                or differing_fields
                or differing_metadata_fields
            ):
                differences.append(
                    {
                        "case": case_name,
                        "tier": tier,
                        "legacy_count": len(legacy_ids),
                        "read_model_count": len(read_model_ids),
                        "legacy_only_ids": sorted(
                            set(legacy_ids) - set(read_model_ids)
                        ),
                        "read_model_only_ids": sorted(
                            set(read_model_ids) - set(legacy_ids)
                        ),
                        "order_mismatch": legacy_ids != read_model_ids,
                        "field_names": differing_fields,
                        "metadata_fields": differing_metadata_fields,
                    }
                )
    return {
        "status": "ok" if not differences else "mismatch",
        "compared_cases": compared_cases,
        "limit": bounded_limit,
        "difference_count": len(differences),
        "differences": differences,
    }


def cmd_signal_read_model(args):
    init_schema()
    output = {}
    if bool(getattr(args, "refresh", False)):
        from services.public_data_publish import publish_public_data

        output["refresh"] = publish_public_data(
            listing_ids=None,
            market_changed=False,
            strict=True,
        )
    if bool(getattr(args, "compare", False)):
        output["compare"] = compare_signal_read_model(
            int(getattr(args, "limit", 200))
        )
    if bool(getattr(args, "compare_listings", False)):
        output["listings_compare"] = compare_listing_read_model(
            int(getattr(args, "limit", 200))
        )
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    if any(
        output.get(key, {}).get("status") == "mismatch"
        for key in ("compare", "listings_compare")
    ):
        raise SystemExit(1)


def _cmd_reprocess(args):
    init_schema()
    from cleansing.reprocess import (
        run_full_reprocess, reprocess_listings, reprocess_valuation,
    )

    full = getattr(args, "full", False)

    if getattr(args, "valuation_only", False):
        # valuation_only mặc định chạy full trừ khi có logic khác
        with advisory_lock("reprocess"):
            stats = reprocess_valuation(incremental_ids=None)
        print(f"Valuation (Full): {stats}")
    elif getattr(args, "listings_only", False):
        with advisory_lock("reprocess"):
            stats = reprocess_listings(source=getattr(args, "source", None), since=getattr(args, "since", None), full=full)
        print(f"Listings: {stats}")
    else:
        result = run_full_reprocess(
            source=getattr(args, "source", None), 
            since=getattr(args, "since", None),
            full=full
        )
        r = result["listings"]
        v = result["valuation"]
        print(f"\n{'='*50}")
        print(f"Mode     : {'FULL' if full else 'INCREMENTAL'}")
        print(f"Listings : {r['new']} new | {r['updated']} updated | {r['skipped']} skipped")
        print(f"Valuation: {v['total']} valuated | {v['signals']} signals | {v['outliers']} outliers")
        print(f"{'='*50}")

def cmd_dashboard(args):
    db_path = getattr(args, "db", None) or ""
    out_path = getattr(args, "out", None) or "dashboard_signals.html"
    result = subprocess.run(
        [sys.executable, "scripts/generate_dashboard.py", "--db", db_path, "--out", out_path],
        capture_output=True, text=True
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)

def cmd_lifecycle(args):
    from analytics.lifecycle import (
        sweep_delisted, backfill_first_seen,
        get_delisted_signals, segment_velocity,
    )
    with get_conn() as conn:
        backfill_first_seen(conn)
        delisted = sweep_delisted(conn, stale_hours=getattr(args, "sweep_hours", 48))
        likely   = [d for d in delisted if d.get("likely_sold")]
        vel      = segment_velocity(conn) if getattr(args, "velocity", False) else []

    print(f"Delisted    : {len(delisted)}  (likely_sold <72h: {len(likely)})")
    if getattr(args, "velocity", False) and vel:
        print("\nSegment velocity (30d):")
        for v in vel:
            print(f"  {v['area']:10s}/{v['property_type']:10s} "
                  f"n={v['n_delisted']:3d} fast={v['fast_sold']:3d} "
                  f"avg_days={v['avg_days_alive'] or 0:.1f} hot={v['hot_score']}")

def cmd_schedule_setup(args):
    if platform.system() != "Windows":
        print("schedule-setup chỉ hỗ trợ Windows (Task Scheduler).")
        print("Linux/Mac: thêm vào crontab:")
        script = Path(__file__).parent.parent / "radar.py"
        print(f"  0 7 * * * python \"{script}\" crawl-daily")
        return

    task_name = "RadarBDS_DailyCrawl"
    script_path = Path(__file__).parent.parent / "radar.py"
    python_exe = sys.executable
    repo_root = str(script_path.parent)

    if getattr(args, "remove", False):
        result = subprocess.run(
            ["schtasks", "/delete", "/tn", task_name, "/f"],
            capture_output=True, text=True
        )
        print("Task đã xóa." if result.returncode == 0 else f"Lỗi: {result.stderr}")
        return

    run_time = getattr(args, "time", "21:00")
    interval_days = str(getattr(args, "every", 1))
    # Ensure the task runs from repo root so relative paths (data/, logs/, etc.) are stable.
    cmd = f'cmd /c "cd /d {repo_root} && \\"{python_exe}\\" -X utf8 \\"{script_path}\\" crawl-daily"'

    result = subprocess.run([
        "schtasks", "/create",
        "/tn",  task_name,
        "/tr",  cmd,
        "/sc",  "DAILY",
        "/mo",  interval_days,
        "/st",  run_time,
        "/f",
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✅ Task '{task_name}' đã tạo — chạy mỗi {interval_days} ngày lúc {run_time}")
        print(f"   Lệnh: {cmd}")
        print(f"\nKiểm tra: schtasks /query /tn {task_name}")
        print(f"Xóa    : python radar.py schedule-setup --remove")
    else:
        print(f"❌ Lỗi tạo task: {result.stderr}")

def cmd_download_images(args):
    with advisory_lock("download-images"):
        return _cmd_download_images(args)


def _cmd_download_images(args):
    init_schema()
    from cleansing.download_images import download_images
    from cleansing.image_cleanup import clean_broker_images
    limit = getattr(args, "limit", 1000)
    download_images(limit=limit)
    stats = clean_broker_images(apply=True, limit=limit, strong=True)
    print(
        f"Clean broker images: scanned={stats.get('scanned', 0)} | "
        f"deleted={stats.get('deleted', 0)} | reasons={stats.get('reasons', {})}"
    )

def cmd_classify_legal_images(args):
    with advisory_lock("classify-legal-images"):
        return _cmd_classify_legal_images(args)


def _cmd_classify_legal_images(args):
    init_schema()
    from cleansing.legal_image_classifier import classify_legal_images
    stats = classify_legal_images(
        source=getattr(args, "source", None),
        apply=bool(getattr(args, "apply", False)),
        limit=getattr(args, "limit", None),
    )
    mode = "APPLIED" if stats["apply"] else "DRY RUN (use --apply to update)"
    print(
        f"[{mode}] scanned={stats['scanned']} | candidates={stats['candidates']} | "
        f"updated={stats['updated']} | reasons={stats['reasons']}"
    )

def cmd_clean_legal_image_tags(args):
    with advisory_lock("clean-legal-image-tags"):
        return _cmd_clean_legal_image_tags(args)


def _cmd_clean_legal_image_tags(args):
    init_schema()
    from cleansing.legal_image_classifier import clean_legal_image_tags
    stats = clean_legal_image_tags(
        source=getattr(args, "source", None),
        apply=bool(getattr(args, "apply", False)),
        limit=getattr(args, "limit", None),
        signals_only=bool(getattr(args, "signals_only", False)),
    )
    mode = "APPLIED" if stats["apply"] else "DRY RUN (use --apply to update)"
    scope = "signals only" if stats.get("signals_only") else "all listings"
    print(
        f"[{mode}] {scope} | scanned={stats['scanned']} | kept={stats['kept']} | "
        f"demoted={stats['demoted']} | reasons={stats['reasons']}"
    )

def cmd_verify_legal_signals(args):
    with advisory_lock("verify-legal-signals"):
        return _cmd_verify_legal_signals(args)


def _cmd_verify_legal_signals(args):
    init_schema()
    from cleansing.legal_verification import refresh_legal_verifications
    stats = refresh_legal_verifications(
        source=getattr(args, "source", None),
        listing_id=getattr(args, "listing_id", None),
        apply=bool(getattr(args, "apply", False)),
        limit=getattr(args, "limit", None),
    )
    mode = "APPLIED" if stats["apply"] else "DRY RUN (use --apply to update)"
    print(
        f"[{mode}] scanned={stats['scanned']} | updated={stats['updated']} | "
        f"statuses={stats['statuses']} | trust_tiers={stats['trust_tiers']}"
    )

def cmd_clean_broker_images(args):
    with advisory_lock("clean-broker-images"):
        return _cmd_clean_broker_images(args)


def _cmd_clean_broker_images(args):
    init_schema()
    from cleansing.image_cleanup import clean_broker_images
    stats = clean_broker_images(
        source=getattr(args, "source", None),
        apply=bool(getattr(args, "apply", False)),
        limit=getattr(args, "limit", None),
        strong=bool(getattr(args, "strong", True)),
    )
    mode = "APPLIED" if stats["apply"] else "DRY RUN (use --apply to delete)"
    print(
        f"[{mode}] scanned={stats['scanned']} | candidates={stats['candidates']} | "
        f"deleted={stats['deleted']} | files={stats['files_deleted']} | "
        f"thumbs={stats['thumbs_deleted']} | raw_updated={stats['raw_updated']} | "
        f"reasons={stats['reasons']}"
    )

def cmd_db_cleanup(args):
    with advisory_lock("db-cleanup"):
        return _cmd_db_cleanup(args)


def _cmd_db_cleanup(args):
    init_schema()
    from cli.cleanup import run_cleanup
    apply = bool(getattr(args, "apply", False))
    stats = run_cleanup(
        apply=apply,
        sold_days=int(getattr(args, "sold_days", 90)),
        raw_days=int(getattr(args, "raw_days", 60)),
        notif_days=int(getattr(args, "notif_days", 180)),
        vacuum=not bool(getattr(args, "no_vacuum", False)),
    )
    mb = stats["bytes_freed"] / (1024 * 1024)
    mode = "APPLIED" if apply else "DRY RUN (use --apply to delete)"
    print(
        f"[{mode}] sold listings={stats['sold_listings']} | "
        f"unpriceable listings={stats['unpriceable_listings']} | "
        f"unpriceable raw={stats['unpriceable_raw']} | "
        f"orphan raw={stats['orphan_raw']} | "
        f"old notif={stats['old_notifications']} | "
        f"orphan images={stats['orphan_image_files']} ({mb:.1f} MB)"
    )

