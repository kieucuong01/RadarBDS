import os
import json
import logging
import google.generativeai as genai
from typing import Optional, Dict
from dotenv import load_dotenv
from pathlib import Path

# Load env từ thư mục gốc
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

class GeminiEnricher:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not found in environment.")
            self.model = None
            return

        genai.configure(api_key=self.api_key)
        # Quay lại gemini-2.0-flash - Model Flash mới nhất
        self.model = genai.GenerativeModel('gemini-2.0-flash')

    def enrich_listing(self, title: str, description: str) -> Optional[Dict]:
        """
        Gửi nội dung bài đăng sang Gemini để bóc tách thông tin nâng cao.
        """
        if not self.model:
            return None

        prompt = f"""
        Bạn là một chuyên gia phân tích dữ liệu bất động sản tại Thủ Dầu Một, Bình Dương.
        Nhiệm vụ của bạn là đọc nội dung bài đăng và trích xuất thông tin chính xác dưới dạng JSON.

        NỘI DUNG BÀI ĐĂNG:
        Tiêu đề: {title}
        Mô tả: {description}

        YÊU CẦU TRÍCH XUẤT (JSON):
        1. "ward": Tên phường chính xác (Tân An, Phú An, Hiệp An, Chánh Hiệp, Chánh Mỹ, Tương Bình Hiệp, Định Hòa, Hiệp Thành, Chánh Nghĩa, Phú Mỹ, Phú Lợi, Phú Hòa, Phú Cường, Phú Tân). Nếu không chắc chắn, để null.
        2. "road_type": Phân loại đường: 'hem_xe_may', 'hem_ba_gac', 'hem_xe_hoi', 'duong_nhua', 'mat_tien_kinh_doanh'.
        3. "road_width_m": Chiều rộng đường (số mét), ví dụ: 6.0. Nếu không ghi, để null.
        4. "price_ty": Tổng giá trị (tỷ VNĐ). Hãy cẩn thận với đơn vị "tỷ", "triệu". Ví dụ "1 tỷ 2" là 1.2.
        5. "area_m2": Tổng diện tích (m2).
        6. "is_verified_deal": true nếu thông tin giá và diện tích logic, không có dấu hiệu nhầm lẫn (ví dụ ghi nhầm giá/m2 thành giá tổng).
        7. "reason": Giải thích ngắn gọn nếu phát hiện sai sót hoặc xác nhận deal hời.

        TRẢ VỀ DUY NHẤT JSON, KHÔNG GIẢI THÍCH THÊM.
        """

        try:
            response = self.model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    response_mime_type="application/json",
                )
            )
            data = json.loads(response.text)
            return data
        except Exception as e:
            logger.error(f"Gemini enrichment error: {e}")
            return None

if __name__ == "__main__":
    # Test nhanh
    logging.basicConfig(level=logging.INFO)
    enricher = GeminiEnricher()
    test_text = "Bán đất Hiệp An, đường nhựa 6m thông, 5x20 tc 60m. Giá 1 tỷ 250 triệu chốt."
    result = enricher.enrich_listing("Nguồn mới Hiệp An", test_text)
    print(json.dumps(result, indent=2, ensure_ascii=False))
