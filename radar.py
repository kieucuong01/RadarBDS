"""
Radar BDS — CLI tiện dụng
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone

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


_COMMAND_LOG_FILE = None


class _TeeTextIO:
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]
        self.encoding = getattr(self.streams[0], "encoding", "utf-8") if self.streams else "utf-8"

    def write(self, text):
        for stream in self.streams:
            try:
                stream.write(text)
            except Exception:
                pass
        return len(text)

    def flush(self):
        for stream in self.streams:
            try:
                stream.flush()
            except Exception:
                pass

    def isatty(self):
        return any(getattr(stream, "isatty", lambda: False)() for stream in self.streams)


def _command_log_name(argv=None):
    argv = argv if argv is not None else sys.argv
    if len(argv) > 1 and argv[1] == "crawl-daily":
        return "crawl-daily.log"
    return ""


def _install_command_log_tee(argv=None):
    global _COMMAND_LOG_FILE
    log_name = _command_log_name(argv)
    if not log_name or _COMMAND_LOG_FILE is not None:
        return ""
    try:
        log_dir = Path(__file__).resolve().parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / log_name
        _COMMAND_LOG_FILE = log_path.open("a", encoding="utf-8", buffering=1)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _COMMAND_LOG_FILE.write(f"\n--- {stamp} {' '.join(argv or sys.argv)} ---\n")
        sys.stdout = _TeeTextIO(sys.stdout, _COMMAND_LOG_FILE)
        sys.stderr = _TeeTextIO(sys.stderr, _COMMAND_LOG_FILE)
        return str(log_path)
    except Exception as exc:
        logging.getLogger(__name__).warning("Command log tee disabled: %s", exc)
        return ""


_install_command_log_tee()

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
from cli.review import cmd_review_queue, cmd_review_save
from cli.system import (
    cmd_reprocess, cmd_dashboard, cmd_schedule_setup,
    cmd_lifecycle, cmd_download_images, cmd_db_cleanup,
    cmd_groq_extract_test, cmd_clean_broker_images,
    cmd_classify_legal_images,
    cmd_clean_legal_image_tags,
    cmd_verify_legal_signals,
)

def build_parser():
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
    p_re.add_argument("--groq-frontage", action="store_true", dest="groq_frontage", help="Groq enrich frontage_m còn NULL")
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
    p_cd.add_argument("--no-groq", action="store_true",
                      help="Bỏ bước LLM verify signals (Groq) sau reprocess")

    # schedule-setup
    p_ss = sub.add_parser("schedule-setup", help="Cài Windows Task Scheduler chạy crawl-daily")
    p_ss.add_argument("--time", default="21:00", help="Giờ chạy (HH:MM, default 21:00)")
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

    # review-queue / review-save (Claude pre-review CỐ VẤN — lưu bảng RIÊNG)
    p_rq = sub.add_parser("review-queue",
                          help="Signal chưa có verdict Claude + memo (JSON stdout)")
    p_rq.add_argument("--top",  type=int, default=5, help="Số signal (mặc định 5)")
    p_rq.add_argument("--ward", type=str, help="Lọc theo phường")

    p_rs = sub.add_parser("review-save",
                          help="Lưu verdict Claude (append-only) vào ai_deal_review")
    p_rs.add_argument("--id", type=int, required=True, help="Listing ID")
    p_rs.add_argument("--verdict", required=True,
                      help="cheap_real|suspect|not_cheap|insufficient_info")
    p_rs.add_argument("--confidence", type=float, help="Độ tin 0.0–1.0")
    p_rs.add_argument("--reasoning", required=True, help="Lập luận (tiếng Việt)")
    p_rs.add_argument("--red-flags", dest="red_flags",
                      help='Cờ đỏ, ngăn cách bằng ";"')
    p_rs.add_argument("--needs-map-check", dest="needs_map_check",
                      action="store_true",
                      help="Kết luận phụ thuộc quy hoạch/pháp lý/vị trí thực địa")

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

    # clean-broker-images
    p_cbi = sub.add_parser("clean-broker-images", help="Xóa ảnh avatar/selfie/profile môi giới khỏi listing_images")
    p_cbi.add_argument("--source", help="Lọc source: guland | facebook | batdongsan")
    p_cbi.add_argument("--limit", type=int, help="Giới hạn số ảnh scan")
    p_cbi.add_argument("--apply", action="store_true", help="Xóa thật (mặc định dry-run)")
    p_cbi.add_argument("--conservative", action="store_false", dest="strong",
                       help="Lọc thận trọng hơn, ít xóa ảnh có người")
    p_cbi.set_defaults(strong=True)

    # classify-legal-images
    p_cli = sub.add_parser("classify-legal-images", help="Nhan dien anh so hong/so do trong listing_images")
    p_cli.add_argument("--source", help="Loc source: guland | facebook | batdongsan")
    p_cli.add_argument("--limit", type=int, help="Gioi han so anh scan")
    p_cli.add_argument("--apply", action="store_true", help="Update img_type='so_hong' (mac dinh dry-run)")

    # clean-legal-image-tags
    p_clit = sub.add_parser("clean-legal-image-tags", help="Go tag so_hong sai khoi anh hien trang/nha/duong")
    p_clit.add_argument("--source", help="Loc source: guland | facebook | batdongsan")
    p_clit.add_argument("--limit", type=int, help="Gioi han so anh scan")
    p_clit.add_argument("--signals-only", action="store_true", dest="signals_only", help="Chi audit signal hien tai")
    p_clit.add_argument("--apply", action="store_true", help="Demote img_type sai ve cover/unknown (mac dinh dry-run)")

    # verify-legal-signals
    p_vls = sub.add_parser("verify-legal-signals", help="Tinh trust tier tu viec co anh so hong/so do")
    p_vls.add_argument("--source", help="Loc source: guland | facebook | batdongsan")
    p_vls.add_argument("--listing-id", type=int, dest="listing_id", help="Listing ID cu the")
    p_vls.add_argument("--limit", type=int, help="Gioi han so listing scan")
    p_vls.add_argument("--apply", action="store_true", help="Update legal_verifications va trust fields")

    # db-cleanup
    p_cl = sub.add_parser("db-cleanup", help="Prune stale rows + orphan image files (dry-run default)")
    p_cl.add_argument("--apply", action="store_true", help="Actually delete (default = dry run)")
    p_cl.add_argument("--sold-days", type=int, default=90, dest="sold_days",
                      help="Xóa listings probably_sold cũ hơn N ngày (default 90)")
    p_cl.add_argument("--raw-days", type=int, default=60, dest="raw_days",
                      help="Xóa raw_listings không match listings cũ hơn N ngày (default 60)")
    p_cl.add_argument("--notif-days", type=int, default=180, dest="notif_days",
                      help="Xóa notification_log cũ hơn N ngày (default 180)")
    p_cl.add_argument("--no-vacuum", action="store_true", dest="no_vacuum",
                      help="Bỏ qua VACUUM sau khi xóa")

    # inspect
    sub.add_parser("inspect", help="In snapshot toàn bộ trạng thái DB")

    # groq-test
    p_gt = sub.add_parser("groq-test", help="Test Groq full-field extraction vs regex cho 1 phường")
    p_gt.add_argument("--ward",   default="Tân An", help="Phường cần test (default: Tân An)")
    p_gt.add_argument("--sample", type=int, default=20, help="Số listings test (default: 20)")

    # crawl-health
    p_ch = sub.add_parser("crawl-health", help="Health dashboard các crawl runs gần đây")
    p_ch.add_argument("--limit", type=int, default=10, help="Số runs hiển thị (default: 10)")

    return parser


def main():
    parser = build_parser()
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
    elif args.cmd == "review-queue":
        cmd_review_queue(args)
    elif args.cmd == "review-save":
        cmd_review_save(args)
    elif args.cmd == "download-images":
        cmd_download_images(args)
    elif args.cmd == "clean-broker-images":
        cmd_clean_broker_images(args)
    elif args.cmd == "classify-legal-images":
        cmd_classify_legal_images(args)
    elif args.cmd == "clean-legal-image-tags":
        cmd_clean_legal_image_tags(args)
    elif args.cmd == "verify-legal-signals":
        cmd_verify_legal_signals(args)
    elif args.cmd == "db-cleanup":
        cmd_db_cleanup(args)
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
