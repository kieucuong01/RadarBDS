import re

def _parse_price(p):
    if not p: return None
    p = str(p).strip().lower().replace(",", ".")
    try:
        if "tỷ" in p or "ty" in p:
            num = re.sub(r"[^\d.]", "", p.split("t")[0].strip())
            return float(num) if num else None
        if "triệu" in p or "trieu" in p:
            num = re.sub(r"[^\d.]", "", p.split("t")[0].strip())
            val = float(num) if num else None
            return val / 1000 if val else None
    except Exception:
        pass
    return None

def _parse_area(a):
    if not a: return None
    try:
        return float(str(a).replace(",", "."))
    except Exception:
        return None

def _detect_prop(title):
    t = title.lower()
    if any(x in t for x in ["đất vườn", "vườn", "vuon"]): return "dat_vuon"
    if any(x in t for x in ["nhà phố", "nha pho"]): return "nha_pho"
    if any(x in t for x in ["biệt thự", "biet thu"]): return "biet_thu"
    if any(x in t for x in ["nhà ", "ban nha"]): return "nha"
    if any(x in t for x in ["đất ", "ban dat", "dat "]): return "dat_nen"
    return "khac"

def _map_road_type(raw: str) -> str:
    s = raw.lower()
    if "nhựa" in s or "nhua" in s:  return "nhua"
    if "bê tông" in s or "be tong" in s: return "be_tong"
    if "đất" in s:                   return "dat"
    if "hẻm" in s or "hem" in s:    return "hem"
    return "unknown"

def _map_has_so(legal_raw: str) -> int:
    s = legal_raw.lower()
    if any(x in s for x in ["sổ hồng", "so hong", "sổ đỏ", "so do", "có sổ"]): return 1
    if any(x in s for x in ["chưa có", "không có", "chua co", "giấy tay"]): return 0
    return 0

def _parse_road_width(raw: str):
    if not raw: return None
    try:
        return float(re.sub(r"[^\d.]", "", raw))
    except Exception:
        return None
