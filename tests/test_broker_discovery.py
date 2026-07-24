from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "radar_broker_discovery.py"
    spec = importlib.util.spec_from_file_location("radar_broker_discovery", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _config(tmp_path: Path, extra_area: dict | None = None) -> Path:
    areas = [
        {
            "city": "Thủ Dầu Một",
            "aliases": ["TDM", "Thủ Dầu Một"],
            "priority_wards": [
                {"name": "Hòa Phú", "aliases": ["Hoa Phu", "Hoà Phú", "TP mới Bình Dương"]},
                {"name": "Phú Cường", "aliases": ["Phu Cuong", "Phú Cường"]},
            ],
        },
        {
            "city": "Bến Cát",
            "aliases": ["Ben Cat", "Bến Cát"],
            "priority_wards": [
                {"name": "Mỹ Phước", "aliases": ["My Phuoc", "Mỹ Phước", "MP3"]},
                {"name": "Hòa Lợi", "aliases": ["Hoa Loi", "Hoà Lợi", "Hòa Lợi"]},
            ],
        },
    ]
    if extra_area:
        areas.append(extra_area)
    payload = {"schema": "radar_broker_discovery_targets.v1", "target_areas": areas}
    path = tmp_path / "targets.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class BrokerDiscoveryTest(unittest.TestCase):
    def test_match_area_is_config_driven_and_supports_future_cities(self):
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = mod.load_target_config(
                _config(
                    Path(tmp),
                    {
                        "city": "Dĩ An",
                        "aliases": ["Di An", "Dĩ An"],
                        "priority_wards": [{"name": "Tân Đông Hiệp", "aliases": ["Tan Dong Hiep"]}],
                    },
                )
            )

        match = mod.match_target_area("Bán nhà Tân Đông Hiệp Dĩ An 80m2 giá 3 tỷ", cfg)

        self.assertEqual(match["city"], "Dĩ An")
        self.assertEqual(match["ward"], "Tân Đông Hiệp")
        self.assertIs(match["target_hit"], True)

    def test_score_post_rewards_clean_real_estate_data_and_document_image(self):
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = mod.load_target_config(_config(Path(tmp)))
        clean_post = {
            "post_url": "https://facebook.com/groups/x/posts/1",
            "author_url": "https://facebook.com/broker-a",
            "text": "Bán đất Hòa Phú Thủ Dầu Một, diện tích 100m2 ngang 5m, đường 7m, giá 2.8 tỷ, sổ riêng công chứng.",
            "posted_at": "2026-07-21T10:00:00+07:00",
            "image_labels": ["real_property_photo", "title_book_or_document"],
        }
        weak_post = {
            "post_url": "https://facebook.com/groups/x/posts/2",
            "author_url": "https://facebook.com/broker-b",
            "text": "Siêu phẩm Bình Dương giá tốt inbox em, cơ hội vàng cho nhà đầu tư.",
            "posted_at": "2026-07-21T11:00:00+07:00",
            "image_labels": [],
        }

        clean = mod.score_post(clean_post, cfg)
        weak = mod.score_post(weak_post, cfg)

        self.assertGreaterEqual(clean["score"], 75)
        self.assertIs(clean["extract"]["price_present"], True)
        self.assertIs(clean["extract"]["area_present"], True)
        self.assertEqual(clean["area_match"]["ward"], "Hòa Phú")
        self.assertIs(clean["extract"]["document_image_present"], True)
        self.assertLess(weak["score"], 35)
        self.assertGreater(weak["penalty_score"], 0)


    def test_price_detection_allows_tens_missing_but_rejects_hundreds_missing(self):
        mod = _load_module()

        ok_examples = [
            "Bán nhà Mỹ Phước giá 1t5xx diện tích 100m2",
            "Bán đất Hòa Phú giá 1 tỷ 5xx diện tích 90m2",
            "Bán nhà Bến Cát 2ty150 diện tích 80m2",
        ]
        missing_examples = [
            "Bán đất Mỹ Phước giá 1 tỷ x diện tích 100m2",
            "Bán nhà Hòa Phú giá 1tx diện tích 90m2",
            "Bán đất Bến Cát hơn 1 tỷ diện tích 120m2",
        ]

        for text in ok_examples:
            with self.subTest(text=text):
                self.assertIs(mod._has_price(text), True)
        for text in missing_examples:
            with self.subTest(text=text):
                self.assertIs(mod._has_price(text), False)

    def test_score_brokers_uses_target_focus_cadence_and_data_quality(self):
        mod = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            cfg = mod.load_target_config(_config(Path(tmp)))
        posts = [
            {
                "post_url": f"https://facebook.com/groups/x/posts/{i}",
                "author_url": "https://facebook.com/broker-a",
                "author_name": "Broker A",
                "group_url": "https://facebook.com/groups/x",
                "text": f"Bán đất Mỹ Phước Bến Cát {90+i}m2 giá 2.{i} tỷ, sổ riêng, đường 8m.",
                "posted_at": f"2026-07-{10+i:02d}T09:00:00+07:00",
                "image_labels": ["real_property_photo"],
            }
            for i in range(1, 7)
        ]
        posts.append(
            {
                "post_url": "https://facebook.com/groups/y/posts/99",
                "author_url": "https://facebook.com/broker-b",
                "author_name": "Broker B",
                "group_url": "https://facebook.com/groups/y",
                "text": "Nhận ký gửi nhà đất nhiều tỉnh, inbox giá tốt.",
                "posted_at": "2026-07-20T09:00:00+07:00",
                "image_labels": [],
            }
        )

        scored_posts = [mod.score_post(post, cfg) for post in posts]
        brokers = mod.score_brokers(scored_posts, cfg)
        by_url = {item["broker_url"]: item for item in brokers}

        self.assertIn(by_url["https://facebook.com/broker-a"]["tier"], {"A", "B"})
        self.assertGreaterEqual(by_url["https://facebook.com/broker-a"]["metrics"]["target_fit_ratio"], 0.9)
        self.assertGreaterEqual(by_url["https://facebook.com/broker-a"]["metrics"]["weeks_active_60d"], 1)
        self.assertIn("target_area_specialist", by_url["https://facebook.com/broker-a"]["labels"])
        self.assertLess(by_url["https://facebook.com/broker-b"]["final_score"], by_url["https://facebook.com/broker-a"]["final_score"])


    def test_normalize_broker_profile_url_prefers_plain_profile_over_group_member_url(self):
        mod = _load_module()

        self.assertEqual(
            mod.normalize_broker_profile_url(
                "https://www.facebook.com/groups/726341611051693/user/100015671537024/?comment_id=1"
            ),
            "https://www.facebook.com/100015671537024",
        )
        self.assertEqual(
            mod.normalize_broker_profile_url("https://www.facebook.com/phan.tuan.320085?mibextid=abc"),
            "https://www.facebook.com/phan.tuan.320085",
        )

    def test_brokers_from_score_payload_accepts_schema_dict(self):
        mod = _load_module()
        brokers = [{"broker_name": "Broker A", "broker_url": "https://facebook.com/a", "final_score": 82}]

        self.assertEqual(mod.brokers_from_score_payload({"schema": "radar_broker_discovery_scores.v1", "brokers": brokers}), brokers)
        self.assertEqual(mod.brokers_from_score_payload(brokers), brokers)

    def test_markdown_report_groups_by_target_area(self):
        mod = _load_module()
        brokers = [
            {
                "broker_name": "Broker A",
                "broker_url": "https://facebook.com/a",
                "final_score": 82,
                "tier": "B",
                "area_focus": {"primary_city": "Bến Cát", "top_wards": ["Mỹ Phước"]},
                "metrics": {"posts_sampled": 8, "price_present_rate": 0.88, "area_present_rate": 0.75, "ward_present_rate": 1.0, "document_image_posts": 2, "weeks_active_60d": 3},
                "labels": ["target_area_specialist", "data_rich_poster"],
                "sample_post_urls": ["https://facebook.com/p/1"],
            }
        ]

        report = mod.render_markdown_report(brokers, campaign_name="test")

        self.assertIn("Bến Cát", report)
        self.assertIn("Broker A", report)
        self.assertIn("Mỹ Phước", report)
        self.assertIn("target_area_specialist", report)


if __name__ == "__main__":
    unittest.main()
