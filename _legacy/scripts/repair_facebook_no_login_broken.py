import sys
import json
import time
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.database_sqlite import get_conn

def repair_facebook_no_login_broken():
    from playwright.sync_api import sync_playwright

    print("Fetching Facebook listings with broken/expired images...")
    with get_conn() as conn:
        # Target listings where local_path is NULL or NOT_FOUND
        rows = conn.execute("""
            SELECT DISTINCT r.id, r.url, r.raw_json, l.id as listing_id
            FROM raw_listings r
            JOIN listings l ON r.id = l.raw_id
            JOIN listing_images li ON l.id = li.listing_id
            WHERE r.source = 'facebook'
              AND (li.local_path IS NULL OR li.local_path = 'NOT_FOUND')
            ORDER BY l.posted_at DESC
            LIMIT 50
        """).fetchall()

    if not rows:
        print("No Facebook listings with broken images found. Done!")
        return

    print(f"Found {len(rows)} listings to repair WITHOUT login...")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        success_count = 0
        for i, row in enumerate(rows):
            raw_id, url, raw_json_str, listing_id = row
            print(f"[{i+1}/{len(rows)}] {url[-50:]}")

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                time.sleep(4)

                # Check for login wall
                if "login" in page.url or "checkpoint" in page.url:
                    print("  -> Login wall detected. Skipping.")
                    continue

                # Dismiss popups
                try:
                    page.click('div[aria-label="Đóng"]', timeout=2000)
                except:
                    try:
                        page.click('div[aria-label="Close"]', timeout=1000)
                    except:
                        pass

                # Extraction logic for high-res if possible
                imgs = page.evaluate("""
                    () => {
                        const results = [];
                        const seen = new Set();
                        // Target the main post images
                        const postImgs = document.querySelectorAll('img');
                        for (const img of postImgs) {
                            const src = img.getAttribute('data-src') || img.src;
                            if (src && src.includes('scontent') && !src.includes('avatar') && !src.includes('logo')) {
                                if (!seen.has(src)) {
                                    seen.add(src);
                                    results.push(src);
                                }
                            }
                        }
                        return results.slice(0, 8);
                    }
                """)

                if imgs:
                    raw_data = json.loads(raw_json_str)
                    raw_data["imgs"] = imgs

                    db = sqlite3.connect(r'C:\Users\ASUS\radar_bds.db', timeout=30)
                    try:
                        db.execute("UPDATE raw_listings SET raw_json=? WHERE id=?", (json.dumps(raw_data, ensure_ascii=False), raw_id))
                        db.execute("DELETE FROM listing_images WHERE listing_id=?", (listing_id,))
                        for idx, src in enumerate(imgs):
                            db.execute("INSERT OR IGNORE INTO listing_images (listing_id, img_url, local_path, img_order) VALUES (?, ?, NULL, ?)", (listing_id, src, idx))
                        db.commit()
                        success_count += 1
                        print(f"  -> Successfully rescued {len(imgs)} images.")
                    except Exception as e:
                        print(f"  -> DB Error: {e}")
                    finally:
                        db.close()
                else:
                    print("  -> No images found.")

            except Exception as e:
                print(f"  -> Error: {e}")

        browser.close()

    print(f"\nDone! Rescued {success_count}/{len(rows)} listings.")

if __name__ == "__main__":
    repair_facebook_no_login_broken()
