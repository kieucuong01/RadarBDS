"""Aggregate product activity, account retention and confirmed commerce."""
from datetime import datetime, timezone


FEATURES = (
    "listing_map_opened", "planning_lookup", "tool_used",
    "modal_open", "watchlist_create", "signup_completed",
)
ACTIVITY = FEATURES + ("seo_landing_viewed", "report_viewed")


def _utc_text(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def build_behavior(conn, start, end, previous, *, today=None):
    today = today or datetime.now(start.tzinfo).date()
    features = {action: {"current": 0, "previous": 0, "accounts": 0} for action in FEATURES}
    for row in conn.execute(
        """SELECT action,
                  COUNT(*) FILTER (WHERE created_at::timestamp >= ?::timestamp) AS current,
                  COUNT(*) FILTER (WHERE created_at::timestamp < ?::timestamp) AS previous,
                  COUNT(DISTINCT user_id) FILTER (WHERE created_at::timestamp >= ?::timestamp) AS accounts
           FROM user_audit_log
           WHERE action = ANY(?) AND created_at >= ? AND created_at < ?
             AND tier IN ('guest', 'free', 'vip')
             AND created_at::timestamp >= ?::timestamp AND created_at::timestamp < ?::timestamp
           GROUP BY action""",
        (_utc_text(start), _utc_text(start), _utc_text(start), list(FEATURES),
         _utc_text(previous)[:10], _utc_text(end)[:10] + "Z", _utc_text(previous), _utc_text(end)),
    ).fetchall():
        features[row["action"]] = {key: row[key] for key in ("current", "previous", "accounts")}

    retention = conn.execute(
        """WITH cohort AS (
               SELECT id, ((created_at::timestamp + INTERVAL '7 hours')::date) AS joined
               FROM users
               WHERE tier IN ('free', 'vip')
                 AND created_at::timestamp >= ?::timestamp AND created_at::timestamp < ?::timestamp
           ), checks AS (
               SELECT id, d, joined + d AS return_day
               FROM cohort CROSS JOIN (VALUES (1), (7)) AS days(d)
               WHERE joined + d < ?::date
           )
           SELECT d, COUNT(*) AS eligible,
                  COUNT(*) FILTER (WHERE EXISTS (
                      SELECT 1 FROM user_audit_log a
                      WHERE a.user_id = checks.id AND a.tier IN ('free', 'vip')
                        AND a.action = ANY(?)
                        AND a.created_at >= to_char(return_day - 1, 'YYYY-MM-DD')
                        AND a.created_at < to_char(return_day + 1, 'YYYY-MM-DD')
                        AND a.created_at::timestamp >= return_day::timestamp - INTERVAL '7 hours'
                        AND a.created_at::timestamp < return_day::timestamp + INTERVAL '17 hours'
                  )) AS returned
           FROM checks GROUP BY d""",
        (_utc_text(start), _utc_text(end), today, list(ACTIVITY)),
    ).fetchall()
    days = {"d1": {"eligible": 0, "returned": 0}, "d7": {"eligible": 0, "returned": 0}}
    for row in retention:
        days[f"d{row['d']}"] = {"eligible": row["eligible"], "returned": row["returned"]}

    orders = conn.execute(
        """WITH cohort AS (
               SELECT product_slug, currency, COUNT(*) AS created,
                      COUNT(*) FILTER (WHERE paid_at IS NOT NULL) AS converted,
                      COUNT(*) FILTER (WHERE status = 'pending' AND paid_at IS NULL) AS pending,
                      COUNT(*) FILTER (WHERE status IN ('expired', 'cancelled') AND paid_at IS NULL) AS unpaid_closed
               FROM digital_product_orders
               WHERE created_at >= ? AND created_at < ?
               GROUP BY product_slug, currency
           ), payments AS (
               SELECT product_slug, currency, COUNT(*) AS paid,
                      COALESCE(SUM(paid_amount), 0) AS revenue
               FROM digital_product_orders
               WHERE paid_at >= ? AND paid_at < ?
               GROUP BY product_slug, currency
           )
           SELECT product_slug, currency, COALESCE(created, 0) AS created,
                  COALESCE(converted, 0) AS converted, COALESCE(pending, 0) AS pending,
                  COALESCE(unpaid_closed, 0) AS unpaid_closed,
                  COALESCE(paid, 0) AS paid, COALESCE(revenue, 0) AS revenue
           FROM cohort FULL JOIN payments USING (product_slug, currency)
           ORDER BY paid DESC, created DESC, product_slug, currency""",
        (start, end, start, end),
    ).fetchall()
    return {"features": features, "retention": days, "orders": [dict(row) for row in orders]}
