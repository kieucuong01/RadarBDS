"""Shared pytest isolation for production-facing public URL contracts."""

from __future__ import annotations

import sys

import pytest


PUBLIC_BASE_URL = "https://radarbds.vn"
SITE_OG_IMAGE = f"{PUBLIC_BASE_URL}/static/images/seo/radarbds-og.png"


@pytest.fixture(autouse=True)
def isolate_public_url_contract(monkeypatch):
    """Keep ignored local URL overrides from leaking into public contract tests."""
    from config import settings

    monkeypatch.setenv("PUBLIC_BASE_URL", PUBLIC_BASE_URL)
    monkeypatch.setenv("DASHBOARD_BASE_URL", PUBLIC_BASE_URL)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", PUBLIC_BASE_URL)
    monkeypatch.setattr(settings, "DASHBOARD_BASE_URL", PUBLIC_BASE_URL)
    monkeypatch.setattr(settings, "SITE_OG_IMAGE", SITE_OG_IMAGE)

    loaded_constants = {
        "app": {
            "PUBLIC_BASE_URL": PUBLIC_BASE_URL,
            "SITE_OG_IMAGE": SITE_OG_IMAGE,
        },
        "auth.core": {"PUBLIC_BASE_URL": PUBLIC_BASE_URL},
        "routes.digital_products": {"PUBLIC_BASE_URL": PUBLIC_BASE_URL},
        "services.payos_client": {"PUBLIC_BASE_URL": PUBLIC_BASE_URL},
    }
    for module_name, constants in loaded_constants.items():
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for name, value in constants.items():
            monkeypatch.setattr(module, name, value)
