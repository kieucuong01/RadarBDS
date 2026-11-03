import re
from pathlib import Path


def test_every_enforced_policy_allows_the_ga4_collector():
    import app as radar_app

    nginx = Path("deployment/ubuntu24/nginx-radar-bds.conf").read_text(encoding="utf-8")
    policies = re.findall(r'add_header Content-Security-Policy "([^"]+)"', nginx)
    assert len(policies) == 4
    policies.append(radar_app.app.test_client().get("/robots.txt").headers["Content-Security-Policy"])
    for policy in policies:
        directives = {parts[0]: parts[1:] for item in policy.split(";") if (parts := item.split())}
        assert "https://analytics.google.com" in directives["connect-src"]
        assert "https://www.google-analytics.com" in directives["connect-src"]
        assert "*" not in directives["connect-src"]
        assert "'unsafe-eval'" not in directives["script-src"]
        assert directives["object-src"] == ["'none'"]
        assert directives["frame-ancestors"] == ["'none'"]
