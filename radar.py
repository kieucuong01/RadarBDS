"""
Radar BDS — CLI tiện dụng
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import logging
try:
    from config.logging_setup import setup_logging
    setup_logging()
except Exception:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

if sys.stdout.encoding.lower() != 'utf-8':
    try:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    except Exception:
        pass

import config.settings as _settings

from cli.data_import import (
    cmd_import_guland, cmd_delete_guland,
    cmd_import_batdongsan, cmd_delete_batdongsan,
    cmd_export_raw, cmd_import_raw_backup,
    cmd_import_facebook_json
)
from cli.crawlers import (
    cmd_crawl, cmd_crawl_facebook, cmd_repair_missing
)
from cli.queries import (
    cmd_query, cmd_deal_brief, cmd_inspect, cmd_crawl_health
)
from cli.system import (
    cmd_reprocess, cmd_dashboard, cmd_schedule_setup,
    cmd_lifecycle, cmd_download_images,
    cmd_groq_extract_test,
)

def main():
    parser = argparse.ArgumentParser(prog="radar", description="Radar BDS CLI")
    sub = parser.add_subparsers(dest="cmd")

    # reprocess
    p_re = sub.add_parser("reprocess", help="Reprocess từ raw_listings")
    p_re.add_argument("--source", help="Filter theo source")
    p_re.add_argument("--since",  help="Từ ngày (YYYY-MM-DD)")
    p_re.add_argument("--full",   action="store_true", help="Chạy toàn bộ dữ liệu (mặc định là incremental)")
    p_re.add_argument("--valuation-only", action="store_true")
    p_re.add_argument("--listings-only",  action="store_true")
    p_re.add_argument("--groq",          action="store_true", help="Enrich hard listings (road_tier=0) bằng Groq LLM")
    p_re.add_argument("--groq-frontage", action="store_true", dest="groq_frontage", help="Groq enrich frontage_m/road_width_m còn NULL")
    p_re.add_argument("--groq-signals",  action="store_true", dest="groq_signals",  help="Groq verify toàn bộ fields cho signal listings")
    p_re.add_argument("--ward",          help="Lọc phường khi dùng --groq* (vd: 'Tân An')")

    # dashboard
    p_db = sub.add_parser("dashboard", help="Generate dashboard HTML")
    p_db.add_argument("--db",  help="DB path")
    p_db.add_argument("--out", help="Output HTML path")

    # import-guland
    p_ig = sub.add_parser("import-guland", help="Import Guland JSON từ file hoặc stdin")
    p_ig.add_argument("--file", help="JSON file path")

    # delete-guland
    p_dg = sub.add_parser("delete-guland", help="Xóa toàn bộ Guland data khỏi DB")
    p_dg.add_argument("--yes", "-y", action="store_true", help="Xác nhận xóa không hỏi lại")

    # import-batdongsan
    p_ib = sub.add_parser("import-batdongsan", help="Import BatDongSan JSON từ file")
    p_ib.add_argument("--file", help="JSON file path")

    # delete-batdongsan
    p_db2 = sub.add_parser("delete-batdongsan", help="Xóa toàn bộ BatDongSan data khỏi DB")
    p_db2.add_argument("--yes", "-y", action="store_true")

    # crawl-all
    p_ca = sub.add_parser("crawl-all", help="Full crawl Guland + BatDongSan → DB trực tiếp")
    p_ca.add_argument("--source",  help="Chỉ crawl 1 nguồn: guland | batdongsan")
    p_ca.add_argument("--visible", action="store_true", help="Hiện browser (debug)")
    p_ca.add_argument("--no-reprocess", action="store_true", help="Không reprocess sau crawl")

    # crawl-daily
    p_cd = sub.add_parser("crawl-daily", help="Crawl tin mới hôm nay → reprocess → VIP notification")
    p_cd.add_argument("--source",  help="Chỉ crawl 1 nguồn")
    p_cd.add_argument("--visible", action="store_true")
    p_cd.add_argument("--no-alert", action="store_true", help="Không gửi VIP notification")

    # schedule-setup
    p_ss = sub.add_parser("schedule-setup", help="Cài Windows Task Scheduler chạy crawl-daily")
    p_ss.add_argument("--time", default="10:15", help="Giờ chạy (HH:MM, default 10:15)")
    p_ss.add_argument("--every", type=int, default=1, help="Chu kỳ chạy theo ngày (default 1)")
    p_ss.add_argument("--remove", action="store_true", help="Xóa task đã cài")

    # crawl-facebook
    p_cf = sub.add_parser("crawl-facebook", help="Crawl Facebook posts qua Apify")
    p_cf.add_argument("--mode",    default="full", choices=["full", "incremental"])
    p_cf.add_argument("--profile", metavar="URL", help="Crawl 1 profile cu the")
    p_cf.add_argument("--area",    help="Crawl theo khu vuc (ví dụ: 'Bến Cát')")
    p_cf.add_argument("--limit",   type=int, default=0, help="Ghi de so bai fetch")
    p_cf.add_argument("--no-reprocess", action="store_true", help="Chi import raw, khong reprocess")

    # import-facebook-json
    p_ifb = sub.add_parser("import-facebook-json", help="Import posts Facebook crawl từ Chrome MCP")
    p_ifb.add_argument("file", help="JSON file path")
    p_ifb.add_argument("--no-reprocess", action="store_true", help="Chỉ import raw, không reprocess")

    # export-raw
    p_er = sub.add_parser("export-raw", help="Backup raw_listings ra JSON")
    p_er.add_argument("--out", help="Output JSON path")

    # import-raw-backup
    p_irb = sub.add_parser("import-raw-backup", help="Restore raw_listings từ backup JSON")
    p_irb.add_argument("--file", help="Backup JSON path")
    p_irb.add_argument("--no-reprocess", action="store_true")

    # repair-missing
    p_rm = sub.add_parser("repair-missing", help="Re-fetch price/area cho listings thiếu data")
    p_rm.add_argument("--source",  default="guland", help="Source cần repair")
    p_rm.add_argument("--visible", action="store_true", help="Hiện browser (debug)")
    p_rm.add_argument("--limit",   type=int, default=0, help="Giới hạn số records")

    # deal-brief
    p_db3 = sub.add_parser("deal-brief", help="Deal brief chi tiết cho 1 listing hoặc top N signals")
    p_db3.add_argument("--id",  type=int, help="Listing ID cụ thể")
    p_db3.add_argument("--top", type=int, help="Top N signals theo signal score")

    # lifecycle
    p_lc = sub.add_parser("lifecycle", help="Sweep delisted + stats feedback loop")
    p_lc.add_argument("--sweep-hours", type=int, default=48, help="Listing không thấy > N giờ → delisted")
    p_lc.add_argument("--velocity",    action="store_true", help="In segment velocity (hot score)")

    # query
    p_q = sub.add_parser("query", help="Query nhanh")
    p_q.add_argument("--stats",       action="store_true", help="DB stats tổng quan")
    p_q.add_argument("--top50-cheap", action="store_true", dest="top50_cheap", help="Top 50 rẻ nhất/m²")
    p_q.add_argument("--signals",     action="store_true", help="Danh sách signals")
    p_q.add_argument("--search",      metavar="KEYWORD",   help="Tìm trong listings")
    p_q.add_argument("--raw-search",  metavar="KEYWORD",   dest="raw_search", help="Tìm trong raw_listings")
    p_q.add_argument("--source",      help="Filter theo source")
    p_q.add_argument("--limit",       type=int,            help="Số kết quả trả về")

    # download-images
    p_di = sub.add_parser("download-images", help="Tải ảnh về máy cục bộ")
    p_di.add_argument("--limit", type=int, default=1000, help="Số lượng ảnh tối đa cần tải")

    # inspect
    sub.add_parser("inspect", help="In snapshot toàn bộ trạng thái DB")

    # groq-test
    p_gt = sub.add_parser("groq-test", help="Test Groq full-field extraction vs regex cho 1 phường")
    p_gt.add_argument("--ward",   default="Tân An", help="Phường cần test (default: Tân An)")
    p_gt.add_argument("--sample", type=int, default=20, help="Số listings test (default: 20)")

    # crawl-health
    p_ch = sub.add_parser("crawl-health", help="Health dashboard các crawl runs gần đây")
    p_ch.add_argument("--limit", type=int, default=10, help="Số runs hiển thị (default: 10)")


    args = parser.parse_args()

    if args.cmd == "reprocess":
        cmd_reprocess(args)
    elif args.cmd == "dashboard":
        cmd_dashboard(args)
    elif args.cmd == "import-guland":
        cmd_import_guland(args)
    elif args.cmd == "delete-guland":
        cmd_delete_guland(args)
    elif args.cmd == "import-batdongsan":
        cmd_import_batdongsan(args)
    elif args.cmd == "delete-batdongsan":
        cmd_delete_batdongsan(args)
    elif args.cmd == "crawl-all":
        cmd_crawl(args, mode="full")
    elif args.cmd == "crawl-daily":
        cmd_crawl(args, mode="incremental")
    elif args.cmd == "schedule-setup":
        cmd_schedule_setup(args)
    elif args.cmd == "crawl-facebook":
        cmd_crawl_facebook(args)
    elif args.cmd == "import-facebook-json":
        cmd_import_facebook_json(args)
    elif args.cmd == "export-raw":
        cmd_export_raw(args)
    elif args.cmd == "import-raw-backup":
        cmd_import_raw_backup(args)
    elif args.cmd == "repair-missing":
        cmd_repair_missing(args)
    elif args.cmd == "lifecycle":
        cmd_lifecycle(args)
    elif args.cmd == "query":
        cmd_query(args)
    elif args.cmd == "deal-brief":
        cmd_deal_brief(args)
    elif args.cmd == "download-images":
        cmd_download_images(args)
    elif args.cmd == "inspect":
        cmd_inspect(args)
    elif args.cmd == "groq-test":
        cmd_groq_extract_test(args)
    elif args.cmd == "crawl-health":
        cmd_crawl_health(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
