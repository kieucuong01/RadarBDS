import pytest

from services.guland_publisher_activity import (
    PublisherEvidence,
    PublisherMetrics,
    build_publisher_key,
    classify_publisher,
    effective_publisher_class,
    normalize_vietnam_phone,
    validate_publisher_evidence,
    validated_raw_publisher_fields,
)


def test_rejects_page_global_guland_hotline_and_uses_description_phone():
    evidence = validate_publisher_evidence(
        {
            "publisher_phone_candidate": "0983284379",
            "publisher_phone_scope": "footer",
            "publisher_profile_url": "",
            "publisher_source_id": "",
        },
        "Chính chủ bán đất, liên hệ 0912345678",
    )

    assert evidence.identity_type == "description_phone"
    assert evidence.confidence == "medium"
    assert normalize_vietnam_phone(evidence.phone) == "0912345678"


def test_member_identity_wins_over_phone_and_key_is_not_raw_identity():
    evidence = validate_publisher_evidence(
        {
            "publisher_source_id": "member-42",
            "publisher_profile_url": "https://guland.vn/user/member-42",
            "publisher_name": "Người đăng",
            "publisher_phone_candidate": "0912345678",
            "publisher_phone_scope": "listing_contact",
        },
        "",
    )

    key = build_publisher_key(evidence, "x" * 64)

    assert evidence.identity_type == "member_id"
    assert evidence.confidence == "high"
    assert len(key) == 64
    assert "member-42" not in key
    assert "0912345678" not in key


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/user/member-42",
        "https://guland.vn.evil.example/user/member-42",
        "http://guland.vn/user/member-42",
        "https://guland.vn:8443/user/member-42",
    ],
)
def test_untrusted_profile_url_does_not_create_identity(value):
    evidence = validate_publisher_evidence(
        {"publisher_profile_url": value},
        "",
    )

    assert evidence.identity_type == "unknown"
    assert evidence.status == "unknown"


def test_missing_key_secret_degrades_reliable_evidence_to_unknown():
    raw = validated_raw_publisher_fields(
        {
            "publisher_source_id": "member-42",
            "publisher_profile_url": "",
            "publisher_phone_candidate": "",
            "publisher_phone_scope": "",
        },
        secret="",
    )

    assert raw["publisher_identity_status"] == "unknown"
    assert raw["publisher_identity_reason"] == "identity_secret_missing"
    assert raw["publisher_key"] == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0912 345 678", "0912345678"),
        ("+84 912-345-678", "0912345678"),
        ("84.912.345.678", "0912345678"),
        ("028 1234 5678", ""),
        ("not a phone", ""),
    ],
)
def test_normalize_vietnam_mobile_phone(value, expected):
    assert normalize_vietnam_phone(value) == expected


@pytest.mark.parametrize(
    ("metrics", "expected"),
    [
        (PublisherMetrics(max_new_on_day=5, new_30d=30), "low_manual"),
        (PublisherMetrics(max_new_on_day=6, new_30d=30), "high_activity"),
        (PublisherMetrics(max_new_on_day=5, new_30d=31), "high_activity"),
        (PublisherMetrics(max_new_on_day=29, new_30d=80), "high_activity"),
        (PublisherMetrics(max_new_on_day=30, new_30d=80), "automated_repost"),
        (PublisherMetrics(bumps_7d=3), "automated_repost"),
        (PublisherMetrics(near_duplicates_max_day=10), "automated_repost"),
        (
            PublisherMetrics(days_ge_15_with_templates_14d=3),
            "automated_repost",
        ),
    ],
)
def test_classification_boundaries(metrics, expected):
    assert classify_publisher(metrics, "high").activity_class == expected


def test_insufficient_identity_confidence_stays_unknown_even_at_high_volume():
    result = classify_publisher(
        PublisherMetrics(max_new_on_day=45, new_30d=200),
        "low",
    )

    assert result.activity_class == "unknown"


@pytest.mark.parametrize(
    ("activity_class", "manual_override", "expected"),
    [
        ("automated_repost", "allow_manual", "low_manual"),
        ("low_manual", "hide_high_activity", "high_activity"),
        ("high_activity", "", "high_activity"),
        ("unknown", None, "unknown"),
    ],
)
def test_effective_class_honors_only_supported_admin_overrides(
    activity_class,
    manual_override,
    expected,
):
    assert (
        effective_publisher_class(activity_class, manual_override)
        == expected
    )


def test_unknown_evidence_never_requires_secret():
    assert build_publisher_key(
        PublisherEvidence(
            status="unknown",
            identity_type="unknown",
            confidence="low",
        ),
        "",
    ) == ""
