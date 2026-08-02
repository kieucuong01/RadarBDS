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


def test_listing_cache_key_includes_complete_sort_page_and_version():
    base = build_public_cache_key(
        endpoint="listings",
        tier="guest",
        versions={"listings": 4},
        query={
            "complete": False,
            "sort": "date:desc",
            "page": 1,
            "limit": 50,
        },
    )
    changes = (
        {
            "complete": True,
            "sort": "date:desc",
            "page": 1,
            "limit": 50,
        },
        {
            "complete": False,
            "sort": "price:asc",
            "page": 1,
            "limit": 50,
        },
        {
            "complete": False,
            "sort": "date:desc",
            "page": 2,
            "limit": 50,
        },
    )

    for changed in changes:
        assert base != build_public_cache_key(
            endpoint="listings",
            tier="guest",
            versions={"listings": 4},
            query=changed,
        )


def test_unknown_listing_query_fields_do_not_change_cache_key():
    known = canonical_query(
        {"page": 1, "complete": True, "sort": "date:desc"}
    )
    unknown = canonical_query(
        {
            "page": 1,
            "complete": True,
            "sort": "date:desc",
            "load_run": "different-every-time",
        }
    )

    assert known == unknown == {
        "complete": True,
        "page": 1,
        "sort": "date:desc",
    }


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
