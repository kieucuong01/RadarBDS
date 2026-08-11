# Facebook Broker Compact Roster Design

## Goal

Make the desktop broker roster denser so an operator can scan more profiles in
one viewport without hiding the operational state needed to decide what to run
or fix next.

## Approved structure

The table columns, in visual and DOM order, are `STT`, `Môi giới`, `Khu vực`,
`Trạng thái`, `Lịch`, `Quota / chu kỳ`, `Chất lượng`, `Crawl cuối`, and
`Thao tác`. `STT` is one-based for the filtered roster. A valid Facebook URL
makes the broker name a safe new-tab link; missing or invalid URLs keep the
name as plain text. The raw URL is not displayed in the desktop table, and the
full value remains available in the existing edit drawer.

## Visual and safety rules

- Target a 48–54px desktop row with single-line primary values.
- Keep text in status badges; color is not the sole status signal.
- Desktop actions may be compact. Mobile keeps the existing card format and
  44px action targets.
- Reuse `safeFacebookProfileLink()` and add `target="_blank"` plus
  `rel="noopener noreferrer"` only for validated links.
- Do not change APIs, filters, draft saving, delete confirmation, or drawer
  behavior. Update system-row `colSpan` to the nine-column table.
