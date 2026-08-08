from __future__ import annotations

from services.marketing_tracking import (
    MARKETING_TRACK_ACTIONS,
    sanitize_marketing_context,
)


def test_marketing_context_keeps_only_safe_bounded_fields():
    safe = sanitize_marketing_context(
        "seo_landing_viewed",
        {
            "path": "/binh-duong/phuong-hiep-thanh?x=1#private",
            "page_slug": "binh-duong/phuong-hiep-thanh",
            "page_title": "A" * 300,
            "channel": "social",
            "utm_source": " Facebook ",
            "utm_campaign": "ward_launch",
            "phone": "0900000000",
            "email": "private@example.test",
            "ip": "127.0.0.1",
            "user_agent": "private browser",
            "note": "private note",
            "referrer": "https://external.test/private",
            "unknown": "must not survive",
        },
    )

    assert safe["path"] == "/binh-duong/phuong-hiep-thanh"
    assert safe["page_slug"] == "binh-duong/phuong-hiep-thanh"
    assert len(safe["page_title"]) == 160
    assert safe["channel"] == "social"
    assert safe["utm_source"] == "facebook"
    assert safe["utm_campaign"] == "ward_launch"
    for forbidden in (
        "phone",
        "email",
        "ip",
        "user_agent",
        "note",
        "referrer",
        "unknown",
    ):
        assert forbidden not in safe


def test_cta_destination_is_internal_path_or_stable_external_class():
    internal = sanitize_marketing_context(
        "cta_clicked",
        {"destination": "/?tab=signals&utm_source=facebook#top"},
    )
    zalo = sanitize_marketing_context(
        "cta_clicked",
        {"destination": "https://zalo.me/0900000000?private=yes"},
    )
    facebook = sanitize_marketing_context(
        "cta_clicked",
        {"target": "https://m.me/radarbds?ref=private"},
    )
    other = sanitize_marketing_context(
        "cta_clicked",
        {"destination": "https://example.test/private?email=a%40b.test"},
    )

    assert internal["destination"] == "/"
    assert zalo["destination"] == "external:zalo"
    assert facebook["destination"] == "external:facebook"
    assert other["destination"] == "external:other"


def test_marketing_context_rejects_unknown_actions_and_malformed_input():
    assert sanitize_marketing_context("not_a_marketing_action", {"path": "/"}) == {}
    assert sanitize_marketing_context("seo_landing_viewed", None) == {}
    assert sanitize_marketing_context("seo_landing_viewed", ["not", "a", "dict"]) == {}
    assert MARKETING_TRACK_ACTIONS == frozenset(
        {
            "seo_landing_viewed",
            "report_viewed",
            "social_utm_visit",
            "ai_referral_visit",
            "cta_clicked",
            "lead_capture_submit",
        }
    )


def test_marketing_context_drops_invalid_paths_enums_and_tokens():
    safe = sanitize_marketing_context(
        "seo_landing_viewed",
        {
            "path": "//external.test/private",
            "page_path": "/safe\nprivate",
            "channel": "paid",
            "ai_source": "unknown-ai",
            "utm_source": "facebook<script>",
            "utm_medium": "social",
            "utm_term": "dat-binh-duong",
        },
    )

    assert safe == {
        "utm_medium": "social",
        "utm_term": "dat-binh-duong",
    }


def test_ai_context_keeps_only_recognized_source_and_hostname():
    safe = sanitize_marketing_context(
        "ai_referral_visit",
        {
            "ai_source": "ChatGPT",
            "referrer_host": "WWW.ChatGPT.com",
            "path": "/binh-duong",
        },
    )
    mismatch = sanitize_marketing_context(
        "ai_referral_visit",
        {
            "ai_source": "chatgpt",
            "referrer_host": "private.example.test",
        },
    )

    assert safe == {
        "path": "/binh-duong",
        "ai_source": "chatgpt",
        "referrer_host": "chatgpt.com",
    }
    assert mismatch == {"ai_source": "chatgpt"}


def test_marketing_tokens_are_lowercase_bounded_and_action_specific():
    safe = sanitize_marketing_context(
        "lead_capture_submit",
        {
            "page_path": "/bao-cao/bds-binh-duong-thang-07-2026",
            "source_context": " SEO_Report_Lead ",
            "utm_campaign": "A" * 100,
            "cta_name": "must_not_cross_action_boundaries",
            "page_title": "must not be retained for a lead event",
        },
    )

    assert safe["page_path"] == "/bao-cao/bds-binh-duong-thang-07-2026"
    assert safe["source_context"] == "seo_report_lead"
    assert safe["utm_campaign"] == "a" * 80
    assert "cta_name" not in safe
    assert "page_title" not in safe


def test_tracking_endpoint_sanitizes_marketing_context_before_audit(monkeypatch):
    import app as radar_app

    captured = {}

    def fake_log_audit(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(radar_app, "log_audit", fake_log_audit)
    response = radar_app.app.test_client().post(
        "/api/track",
        json={
            "action": "lead_capture_submit",
            "context": {
                "page_path": "/bao-cao?utm_source=facebook",
                "utm_source": "facebook",
                "source_context": "seo_report_lead",
                "phone": "0900000000",
                "email": "private@example.test",
                "ip": "127.0.0.1",
                "user_agent": "private browser",
                "note": "private note",
                "referrer": "https://external.test/private",
                "unknown": "must not survive",
            },
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert captured["action"] == "lead_capture_submit"
    assert captured["context"] == {
        "page_path": "/bao-cao",
        "utm_source": "facebook",
        "source_context": "seo_report_lead",
    }


def test_tracking_endpoint_accepts_malformed_context_and_rejects_unknown_action(
    monkeypatch,
):
    import app as radar_app

    captured = {}
    monkeypatch.setattr(
        radar_app,
        "log_audit",
        lambda **kwargs: captured.update(kwargs),
    )
    malformed = radar_app.app.test_client().post(
        "/api/track",
        json={"action": "seo_landing_viewed", "context": ["not", "a", "dict"]},
    )
    unknown = radar_app.app.test_client().post(
        "/api/track",
        json={"action": "unknown_marketing_action", "context": {"path": "/"}},
    )

    assert malformed.status_code == 200
    assert malformed.get_json() == {"ok": True}
    assert captured["context"] == {}
    assert unknown.status_code == 400
    assert unknown.get_json() == {"ok": False, "error": "invalid_action"}
