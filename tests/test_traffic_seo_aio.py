import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path


PRIORITY_WARDS = {
    "hiep-thanh": "Hiệp Thành",
    "phu-hoa": "Phú Hòa",
    "phu-my": "Phú Mỹ",
    "dinh-hoa": "Định Hòa",
    "phu-loi": "Phú Lợi",
    "tan-an": "Tân An",
    "hiep-an": "Hiệp An",
    "chanh-nghia": "Chánh Nghĩa",
}


def _json_ld_graph(html):
    scripts = re.findall(
        r'<script type="application/ld\+json">\s*(.*?)\s*</script>',
        html,
        flags=re.DOTALL,
    )
    assert scripts, "expected server-rendered JSON-LD"
    return [item for script in scripts for item in json.loads(script).get("@graph", [])]


def _fake_signals():
    return [
        {
            "id": index,
            "title": f"Tin Hiệp Thành đáng kiểm tra {index}",
            "ward": "Hiệp Thành",
            "price_ty": 2.0 + index / 10,
            "area_m2": 90 + index,
            "actual_ppm2": 20.0 + index,
            "mos_pct": 12.0 + index,
            "prop_type_label": "Đất nền",
            "days_ago": index,
        }
        for index in range(1, 6)
    ]


def _patch_live_snapshot(monkeypatch, radar_app):
    calls = {}

    def fake_summary(*args, **kwargs):
        calls["summary"] = kwargs
        return {
            "stats": {"total": 204, "signals": 36},
            "market": [
                {"type": "land", "label": "Đất nền", "median": 22.5, "n": 120},
                {"type": "house", "label": "Nhà đất", "median": 31.2, "n": 84},
            ],
        }

    def fake_signals(*args, **kwargs):
        calls["signals"] = kwargs
        return {"signals": _fake_signals()}

    monkeypatch.setattr(radar_app, "load_dashboard_summary", fake_summary)
    monkeypatch.setattr(radar_app, "load_signals", fake_signals)
    radar_app.clear_dashboard_cache()
    radar_app.clear_signal_cache()
    return calls


def test_priority_ward_page_renders_live_search_and_aio_snapshot(monkeypatch):
    import app as radar_app

    calls = _patch_live_snapshot(monkeypatch, radar_app)
    response = radar_app.app.test_client().get("/binh-duong/phuong-hiep-thanh")
    html = response.get_data(as_text=True)
    period = datetime.now(timezone(timedelta(hours=7))).strftime("%m/%Y")

    assert response.status_code == 200
    assert f"<title>Giá nhà đất Hiệp Thành, Thủ Dầu Một tháng {period}" in html
    assert f"<h1>Giá nhà đất Hiệp Thành, Thủ Dầu Một tháng {period}</h1>" in html
    assert "Thủ Dầu Một – Bình Dương cũ" in html
    assert "204 tin" in html
    assert "36 tín hiệu" in html
    assert "Giá tham khảo trung bình" in html
    assert "22,5" in html and "31,2" in html
    for signal in _fake_signals():
        assert signal["title"] in html
    assert "Nguồn dữ liệu" in html
    assert "pháp lý" in html
    assert "không thay thế" in html
    assert '<div class="price-tag tag-one">2.3 tỷ</div>' not in html
    assert "<span>TDM</span><span>Thuận An</span>" not in html
    assert 'href="/?tab=signals&amp;ward=Hi%E1%BB%87p+Th%C3%A0nh"' in html
    assert "intent=watchlist" not in html
    assert 'href="/bao-cao/hiep-thanh-thang-07-2026"' in html
    assert "Hơn 1.000 nhà đầu tư" not in html

    assert calls["summary"]["wards"] == ["Hiệp Thành"]
    assert calls["summary"]["tier"] == "guest"
    assert calls["signals"]["wards"] == ["Hiệp Thành"]
    assert calls["signals"]["limit"] == 5
    assert calls["signals"]["include_total"] is False
    assert calls["signals"]["tier"] == "guest"

    graph = _json_ld_graph(html)
    web_page = next(item for item in graph if item.get("@type") == "WebPage")
    dataset = next(item for item in graph if item.get("@type") == "Dataset")
    assert web_page["dateModified"]
    assert dataset["dateModified"]
    assert dataset["spatialCoverage"]["name"] == "Hiệp Thành, Thủ Dầu Một – Bình Dương cũ"


def test_priority_ward_page_degrades_without_database(monkeypatch):
    import app as radar_app

    def unavailable(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(radar_app, "load_dashboard_summary", unavailable)
    monkeypatch.setattr(radar_app, "load_signals", unavailable)
    radar_app.clear_dashboard_cache()
    radar_app.clear_signal_cache()

    response = radar_app.app.test_client().get("/binh-duong/phuong-hiep-thanh")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Dữ liệu trực tiếp tạm thời chưa khả dụng" in html
    assert "Hơn 1.000 nhà đầu tư" not in html
    assert not any(item.get("@type") == "Dataset" for item in _json_ld_graph(html))


def test_natural_thu_dau_mot_ward_paths_redirect_to_canonical_pages():
    import app as radar_app

    client = radar_app.app.test_client()
    for slug in PRIORITY_WARDS:
        response = client.get(f"/binh-duong/thu-dau-mot/{slug}")
        assert response.status_code == 301
        assert response.headers["Location"].endswith(f"/binh-duong/phuong-{slug}")

    tracked = client.get(
        "/binh-duong/thu-dau-mot/hiep-thanh"
        "?utm_source=facebook&utm_medium=social"
    )
    assert tracked.headers["Location"].endswith(
        "/binh-duong/phuong-hiep-thanh"
        "?utm_source=facebook&utm_medium=social"
    )
    assert client.get("/binh-duong/thu-dau-mot/khong-ton-tai").status_code == 404


def test_llms_txt_is_stable_and_links_priority_ward_sources():
    import app as radar_app

    response = radar_app.app.test_client().get("/llms.txt")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert response.content_type == "text/plain; charset=utf-8"
    assert "https://radarbds.vn/binh-duong/thu-dau-mot" in body
    for slug in PRIORITY_WARDS:
        assert f"https://radarbds.vn/binh-duong/phuong-{slug}" in body
    assert "pháp lý" in body
    assert "không thay thế" in body
    assert "204" not in body and "36" not in body


def test_sitemap_has_unique_hub_and_only_canonical_priority_ward_urls():
    import app as radar_app

    sitemap = radar_app.app.test_client().get("/sitemap.xml").get_data(as_text=True)
    locations = re.findall(r"<loc>(.*?)</loc>", sitemap)

    assert locations.count("https://radarbds.vn/bao-cao") == 1
    assert len(locations) == len(set(locations))
    for slug in PRIORITY_WARDS:
        assert f"https://radarbds.vn/binh-duong/phuong-{slug}" in locations
        assert f"https://radarbds.vn/binh-duong/thu-dau-mot/{slug}" not in locations


def test_tracking_separates_social_utm_and_ai_referrals_without_full_referrer():
    template = Path("templates/seo_landing.html").read_text(encoding="utf-8")

    assert "socialSources" in template
    assert "socialMediums" in template
    assert "if (params.get('utm_source'))" not in template
    assert "ai_referral_visit" in template
    assert "referrer_host" in template
    for source in ("chatgpt.com", "gemini.google.com", "perplexity.ai", "copilot.microsoft.com"):
        assert source in template
    assert "referrer: document.referrer" not in template
    assert "page_referrer" not in template


def test_ai_referral_event_is_accepted_by_tracking_endpoint(monkeypatch):
    import app as radar_app

    captured = {}

    def fake_log_audit(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(radar_app, "log_audit", fake_log_audit)
    response = radar_app.app.test_client().post(
        "/api/track",
        json={
            "action": "ai_referral_visit",
            "context": {
                "ai_source": "chatgpt",
                "referrer_host": "chatgpt.com",
                "path": "/binh-duong/phuong-hiep-thanh",
                "page_slug": "binh-duong/phuong-hiep-thanh",
            },
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert captured["action"] == "ai_referral_visit"
    assert captured["context"]["referrer_host"] == "chatgpt.com"
