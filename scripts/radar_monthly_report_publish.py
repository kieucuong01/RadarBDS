#!/usr/bin/env python3
"""Publish the previous closed month of Radar BDS market reports.

This script is intentionally stored in the Radar BDS repository so any AI coding
agent (Codex, Hermes, Claude, etc.) can inspect and maintain the full monthly
report pipeline from source control.

Normal cron behavior:
  - Run on the 1st day of each month.
  - Publish the previous closed month only.
  - Generate base reports, enrich them, restart production, verify live URLs,
    then commit/push config/seo_pages.py if it changed.

Manual smoke/dry-run:
  python3 \
    /opt/radar-bds/current/scripts/radar_monthly_report_publish.py \
    --month 06 --year 2026 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
from pathlib import Path

PROJECT = Path("/opt/radar-bds/current")
PYTHON = "/opt/radar-bds/.venv/bin/python"
DOMAIN = "https://radarbds.vn"
WARDS = [
    "tan-an",
    "hiep-an",
    "tuong-binh-hiep",
    "dinh-hoa",
    "chanh-my",
    "phu-my",
    "phu-cuong",
    "phu-hoa",
    "phu-loi",
    "hiep-thanh",
    "chanh-nghia",
    "phu-tan",
    "hoa-phu",
]


def run(cmd: list[str] | str, *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout,
        shell=isinstance(cmd, str),
    )


def sh(cmd: str, *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return run(cmd, timeout=timeout)


def previous_month(today: dt.date) -> tuple[int, int]:
    first = today.replace(day=1)
    prev_last = first - dt.timedelta(days=1)
    return prev_last.month, prev_last.year


def is_closed_month(month: int, year: int, today: dt.date) -> bool:
    return (year, month) < (today.year, today.month)


def report_key_exists(month: int, year: int) -> bool:
    mm = f"{month:02d}"
    key = f'"bao-cao/bds-binh-duong-thang-{mm}-{year}"'
    # The wrapper may run as Hermes/user while the repo is owned by radar.
    # Query through sudo instead of reading config/seo_pages.py directly.
    p = sh(f"sudo -u radar bash -lc 'cd {PROJECT} && grep -Fq {key!r} config/seo_pages.py'", timeout=60)
    return p.returncode == 0


def http_html(path: str) -> tuple[str, str]:
    url = DOMAIN + path
    p = run(["curl", "-L", "-sS", "-w", "\n__HTTP_STATUS__:%{http_code}", url], timeout=45)
    if p.returncode != 0:
        return "ERR", (p.stderr or p.stdout or "")
    body, _, marker = (p.stdout or "").rpartition("\n__HTTP_STATUS__:")
    return (marker.strip() or "ERR"), body


def git_config_changed() -> bool:
    p = sh(f"sudo -u radar git -C {PROJECT} diff --quiet -- config/seo_pages.py; echo $?", timeout=60)
    return (p.stdout or "1").strip() != "0"


def expected_paths(month: int, year: int) -> tuple[str, list[str]]:
    mm = f"{month:02d}"
    master = f"/bao-cao/bds-binh-duong-thang-{mm}-{year}"
    wards = [f"/bao-cao/{ward}-thang-{mm}-{year}" for ward in WARDS]
    return master, [master] + wards


def verify_live(month: int, year: int) -> int:
    mm = f"{month:02d}"
    master_path, paths = expected_paths(month, year)
    bad: list[tuple] = []

    print("\n### Verify live URLs + report structure")
    for path in paths:
        status, html = http_html(path)
        cards = html.count("report-signal-card")
        canvases = html.count("<canvas")
        filtered = "/?tab=signals" in html and "city=TH" in html
        inline_links = html.count("report-inline-links")
        seo_links = html.count("report-seo-links")
        has_mos_links = "mos_min=10" in html and "mos_min=15" in html
        has_type_links = "prop_type=dat_nen" in html and "prop_type=nha_dat" in html

        if path == master_path:
            child_links = sorted(
                set(re.findall(r'href="(/bao-cao/[a-z\-]+-thang-' + re.escape(mm) + r'-' + str(year) + r')"', html))
            )
            child_links = [href for href in child_links if "bds-binh-duong" not in href]
            has_child_section = "Tổng hợp 13 báo cáo phường Thủ Dầu Một" in html
            ok = (
                status == "200"
                and canvases == 2
                and cards == 0
                and filtered
                and seo_links >= 1
                and has_child_section
                and len(child_links) == 13
            )
            print(
                f"- {path}: {status} canvas={canvases} child_links={len(child_links)} "
                f"seo={seo_links} filtered_cta={filtered} ok={ok}"
            )
            if not ok:
                bad.append((path, status, canvases, cards, filtered, seo_links, len(child_links)))
        else:
            ok = (
                status == "200"
                and canvases == 4
                and cards == 6
                and "Xem thêm trên Radar BDS" in html
                and filtered
                and inline_links >= 2
                and seo_links >= 1
                and has_mos_links
                and has_type_links
            )
            print(
                f"- {path}: {status} canvas={canvases} cards={cards} inline={inline_links} "
                f"seo={seo_links} filtered_cta={filtered} ok={ok}"
            )
            if not ok:
                bad.append((path, status, canvases, cards, filtered, inline_links, seo_links))

    sitemap = run(["curl", "-sS", f"{DOMAIN}/sitemap.xml"], timeout=60)
    sitemap_text = sitemap.stdout or ""
    missing = [path for path in paths if path not in sitemap_text]
    print(f"\nSitemap contains expected monthly paths: {len(paths) - len(missing)}/{len(paths)}")

    if bad or missing:
        print("❌ Verification failed")
        if bad:
            print("Bad pages:", bad)
        if missing:
            print("Missing sitemap paths:", missing[:10])
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish closed-month Radar BDS market reports")
    parser.add_argument("--month", type=int, help="Closed month to publish/verify, 1-12. Defaults to previous month.")
    parser.add_argument("--year", type=int, help="Year for --month. Defaults with previous month.")
    parser.add_argument("--dry-run", action="store_true", help="Run generator/enhancer in dry-run mode; do not restart or commit.")
    parser.add_argument("--skip-git", action="store_true", help="Do not commit/push even if config/seo_pages.py changed.")
    parser.add_argument("--skip-restart", action="store_true", help="Do not restart radar-bds after changes.")
    args = parser.parse_args()

    today = dt.date.today()
    if args.month is None and args.year is None:
        month, year = previous_month(today)
    elif args.month and args.year:
        month, year = args.month, args.year
    else:
        print("❌ Pass both --month and --year, or neither.")
        return 2

    if not 1 <= month <= 12:
        print("❌ --month must be 1..12")
        return 2
    if not is_closed_month(month, year, today):
        print("❌ Formal /bao-cao monthly reports only publish closed months. Use dashboard/tin-tuc for in-progress month.")
        return 2

    mm = f"{month:02d}"
    print(f"## 🗓️ @rb Monthly Market Reports — publish {mm}/{year}")
    print(f"Run date: {today.isoformat()} — chỉ publish tháng đã chốt. dry_run={args.dry_run}\n")

    before_changed = git_config_changed()
    dry_flag = " --dry-run" if args.dry_run else ""

    gen_cmd = (
        f"cd {PROJECT} && {PYTHON} scripts/generate_monthly_report.py "
        f"--month {mm} --year {year} --all{dry_flag}"
    )
    gen = sh(f"sudo -u radar bash -lc {gen_cmd!r}", timeout=900)
    print("### Base generator")
    print((gen.stdout or "").strip()[-3000:] or "(no stdout)")
    if gen.returncode != 0:
        print((gen.stderr or "").strip()[-2000:])
        return gen.returncode

    if args.dry_run and not report_key_exists(month, year):
        print("\n### Rich report enhancement")
        print("Skipped dry-run: base pages are not yet present in config/seo_pages.py.")
    else:
        rich_cmd = (
            f"cd {PROJECT} && {PYTHON} scripts/enhance_monthly_report_rich.py "
            f"--month {mm} --year {year}{dry_flag}"
        )
        rich = sh(f"sudo -u radar bash -lc {rich_cmd!r}", timeout=1200)
        print("\n### Rich report enhancement")
        print((rich.stdout or "").strip()[-4000:] or "(no stdout)")
        if rich.returncode != 0:
            print((rich.stderr or "").strip()[-2000:])
            return rich.returncode

    changed = git_config_changed()
    if args.dry_run:
        if report_key_exists(month, year):
            verify_code = verify_live(month, year)
            if verify_code != 0:
                return verify_code
        print("\n✅ Dry run completed. No restart, commit, or push performed.")
        return 0

    if changed and not args.skip_restart:
        print("\n### Restart service")
        restart = sh("sudo systemctl restart radar-bds", timeout=120)
        if restart.returncode != 0:
            print((restart.stderr or restart.stdout)[-1000:])
            return restart.returncode
        print("radar-bds restarted")
    elif changed:
        print("\nSkipping service restart by --skip-restart")
    elif not changed and not before_changed:
        print("\nKhông có thay đổi mới trong `config/seo_pages.py` — có thể tháng này đã publish trước đó.")

    verify_code = verify_live(month, year)
    if verify_code != 0:
        return verify_code

    if changed and not args.skip_git:
        print("\n### Git commit/push")
        sh(f"sudo -u radar git -C {PROJECT} add config/seo_pages.py", timeout=60)
        commit_msg = f"publish Radar monthly market reports {mm}-{year}"
        commit = sh(f"sudo -u radar git -C {PROJECT} commit -m {commit_msg!r}", timeout=120)
        print((commit.stdout or commit.stderr).strip()[-2000:])
        if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr).lower():
            return commit.returncode
        push = sh(f"sudo -u radar git -C {PROJECT} push", timeout=240)
        print((push.stdout or push.stderr).strip()[-2000:])
        if push.returncode != 0:
            return push.returncode
    elif changed:
        print("\nSkipping git commit/push by --skip-git")

    print("\n✅ Monthly reports published and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
