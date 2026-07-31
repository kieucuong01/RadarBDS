# Facebook broker removal and list UX

## Goal

Let an administrator remove a Facebook broker from the future crawl
configuration at `/admin/facebook-crawl?view=brokers`, while preserving every
already crawled `raw_listings`, derived `listings`, images, and valuation data.
Make the broker list easier to scan and operate on desktop and mobile.

## Scope

- Add a visible destructive `Xóa` action beside the existing `Sửa` and `Chạy`
  actions in the broker-list view.
- On confirmation, remove the selected profile only from the client-side
  configuration draft. The action must say that crawled listings are retained.
- Continue to persist all draft changes through the existing revision-protected
  `POST /admin/api/facebook-crawl/profiles` endpoint when the administrator
  selects `Lưu thay đổi`.
- Improve the existing broker table's hierarchy: recognizable broker identity,
  compact textual status badges, grouped actions, a clear pending-save state,
  responsive action layout, keyboard-visible focus, and touch-sized controls.

## Data and security contract

The browser must never call a listing deletion endpoint. The saved profile
collection is the only data submitted. Server-side admin authorization,
revision conflict handling, profile normalization, and the transactional
configuration replacement remain unchanged.

`facebook_crawl_profiles` is an independent configuration table. It has no
foreign key or cascade relationship to `raw_listings`, `listings`, images, or
valuations, so removing a profile stops future scheduled selection only.

## Interaction flow

1. The admin opens the Brokers tab and sees a row for each configured profile.
2. Selecting `Xóa` opens a native confirmation that names the broker and says
   its old crawled listings will remain intact.
3. Confirmation removes that profile from the draft, re-renders filters, the
   run selector, and duplicate suggestions, and enables `Lưu thay đổi`.
4. Saving sends the draft plus its current revision. On success, the server's
   canonical profile list becomes the new baseline. On a revision conflict, the
   existing conflict banner continues to preserve the local draft.

## Validation

- JavaScript contract test proves the delete action is part of the Brokers UI
  and that its confirmation explicitly preserves crawled listings.
- The focused Flask API regression test continues to prove profile changes use
  the revision-protected configuration endpoint.
- JavaScript syntax, CSS/template regression tests, and a rendered browser
  check cover the affected desktop and narrow layouts.
