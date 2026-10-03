from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "rb_page_news_workflow.py"
spec = importlib.util.spec_from_file_location("rb_page_news_workflow", MODULE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _iso(hours: int = 0, days: int = 0) -> str:
    base = dt.datetime(2026, 9, 12, 10, 0, tzinfo=dt.timezone.utc)
    return (base + dt.timedelta(hours=hours, days=days)).isoformat()


def _candidate(cid: str = "n1", *, url: str = "https://cafeland.vn/tin-tuc/foo.html", text: str = "UBND tỉnh cho biết dự án đang lấy ý kiến, chưa khởi công.", published_at: str | None = None, fetched_at: str | None = None, is_primary: bool = False, requires_primary: bool = False, trend_evidence=None) -> dict:
    return {
        "id": cid,
        "url": url,
        "publisher": "CafeLand",
        "title": "Bình Dương cập nhật quy hoạch khu vực Dĩ An",
        "published_at": published_at or _iso(days=-1),
        "fetched_at": fetched_at or _iso(hours=-1),
        "text": text,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "is_primary": is_primary,
        "eligible": True,
        "classification": "news_candidate",
        "trend_evidence": trend_evidence or [],
        "location": "Bình Dương",
        "topic_key": "quy-hoach-di-an",
        "score": 8.5,
        "requires_primary": requires_primary,
        "rejection_reasons": [],
    }


def _product_reference(
    cid: str = "r1",
    *,
    text: str = "So cùng loại đường, cùng tình trạng đất ở trước khi hỏi giá m2.",
    url: str = "https://radarbds.vn/tin-tuc/cach-doc-gia-m2-dat-nen-binh-duong",
    published_at: str | None = "2026-07-25",
    fetched_at: str | None = None,
) -> dict:
    return {
        "id": cid,
        "url": url,
        "publisher": "Radar BDS",
        "title": "Cách đọc giá m2 đất nền Bình Dương",
        "published_at": published_at,
        "fetched_at": fetched_at or _iso(hours=-1),
        "text": text,
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "is_primary": False,
        "eligible": True,
        "classification": "product_reference",
        "trend_evidence": [],
        "location": "Bình Dương",
        "topic_key": "cach-doc-gia-m2-dat-nen-binh-duong",
        "score": 0,
        "requires_primary": False,
        "rejection_reasons": [],
    }


def _report(*candidates: dict) -> dict:
    return {"schema": "rb_page_news_discovery.v1", "generated_at": _iso(), "candidates": list(candidates), "errors": []}


def _draft() -> dict:
    return {
        "schema": "rb_page_news_draft.v1",
        "selected_ids": ["n1"],
        "headline": "Quy hoạch Dĩ An: đọc tin theo mốc chính thức",
        "caption": "Theo CafeLand ngày 11/09/2026, Dĩ An có cập nhật quy hoạch cần đọc theo mốc chính thức. Người mua nên kiểm tra văn bản gốc trước khi đặt cọc.",
        "reader_benefit": "Giúp người mua biết cần kiểm tra giấy tờ nào trước khi hỏi giá.",
        "radar_url": "https://radarbds.vn/tin-tuc/gia-dat-phu-tan-hien-bao-nhieu",
        "visual_mode": "infographic",
        "claims": [
            {"source_id": "n1", "quote": "dự án đang lấy ý kiến", "kind": "news", "claim": "Dự án đang ở bước lấy ý kiến."}
        ],
        "event_status": "đang lấy ý kiến, chưa khởi công",
        "known_unknowns": ["Chưa có thời điểm phê duyệt cuối cùng trong bài nguồn."],
    }


def test_recommended_lane_targets_three_news_per_ten_without_consecutive_news():
    posted = {
        "radar-a": {"posted_at": "2026-09-01T18:40:00+07:00", "lane": "radar"},
        "radar-b": {"posted_at": "2026-09-02T18:40:00+07:00", "lane": "radar"},
        "news-a": {"posted_at": "2026-09-03T18:40:00+07:00", "lane": "news"},
        "news-b": {"posted_at": "2026-09-04T18:40:00+07:00", "lane": "news"},
        "radar-c": {"posted_at": "2026-09-05T18:40:00+07:00", "lane": "radar"},
        "radar-d": {"posted_at": "2026-09-06T18:40:00+07:00", "lane": "radar"},
        "radar-e": {"posted_at": "2026-09-07T18:40:00+07:00", "lane": "radar"},
        "radar-f": {"posted_at": "2026-09-08T18:40:00+07:00", "lane": "radar"},
        "radar-g": {"posted_at": "2026-09-09T18:40:00+07:00", "lane": "radar"},
        "old-unknown": {"posted_at": "2026-09-10T18:40:00+07:00"},
    }

    assert mod.recommended_lane(posted) == "news"

    posted["news-c"] = {"posted_at": "2026-09-11T18:40:00+07:00", "lane": "news"}
    assert mod.recommended_lane(posted) == "radar"

    posted["radar-h"] = {"posted_at": "2026-09-12T18:40:00+07:00", "lane": "radar"}
    assert mod.recommended_lane(posted) == "radar"


def test_validate_report_and_draft_rejects_forged_hash_and_missing_quote():
    bad_hash = _candidate()
    bad_hash["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="content_sha256"):
        mod.validate_report_and_draft(_report(bad_hash), _draft(), now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))

    draft = _draft()
    draft["claims"][0]["quote"] = "không có trong nguồn"
    with pytest.raises(ValueError, match="quote"):
        mod.validate_report_and_draft(_report(_candidate()), draft, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))


def test_material_law_infrastructure_financing_claim_requires_official_primary_source():
    source = _candidate(text="Một môi giới nói tuyến đường sẽ mở rộng trong năm nay.", requires_primary=False)
    draft = _draft()
    draft["claims"] = [{"source_id": "n1", "quote": "tuyến đường sẽ mở rộng", "kind": "infrastructure", "claim": "Tuyến đường sẽ mở rộng trong năm nay."}]

    with pytest.raises(ValueError, match="primary"):
        mod.validate_report_and_draft(_report(source), draft, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))

    official_text = "UBND tỉnh thông báo tuyến đường sẽ mở rộng sau khi phê duyệt kế hoạch."
    official = _candidate("gov1", url="https://binhduong.gov.vn/van-ban/foo", text=official_text, is_primary=True)
    draft["selected_ids"] = ["n1", "gov1"]
    draft["claims"][0]["source_id"] = "gov1"
    draft["claims"][0]["quote"] = "tuyến đường sẽ mở rộng"
    assert mod.validate_report_and_draft(_report(source, official), draft, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))["lead"]["id"] == "n1"


def test_accepts_radar_product_reference_for_non_news_buyer_tip_and_preserves_date_only(tmp_path, monkeypatch):
    image = tmp_path / "concept.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(mod, "make_placeholder_image", lambda *_args, **_kwargs: image)
    product = _product_reference(published_at="2026-07-25")
    draft = _draft()
    draft["selected_ids"] = ["n1", "r1"]
    draft["claims"].append(
        {
            "source_id": "r1",
            "quote": "So cùng loại đường, cùng tình trạng đất ở",
            "kind": "buyer_tip",
            "claim": "So cùng loại đường, cùng tình trạng đất ở trước khi hỏi giá m2.",
        }
    )

    queue = mod.build_news_queue(
        _report(_candidate(published_at="2026-09-11"), product),
        draft,
        out_dir=tmp_path,
        now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc),
    )
    data = json.loads(queue.read_text(encoding="utf-8"))

    assert data["news"]["sources"][1]["published_at"] == "2026-07-25"
    assert data["news"]["sources"][1]["requires_primary"] is False


def test_rejects_product_reference_as_lead_or_non_radar_source():
    draft = _draft()
    draft["selected_ids"] = ["r1"]
    draft["claims"] = [{"source_id": "r1", "quote": "So cùng loại đường", "kind": "buyer_tip", "claim": "So cùng loại đường."}]
    with pytest.raises(ValueError, match="lead source must be news_candidate"):
        mod.validate_report_and_draft(_report(_product_reference()), draft, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))

    offsite = _product_reference(url="https://example.com/tin-tuc/cach-doc-gia-m2-dat-nen-binh-duong")
    with pytest.raises(ValueError, match="product_reference"):
        mod.validate_source_report(_report(_candidate(), offsite), now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))


def test_generated_at_z_and_news_date_only_publish_date_are_valid_honest_day():
    report = _report(_candidate(published_at="2026-09-11"))
    report["generated_at"] = "2026-09-12T10:00:00Z"

    validated = mod.validate_report_and_draft(report, _draft(), now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))

    assert validated["lead"]["published_at"] == "2026-09-11"


def test_buyer_tip_material_assertion_still_requires_primary():
    product = _product_reference(text="Đường đã được phê duyệt theo lời môi giới.")
    draft = _draft()
    draft["selected_ids"] = ["n1", "r1"]
    draft["claims"] = [
        {
            "source_id": "r1",
            "quote": "Đường đã được phê duyệt",
            "kind": "buyer_tip",
            "claim": "Đường đã được phê duyệt.",
        }
    ]

    with pytest.raises(ValueError, match="primary"):
        mod.validate_report_and_draft(_report(_candidate(published_at="2026-09-11"), product), draft, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))


def test_build_news_queue_is_browser_compatible_and_truthful(tmp_path, monkeypatch):
    image = tmp_path / "concept.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(mod, "make_placeholder_image", lambda *_args, **_kwargs: image)
    queue = mod.build_news_queue(
        _report(_candidate()),
        _draft(),
        out_dir=tmp_path,
        now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc),
    )
    data = json.loads(queue.read_text(encoding="utf-8"))

    assert data["schema"] == "radar_social_queue.v1"
    assert data["target"]["mode"] == "review"
    assert data["target"]["surface"] == "page"
    assert data["source"]["slug"].startswith("news-n1-2026-09-12")
    assert data["content"]["message"] == _draft()["caption"]
    assert "https://cafeland.vn/tin-tuc/foo.html" in data["content"]["self_comment"]
    assert "utm_source=facebook" in data["content"]["self_comment"]
    assert data["content"]["visual_prompt"].startswith("Conceptual AI illustration")
    assert "actual project progress" in data["content"]["visual_prompt"]
    assert data["editorial"]["metadata"]["pillar"] == "news_explainer"
    assert data["lane"] == "news"
    assert data["news"]["evidence"][0]["quote"] == "dự án đang lấy ý kiến"


def test_prepare_news_calls_gemini_upgrade_after_writing_queue(tmp_path, monkeypatch):
    report = tmp_path / "report.json"
    draft = tmp_path / "draft.json"
    report.write_text(json.dumps(_report(_candidate()), ensure_ascii=False), encoding="utf-8")
    draft.write_text(json.dumps(_draft(), ensure_ascii=False), encoding="utf-8")
    upgraded = []
    monkeypatch.setattr(mod.radar_auto, "upgrade_queue_image", lambda path: upgraded.append(path) or {"ok": True})
    monkeypatch.setattr(mod, "make_placeholder_image", lambda *_args, **_kwargs: (tmp_path / "concept.png"))
    (tmp_path / "concept.png").write_bytes(b"image")

    out = mod.prepare_news(report, draft, tmp_path, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))

    assert out.exists()
    assert upgraded == [out]


def test_approve_stamp_binds_caption_source_comment_evidence_and_actual_image(tmp_path):
    image = tmp_path / "concept.png"
    image.write_bytes(b"image-v1")
    monkeypatch_placeholder = lambda *_args, **_kwargs: image
    # direct assignment keeps this test independent of pytest monkeypatch fixture in helper calls
    original = mod.make_placeholder_image
    mod.make_placeholder_image = monkeypatch_placeholder
    try:
        queue = mod.build_news_queue(_report(_candidate()), _draft(), out_dir=tmp_path, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))
    finally:
        mod.make_placeholder_image = original

    stamped = mod.approve_queue(queue, note="Caption/source checked; visual is a conceptual illustration, not a map or progress photo.")
    assert stamped["review"]["stamp_hash"]
    mod.validate_review_stamp(json.loads(queue.read_text(encoding="utf-8")))

    data = json.loads(queue.read_text(encoding="utf-8"))
    data["content"]["message"] += " changed"
    queue.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="review stamp"):
        mod.validate_review_stamp(json.loads(queue.read_text(encoding="utf-8")))


def test_publish_requires_approval_dedupes_and_records_news_metadata(tmp_path, monkeypatch):
    image = tmp_path / "concept.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(mod, "make_placeholder_image", lambda *_args, **_kwargs: image)
    queue = mod.build_news_queue(_report(_candidate()), _draft(), out_dir=tmp_path, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))

    with pytest.raises(ValueError, match="approval review stamp"):
        mod.publish_queue(queue, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))

    mod.approve_queue(queue, note="Caption/source checked; visual QA checked.")
    state = {"posted": {}}
    monkeypatch.setattr(mod.radar_auto, "load_state", lambda: state)
    saved = []
    monkeypatch.setattr(mod.radar_auto, "save_state", lambda s: saved.append(json.loads(json.dumps(s))))
    monkeypatch.setattr(mod, "verify_lead_source_http", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(mod.radar_auto, "publish", lambda path: {"post_url": "https://www.facebook.com/radarbdsvn/posts/pfbid123", "browser_result": {"photo_permalink": "https://www.facebook.com/photo/?fbid=1", "verified_text": True, "verified_visual": True, "verified_comment": True}})

    result = mod.publish_queue(queue, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc), lock_path=tmp_path / "lock")

    assert result["post_url"].endswith("pfbid123")
    record = next(iter(saved[-1]["posted"].values()))
    assert record["lane"] == "news"
    assert record["news_source_urls"] == ["https://cafeland.vn/tin-tuc/foo.html"]
    assert record["news_topic_key"] == "quy-hoach-di-an"
    assert record["editorial_pillar"] == "news_explainer"

    with pytest.raises(SystemExit, match="already posted today"):
        mod.publish_queue(queue, now=dt.datetime(2026, 9, 12, 11, tzinfo=dt.timezone.utc), lock_path=tmp_path / "lock")


def test_ambiguous_publish_failure_writes_inflight_marker(tmp_path, monkeypatch):
    image = tmp_path / "concept.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(mod, "make_placeholder_image", lambda *_args, **_kwargs: image)
    queue = mod.build_news_queue(_report(_candidate()), _draft(), out_dir=tmp_path, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc))
    mod.approve_queue(queue, note="Caption/source checked; visual QA checked.")
    state = {"posted": {}}
    monkeypatch.setattr(mod.radar_auto, "load_state", lambda: state)
    monkeypatch.setattr(mod, "verify_lead_source_http", lambda *_args, **_kwargs: True)

    def fail(_path):
        raise SystemExit("browser timed out after possible click")

    monkeypatch.setattr(mod.radar_auto, "publish", fail)

    with pytest.raises(SystemExit, match="reconciliation"):
        mod.publish_queue(queue, now=dt.datetime(2026, 9, 12, 10, tzinfo=dt.timezone.utc), lock_path=tmp_path / "lock")
    marker = queue.with_suffix(".in-flight.json")
    assert marker.exists()
    assert json.loads(marker.read_text(encoding="utf-8"))["status"] == "requires_reconciliation"


ACTUAL_SEP14_RADAR_QUEUE = Path("/opt/radar-bds/var/social_preview/2026-09-14-chanh-my-hay-phu-loi-nen-xem-khu-nao-truoc-page-review.json")


def _copy_actual_sep14_radar_queue(tmp_path: Path) -> Path:
    if not ACTUAL_SEP14_RADAR_QUEUE.exists():
        pytest.skip(f"production regression fixture missing: {ACTUAL_SEP14_RADAR_QUEUE}")
    queue = tmp_path / ACTUAL_SEP14_RADAR_QUEUE.name
    data = json.loads(ACTUAL_SEP14_RADAR_QUEUE.read_text(encoding="utf-8"))
    data.setdefault("content", {})["self_comment"] = (
        "Bài Radar về Chánh Mỹ: "
        "https://radarbds.vn/tin-tuc/chanh-my-hay-phu-loi-nen-xem-khu-nao-truoc"
        "?utm_source=facebook&utm_medium=social&utm_campaign=rb_content_v2"
        "&utm_content=chanh-my-hay-phu-loi-nen-xem-khu-nao-truoc\n\n"
        "Radar BDS dùng dữ liệu giá rao để lọc ban đầu; trước khi quyết định mua vẫn cần kiểm tra thực tế, vị trí và giấy tờ."
    )
    queue.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mod.approve_queue(queue, note="Test fixture: relevant article CTA and review stamp.")
    return queue


def test_publish_routes_actual_sep14_reviewed_radar_queue_through_publish_adapter(tmp_path, monkeypatch):
    queue = _copy_actual_sep14_radar_queue(tmp_path)
    state = {"posted": {}}
    saved = []
    monkeypatch.setattr(mod.radar_auto, "load_state", lambda: state)
    monkeypatch.setattr(mod.radar_auto, "save_state", lambda s: saved.append(json.loads(json.dumps(s))))

    def fake_publish(path):
        dispatched = json.loads(Path(path).read_text(encoding="utf-8"))
        assert path != queue
        assert dispatched["lane"] == "radar"
        assert dispatched["target"]["mode"] == "publish"
        assert dispatched["target"]["requires_review"] is False
        assert dispatched["source"]["http_status"] == 200
        assert dispatched["content"]["self_comment"].count("radarbds.vn") == 1
        assert "?tab=" not in dispatched["content"]["self_comment"]
        assert "&ward=" not in dispatched["content"]["self_comment"]
        assert dispatched["review"]["stamp_hash"] == json.loads(queue.read_text(encoding="utf-8"))["review"]["stamp_hash"]
        return {
            "post_url": "https://www.facebook.com/radarbdsvn/posts/pfbid-radar-sep14",
            "browser_result": {
                "photo_permalink": "https://www.facebook.com/photo/?fbid=1914",
                "verified_text": True,
                "verified_visual": True,
                "verified_comment": True,
                "comment_needle": "Radar BDS dùng dữ liệu",
            },
        }

    monkeypatch.setattr(mod.radar_auto, "publish", fake_publish)

    result = mod.publish_queue(queue, now=dt.datetime(2026, 9, 14, 18, 50, tzinfo=mod.LOCAL_TZ), lock_path=tmp_path / "lock")

    assert result["post_url"].endswith("pfbid-radar-sep14")
    key = "chanh-my-hay-phu-loi-nen-xem-khu-nao-truoc:2026-09-12"
    record = saved[-1]["posted"][key]
    assert record["lane"] == "radar"
    assert record["editorial_pillar"] == "radar_insight"
    assert record["verified_comment"] is True
    assert record["queue"] == str(queue)


def test_publish_blocks_radar_draft_queue_before_browser_dispatch(tmp_path, monkeypatch):
    queue = _copy_actual_sep14_radar_queue(tmp_path)
    data = json.loads(queue.read_text(encoding="utf-8"))
    data["status"] = "draft"
    queue.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(mod.radar_auto, "load_state", lambda: {"posted": {}})
    monkeypatch.setattr(mod.radar_auto, "publish", lambda _path: pytest.fail("draft queue reached browser adapter"))

    with pytest.raises(ValueError, match="status"):
        mod.publish_queue(queue, now=dt.datetime(2026, 9, 14, 18, 50, tzinfo=mod.LOCAL_TZ), lock_path=tmp_path / "lock")


def test_publish_blocks_stale_radar_queue_before_browser_dispatch(tmp_path, monkeypatch):
    queue = _copy_actual_sep14_radar_queue(tmp_path)
    monkeypatch.setattr(mod.radar_auto, "load_state", lambda: {"posted": {}})
    monkeypatch.setattr(mod.radar_auto, "publish", lambda _path: pytest.fail("stale queue reached browser adapter"))

    with pytest.raises(ValueError, match="older than 7d"):
        mod.publish_queue(queue, now=dt.datetime(2026, 9, 25, 18, 50, tzinfo=mod.LOCAL_TZ), lock_path=tmp_path / "lock")


def test_publish_blocks_duplicate_radar_queue_before_browser_dispatch(tmp_path, monkeypatch):
    queue = _copy_actual_sep14_radar_queue(tmp_path)
    key = "chanh-my-hay-phu-loi-nen-xem-khu-nao-truoc:2026-09-12"
    monkeypatch.setattr(mod.radar_auto, "load_state", lambda: {"posted": {key: {"posted_at": "2026-09-13T18:40:00+07:00"}}})
    monkeypatch.setattr(mod.radar_auto, "publish", lambda _path: pytest.fail("duplicate queue reached browser adapter"))

    with pytest.raises(SystemExit, match="queue already published"):
        mod.publish_queue(queue, now=dt.datetime(2026, 9, 14, 18, 50, tzinfo=mod.LOCAL_TZ), lock_path=tmp_path / "lock")


def test_plan_cli_prints_lane_candidates_and_editorial_slugs_without_side_effects(tmp_path, monkeypatch, capsys):
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_report(_candidate()), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(mod.radar_auto, "load_state", lambda: {"posted": {"x": {"posted_at": "2026-09-12T08:00:00+07:00", "lane": "radar"}}})
    monkeypatch.setattr(mod.radar_auto, "posted_today", lambda posted: (False, None))
    monkeypatch.setattr(mod.radar_auto, "editorial_candidates", lambda posted: [{"slug": "radar-slug-a"}, {"slug": "radar-slug-b"}])

    assert mod.main(["plan", "--report", str(report)]) == 0
    out = capsys.readouterr().out
    assert "recommended_lane: news" in out
    assert "already_today: false" in out
    assert "n1" in out and "CafeLand" in out
    assert "editorial_candidates: radar-slug-a, radar-slug-b" in out
