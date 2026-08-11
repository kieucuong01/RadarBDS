from __future__ import annotations

from datetime import date
import importlib
import inspect
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

from scripts.generate_traffic_distribution_pack import (
    build_distribution_items,
    validate_distribution_item,
    write_distribution_pack,
)


RUN_DATE = date(2026, 8, 11)


def test_pack_is_deterministic_and_review_only():
    first = build_distribution_items(RUN_DATE, "all")
    second = build_distribution_items(RUN_DATE, "all")

    assert first == second
    assert len(first) == 80
    assert len({item["queue_id"] for item in first}) == 80
    assert {item["status"] for item in first} == {"review_required"}


def test_utm_values_are_lowercase_ascii_and_query_order_is_stable():
    item = build_distribution_items(RUN_DATE, "facebook")[0]
    query_pairs = parse_qsl(urlsplit(item["utm_url"]).query, keep_blank_values=True)

    assert [key for key, _value in query_pairs] == [
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
    ]
    for _key, value in query_pairs:
        assert value == value.lower()
        assert value.isascii()
        assert all(character.isalnum() or character == "_" for character in value)


def test_existing_json_queue_deduplicates_queue_ids(tmp_path: Path):
    items = build_distribution_items(RUN_DATE, "broker")

    write_distribution_pack(items, tmp_path, "both", run_date=RUN_DATE)
    paths = write_distribution_pack(items, tmp_path, "both", run_date=RUN_DATE)
    json_path = next(path for path in paths if path.suffix == ".json")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    queue_ids = [item["queue_id"] for item in payload["items"]]
    assert len(queue_ids) == 20
    assert len(queue_ids) == len(set(queue_ids))


def test_malformed_existing_queue_fails_closed_without_overwrite(tmp_path: Path):
    json_path = tmp_path / "traffic-distribution-2026-08-11.json"
    json_path.write_text("{malformed", encoding="utf-8")

    with pytest.raises(ValueError, match="existing distribution JSON"):
        write_distribution_pack(
            build_distribution_items(RUN_DATE, "community"),
            tmp_path,
            "json",
            run_date=RUN_DATE,
        )

    assert json_path.read_text(encoding="utf-8") == "{malformed"


@pytest.mark.parametrize(
    "field,value",
    [
        ("copy", "Gọi 0912345678 để nhận dữ liệu"),
        ("copy", "Gửi về buyer@example.com"),
        ("canonical_url", "https://radarbds.vn/admin/tang-truong"),
        ("utm_url", "https://facebook.com/groups/example"),
        ("utm_url", "https://radarbds.vn/bao-cao?utm_source=x&phone=0912345678"),
    ],
)
def test_pack_rejects_phone_email_admin_and_restricted_urls(field: str, value: str):
    item = dict(build_distribution_items(RUN_DATE, "community")[0])
    item[field] = value

    with pytest.raises(ValueError):
        validate_distribution_item(item)


def test_module_has_no_auto_post_or_network_delivery_imports():
    module = importlib.import_module("scripts.generate_traffic_distribution_pack")
    source = inspect.getsource(module).casefold()

    for forbidden in (
        "radar_social_auto_post",
        "urllib.request",
        "requests",
        "playwright",
        "selenium",
        "smtplib",
        "webhook",
    ):
        assert forbidden not in source


def test_markdown_has_broker_media_and_community_review_sections(tmp_path: Path):
    paths = write_distribution_pack(
        build_distribution_items(RUN_DATE, "all"),
        tmp_path,
        "markdown",
        run_date=RUN_DATE,
    )
    markdown = paths[0].read_text(encoding="utf-8")

    for heading in ("## Facebook", "## Broker", "## Local media", "## Community"):
        assert heading in markdown
    assert "Giá rao không phải giá chốt giao dịch" in markdown
    assert "review_required" in markdown
