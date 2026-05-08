import sys
import json
import time
import sqlite3
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.database_sqlite import get_conn

def repair_all_missing_images():
    from playwright.sync_api import sync_playwright

    print("Fetching listings missing images from DB...")
    with get_conn() as conn:
        # Find raw_listings (Guland & Batdongsan) that have NO records in listing_images
        rows = conn.execute("""
            SELECT r.id, r.url, r.source, r.raw_json, l.id as listing_id
            FROM raw_listings r
            JOIN listings l ON r.id = l.raw_id
            WHERE r.source IN ('guland', 'batdongsan')
              AND NOT EXISTS (
                  SELECT 1 FROM listing_images li WHERE li.listing_id = l.id
              )
            ORDER BY r.id DESC
            LIMIT 200
        """).fetchall()
        
    if not rows:
        print("No missing images found for Guland/Batdongsan!")
        return

    print(f"Found {len(rows)} listings missing images. Starting visible repair...")
    
    with sync_playwright() as pw:
        # Launch visible browser to bypass Cloudflare
        browser = pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1280, 'height': 800}
        )
        page = context.new_page()
        
        success_count = 0
        for i, row in enumerate(rows):
            raw_id, url, source, raw_json_str, listing_id = row
            print(f"[{i+1}/{len(rows)}] Repairing {source}: {url[-60:]}")
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                time.sleep(3) # Wait for images to load
                
                imgs = []
                if source == "guland":
                    imgs = page.evaluate('''
                        () => [...document.querySelectorAll('img')]
                                    .map(i => i.getAttribute('data-src') || i.getAttribute('src'))
                                    .filter(s => s && s.startsWith('http') && !s.includes('logo') && !s.includes('avatar'))
                    ''')
                elif source == "batdongsan":
                    imgs = page.evaluate('''
                        () => [...document.querySelectorAll('.re__media-slider img[src], .re__media-thumb-slider img[src], .re__media-thumb-item img[src], .js__card img, img[src*="batdongsan"]')]
                                        .map(img => img.getAttribute('data-src') || img.src)
                                        .filter(src => src && src.startsWith('http') && !src.includes('avatar') && !src.includes('logo'))
                    ''')
                    
                if imgs:
                    raw_data = json.loads(raw_json_str)
                    raw_data["imgs"] = imgs
                    
                    conn = sqlite3.connect(r'C:\Users\ASUS\radar_bds.db', timeout=30)
                    try:
                        conn.execute("UPDATE raw_listings SET raw_json=? WHERE id=?", 
                                     (json.dumps(raw_data, ensure_ascii=False), raw_id))
                        
                        # Clear existing images just in case
                        conn.execute("DELETE FROM listing_images WHERE listing_id=?", (listing_id,))
                        
                        # Insert directly (ignore duplicates)
                        for idx, src in enumerate(imgs[:8]): # max 8 images
                            conn.execute("""
                                INSERT OR IGNORE INTO listing_images (listing_id, img_url, local_path, img_order)
                                VALUES (?, ?, NULL, ?)
                            """, (listing_id, src, idx))
                        conn.commit()
                        success_count += 1
                        print(f"  -> Extracted & saved {len(imgs)} images.")
                    except Exception as e:
                        print(f"  -> DB Error: {e}")
                    finally:
                        conn.close()
                else:
                    print("  -> No images found.")
                    
            except Exception as e:
                print(f"  -> Page Error: {e}")
                
        browser.close()
        print(f"\\nRepair done! Successfully rescued images for {success_count} listings.")

if __name__ == "__main__":
    repair_all_missing_images()
