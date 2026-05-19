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

WARDS = [
    "Tân An", "Phú An", "Hiệp An", "Chánh Nghĩa", "Phú Cường",
    "Phú Hòa", "Phú Lợi", "Phú Mỹ", "Phú Thọ", "Định Hòa",
    "Tương Bình Hiệp", "Chánh Mỹ", "Hòa Phú", "Mỹ Phước",
]

_SYSTEM = (
    "Bạn là chuyên gia phân tích BĐS Thủ Dầu Một, Bình Dương. "
    "Trích xuất thông tin từ danh sách bài đăng BĐS. "
    "Luôn trả về JSON object có key \"results\" chứa array kết quả, không giải thích thêm."
)

_USER_TMPL = """\
Trích xuất thông tin từ {n} bài đăng BĐS dưới đây.
Trả về JSON object: {{"results": [...]}}
Mỗi phần tử trong array gồm:
- "id": giữ nguyên số từ input
- "ward": tên phường (chỉ chọn trong {wards}, hoặc null nếu không rõ)
- "road_type": "hem_xe_may" | "hem_ba_gac" | "hem_xe_hoi" | "duong_nhua" | "be_tong" | "duong_dat" | "mat_tien_kinh_doanh" | null
- "road_tier": 1 nếu mặt tiền đường lớn có tên (Lê Chí Dân, Mạc Đĩnh Chi...); \
2 nếu đường nhựa/ĐX/mặt tiền không hẻm; \
3 nếu hẻm bê tông xe hơi vào được (rộng hơn 3m); \
4 nếu hẻm xe máy (dưới 3m hoặc ghi rõ chỉ xe máy); \
null nếu không rõ
- "has_so": false chỉ khi bài ghi rõ không có sổ ("không sổ","chưa có sổ","vi bằng","giấy tay","đang làm sổ"); \
true trong mọi trường hợp còn lại (mặc định)

BÀI ĐĂNG (JSON array):
{listings_json}"""


_FULL_USER_TMPL = """\
Trích xuất thông tin từ {n} bài đăng BĐS Thủ Dầu Một, Bình Dương.
Trả về JSON object: {{"results": [...]}}
Mỗi phần tử trong array gồm:
- "id": giữ nguyên số từ input
- "price_ty": giá bán (float, đơn vị tỷ VNĐ; null nếu thỏa thuận hoặc không rõ)
- "area_m2": tổng diện tích (float, m²; null nếu không rõ)
- "frontage_m": chiều ngang mặt tiền lô đất (float, m; null nếu không rõ)
- "tx_type": "ban" | "thue" (mặc định "ban")
- "property_type": "nha_dat" | "dat_nen" | "dat_vuon" | "chung_cu" | "xuong_kho" | null
- "ward": tên phường (chỉ chọn trong {wards}; null nếu không rõ)
- "road_tier": 1 (mặt tiền đường lớn có tên) | 2 (đường nhựa/DX/mặt tiền) | 3 (hẻm bê tông xe hơi >3m) | 4 (hẻm xe máy <3m) | null
- "road_type": "hem_xe_may" | "hem_ba_gac" | "hem_xe_hoi" | "duong_nhua" | "be_tong" | "mat_tien_kinh_doanh" | null
- "has_so": false CHỈ KHI ghi rõ không có sổ / vi bằng / giấy tay / đang làm sổ; true trong mọi trường hợp còn lại
- "is_hot": true nếu có từ "cắt lỗ" / "ngộp" / "bán gấp" / "bán nhanh" / "kẹt tiền" / "giảm sốc" / "hạ giá"

BÀI ĐĂNG (JSON array):
{listings_json}"""


class GroqEnricher:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.enabled = bool(self.api_key)
        if not self.enabled:
            logger.warning("GROQ_API_KEY không tìm thấy trong .env")

    def enrich_batch(self, listings: list) -> dict:
        """
        listings: [{"id": int, "title": str, "description": str}]
        returns:  {id: {"ward": ..., "road_type": ..., "road_tier": ..., "has_so": ...}}
        """
        if not self.enabled or not listings:
            return {}

        user_msg = _USER_TMPL.format(
            n=len(listings),
            wards=WARDS,
            listings_json=json.dumps(listings, ensure_ascii=False),
        )
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 2048,
        }
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()

        content = resp.json()["choices"][0]["message"]["content"]
        raw = json.loads(content)

        items = raw.get("results", [])
        if not isinstance(items, list):
            logger.warning(f"Groq trả về format lạ: {list(raw.keys())}")
            return {}

        return {item["id"]: item for item in items if isinstance(item, dict) and "id" in item}

    def enrich_full_batch(self, listings: list) -> dict:
        """
        Full extraction: price, area, property_type, road_tier, road_type,
        frontage_m, has_so, is_hot, tx_type, ward.
        listings: [{"id": int, "title": str, "description": str}]
        """
        if not self.enabled or not listings:
            return {}

        user_msg = _FULL_USER_TMPL.format(
            n=len(listings),
            wards=WARDS,
            listings_json=json.dumps(listings, ensure_ascii=False),
        )
        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": user_msg},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 3000,
        }
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=45,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        raw = json.loads(content)
        items = raw.get("results", [])
        if not isinstance(items, list):
            logger.warning(f"Groq full extract: format lạ — {list(raw.keys())}")
            return {}
        return {item["id"]: item for item in items if isinstance(item, dict) and "id" in item}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    e = GroqEnricher()
    if not e.enabled:
        print("Thiếu GROQ_API_KEY trong .env")
    else:
        test = [
            {"id": 1, "title": "Bán đất Tân An 5x20 sổ đỏ 1ty2", "description": "đường nhựa 6m, gần chợ"},
            {"id": 2, "title": "Lô đất hẻm xe hơi 4m Hiệp An", "description": "chưa có sổ, giá 800 triệu"},
        ]
        result = e.enrich_batch(test)
        print(json.dumps(result, ensure_ascii=False, indent=2))
