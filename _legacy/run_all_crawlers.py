import subprocess
import os
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    filename='deploy_crawl.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def run_script(script_path):
    logging.info(f"--- Đang chạy: {script_path} ---")
    try:
        # Chạy script bằng môi trường hiện tại
        result = subprocess.run(['python3', script_path], capture_output=True, text=True)
        if result.returncode == 0:
            logging.info(f"Thành công: {script_path}")
        else:
            logging.error(f"Lỗi khi chạy {script_path}: {result.stderr}")
    except Exception as e:
        logging.error(f"Lỗi hệ thống: {str(e)}")

if __name__ == "__main__":
    scripts = [
        "crawler/batdongsan_pw.py",
        "crawler/guland_crawler.py",
        "cleansing/dedup.py",
        "analytics/valuation.py",
        "analytics/market_trend.py"
    ]
    
    logging.info("=== BẮT ĐẦU CHU KỲ CẬP NHẬT DỮ LIỆU ===")
    for s in scripts:
        if os.path.exists(s):
            run_script(s)
        else:
            logging.warning(f"Không tìm thấy file: {s}")
    logging.info("=== KẾT THÚC CHU KỲ ===")
