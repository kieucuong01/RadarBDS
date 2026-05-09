"""
Macro Clock Service
Tracks SBV (State Bank of Vietnam) monetary policy cycle.
Update MACRO_CONFIG when policy changes.
Last updated: 2026-05-09
"""

# ============================================================
# CONFIG: Update this when SBV changes policy
# ============================================================
MACRO_CONFIG = {
    "state": "easing",           # "easing" | "tightening" | "neutral"
    "policy_rate_pct": 4.5,      # SBV base rate (%)
    "credit_growth_target": 15,  # YTD credit growth target (%)
    "credit_growth_actual": 3.8, # YTD actual credit growth (%)
    "last_change": "2023-06-15", # Date of last rate change
    "direction": "down",         # "down" (cut) | "up" (hike) | "hold"
    "source": "NHNN Việt Nam",
    "updated_at": "2026-05-01",
}

# ============================================================
# Strategy rules per cycle state
# ============================================================
STRATEGIES = {
    "easing": {
        "label": "Nới lỏng",
        "color": "#10B981",
        "color_bg": "rgba(16, 185, 129, 0.1)",
        "icon": "trending-up",
        "summary": "Tín dụng mở rộng — đây là thời điểm tốt để đón sóng hạ tầng và đất vùng ven.",
        "recommendations": [
            {"icon": "map", "text": "Đón sóng hạ tầng — BĐS vùng ven gần dự án lớn"},
            {"icon": "maximize-2", "text": "Đất diện tích lớn có tiềm năng phân lô"},
            {"icon": "trending-up", "text": "Lướt sóng ngắn hạn tại khu công nghiệp mới"},
            {"icon": "building", "text": "Đất nông nghiệp có quy hoạch chuyển đổi"},
        ],
        "filter_hint": None,  # No auto-filter in easing mode
    },
    "tightening": {
        "label": "Thắt chặt",
        "color": "#EF4444",
        "color_bg": "rgba(239, 68, 68, 0.1)",
        "icon": "shield",
        "summary": "Tín dụng thu hẹp — ưu tiên tài sản dòng tiền thực, pháp lý sạch, nhu cầu ở thực.",
        "recommendations": [
            {"icon": "home", "text": "Đất nền trung tâm, thổ cư pháp lý chuẩn"},
            {"icon": "store", "text": "Nhà phố cho thuê — dòng tiền ổn định"},
            {"icon": "shield-check", "text": "Ưu tiên Sổ Hồng, tránh đất giấy tay"},
            {"icon": "x-circle", "text": "Hạn chế đất nông nghiệp vùng ven không có thổ cư"},
        ],
        "filter_hint": "Tự động ẩn đất nông nghiệp vùng ven không có thổ cư trong Bộ lọc.",
        "auto_hide_prop_types": ["dat_vuon"],
    },
    "neutral": {
        "label": "Trung lập",
        "color": "#F59E0B",
        "color_bg": "rgba(245, 158, 11, 0.1)",
        "icon": "minus-circle",
        "summary": "Chính sách tiền tệ ổn định — cân bằng danh mục giữa tài sản an toàn và tăng trưởng.",
        "recommendations": [
            {"icon": "layers", "text": "Đa dạng hóa: kết hợp đất trung tâm và vùng ven"},
            {"icon": "percent", "text": "Ưu tiên sản phẩm có tỷ suất sinh lời > 8%"},
            {"icon": "shield", "text": "Giữ tỷ lệ vay không quá 50% giá trị tài sản"},
        ],
        "filter_hint": None,
    }
}


def get_macro_state():
    """Return the current macro clock state with all recommendations."""
    cfg = MACRO_CONFIG.copy()
    state_key = cfg["state"]
    strategy = STRATEGIES.get(state_key, STRATEGIES["neutral"])

    # Gauge needle position (0–180 degrees):
    # 0° = Thắt chặt cực mạnh, 90° = Trung lập, 180° = Nới lỏng tối đa
    gauge_angle = {
        "tightening": 30,
        "neutral": 90,
        "easing": 150,
    }.get(state_key, 90)

    return {
        **cfg,
        **strategy,
        "gauge_angle": gauge_angle,
    }
