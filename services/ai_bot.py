import os
import json
import logging
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

class AIBot:
    def __init__(self, db_path: str):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.db_path = db_path
        self.enabled = bool(self.api_key)

    def get_market_context(self):
        """Fetch some basic market stats to give the AI context."""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Get top 5 signals
            signals = conn.execute("""
                SELECT l.title, l.ward, l.price_ty, v.mos_pct 
                FROM listings l 
                JOIN valuation_results v ON l.id = v.listing_id 
                WHERE v.is_signal = 1 
                ORDER BY v.mos_pct DESC LIMIT 5
            """).fetchall()
            
            # Get avg price by ward
            avg_prices = conn.execute("""
                SELECT ward, AVG(price_per_m2) as avg_p 
                FROM listings 
                WHERE price_per_m2 > 0 
                GROUP BY ward ORDER BY AVG(price_per_m2) DESC LIMIT 10
            """).fetchall()
            
            context = "Dữ liệu thị trường hiện tại:\n"
            context += "- Top 5 cơ hội (Signals): " + ", ".join([f"{r['title']} ({r['ward']}, {r['price_ty']} tỷ, MOS {r['mos_pct']}%)" for r in signals]) + "\n"
            context += "- Giá trung bình một số khu vực: " + ", ".join([f"{r['ward']}: {round(r['avg_p'],1)} tr/m2" for r in avg_prices])
            return context
        except Exception as e:
            logger.error(f"Error getting market context: {e}")
            return "Không có dữ liệu thị trường mới nhất."
        finally:
            conn.close()

    def chat(self, message: str, history: list = None) -> str:
        if not self.enabled:
            return "Tính năng AI Chat hiện chưa được cấu hình (Thiếu API Key)."

        market_context = self.get_market_context()
        
        system_msg = (
            "Bạn là trợ lý ảo chuyên nghiệp của RadarBDS, chuyên về bất động sản Bình Dương (đặc biệt là Thủ Dầu Một). "
            "Sử dụng dữ liệu thị trường cung cấp dưới đây để trả lời câu hỏi của khách hàng. "
            "Hãy trả lời thân thiện, chuyên nghiệp và ngắn gọn. "
            f"\n\n{market_context}"
        )

        messages = [{"role": "system", "content": system_msg}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": message})

        try:
            payload = {
                "model": GROQ_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1024,
            }
            resp = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Groq Chat Error: {e}")
            return "Xin lỗi, tôi đang gặp trục trặc kỹ thuật. Vui lòng thử lại sau."
