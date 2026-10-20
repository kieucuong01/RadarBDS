# Shared public visual identity

The homepage is the reference for interactive controls. Public SEO, news,
reports, research tools, maps and map checkout pages load
`partials/public_brand_assets.html` immediately before `</head>`, after all
page layout styles. New shared-header templates must do the same.

`static/css/public_brand.css` owns the interaction palette: indigo `#4f46e5`
to blue `#2563eb`, 12px action corners, pill header CTA, 16px panel corners,
blue keyboard focus and a small hover lift/shadow on primary actions.
Secondary actions use white/indigo with an indigo tint on hover. Disabled
buttons retain their disabled appearance; reduced-motion users get no lift.

Page-specific styles still own layout, content hierarchy, illustrations and
data colours. Green price/success indicators and map layer legends are
semantic data, not primary brand actions. Do not recolour them globally.
No dashboard stylesheet is imported into public pages: it contains different
theme and layout defaults. Change the shared brand file for future public
control updates instead of adding another per-page button palette.

Typography follows the homepage's Plus Jakarta Sans throughout public headings,
body copy and controls. Vietnamese, Latin and Latin Extended variable subsets
(400–800) are self-hosted in `static/fonts/plus-jakarta-sans/` under OFL 1.1.
Preload only Vietnamese and Latin; use `font-display: swap`. Legacy Noto Serif
faces and preloads were removed from the page stylesheets. Article body copy
keeps a comfortable 1.85 line height and its existing reading column.

`partials/public_brand_logo.html` is the shared header/footer lockup: the same
`app-icon-192.png` as the dashboard, RadarBDS wordmark and "Chuyên sâu Bình Dương"
caption. Preserve the containing link's accessible name; the image is decorative
because the link already names the brand. Both research tools also use the
common footer; that partial supports pages without a `page` context.

2026-10-19 follow-up audit scope: all 188 HTML URLs in the public sitemap,
plus template coverage for unpublished/empty document and category pages.
Rendered HTML checks cover HTTP status, a single H1/canonical, shared assets,
and matching header/footer logos. Browser review samples the actual layouts
on desktop and narrow mobile widths; this is not 188 individual visual reviews.

Verification: `tests/test_public_brand.py` checks every shared-header template
and representative rendered routes for exactly one final brand stylesheet.
Browser QA checks computed CTA styles, hover/focus, disabled controls and
mobile overflow in news, tools, reports and map pages.

## Shared footer and contact identity

The canonical public contact details live in `PUBLIC_CONTACT` in
`services/public_marketing.py`. The template context and Organization schema
read the same values, including the support telephone, email, address and
official Facebook/YouTube URLs. Update that source when business details change.

`partials/seo_footer.html` renders the complete semantic footer with contact
`address`, descriptive internal links, social links, data limitations, copyright
and sitemap. `public_footer.css` is scoped so it also works in the dashboard
and listing page without importing public-page layout styles. Dashboard and
Radar Ask use `public_footer_compact.html`, a native expandable disclosure that
keeps the data workspace usable while retaining the full footer in server HTML.
Do not add unverified office hours, registration details or policy URLs.

The shared footer and public/dashboard Tools menus expose “Cài Radar BDS”.
`public_install.js` retains `beforeinstallprompt` for an explicit install action;
the native dialog shows platform-specific manual steps when no prompt is available.
It never opens automatically and never installs without browser confirmation.

The authenticated dashboard's `main/account_menu.js` loads with the shell before
`core.js`. Opening the already-rendered account menu is synchronous and does not
load auth/modal resources. On mobile it moves the dropdown outside the header's
filter context and uses the same dark overlay and 4px blur as Tools. Outside
click, close, Escape, keyboard focus and breakpoint changes share that state.
`auth.js` delegates menu state to this shell after it loads for account actions.

Tin rao cards at widths up to 720px use a 2:1 image/price grid in `cards.css`,
scoped to `#tab-all .signal-shared-card`. Asking price and valuation stack in the
right column; the title, property chips and actions span the full width below.
The existing DOM/data/click handlers are retained via `display: contents` on the
card body. Signal cards, saved cards and desktop keep their normal layout.
