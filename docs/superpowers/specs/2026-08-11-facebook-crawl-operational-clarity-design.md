# Facebook Crawl Operational Clarity Design

**Status:** Approved direction; awaiting written-spec review

**Routes:** `/admin/facebook-crawl?view=overview` and `/admin/facebook-crawl?view=brokers`
**Scope:** Rebuild the visual hierarchy and responsive interaction surface of the Facebook Crawl admin views without changing crawl, profile, job, duplicate, or API behavior.

## Goal

Make Facebook Crawl feel like a calm operations console: an admin should understand the current crawl state within three seconds, identify the next meaningful action, and operate the broker roster without navigating a visually dense collection of competing cards.

The product is an internal, data-dense workflow. The redesign therefore favors scan speed, reliable state feedback, and a compact layout over decorative visuals or marketing-page composition.

## Product Decision

Use a shared **Operational Clarity** system across the two views:

- A neutral charcoal canvas with clearly layered surfaces.
- Teal is the sole navigation/primary-action color; amber, red, and green remain strictly semantic state colors and always include text.
- A 4/8px spacing rhythm, tabular figures for quota/timing data, 150-220ms opacity/transform transitions, and no decorative motion.
- System sans-serif typography rather than luxury/editorial fonts. Headings communicate section purpose; numbers communicate urgency.
- One primary action per view. Secondary and destructive controls are visually subordinate and spatially separated.

The ui-ux-pro-max design-system search suggested an operations pattern, high dashboard density, subtle motion, and teal/professional-blue trust colors. This spec keeps those applicable findings but deliberately rejects oversized editorial typography and landing-page whitespace because they reduce operational scan speed.

## Shared Shell

Both views live inside one quiet, predictable shell.

1. **Route header**: a compact eyebrow (`Facebook Crawl`), clear page title, short status copy, and one contextual primary action. The title block never competes with the data surface below it.
2. **Context strip**: a thin, persistent status strip records loading, saved-draft, stale, or failure feedback through text plus semantic styling. It is not a second page heading.
3. **Surface hierarchy**: health/action surfaces use the strongest border and background contrast; supporting metrics use lower emphasis; dividers are visible in both themes.
4. **Controls**: all buttons, inputs, selects, and drawer close controls have at least a 44px target, 8px separation, visible focus rings, and disabled/loading states.
5. **Responsive breakpoints**: 375px, 768px, 1024px, and 1440px. The page must never create horizontal document scrolling.
6. **Motion/accessibility**: no color-only statuses; keyboard order follows the visible order; `prefers-reduced-motion` removes nonessential transitions; drawers retain Escape, backdrop close, focus trap, and focus return.

## Overview: Command State First

### Information hierarchy

The Overview must answer these questions in order:

1. Is Facebook Crawl healthy right now?
2. What action should the admin take next?
3. When did the last run happen, and when is the next run?
4. Is the operational budget or latest job a constraint?

### Layout

At desktop width, the page uses a two-column command composition:

- **Primary command panel (wide column):** health status, concise summary, last/next run values, and the one primary `Chạy tác vụ` action. `Quản lý môi giới` remains a secondary route action.
- **Operational snapshot (narrow column):** two concise cards for available Apify capacity and latest job state. Cards show one prominent value, one explanatory line, and no redundant framing.
- **Failure state:** the command panel itself explains what did not load and provides a nearby retry action. It does not leave an empty card grid.

On mobile, the health/action panel stays first, the primary action fills the available row, the secondary route action follows beneath it, and snapshot cards become a two-up or one-up stack depending on available width.

### Visual treatment

- Health receives a compact labeled badge and a left state rail, not a large colored block.
- Timing values use tabular figures and a clear label/value rhythm.
- Resource cards use restrained icons only if an existing consistent SVG icon source is available; no emoji or new third-party icon dependency is introduced.
- Loading reserves the command/snapshot layout dimensions to prevent visible layout shift.

### Behavior preserved

- `GET /admin/api/facebook-crawl/overview` remains the only Overview data source.
- Overview must not load profiles or duplicates merely to render its page.
- Existing `Chạy tác vụ`, `Quản lý môi giới`, and retry actions retain their URL/view behavior.

## Brokers: Roster, Not Card Collection

### Information hierarchy

The Brokers view must answer these questions in order:

1. How many brokers are active, due today, or need attention?
2. Can I find the broker I need immediately?
3. Which row requires action, and why?
4. Can I safely edit, run, or remove a broker without losing draft work?

### Layout

1. **Roster header:** compact title, one-line operational description, `Thêm môi giới` as the primary action, and the existing saved/draft status in the shared context strip.
2. **Summary rail:** four low-height metrics (total, active, due, attention) use a continuous surface rather than four visually unrelated cards. Attention is textual and semantic, not red-only.
3. **Filter bar:** search is always visible. Advanced filters live in one compact, expandable region on narrow and medium widths; the active-filter count and reset action remain visible.
4. **Table:** use a stable five-column desktop hierarchy: Broker, Operational state, Schedule/quota, Quality/latest activity, Actions. Supporting text wraps or truncates with a native title/tooltip affordance instead of forcing a wide table.
5. **Action menu:** the row retains explicit `Sửa`, `Chạy`, and `Xóa` actions. `Xóa` remains visually distinct and requires the existing confirmation. It is never an icon-only control.
6. **Drawer:** editing remains a right-side drawer on desktop and becomes a bottom sheet-like full-height panel on small screens. Identity, schedule, and limits remain fieldset groups with visible legends.
7. **Duplicate analysis:** stays below roster operations as a concise, progressive-disclosure panel. Existing cards/load-more behavior remains; loading, empty, and error copy explain the available recovery action.

### Mobile behavior

- Each broker row becomes an ordered, label/value block with identity first, operational state second, schedule/quality next, and actions last.
- The filter region does not force six controls into the first viewport; search and a visible `Bộ lọc` summary lead, with the remaining controls expanded on demand.
- Destructive action is separated from edit/run controls, but all actions remain touch-safe and keyboard reachable.

### Behavior preserved

- Draft edits are local until explicit save.
- `profile_revision_conflict` recovery, unsaved-change protection, safe URL handling, and `removeProfileFromDraft()` semantics remain unchanged.
- Removal changes only broker configuration after explicit save; it must not remove crawled listings.
- Profile list, duplicates, run selection, and save endpoints remain unchanged.

## Design Tokens and CSS Boundaries

Add a Facebook Crawl-scoped token layer under `.facebook-crawl-shell`, rather than changing global admin values:

```css
--crawl-bg: neutral canvas;
--crawl-surface: elevated panel;
--crawl-surface-strong: command/attention panel;
--crawl-border: visible low-contrast divider;
--crawl-text: primary content;
--crawl-muted: secondary content;
--crawl-primary: teal route/action color;
--crawl-success: semantic healthy state;
--crawl-warning: semantic attention state;
--crawl-danger: semantic destructive state;
--crawl-ring: keyboard focus ring;
--crawl-radius: 12px;
--crawl-gap-1 through --crawl-gap-6: 4px to 32px scale;
```

Light and dark values must be paired in the existing theme mechanism. No raw, one-off colors belong in individual view rules.

## Implementation Boundaries

Expected files:

- `templates/admin_control_room.html` — hierarchy and semantic affordances only.
- `static/css/admin.css` — scoped token layer, Overview/Brokers layouts, responsive and reduced-motion rules.
- `static/js/admin/facebook-crawl.js` — only where a compact filter disclosure, status message, or semantic state hook requires markup/render changes.
- `tests/js/test_facebook_crawl_admin.js` — pure helper and source-contract coverage.
- `tests/test_admin_growth_ui.py` — semantic markup, cache key, responsive, and safety contracts.

Out of scope:

- Backend API, database schema, crawl scheduler, Apify quota logic, duplicate-analysis algorithms, or authentication changes.
- New icon, chart, CSS, or JavaScript dependencies.
- Reprocessing existing crawl/listing data.

## Verification

Before release, verify:

1. `node --check static/js/admin/facebook-crawl.js`.
2. `node --test tests/js/test_facebook_crawl_admin.js`.
3. `pytest tests/test_admin_growth_ui.py tests/test_facebook_crawl_admin_api.py -q` using the project Python runtime.
4. Template/CSS source contracts for the two cache-busted assets and retained IDs/API routes.
5. Browser checks at 1440px and 375px: no horizontal scrolling, clear primary action, keyboard-visible focus, drawer close/focus behavior, filter disclosure, empty/loading/error states, and reduced-motion styling.

## Acceptance Criteria

- An admin can identify current health, next action, last/next run, and resource constraint from Overview without scrolling through unrelated controls.
- A broker can be searched, filtered, assessed, edited, run, or safely removed from Brokers without ambiguity about draft state or side effects.
- Both pages look like one professional operations product, not two generations of card UI.
- Existing API and draft-safety behavior remains intact, and focused regression coverage remains green.
