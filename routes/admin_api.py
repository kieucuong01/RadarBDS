"""Admin control room and QC API routes."""
from __future__ import annotations

from flask import Blueprint, redirect

bp = Blueprint("admin_api", __name__)


def _impl(name: str, **kwargs):
    import app as app_module

    return getattr(app_module, name)(**kwargs)


@bp.route("/admin/control-room/<panel_slug>")
@bp.route("/admin/control-room")
def admin_control_room_legacy(panel_slug=None, **kwargs):
    target = f"/admin/{panel_slug}" if panel_slug else "/admin"
    return redirect(target, code=302)


@bp.route("/admin")
@bp.route("/admin/<panel_slug>")
def admin_control_room(panel_slug=None, **kwargs):
    return _impl("admin_control_room", panel_slug=panel_slug, **kwargs)


@bp.route("/admin/api/leads")
def admin_api_leads(**kwargs):
    return _impl("admin_api_leads", **kwargs)


@bp.route("/admin/api/leads/export.csv")
def admin_api_leads_export(**kwargs):
    return _impl("admin_api_leads_export", **kwargs)


@bp.route("/admin/api/leads/<int:lead_id>/status", methods=["PATCH"])
def admin_api_update_lead_status(**kwargs):
    return _impl("admin_api_update_lead_status", **kwargs)


@bp.route("/admin/api/leads/<int:lead_id>", methods=["DELETE"])
def admin_api_delete_lead(**kwargs):
    return _impl("admin_api_delete_lead", **kwargs)


@bp.route("/admin/api/facebook-crawl/config", methods=["GET", "POST"])
def admin_api_facebook_crawl_config(**kwargs):
    return _impl("admin_api_facebook_crawl_config", **kwargs)


@bp.route("/admin/api/facebook-crawl/run", methods=["POST"])
def admin_api_facebook_crawl_run(**kwargs):
    return _impl("admin_api_facebook_crawl_run", **kwargs)


@bp.route("/admin/api/facebook-crawl/tokens", methods=["GET", "POST"])
@bp.route("/admin/api/facebook-crawl/tokens/<token_id>", methods=["DELETE", "PATCH"])
def admin_api_facebook_crawl_tokens(**kwargs):
    return _impl("admin_api_facebook_crawl_tokens", **kwargs)


@bp.route("/admin/api/facebook-crawl/jobs")
@bp.route("/admin/api/facebook-crawl/jobs/<job_id>")
def admin_api_facebook_crawl_jobs(**kwargs):
    return _impl("admin_api_facebook_crawl_jobs", **kwargs)


@bp.route("/admin/api/infra", methods=["GET", "POST"])
def admin_api_infra(**kwargs):
    return _impl("admin_api_infra", **kwargs)


@bp.route("/admin/api/infra/<int:entry_id>", methods=["DELETE", "PATCH"])
def admin_api_infra_item(**kwargs):
    return _impl("admin_api_infra_item", **kwargs)


@bp.route("/admin/api/qc/signals")
def admin_api_qc_signals(**kwargs):
    return _impl("admin_api_qc_signals", **kwargs)


@bp.route("/admin/api/data-quality/summary")
def admin_api_data_quality_summary(**kwargs):
    return _impl("admin_api_data_quality_summary", **kwargs)


@bp.route("/admin/api/data-quality/items")
def admin_api_data_quality_items(**kwargs):
    return _impl("admin_api_data_quality_items", **kwargs)


@bp.route("/admin/api/ai-training/feedback", methods=["POST"])
def admin_api_ai_training_feedback(**kwargs):
    return _impl("admin_api_ai_training_feedback", **kwargs)


@bp.route("/admin/api/ai-training/items")
def admin_api_ai_training_items(**kwargs):
    return _impl("admin_api_ai_training_items", **kwargs)


@bp.route("/admin/api/legal-verification", methods=["POST"])
def admin_api_legal_verification(**kwargs):
    return _impl("admin_api_legal_verification", **kwargs)


@bp.route("/admin/api/ai-training/disagreements")
def admin_api_ai_training_disagreements(**kwargs):
    return _impl("admin_api_ai_training_disagreements", **kwargs)


@bp.route("/admin/api/qc/duplicates")
def admin_api_qc_duplicates(**kwargs):
    return _impl("admin_api_qc_duplicates", **kwargs)


@bp.route("/admin/api/qc/duplicates/merge", methods=["POST"])
def admin_api_qc_duplicates_merge(**kwargs):
    return _impl("admin_api_qc_duplicates_merge", **kwargs)


@bp.route("/admin/api/qc/duplicates/split", methods=["POST"])
def admin_api_qc_duplicates_split(**kwargs):
    return _impl("admin_api_qc_duplicates_split", **kwargs)


@bp.route("/admin/api/blacklist", methods=["GET", "POST", "DELETE"])
def admin_api_blacklist(**kwargs):
    return _impl("admin_api_blacklist", **kwargs)


@bp.route("/admin/api/audit")
def admin_api_audit(**kwargs):
    return _impl("admin_api_audit", **kwargs)


@bp.route("/admin/api/users")
def admin_api_users(**kwargs):
    return _impl("admin_api_users", **kwargs)


@bp.route("/admin/api/users/<int:user_id>", methods=["DELETE"])
def admin_api_delete_user(**kwargs):
    return _impl("admin_api_delete_user", **kwargs)


@bp.route("/admin/api/users/<int:user_id>/grant-vip", methods=["POST"])
def admin_api_grant_vip(**kwargs):
    return _impl("admin_api_grant_vip", **kwargs)


@bp.route("/admin/api/users/<int:user_id>/revoke", methods=["POST"])
def admin_api_revoke_vip(**kwargs):
    return _impl("admin_api_revoke_vip", **kwargs)


@bp.route("/admin/api/users/<int:user_id>/ban", methods=["POST"])
def admin_api_ban_user(**kwargs):
    return _impl("admin_api_ban_user", **kwargs)
