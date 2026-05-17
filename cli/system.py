import sys
import subprocess
import platform
from pathlib import Path
from config.database_sqlite import init_schema, get_conn
import config.database_sqlite as _db

def cmd_reprocess(args):
    init_schema()
    from cleansing.reprocess import (
        run_full_reprocess, reprocess_listings, reprocess_valuation,
        enrich_listings_with_groq, enrich_frontage_with_groq, verify_signals_with_groq,
    )

    ward = getattr(args, "ward", None)
    full = getattr(args, "full", False)

    if getattr(args, "groq_frontage", False):
        n = enrich_frontage_with_groq(ward=ward)
        print(f"Groq frontage enrich: {n} listings updated.")
    elif getattr(args, "groq_signals", False):
        n = verify_signals_with_groq(ward=ward)
        print(f"Groq signal verify: {n} listings updated + re-valuated.")
    elif getattr(args, "valuation_only", False):
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
            use_groq=getattr(args, 'groq', False),
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
    db_path = getattr(args, "db", None) or str(_db.DB_PATH)
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

    run_time = getattr(args, "time", "10:15")
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
    init_schema()
    from cleansing.download_images import download_images
    limit = getattr(args, "limit", 1000)
    download_images(limit=limit)

def cmd_db_cleanup(args):
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
        f"orphan raw={stats['orphan_raw']} | "
        f"old notif={stats['old_notifications']} | "
        f"orphan images={stats['orphan_image_files']} ({mb:.1f} MB)"
    )

def cmd_groq_extract_test(args):
    """
    Test: Groq full-field extraction vs regex, sample N listings từ 1 phường.
    In bảng so sánh: regex value → groq value, highlight DIFF.
    """
    init_schema()
    import time
    from cleansing.groq_enricher import GroqEnricher

    ward   = getattr(args, "ward",   "Tân An")
    sample = getattr(args, "sample", 20)
    batch  = 5   # nhỏ hơn vì full extract nhiều token hơn

    enricher = GroqEnricher()
    if not enricher.enabled:
        print("GROQ_API_KEY không tìm thấy trong .env")
        return

    with get_conn() as conn:
        rows = conn.execute("""
            SELECT id, title, description,
                   price_ty, area_m2, property_type, road_tier,
                   road_type, road_width_m, frontage_m, has_so, is_hot, tx_type, ward
            FROM listings
            WHERE ward = ?
            ORDER BY RANDOM()
            LIMIT ?
        """, (ward, sample)).fetchall()

    if not rows:
        print(f"Không tìm thấy listings cho phường '{ward}'")
        return

    print(f"\n{'='*65}")
    print(f"  Groq Full Extract Test — {ward} ({len(rows)} listings, batch={batch})")
    print(f"{'='*65}")

    FIELDS = [
        ("price_ty",     "Giá(tỷ)"),
        ("area_m2",      "DT(m²)"),
        ("frontage_m",   "Mặt tiền"),
        ("property_type","Loại BDS"),
        ("road_tier",    "Tier"),
        ("road_type",    "Loại đường"),
        ("road_width_m", "Rộng(m)"),
        ("has_so",       "Có sổ"),
        ("is_hot",       "Nóng"),
        ("tx_type",      "Giao dịch"),
        ("ward",         "Phường"),
    ]

    chunks = [rows[i:i+batch] for i in range(0, len(rows), batch)]
    all_results = {}

    for i, chunk in enumerate(chunks, 1):
        batch_input = [
            {"id": r["id"],
             "title": r["title"] or "",
             "description": (r["description"] or "")[:300]}
            for r in chunk
        ]
        try:
            res = enricher.enrich_full_batch(batch_input)
            all_results.update(res)
        except Exception as exc:
            print(f"  [Batch {i}] Lỗi: {exc}")
        if i < len(chunks):
            time.sleep(8)

    diffs_total = 0
    for row in rows:
        rid = row["id"]
        groq = all_results.get(rid, {})
        title_short = (row["title"] or "")[:55]
        print(f"\n#{rid}  {title_short}")

        row_diffs = 0
        for field, label in FIELDS:
            regex_val = row[field]
            groq_val  = groq.get(field, "—")

            # Normalise để so sánh
            def _fmt(v):
                if v is None: return "null"
                if isinstance(v, float): return f"{v:.1f}"
                return str(v)

            r_str = _fmt(regex_val)
            g_str = _fmt(groq_val) if groq_val != "—" else "—"

            is_diff = (groq_val != "—") and (str(regex_val) != str(groq_val)) and not (
                regex_val in (None, 0, "") and groq_val in (None, 0, False, "")
            )
            marker = " ← DIFF" if is_diff else ""
            if is_diff:
                row_diffs += 1
                diffs_total += 1
            print(f"    {label:<12}: regex={r_str:<14} groq={g_str}{marker}")

        if not groq:
            print("    [Groq không trả kết quả cho listing này]")

    print(f"\n{'='*65}")
    print(f"  Tổng DIFF: {diffs_total} trường khác biệt / {len(rows)} listings")
    print(f"{'='*65}\n")

