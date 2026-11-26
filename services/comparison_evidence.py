"""Buyer-facing evidence calculated from the asking prices actually shown."""
from statistics import median

from services.listing_evidence import _date_label, _positive
from services.market_data import ROAD_TIER_LABELS


def _number(value):
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def comparison_summary(asking_ppm2, items):
    prices = [item["asking_ppm2"] for item in items if _positive(item.get("asking_ppm2"))]
    parts = []
    if _positive(asking_ppm2):
        parts.append(f"Lô đang xem: {_number(asking_ppm2)} triệu/m².")
    n = len(prices)
    if not n:
        parts.append("Chưa có tin rao đủ điều kiện để so đơn giá.")
    elif n < 5:
        parts.append(f"Chỉ có {n} tin rao đối chiếu. Mẫu còn ít để kết luận về mặt bằng giá.")
    else:
        parts.append(f"Trung vị giá rao của {n} tin dưới đây: {_number(median(prices))} triệu/m².")
    return " ".join(parts)


def add_comparison_evidence(card, row, *, area, road_tier, tho_cu):
    card["asking_ppm2"] = _positive(row["price_per_m2"])
    card["observed_at_label"] = _date_label(row.get("last_seen_at")) or _date_label(row.get("crawled_at"))
    differences = []
    road = ROAD_TIER_LABELS.get(row.get("road_tier"))
    target_road = ROAD_TIER_LABELS.get(road_tier)
    if road and target_road and road != target_road:
        differences.append(f"Đường vào: {road.lower()} (lô đang xem: {target_road.lower()})")
    if not road or not target_road:
        differences.append("Chưa đủ dữ liệu đối chiếu đường vào")
    for label, target, sample in (
        ("Diện tích", area, row.get("area_m2")),
        ("Thổ cư", tho_cu, row.get("tho_cu_m2")),
    ):
        if target is None or sample is None:
            if label == "Thổ cư":
                differences.append("Chưa đủ dữ liệu đối chiếu thổ cư")
        elif abs(sample - target) >= 0.01:
            differences.append(f"{label} {'nhiều' if sample > target else 'ít'} hơn {_number(abs(sample - target))} m²")
    card["comparison_note"] = " · ".join(differences) or "Cùng nhóm đường, diện tích và diện tích thổ cư ghi nhận."
    return card
