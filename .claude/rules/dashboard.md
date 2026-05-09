---
paths:
  - "app.py"
  - "services/market_data.py"
  - "static/js/main.js"
  - "templates/index.html"
---

# Dynamic Dashboard Architecture

## Core Components
1. **Backend (Python/Flask)**:
   - `app.py`: Route definitions and API endpoints (`/api/dashboard`, `/api/heatmap`).
   - `services/market_data.py`: Centralized data loading logic (`load_data`, `get_base_filters`). Handle SQL queries and MOS calculations here.
2. **Frontend (JS/HTML)**:
   - `templates/index.html`: Main layout using custom Vanilla CSS (Glassmorphism). Contains Sidebar filters and Tab content.
   - `static/js/main.js`: Client-side logic. Handles `applyFilters()`, `fetchDashboard()`, and rendering charts via Chart.js.

## Filter Pipeline (MANDATORY FLOW)
To prevent regressions and 500 errors, always follow this data flow:
1. **UI Event**: User clicks a checkbox or moves a slider in `index.html`.
2. **Aggregation**: `applyFilters()` in `main.js` collects ALL current states (City, Ward, Source, PropType, MOS, Sort).
3. **API Request**: `fetchDashboard()` sends the aggregated `URLSearchParams` to `/api/dashboard`.
4. **Backend Extraction**: `get_base_filters()` in `market_data.py` extracts parameters safely (using `getlist` for arrays and `int()` for thresholds).
5. **Data Load**: `load_data()` builds the SQL `WHERE` clause and applies `ORDER BY`. **Always use `COALESCE` for potentially NULL fields.**
6. **Serialization**: Return `dict(stats)` and list of dicts. Never return raw `sqlite3.Row` objects.

## Efficiency & Stability
- **Token Saving**: When analyzing dashboard issues, read `services/market_data.py` FIRST as it contains 90% of the data logic.
- **Verification**: After modifying any part of this pipeline, you MUST run:
  ```bash
  python tests/sanity_test.py
  ```
- **Performance**: Use `skip_listings=True` for dashboard API calls that only need statistics and signals, reducing payload size.
- **Dark Mode**: Always update the `[data-theme="dark"]` overrides in `index.html` if adding new components.
