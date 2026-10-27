# Planning Map Controls Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make area navigation, parcel search, planning layers, opacity and parcel information as easy to reach as the supplied Guland references.

**Architecture:** Keep Leaflet, existing raster/parcel loaders and their cancellation guards. Add one on-map toolbar with independent area/search/layer popovers, a two-layer quick dock and an opacity rail. Use a local indexed exact sheet/parcel lookup; retain GIS/PDF choices and source provenance.

**Tech Stack:** Flask, SQLite spatial asset index, plain JavaScript/CSS, Leaflet.

**Spec:** User screenshots and the interaction decisions below.

## Global constraints

- Local pilot on port 5055; preserve all existing dirty work and ignored captures.
- Area selection frames Maps; panning still loads surrounding wards and listings.
- Partition on, general planning off initially; both can be enabled together.
- No new dependencies, owner data, source geometry edits, fake tools or legal conclusions.
- All controls support keyboard and touch; mobile avoids horizontal overflow and competing sheets.

## Interaction decisions

- Toolbar: Khu vực, Tờ/thửa, Lớp bản đồ. Open one popover at a time.
- Area: city/ward navigation using existing initial-bounds endpoint.
- Search: historic ward + exact source sheet/parcel strings; show bounded multiple results rather than choosing a duplicate automatically.
- Layer dock: independent partition/general toggles. Opacity rail adjusts the last chosen active layer; per-layer values remain independent.
- Parcel card: close button, sheet/parcel, source area, historic location, compact land-use intersection rows; raw indicators and decision metadata remain expandable.

## Review focus

- Duplicate sheet/parcel pairs across wards must not cross scope.
- Rapid search, pan, selection and close must ignore late responses.
- Closing parcel info restores the listing sheet without clearing the map.
- Opacity changes must not create new raster downloads.
- Mobile keyboard, small screens and desktop/mobile transitions keep controls reachable.

## Tasks

- [x] Add failing search tests, implement indexed exact lookup and bounded local route, rebuild local index.
- [x] Add UI runtime checks for dock/opacity, search/cancellation and info close; implement shared toolbar and compact parcel card.
- [x] Update responsive styles and asset versions; retain existing GIS/PDF and overlay lifecycle checks.
- [x] Run focused tests, inspect actual search/click flows on desktop/mobile, record screenshots and source limits.

Ruling: colour chips use a neutral UI colour, not invented source zoning colours, because the GIS lookup contains no authoritative colour field.

Ruling: compact layout applies through 1100 px because the existing listing rail leaves a narrow map above the 760 px mobile breakpoint. Selected-parcel opacity is horizontal in that layout and vertical on wide maps.

Verification: 148 passed, 2 standalone browser tests deselected; direct browser QA at 390/900/1280 px. Search, cross-city area navigation, real polygon clicks, opacity keyboard input and unchanged source indicators were checked. Local pilot only; no commit/push/deploy requested.
