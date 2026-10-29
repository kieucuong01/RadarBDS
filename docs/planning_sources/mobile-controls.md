# Compact Maps controls

Updated 2026-10-29. At widths up to 760 px, Maps keeps Khu vực, Tờ/thửa,
Lớp bản đồ and the listing visibility toggle on one row. Basemap selection
uses Leaflet's native collapsed control; it expands on desktop and updates
when the viewport crosses the mobile breakpoint.

Opacity and draw/delete/legend controls sit in a narrow right rail. The percentage
also opens the native layer selector, allowing independent opacity changes when
multiple themes are enabled. Icons retain accessible names and 44 px touch areas.
The rail is hidden while a parcel card or a form is open to avoid overlap.

The bottom row scrolls horizontally in actual DOM order: Ranh thửa, QH SDĐ 2030,
QH Chung, QH Phân khu, QH Chi tiết. Ordinary Maps keeps planning disabled;
explicit planning entries retain their existing fullscreen, hidden-listings and
35% opacity defaults. Geography, listing filters and viewport loading are unchanged.

`planning_mobile.css` follows the shared overlay styles and owns phone layout.
No new JavaScript library or third-party imagery is required for these controls.
