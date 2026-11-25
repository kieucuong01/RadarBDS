"""Bounded first-party page measurement, keyed by a random ID per page load."""
import re
from datetime import datetime, timedelta


_PUBLIC_PATH = re.compile(
    r"/(?:|listing/[1-9][0-9]{0,11}|"
    r"(?:tin-tuc|bao-cao|kien-thuc|binh-duong|gia-dat|quy-hoach-binh-duong)"
    r"(?:/[a-z][a-z0-9-]{0,99}){0,3}|"
    r"(?:ban-do-[a-z][a-z0-9-]{0,75}|dinh-gia-bds|bang-gia-dat-tphcm|hoi-radar|san-deal-bds))"
)
_ID = re.compile(r"[0-9a-f]{32}")
_STEPS = {"planning_entry", "map_click", "map_ready", "map_error",
          "lookup_start", "lookup_result", "lookup_empty", "lookup_error"}
_WARD_STEPS = {"ward_start", "ward_result", "ward_planning_click", "ward_listings_click"}


def sanitize_engagement(context):
    if not isinstance(context, dict):
        return None
    path, view, seconds, depth, closed = (
        context.get(key) for key in ("path", "view", "seconds", "depth", "closed")
    )
    if (
        not isinstance(path, str) or len(path) > 180 or not _PUBLIC_PATH.fullmatch(path)
        or re.search(r"[0-9]{8}", path)
        or not isinstance(view, str) or not _ID.fullmatch(view)
        or type(seconds) is not int or not 0 <= seconds <= 1800
        or type(depth) is not int or depth not in {-1, 0, 25, 50, 75, 90}
        or type(closed) is not bool
    ):
        return None
    sample = {"path": path, "view": view, "seconds": seconds, "depth": depth, "closed": closed}
    session = context.get("session")
    if isinstance(session, str) and _ID.fullmatch(session):
        sample["session"] = session
        if context.get("session_start") is True:
            sample["session_start"] = True
        step = context.get("step")
        if isinstance(step, str) and (step in _STEPS or
                (path == "/ban-do-thu-dau-mot" and step in _WARD_STEPS)):
            sample["step"] = step
    return sample


def summarize_traffic(conn, previous, start, end):
    # Include late samples near the period boundaries without assigning a view to two days.
    lower = (datetime.fromisoformat(previous) - timedelta(days=1)).date().isoformat()
    upper = (datetime.fromisoformat(end) + timedelta(days=1)).date().isoformat() + "Z"
    rows = conn.execute(
        """WITH samples AS (
               SELECT context::jsonb AS sample, created_at::timestamp AS at
               FROM user_audit_log
               WHERE action = 'page_engagement' AND created_at >= ? AND created_at < ?
           ), views AS (
               SELECT sample->>'path' AS path, sample->>'view' AS view,
                      MIN(at) AS opened, MAX((sample->>'seconds')::int) AS seconds,
                      MAX((sample->>'depth')::int) AS depth,
                      BOOL_OR((sample->>'closed')::boolean) AS closed,
                      BOOL_OR(sample->>'step' = 'map_click') AS map_clicked,
                      COUNT(*) > 1 OR MAX((sample->>'seconds')::int) > 0
                          OR BOOL_OR((sample->>'closed')::boolean) AS measured,
                      MIN(sample->>'session') AS session
               FROM samples GROUP BY 1, 2
           ), period_views AS (
               SELECT *, (opened + interval '7 hours')::date AS day, opened >= ?::timestamp AS current_period
               FROM views WHERE opened >= ?::timestamp AND opened < ?::timestamp
           ), session_starts AS (
               SELECT (MIN(at) + interval '7 hours')::date AS day
               FROM samples WHERE (sample->>'session_start')::boolean
               GROUP BY sample->>'session'
           ), daily_sessions AS (
               SELECT day, COUNT(*) AS sessions FROM session_starts GROUP BY day
           )
           SELECT path, day::text AS day, COUNT(*) AS views,
                  COUNT(*) FILTER (WHERE NOT current_period) AS previous_views,
                  COUNT(DISTINCT session) FILTER (WHERE current_period) AS page_sessions,
                  (SELECT sessions FROM daily_sessions WHERE daily_sessions.day = period_views.day) AS sessions,
                  ROUND(AVG(seconds) FILTER (WHERE current_period))::int AS avg_seconds,
                  COUNT(*) FILTER (WHERE current_period AND measured) AS timed,
                  ROUND((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY seconds)
                         FILTER (WHERE current_period AND measured))::numeric)::int AS median_seconds,
                  COUNT(*) FILTER (WHERE current_period AND closed) AS completed,
                  COUNT(*) FILTER (WHERE current_period AND closed AND seconds < 10) AS short,
                  COUNT(*) FILTER (WHERE current_period AND map_clicked) AS map_click_views,
                  COUNT(*) FILTER (WHERE current_period AND depth >= 0) AS scroll_views,
                  COUNT(*) FILTER (WHERE current_period AND depth >= 25) AS reached_25,
                  COUNT(*) FILTER (WHERE current_period AND depth >= 50) AS reached_50,
                  COUNT(*) FILTER (WHERE current_period AND depth >= 75) AS reached_75,
                  COUNT(*) FILTER (WHERE current_period AND depth >= 90) AS reached_90
           FROM period_views
           GROUP BY GROUPING SETS ((path), (day))
           ORDER BY day NULLS LAST, (COUNT(*) FILTER (WHERE current_period)) DESC, views DESC, path
           LIMIT 3500""",
        (lower, upper, start, previous, end),
    ).fetchall()
    first = (datetime.fromisoformat(start) + timedelta(hours=7)).date().isoformat()
    last = (datetime.fromisoformat(end) + timedelta(hours=7)).date()
    counts = {row["day"]: row for row in rows if row["day"]}
    days = []
    day = datetime.fromisoformat(first).date()
    while day < last:
        key = day.isoformat()
        row = counts.get(key, {})
        days.append({"day": key, "views": row.get("views", 0), "sessions": row.get("sessions") or 0})
        day += timedelta(days=1)
    return {
        "days": days,
        "previous_total": sum(row["views"] for row in counts.values() if row["day"] < first),
        "first_measured_day": min(counts, default=None),
        "pages": [{**row, "views": row["views"] - row["previous_views"]}
                  for row in rows if not row["day"]],
        "truncated": len(rows) == 3500,
    }


def summarize_planning_funnel(conn, start, end):
    row = conn.execute(
        """WITH samples AS (
               SELECT id, created_at::timestamp AS at, context::jsonb AS sample
               FROM user_audit_log
               WHERE action = 'page_engagement' AND created_at >= ? AND created_at < ?
           ), journeys AS (
               SELECT MAX(at) AS last_seen,
                      STRING_AGG(CASE sample->>'step'
                          WHEN 'planning_entry' THEN CASE WHEN at < ?::timestamp THEN 'E' END
                          WHEN 'map_click' THEN 'C' WHEN 'map_ready' THEN 'M' WHEN 'map_error' THEN 'F'
                          WHEN 'lookup_start' THEN 'S' WHEN 'lookup_result' THEN 'R'
                          WHEN 'lookup_empty' THEN 'N' WHEN 'lookup_error' THEN 'X'
                      END, '' ORDER BY at, id) AS steps
               FROM samples
               WHERE at >= ?::timestamp AND sample->>'session' IS NOT NULL
               GROUP BY sample->>'session'
           )
           SELECT COUNT(*) FILTER (WHERE steps LIKE '%E%') AS entered,
                  COUNT(*) FILTER (WHERE steps ~ 'E.*C') AS clicked,
                  COUNT(*) FILTER (WHERE steps ~ 'E.*C.*M') AS ready,
                  COUNT(*) FILTER (WHERE steps ~ 'E.*C.*F') AS map_error,
                  COUNT(*) FILTER (WHERE steps ~ 'E.*C.*M.*S') AS searched,
                  COUNT(*) FILTER (WHERE steps ~ 'E.*C.*M.*S.*R') AS result,
                  COUNT(*) FILTER (WHERE steps ~ 'E.*C.*M.*S.*N') AS empty,
                  COUNT(*) FILTER (WHERE steps ~ 'E.*C.*M.*S.*X') AS lookup_error
           FROM journeys WHERE last_seen < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - interval '30 minutes'""",
        (start[:10], (datetime.fromisoformat(end) + timedelta(days=1)).date().isoformat() + "Z", end, start),
    ).fetchone()
    return dict(row)


def summarize_ward_lookup(conn, start, end):
    return dict(conn.execute(
        """WITH sessions AS (
               SELECT context::jsonb->>'session' AS session,
                      BOOL_OR(context::jsonb->>'step' = 'ward_result') AS result,
                      BOOL_OR(context::jsonb->>'step' = 'ward_planning_click') AS planning,
                      BOOL_OR(context::jsonb->>'step' = 'ward_listings_click') AS listings,
                      BOOL_OR(context::jsonb->>'step' IN ('ward_start','ward_result')) AS started
               FROM user_audit_log
               WHERE created_at >= ? AND created_at < ? AND action = 'page_engagement'
                 AND context::jsonb->>'path' = '/ban-do-thu-dau-mot'
                 AND context::jsonb->>'session' IS NOT NULL AND context::jsonb->>'step' LIKE 'ward_%'
               GROUP BY 1
           ) SELECT COUNT(*) FILTER (WHERE started) AS started, COUNT(*) FILTER (WHERE result) AS result,
                    COUNT(*) FILTER (WHERE planning) AS planning, COUNT(*) FILTER (WHERE listings) AS listings
             FROM sessions""", (start, end),
    ).fetchone())


def summarize_engagement(conn, start, end):
    rows = conn.execute(
        """WITH measurements AS (
               SELECT context::jsonb AS sample, created_at::timestamp AS at
               FROM user_audit_log
               WHERE action = 'page_engagement'
                 AND created_at >= ? AND created_at < ?
           ), views AS (
               SELECT sample->>'path' AS path, sample->>'view' AS view,
                      MAX((sample->>'seconds')::int) AS seconds,
                      MAX((sample->>'depth')::int) AS depth,
                      BOOL_OR((sample->>'closed')::boolean) AS closed
               FROM measurements
               WHERE at >= ?::timestamp AND at < ?::timestamp
               GROUP BY 1, 2
           )
           SELECT path, COUNT(*) AS views, ROUND(AVG(seconds))::int AS avg_seconds,
                  COUNT(*) FILTER (WHERE closed) AS completed,
                  COUNT(*) FILTER (WHERE closed AND seconds < 10) AS short,
                  COUNT(*) FILTER (WHERE depth >= 0) AS scroll_views,
                  COUNT(*) FILTER (WHERE depth >= 25) AS reached_25,
                  COUNT(*) FILTER (WHERE depth >= 50) AS reached_50,
                  COUNT(*) FILTER (WHERE depth >= 75) AS reached_75,
                  COUNT(*) FILTER (WHERE depth >= 90) AS reached_90
           FROM views GROUP BY path
           ORDER BY views DESC, path LIMIT 30""",
        (start[:10], end[:10] + "Z", start, end),
    ).fetchall()
    return [dict(row) for row in rows]
