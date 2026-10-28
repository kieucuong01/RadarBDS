# Map drawing and land symbols

User request: draw a boundary with edge distances, show area when closed, delete
it, and open a searchable land-symbol table. Draw/delete sit immediately below
the opacity control. Keep the current Leaflet map and existing source choices.

Implementation decisions:

- One transient drawing per Maps session. Tap/click places vertices; the first
  vertex or an explicit finish button closes it. Undo removes the latest point;
  Escape pauses an open drawing. Enter on the focused map adds its centre.
- Great-circle distances and spherical polygon area in metres/m², with hectares
  for larger shapes. Results are approximate map measurements. Reject crossing
  edges, duplicate points and zero-area polygons rather than showing bad areas.
- Drawing owns map clicks while active; marker and parcel clicks work normally
  after drawing stops. Restore double-click zoom and remove handlers on cleanup.
- Keep draw/delete/legend controls reachable at small widths. Hide competing
  listing sheets during drawing; show a compact status and finish/undo actions.
- The symbol panel loads its bundled source data only on first open, filters by
  code/name and identifies the source. Keep source-specific colours separate;
  never invent a universal colour legend across different planning editions.
- No database changes, new map dependency or publication of user geometry.

Validation: geometry/runtime regressions, existing Maps/planning checks, actual
desktop and phone-size draw/close/delete/legend interactions, then the exact
commit's CI and deployment verification under the existing release workflow.
