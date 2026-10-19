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

Page-specific styles still own layout, reading typography, illustrations and
data colours. Green price/success indicators and map layer legends are
semantic data, not primary brand actions. Do not recolour them globally.
No dashboard stylesheet is imported into public pages: it contains different
theme and layout defaults. Change the shared brand file for future public
control updates instead of adding another per-page button palette.

Verification: `tests/test_public_brand.py` checks every shared-header template
and representative rendered routes for exactly one final brand stylesheet.
Browser QA checks computed CTA styles, hover/focus, disabled controls and
mobile overflow in news, tools, reports and map pages.
