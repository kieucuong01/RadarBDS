# Facebook Crawl Brokers Roster Workbench Design

**Date:** 2026-08-11
**Route:** `/admin/facebook-crawl?view=brokers`
**Status:** Approved direction, pending written-spec review

## Goal

Upgrade the Brokers view into a roster-first operational workspace where an admin can find a broker, understand crawl readiness, and take the correct action with minimal scanning.

The redesign must preserve the current product contracts:

- Profiles load from `/admin/api/facebook-crawl/profiles`.
- Duplicate suggestions load independently from `/admin/api/facebook-crawl/duplicates`.
- Profile edits remain local drafts until the explicit Save action.
- Revision conflicts and unsaved-change protection remain intact.
- Add, edit, run, delete, duplicate-suggestion, and load-more behavior remain available.
- Deleting a broker removes it from the draft only and does not delete crawled listings.
- No API shape, framework, or third-party UI dependency changes are required.

## Design Read

The target is an enterprise admin workbench rather than a marketing dashboard.

- **Primary job:** search and manage the broker roster.
- **Secondary job:** review duplicate-profile suggestions.
- **Visual character:** compact, calm, scan-first, and operational.
- **Design variance:** 5/10.
- **Motion intensity:** 2/10.
- **Visual density:** 7/10.
- **Accent policy:** use the existing blue accent sparingly; reserve semantic colors for status.
- **Typography:** retain the existing admin typography and token system.

The installed taste skill is used as an anti-slop and hierarchy check only. The view remains a dense administrative table rather than adopting landing-page patterns.

## Current-State Audit

### Strengths to preserve

- Broker and duplicate data use focused APIs.
- Draft edits, one-time save behavior, revision checks, and conflict handling protect operator work.
- Run and delete actions are scoped to a single broker.
- The existing implementation avoids unsafe HTML injection.
- Desktop and mobile layouts already exist.
- Filters cover the operational dimensions admins need: search, city, active state, cadence, due state, and quality.

### Problems to solve

- Six equal-weight filters create a large control wall before the roster.
- There is no reset action or visible count of applied filters.
- The roster has no compact summary of total, active, due, and attention-needed brokers.
- Status, schedule, and quality are plain text and require slow row-by-row reading.
- Facebook profile URLs are searchable but not visible in the roster.
- The desktop table is dense without a strong visual hierarchy.
- Mobile rows become long records with weak prioritization.
- Duplicate analysis looks like another generic block even though it is a secondary workflow.
- The edit drawer presents fields as one sequence instead of meaningful groups.
- Quality styling depends on table-column position, which is fragile when columns change.
- Loading, empty, filtered-empty, and error states are not sufficiently distinct.

## Scope

### In scope

- Recompose the Brokers header, summary, filters, roster, duplicate queue, and edit drawer.
- Derive roster summaries and presentation states from already-loaded profile data.
- Add a search-first filter layout, applied-filter count, and reset action.
- Make broker identity, status, due state, quality, and last crawl easier to scan.
- Display a safely truncated profile URL beneath the broker name.
- Add explicit loading, empty, filtered-empty, and error presentation.
- Improve mobile hierarchy and touch targets.
- Add focused tests for derived view-model behavior and source-level UI contracts.
- Bump affected static asset cache keys.

### Out of scope

- API changes or new endpoints.
- Database or profile-schema changes.
- Bulk broker actions.
- Server-side search, filtering, sorting, or pagination.
- New crawl scheduling logic.
- Automatic saving.
- Changing duplicate-detection rules.
- Deleting previously crawled listings.
- New frontend frameworks, icon libraries, fonts, or animation packages.

## Information Architecture

### 1. Compact page heading and actions

The top row contains:

- Page title and one-line operational description.
- Unsaved-change state near the actions.
- Primary `Lưu thay đổi` action.
- Secondary `Thêm môi giới` action.

The header remains compact so the roster appears in the first desktop viewport.

### 2. Inline roster summary

Show a restrained summary strip derived from the loaded draft:

- Total brokers.
- Active brokers.
- Due now.
- Needs attention.

This is one compact operational strip, not four equal hero cards. Counts use these exact client-side predicates:

- **Active:** `profile.active !== false`.
- **Due now:** active and `profile.due_today === true`.
- **Needs attention:** active and either due now, missing a quality score, or having a quality score below `68`.

“Needs attention” is a presentation grouping only. It does not introduce a persisted status or change scheduler behavior.

### 3. Search-first filter workbench

The filter area has two levels:

- A large, primary search input for broker name or Facebook URL.
- A compact filter rail for city, active state, cadence, due state, and quality.

The rail includes:

- A visible applied-filter count.
- A `Đặt lại` action that clears search and all secondary filters.
- A result count that updates from local data.

Filters remain client-side state. They are not added to the route URL because the current workflow does not require shareable filter links.

### 4. Broker roster

The roster remains a semantic table on desktop. Its visual order prioritizes decisions:

1. Broker identity: name, city, and truncated Facebook URL.
2. Operating state: active or paused.
3. Next crawl: due wording and exact schedule context.
4. Crawl plan: quota and cadence.
5. Quality: explicit label and score.
6. Latest crawl.
7. Row actions.

Presentation rules:

- Active, paused, due, and quality states use text plus semantic badges.
- Due or low-quality rows receive a small priority marker near the relevant state, not a full-row background tint.
- URL text truncates visually but keeps the full value available through the link or accessible label.
- Quality classes are attached by meaning, not by `:nth-child` position.
- No decorative progress bars are added for quality.
- The action group preserves Edit, Run, and Delete with clear labels or tooltips.

### 5. Duplicate analysis queue

Duplicate analysis remains below the main roster and is visually secondary.

It retains:

- Actionable and total counts.
- All/actionable toggle.
- Suggested cadence actions.
- Load-more behavior.

It gains explicit loading, empty, and error states. Duplicate requests remain independent so failure in this queue does not block roster management.

### 6. Grouped edit drawer

The existing drawer is retained but fields are grouped into:

- **Identity:** broker name, Facebook URL, city, active state.
- **Crawl schedule:** active state and crawl cadence.
- **Collection limits:** posts per day and range-day limit.

The footer keeps explicit cancel/close and apply-to-draft actions. Applying the drawer updates the local draft only; the page-level Save action remains the only persistence step.

## Client-Side View Model

Rendering should use pure helpers so filtering and state presentation can be tested independently from DOM events.

A helper such as `buildBrokerRosterViewModel(profiles, filters)` should return:

- `summary.total`
- `summary.active`
- `summary.due`
- `summary.needsAttention`
- `filteredProfiles`
- `resultCount`
- `activeFilterCount`
- the appropriate empty-state key or copy

Additional pure helpers may derive:

- Active-state badge.
- Due-state badge and schedule label.
- Quality class and label.
- Safe, compact profile URL display.

The view model must not mutate `state.draft`, server payloads, or profile objects. Existing API payloads remain the source of truth. Its summary predicates must match the exact definitions in the Information Architecture section.

## Interaction Behavior

### Search and filters

- Search matches broker name and Facebook URL using the existing case-insensitive behavior.
- Any filter change updates the roster and counts locally without a request.
- Reset clears all filter controls and restores the full roster.
- A filter combination with zero matches shows a filtered-empty state and a reset action.
- An empty server dataset shows an onboarding-style empty state with `Thêm môi giới`.

### Draft and persistence

- Add, edit, delete, and duplicate suggestions change only the draft.
- The unsaved indicator appears whenever the draft differs from the loaded revision.
- Save sends the existing payload exactly once per user action.
- Revision conflicts continue to surface without discarding local edits.
- Navigation protection remains active while unsaved changes exist.

### Row actions

- Edit opens the existing drawer with the selected profile.
- Run triggers the existing single-profile crawl action and displays its current feedback.
- Delete uses the existing confirmation language and affects the draft only.
- Controls remain disabled or guarded according to existing request-in-flight behavior.

### Data states

The roster must distinguish:

- Initial loading.
- Loaded with profiles.
- Loaded but no profiles exist.
- Loaded with profiles but current filters have no matches.
- Request error with no prior data.
- Refresh error while prior roster data is still available.

The duplicate queue must separately distinguish loading, loaded, empty, and error states.

## Visual System

- Reuse current admin CSS variables for surfaces, borders, text, accent, and semantic colors.
- Use a quiet surface hierarchy: page background, workbench panel, then compact controls.
- Keep border radii and shadows restrained and consistent with the upgraded Overview.
- Use blue for focus, primary actions, and selected controls only.
- Use green, amber, red, and neutral tones for semantic status with accompanying text.
- Avoid gradients, decorative illustrations, oversized metrics, and excessive pill shapes.
- Keep labels short and operational. User-facing text must avoid em dashes.
- Motion is limited to existing drawer and hover/focus feedback and must respect reduced-motion preferences.

## Responsive Layout

### Desktop

- Header actions remain on one compact row where space allows.
- Search receives the most width.
- Secondary filters wrap predictably without creating equal oversized boxes.
- The roster is visible in the first viewport at common admin resolutions.
- The table container may scroll horizontally internally when necessary; the page itself must not overflow.

### Mobile

- Header actions stack without hiding Save or Add.
- Search is full width.
- Secondary filters collapse into a compact, usable rail or grid with a visible applied count and reset.
- Each table row presents as a compact broker record while retaining semantic table markup where practical.
- The first visible information is name, active state, due state, and quality.
- Supporting schedule and quota details are grouped below.
- Edit, Run, and Delete controls have at least 44-by-44-pixel touch targets.
- The drawer fills the available width without horizontal overflow.
- The page must fit a 390-pixel viewport without page-level horizontal scrolling.

## Accessibility

- Every input keeps a visible label or an unambiguous accessible name.
- Status does not rely on color alone.
- Focus indicators remain clearly visible in light and dark themes.
- Table headers remain associated with their data on desktop.
- Mobile records retain meaningful labels for transformed cells.
- Icon-only actions, if any, require accessible names and visible tooltips.
- Drawer close and apply controls are keyboard reachable.
- Loading and error messages use appropriate live-region behavior without announcing every local filter keystroke.
- Reduced-motion settings suppress non-essential transitions.

## Files Expected to Change

- `templates/admin_control_room.html`
- `static/js/admin/facebook-crawl.js`
- `static/css/admin.css`
- `tests/js/test_facebook_crawl_admin.js`
- `tests/test_admin_growth_ui.py`
- Focused API regression tests only if source changes expose a contract gap

No database migration or new runtime dependency is expected.

## Testing Strategy

Implementation follows focused test-driven development:

1. Add failing tests for the pure roster view model, filter count/reset behavior, semantic status derivation, and empty-state selection.
2. Implement the smallest JavaScript changes needed to pass.
3. Add or update source-level UI contract tests for required controls, cache-key bumps, and responsive/accessibility hooks.
4. Run existing Facebook crawl admin API tests to prove the endpoint contract remains unchanged.
5. Run JavaScript syntax checks and the focused browser-admin test suite.
6. Exercise the rendered view at desktop and 390-pixel mobile widths in light and dark themes.

Browser QA must cover:

- Initial roster load.
- Search by name and URL.
- At least two secondary filters.
- Applied-filter count and reset.
- No-result and empty-state presentation.
- Add and edit drawer.
- Run action.
- Delete-to-draft behavior.
- Unsaved-change and save flow.
- Duplicate actionable/all toggle and suggestion.
- Duplicate loading, empty, and error presentation where feasible.
- No page-level horizontal overflow.

## Acceptance Criteria

- The roster, search, and primary actions dominate the first desktop viewport.
- An admin can identify active, paused, due, and low-quality brokers without reading every cell.
- Broker URLs are visible in compact form and remain accessible.
- Applied filters and result count are always understandable, and reset restores the full roster.
- Summary counts are derived locally and do not add API requests.
- Add, edit, run, delete, save, revision conflict, and unsaved-navigation behavior remain intact.
- Duplicate analysis remains functional and clearly secondary to the roster.
- Loading, empty, filtered-empty, and error states are explicit.
- Desktop table semantics remain valid.
- The 390-pixel layout has no page-level horizontal overflow and preserves 44-pixel touch targets.
- Light and dark themes remain legible.
- No new endpoint, dependency, database migration, or persistence behavior is introduced.
