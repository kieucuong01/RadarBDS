# Compact Maps controls

Updated 2026-10-29. At widths up to 760 px, Maps keeps Bộ lọc, Tờ/thửa,
Lớp bản đồ and the listing visibility toggle on one row. Basemap selection
uses Leaflet's native collapsed control; it expands on desktop and updates
when the viewport crosses the mobile breakpoint.

Opacity and draw/delete/legend controls sit in a narrow right rail. The percentage
also opens the native layer selector, allowing independent opacity changes when
multiple themes are enabled. Icons retain accessible names and 44 px touch areas.
The rail is hidden while a parcel card or a form is open to avoid overlap.

The bottom row scrolls horizontally in actual DOM order: Ranh thửa, QH SDĐ 2030,
QH Chung, QH Phân khu, QH Chi tiết. An additional QH 100 năm (Dự thảo) chip follows.
Maps opens in focus mode on satellite imagery; ordinary entries enable QH SDĐ
2030 at 65% and retain listing visibility. Explicit
planning entries enable the requested theme and hide listings. Mobile hides the
focus-mode control, and the toolbar's Bộ lọc opens the existing sidebar/sheet.
Parcel lookup cascades from former province to former district and ward using the
available GIS catalog; unavailable districts are not represented as supported.

`planning_mobile.css` follows the shared overlay styles and owns phone layout.
No new JavaScript library or third-party imagery is required for these controls.
