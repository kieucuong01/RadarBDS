"""
Script tải hình ảnh về local để hiển thị trên dashboard.
Mục đích: Tránh lỗi ảnh CDN của FB, Guland, Batdongsan bị chặn hoặc hết hạn.
"""
import logging
import os
import time
import urllib.request
from pathlib import Path

from config.database_sqlite import get_conn
from services.image_assets import ensure_thumbnail

logger = logging.getLogger(__name__)

# Thư mục lưu ảnh: cùng cấp với DB
DATA_DIR = Path(__file__).parent.parent / "data" / "images"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Fake User-Agent để tránh 403 Forbidden
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def download_images(limit: int = 1000):
    """
    Quét bảng listing_images, tải các ảnh chưa có local_path.
    Chỉ lấy các ảnh cover (img_order = 0) để tiết kiệm dung lượng, hoặc tùy nhu cầu.
    """
    logger.info(f"Bắt đầu tải ảnh vào: {DATA_DIR}")
    
    with get_conn() as conn:
        # Lấy danh sách ảnh cần tải (ưu tiên ảnh bìa img_order=0 trước)
        rows = conn.execute("""
            SELECT id, listing_id, img_url, img_order
            FROM listing_images
            WHERE local_path IS NULL
            ORDER BY img_order ASC, id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        
    if not rows:
        logger.info("Không có ảnh mới cần tải.")
        return 0

    success_count = 0
    
    for row in rows:
        img_id     = row['id']
        listing_id = row['listing_id']
        img_url    = row['img_url']
        img_order  = row['img_order']
        
        if not img_url or not img_url.startswith('http'):
            continue
            
        # Extract extension
        ext = '.jpg'
        if '.png' in img_url.lower():
            ext = '.png'
        elif '.webp' in img_url.lower():
            ext = '.webp'
            
        filename = f"{listing_id}_{img_order}{ext}"
        local_file_path = DATA_DIR / filename
        relative_path = f"data/images/{filename}"
        
        try:
            req = urllib.request.Request(img_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as response:
                img_data = response.read()
                with open(local_file_path, "wb") as f:
                    f.write(img_data)
            try:
                ensure_thumbnail(local_file_path)
            except Exception as e:
                logger.warning(f"Không tạo được thumbnail {local_file_path}: {e}")
            
            # Cập nhật DB
            with get_conn() as conn:
                conn.execute(
                    "UPDATE listing_images SET local_path = ? WHERE id = ?",
                    (relative_path, img_id)
                )
            success_count += 1
            logger.info(f"Đã tải ảnh: {relative_path}")
            
            time.sleep(0.5) # Tránh bị rate limit
            
        except urllib.error.HTTPError as e:
            logger.warning(f"Lỗi tải ảnh {img_url}: {e.code}")
            if e.code in (404, 403, 410): # Nếu ảnh chết hoàn toàn
                # Đánh dấu đã thử tải nhưng thất bại để lần sau không tải lại
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE listing_images SET local_path = ? WHERE id = ?",
                        ('NOT_FOUND', img_id)
                    )
        except Exception as e:
            logger.warning(f"Lỗi tải ảnh {img_url}: {str(e)}")

    logger.info(f"Đã tải thành công: {success_count}/{len(rows)} ảnh.")
    return success_count

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    download_images()
