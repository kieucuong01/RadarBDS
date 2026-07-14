def test_binh_duong_market_report_page_now_focuses_on_thu_dau_mot_wards_only():
    import app as radar_app

    html = radar_app.app.test_client().get("/bao-cao/bds-binh-duong-thang-06-2026").get_data(as_text=True)

    assert "chỉ tập trung các phường Thủ Dầu Một" in html
    assert "Phú Mỹ" in html
    assert "Định Hòa" in html
    assert "Hiệp Thành" in html
    assert "Hiệp An" in html

    report_block = html.split('class="seo-report-block"', 1)[1].split("</section>", 1)[0]
    assert "Mỹ Phước" not in report_block
    assert "Bến Cát" not in report_block
