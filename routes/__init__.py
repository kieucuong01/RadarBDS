"""Blueprint registration for Radar BDS web routes."""
from __future__ import annotations

from .admin_api import bp as admin_api_bp
from .auth_api import bp as auth_api_bp
from .market_api import bp as market_api_bp
from .public import bp as public_bp


def register_blueprints(app):
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_api_bp)
    app.register_blueprint(market_api_bp)
    app.register_blueprint(admin_api_bp)
