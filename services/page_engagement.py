"""Bounded first-party page measurement, keyed by a random ID per page load."""
import re


_PUBLIC_PATH = re.compile(
    r"/(?:|listing/[1-9][0-9]{0,11}|"
    r"(?:tin-tuc|bao-cao|kien-thuc|binh-duong|gia-dat|quy-hoach-binh-duong)"
    r"(?:/[a-z][a-z0-9-]{0,99}){0,3}|"
    r"(?:ban-do-[a-z][a-z0-9-]{0,75}|dinh-gia-bds|bang-gia-dat-tphcm|hoi-radar|san-deal-bds))"
)


def sanitize_engagement(context):
    if not isinstance(context, dict):
        return None
    path, view, seconds, depth, closed = (
        context.get(key) for key in ("path", "view", "seconds", "depth", "closed")
    )
    if (
        not isinstance(path, str) or len(path) > 180 or not _PUBLIC_PATH.fullmatch(path)
        or re.search(r"[0-9]{8}", path)
        or not isinstance(view, str) or not re.fullmatch(r"[0-9a-f]{32}", view)
        or type(seconds) is not int or not 0 <= seconds <= 1800
        or type(depth) is not int or depth not in {-1, 0, 25, 50, 75, 90}
        or type(closed) is not bool
    ):
        return None
    return {"path": path, "view": view, "seconds": seconds, "depth": depth, "closed": closed}


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
