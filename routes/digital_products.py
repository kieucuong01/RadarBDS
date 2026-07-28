"""Public digital-product routes. Checkout endpoints are added separately."""

from __future__ import annotations

from flask import Blueprint

bp = Blueprint("digital_products", __name__)


def _impl(name: str, **kwargs):
    import app as app_module

    return getattr(app_module, name)(**kwargs)


@bp.get("/ban-do-thu-dau-mot")
def thu_dau_mot_map_product_page(**kwargs):
    return _impl("thu_dau_mot_map_product_page", **kwargs)
