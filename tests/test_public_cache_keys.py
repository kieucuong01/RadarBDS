import pytest

from services.public_cache_keys import build_public_cache_key, canonical_query


def test_equivalent_multi_value_filters_share_one_key():
    a = build_public_cache_key(
        endpoint="signals",
        tier="guest",
        versions={"signals": 7},
        query={
            "wards": ["Tan An", "Hiep An", "Tan An"],
            "sources": ["guland", "facebook"],
            "page": 1,
        },
    )
    b = build_public_cache_key(
        endpoint="signals",
        tier="guest",
        versions={"signals": 7},
        query={
            "page": 1,
            "sources": ["facebook", "guland"],
            "wards": ["Hiep An", "Tan An"],
        },
    )

    assert a == b


@pytest.mark.parametrize(
    "change",
    (
        {"tier": "free"},
        {"versions": {"signals": 8}},
        {"query": {"wards": ["Tan An"], "page": 2}},
    ),
)
def test_tier_version_and_page_change_the_key(change):
    base = {
        "endpoint": "signals",
        "tier": "guest",
        "versions": {"signals": 7},
        "query": {"wards": ["Tan An"], "page": 1},
    }
    changed = {**base, **change}

    assert build_public_cache_key(**base) != build_public_cache_key(**changed)


def test_client_only_and_unknown_fields_are_not_passed_to_key_builder():
    canonical = canonical_query(
        {"page": 1, "sigv": "client-only", "unknown": "x"}
    )

    assert canonical == {"page": 1}


@pytest.mark.parametrize(
    ("endpoint", "tier"),
    (("unknown", "guest"), ("signals", "superadmin")),
)
def test_invalid_namespaces_are_rejected(endpoint, tier):
    with pytest.raises(ValueError, match="namespace"):
        build_public_cache_key(
            endpoint=endpoint,
            tier=tier,
            versions={"signals": 1},
            query={"page": 1},
        )
