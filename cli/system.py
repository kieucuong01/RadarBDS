import sys
import subprocess
import platform
from pathlib import Path
from db.connection import advisory_lock, get_conn
from db.schema import init_schema

def cmd_reprocess(args):
    with advisory_lock("reprocess"):
        return _cmd_reprocess(args)


def _cmd_reprocess(args):
    init_schema()
    from cleansing.reprocess import (
        run_full_reprocess, reprocess_listings, reprocess_valuation,
    )

    full = getattr(args, "full", False)

    if getattr(args, "valuation_only", False):
        # valuation_only mặc định chạy full trừ khi có logic khác
        stats = reprocess_valuation(incremental_ids=None)
        print(f"Valuation (Full): {stats}")
    elif getattr(args, "listings_only", False):
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

