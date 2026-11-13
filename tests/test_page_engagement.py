from services.page_engagement import sanitize_engagement


def test_engagement_accepts_only_bounded_public_page_metrics():
    sample = {"path": "/tin-tuc/cach-doc-ban-do", "view": "a" * 32,
              "seconds": 60, "depth": 50, "closed": True, "phone": "0901234567"}
    assert sanitize_engagement(sample) == {k: v for k, v in sample.items() if k != "phone"}
    for change in ({"path": "/admin/users"}, {"path": "/tin-tuc/0901234567"},
                   {"path": "/?lat=10"}, {"seconds": 1801}, {"seconds": True},
                   {"depth": 53}, {"view": "user@example.com"}):
        assert sanitize_engagement({**sample, **change}) is None
