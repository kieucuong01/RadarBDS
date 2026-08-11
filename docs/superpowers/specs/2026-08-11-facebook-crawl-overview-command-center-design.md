# Facebook Crawl Overview Command Center Design

## Goal

Redesign `/admin/facebook-crawl?view=overview` as an operations command center that lets an administrator answer three questions within a few seconds:

1. Is the Facebook crawl system healthy now?
2. What needs attention first?
3. What is the next safe action?

The redesign changes the visual hierarchy and interaction model comprehensively while preserving the existing route, authentication, API contract, crawl behavior, and lightweight overview request.

## Design Read

This is a redesign-overhaul of an operational admin surface for the RadarBDS owner and administrator. The visual language is calm, precise, and decision-first. It uses the existing native CSS system and RadarBDS theme tokens rather than introducing a new frontend framework.

- `DESIGN_VARIANCE: 5`: asymmetric enough to establish priority without making an operations screen unpredictable.
- `MOTION_INTENSITY: 3`: tactile feedback and restrained state transitions only.
- `VISUAL_DENSITY: 7`: compact operational information with clear grouping and readable spacing.

## Current-State Audit

### Existing strengths to preserve

- The overview loads only `/admin/api/facebook-crawl/overview`.
- Profile statistics and duplicate analysis remain isolated to the Brokers view.
- The page already supports light and dark themes.
- Controls have visible keyboard focus and mobile touch targets.
- Apify token values are never returned after creation.
- Overview, Brokers, and Run views retain URL-addressable state through `?view=`.

### Problems to retire

- Four equal cards imply equal importance even when system health is degraded.
- A long latest-job label can dominate its card and break scanning rhythm.
- Repeated source errors create duplicate warning rows.
- Problems have no visible severity or grouped count.
- Mobile users must scroll past four full-height cards before reaching active problems.
- The expanded Apify management area can overwhelm the overview and pull attention away from crawl health.
- Loading and request failure are communicated only through a small inline sentence.

## Scope

### In scope

- Shared Facebook Crawl page header and three-view navigation.
- The complete Overview view layout and hierarchy.
- Overview loading, healthy, warning, critical, empty, and request-error states.
- Client-side derivation and grouping of the existing overview payload.
- Responsive behavior from 390px mobile through wide desktop.
- Accessibility, reduced-motion behavior, and cache-busted asset delivery.
- Focused unit, contract, responsive, and browser verification.

### Out of scope

- Changes to crawler execution, scheduling, valuation, reprocessing, or image download logic.
- Additional overview database queries.
- Changes to `/admin/api/facebook-crawl/overview` fields.
- A redesign of the Brokers table, broker editor drawer, Run composer, or job history content.
- Changes to route slugs, admin navigation labels, authentication, authorization, or Apify token security.
- Deployment. A production release requires a separate explicit instruction.

## Information Architecture

The Facebook Crawl workspace keeps the same three top-level views:

1. `Tổng quan`
2. `Môi giới`
3. `Chạy & lịch sử`

The Overview view is reorganized into five layers in priority order.

### 1. Workspace header

The header contains:

- Page title: `Facebook Crawl`
- One concise purpose sentence.
- A small last-updated status.
- One `Làm mới` action.

The refresh control remains available but no longer competes visually with operational actions.

### 2. System health panel

The dominant panel answers whether intervention is required. It contains:

- Health label: `Cần xử lý ngay`, `Cần theo dõi`, or `Hệ thống ổn định`.
- One plain-language summary generated from current problem types.
- The next scheduled crawl time.
- The latest Facebook run state.
- A primary `Chạy tác vụ` action that switches to the existing Run view.
- A secondary `Quản lý môi giới` action that switches to the existing Brokers view.

The panel uses semantic status color only. Red means a blocking condition, amber means an active warning, and green means no current problems.

### 3. Resource and activity rail

A narrower companion column contains two compact modules:

- `Tài nguyên Apify`: enabled keys, total keys, and availability ratio.
- `Tác vụ gần nhất`: normalized status and a truncated progress label with the full value available as accessible title text.

These modules support the health panel without competing with it.

### 4. Attention queue

The active-problem area becomes an operational queue:

- Duplicate items are grouped by normalized `code + label`.
- Each group displays its severity, plain-language label, and occurrence count when greater than one.
- `schedule_missing` and `apify_unavailable` are critical.
- `source_error` and `lock_blocker` are warnings.
- Unknown codes are warnings and remain visible.
- When no problems exist, a compact healthy confirmation replaces the queue.

Grouping is presentational only. It does not modify the API payload or hide distinct labels.

### 5. Advanced Apify management

Token management stays in the Overview view but moves into a clearly labeled advanced disclosure:

- The disclosure is collapsed by default.
- Its summary includes the enabled-key count.
- Existing add, enable, disable, reset, and delete behavior remains unchanged.
- Existing security copy remains unchanged.

## Client-Side View Model

`static/js/admin/facebook-crawl.js` will add pure helpers so display decisions can be tested without a browser DOM.

### `buildOverviewViewModel(payload)`

The function accepts the current overview payload and returns:

```js
{
  health: 'healthy' | 'warning' | 'critical',
  healthLabel: string,
  healthSummary: string,
  nextRun: string,
  lastFacebookRun: string,
  latestJob: {
    status: string,
    label: string,
    fullLabel: string,
  },
  apify: {
    enabled: number,
    total: number,
    ratioLabel: string,
  },
  problems: Array<{
    key: string,
    code: string,
    label: string,
    severity: 'warning' | 'critical',
    count: number,
  }>,
}
```

The helper must tolerate missing objects, missing arrays, unexpected values, and long strings.

### Problem grouping

`groupOverviewProblems(problems)` will:

1. Normalize missing codes to `unknown`.
2. Trim labels and fall back to `Có vấn đề cần kiểm tra`.
3. Group only entries with the same normalized code and label.
4. Preserve the order of first occurrence.
5. Increment a count instead of rendering repeated rows.

### Health derivation

- `critical` when at least one grouped problem has critical severity.
- `warning` when there are problems but none are critical.
- `healthy` when the grouped problem list is empty.

No backend field is reinterpreted as proof that a crawl succeeded. Missing Facebook history continues to display as unavailable data.

## Interaction Behavior

### View switching

The two actions in the health panel call the existing `setView()` path. They update `?view=` and preserve all current unsaved-change protections.

### Refresh

- Refresh keeps the existing 10-second overview cache behavior unless explicitly forced.
- The button enters a disabled busy state during a forced refresh.
- The visible label changes to `Đang làm mới` while loading.
- Success updates the last-updated text.
- Failure leaves the previous successful data visible when available and adds a contextual error message.

### Loading

The first load displays layout-matched skeletons for the health panel, resource rail, and attention queue. It does not use a generic spinner.

### Empty and healthy states

- No latest job: `Chưa có tác vụ gần đây`.
- No Facebook run: `Chưa có dữ liệu lần chạy Facebook`.
- No enabled Apify keys: resource state is critical.
- No active problems: show a concise healthy confirmation.

### Error state

When the initial overview request fails, the view shows:

- `Không tải được tổng quan`
- A short recovery instruction.
- A `Thử lại` button using the existing forced refresh path.

## Visual System

### Theme

- Continue using the current `--bg`, `--panel`, `--ink`, `--muted`, `--line`, `--blue`, and semantic status tokens.
- Support both current light and dark themes.
- Use one brand accent, RadarBDS blue.
- Red, amber, and green are reserved for real status meaning.

### Typography

- Keep the existing Inter and Segoe UI stack for consistency with the admin shell.
- Use stronger size and weight contrast instead of introducing another font.
- Use a monospace fallback for timestamps, quotas, and counts where alignment helps scanning.
- Limit the dominant health headline to two lines at desktop widths.

### Shape system

- Primary surfaces: 14px radius.
- Inputs and buttons: 10px radius.
- Status badges only: pill radius.
- Shadows are subtle and tinted to the surrounding theme.
- Borders and spacing communicate hierarchy before elevation.

### Motion

- Buttons receive a small active-state press.
- Newly rendered status content may use a short opacity and vertical transition.
- No perpetual animation, parallax, marquee, glow, or decorative motion.
- All transitions are disabled under `prefers-reduced-motion: reduce`.

### Copy rules

- Use plain operational Vietnamese.
- Do not expose raw internal labels when a stable user-facing status exists.
- Do not use em dashes or decorative version labels.
- Do not invent timestamps, quotas, percentages, or success claims.

## Responsive Layout

### Wide desktop: 1200px and above

- The workspace header and tabs remain on one line where space permits.
- Main command area uses an asymmetric `minmax(0, 2fr) minmax(280px, 1fr)` grid.
- Attention queue spans the available width below the command area.

### Tablet: 761px to 1199px

- The command area uses two balanced columns when space permits.
- Activity modules remain compact.
- Actions wrap without reducing touch targets.

### Mobile: 760px and below

- Strict single-column layout.
- Order: system health, attention queue, actions, resource details, advanced token management.
- Critical information appears before secondary history.
- The three view tabs remain horizontally scrollable and keep 44px touch targets.
- No horizontal document overflow at 390px.
- Primary actions become full-width only when needed for readable labels.

## Accessibility

- The dominant health state uses text and structure, not color alone.
- Status updates remain inside an `aria-live="polite"` region.
- Problems render as a semantic list.
- Busy controls use `disabled` and `aria-busy`.
- Error recovery remains keyboard accessible.
- Focus rings keep at least the current visibility.
- Button labels do not wrap on desktop.
- Light and dark variants must maintain WCAG AA contrast for body copy and controls.

## Files Expected to Change

- `templates/admin_control_room.html`
  - Replace the Overview skeleton and add semantic regions and action hooks.
  - Bump the `admin.css` and `facebook-crawl.js` asset query keys.
- `static/js/admin/facebook-crawl.js`
  - Add pure overview view-model helpers.
  - Render the new states without `innerHTML`.
  - Preserve existing view switching and token operations.
- `static/css/admin.css`
  - Replace Overview-specific layout rules.
  - Add responsive, dark-theme, skeleton, focus, and reduced-motion rules.
- `tests/js/test_facebook_crawl_admin.js`
  - Cover grouping, severity, missing data, long job labels, and view-model output.
- `tests/test_admin_growth_ui.py`
  - Cover semantic hooks, cache keys, responsive contract, and accessibility markers.
- `tests/test_facebook_crawl_admin_api.py`
  - Remain unchanged unless a regression assertion is needed to prove the API stays lightweight.

## Testing Strategy

### Unit and contract tests

- Red-green tests for `groupOverviewProblems()` and `buildOverviewViewModel()`.
- Existing request-per-view contract remains unchanged.
- Existing safe DOM contract continues to prohibit `innerHTML` assignment.
- Existing profile draft, conflict, token, and run tests remain green.

### Static verification

- `node --check static/js/admin/facebook-crawl.js`
- `node tests/js/test_facebook_crawl_admin.js`
- Focused Python tests for Facebook Crawl API and admin UI contracts.
- `git diff --check`

### Browser verification

- Authenticated production-shaped page at desktop width 1536px.
- Mobile viewport 390px by 844px.
- Light and dark themes.
- Healthy, warning, critical, loading, and request-error fixtures.
- No horizontal overflow.
- No console errors.
- One overview request on initial load and one request per forced refresh.
- Brokers and Run view switching still works.

## Acceptance Criteria

1. An administrator can identify health, active problems, and the next action from the first viewport on desktop and mobile.
2. Duplicate problem labels render once with an accurate count.
3. Critical problems appear before secondary activity information on mobile.
4. Long latest-job labels cannot break the grid or dominate the page.
5. The Overview initial load still requests only `/admin/api/facebook-crawl/overview`.
6. No profile-statistics or duplicate-analysis request is introduced into Overview.
7. Existing token-management behavior and security copy remain intact.
8. Existing URL view state and unsaved-change protection remain intact.
9. The page has explicit loading, healthy, empty, and request-error states.
10. Desktop, mobile, light theme, dark theme, keyboard focus, and reduced motion are verified.
11. No unrelated files are staged or committed.

