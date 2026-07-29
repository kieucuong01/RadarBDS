# Bình Dương City Map Products Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build complete paid map products for Thuận An, Dĩ An, and Bến Cát with free interactive pages, validated PDF/SVG/KML packages, previews, and product-safe PayOS checkout/download.

**Architecture:** A single `CITY_MAP_PRODUCTS` registry drives public pages, datasets, product identity, release filenames, and dashboard links. The existing GIS pipeline is generalized by passing a `MapProductSpec`/`MapReleaseProfile` instead of relying on Thủ Dầu Một constants; checkout derives the trusted product from the allowlisted route and download derives it from the immutable order.

**Tech Stack:** Python 3.12, Flask/Jinja, PostgreSQL order repository, Shapely, ReportLab, Pillow, Leaflet, vanilla JavaScript, PayOS, pytest, Node syntax tests.

## Global Constraints

- Each product costs exactly 99,000 VND and has its own immutable v1.0 ZIP.
- Thuận An must contain exactly 10 legacy and 5 current boundaries.
- Dĩ An must contain exactly 7 legacy and 3 current boundaries.
- Bến Cát must contain exactly 8 legacy and 6 current boundaries; legacy Phú An is a `Xã cũ`.
- Only Vĩnh Phú and An Bình may be marked as `derived_boundary`.
- Current boundaries come from `static/maps/binh-duong/current-36-wards.geojson`.
- Historical sourced boundaries come from the Stanford/GADM v2.8 snapshot already used by Thủ Dầu Một.
- Khu phố are named reference points only; no neighborhood boundary claims.
- PDF/SVG/KML originals and ZIP files must remain outside `static/`.
- Checkout never trusts product slug, version, price, or currency from the browser.
- PayOS credentials remain environment-only and must not appear in diffs or logs.
- Download resolves the product from `order.product_slug`; it must never use a global Thủ Dầu Một product constant.
- Existing `/ban-do-thu-dau-mot` behavior and its released package remain backward compatible.

## Trust Boundaries and Abuse Cases

- HTTP route `city_slug`: hostile until matched against `CITY_MAP_PRODUCTS`.
- `public_id`, retry cookie, recovery token, and order cookie: hostile until format/signature/order binding is verified.
- PayOS webhook: hostile until signature, order code, amount, and immutable order identity are verified.
- Protected ZIP/manifest: hostile until path containment, filename, manifest, checksum, and product/version match.
- Public GeoJSON edition: hostile until allowlisted to `truoc-sap-nhap` or `sau-sap-nhap`.

First security tests must catch:

- posting a Thuận An form cannot create a Bến Cát order;
- a retry cookie from one product cannot be reused on another product route;
- a paid Dĩ An order cannot download the Thủ Dầu Một ZIP;
- changing client-side fields cannot alter price/version/product;
- an unknown city or edition returns 404 without filesystem probing;
- PayOS secrets, recovery tokens, and order identifiers never enter analytics context.

---

### Task 1: Add the canonical city-map registry and product specifications

**Files:**
- Create: `config/city_map_products.py`
- Create: `config/map_products/thuan_an_product.json`
- Create: `config/map_products/di_an_product.json`
- Create: `config/map_products/ben_cat_product.json`
- Modify: `config/thu_dau_mot_map_product.py`
- Modify: `map_products/models.py`
- Test: `tests/test_city_map_product_registry.py`
- Test: `tests/test_thu_dau_mot_map_sources.py`

**Interfaces:**
- Produces: `CITY_MAP_PRODUCTS: dict[str, dict]`
- Produces: `get_city_map_page(city_slug: str) -> dict`
- Produces: `get_city_map_page_by_path(path: str) -> dict`
- Produces: `MapProductSpec.city_slug`, `.city_name`, `.derived_legacy_wards`

- [ ] **Step 1: Write failing registry and spec-loader tests**

```python
EXPECTED_COUNTS = {
    "thuan-an": (10, 5),
    "di-an": (7, 3),
    "ben-cat": (8, 6),
}

def test_city_map_registry_has_unique_paths_products_and_expected_counts():
    pages = [get_city_map_page(slug) for slug in EXPECTED_COUNTS]
    assert {page["path"] for page in pages} == {
        "/ban-do-thuan-an", "/ban-do-di-an", "/ban-do-ben-cat"
    }
    assert len({page["product_slug"] for page in pages}) == 3
    for slug, (legacy_count, current_count) in EXPECTED_COUNTS.items():
        page = get_city_map_page(slug)
        assert len(page["legacy_units"]) == legacy_count
        assert len(page["current_units"]) == current_count
        assert page["price_vnd"] == 99_000

def test_ben_cat_preserves_legacy_phu_an_as_commune():
    page = get_city_map_page("ben-cat")
    phu_an = next(item for item in page["legacy_units"] if item["name"] == "Phú An")
    assert phu_an["unit_type"] == "Xã cũ"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_product_registry.py -q
```

Expected: collection/import failure because `config.city_map_products` does not exist.

- [ ] **Step 3: Implement strict page registry and extended product spec**

Add immutable-looking config dictionaries for Thủ Dầu Một, Thuận An, Dĩ An, and
Bến Cát. Validate on import:

```python
def _validate_pages(pages: dict[str, dict]) -> None:
    paths = [page["path"] for page in pages.values()]
    products = [page["product_slug"] for page in pages.values()]
    if len(paths) != len(set(paths)) or len(products) != len(set(products)):
        raise ValueError("city map paths and product slugs must be unique")
    for slug, page in pages.items():
        if page["city_slug"] != slug or page["price_vnd"] != 99_000:
            raise ValueError(f"invalid city map product: {slug}")
```

Extend the product JSON schema with literal fields:

```json
{
  "city_slug": "thuan-an",
  "city_name": "Thuận An",
  "derived_legacy_wards": ["Vĩnh Phú"]
}
```

Keep `THU_DAU_MOT_MAP_PRODUCT_PAGE` as a compatibility alias to the registry
entry.

- [ ] **Step 4: Run registry/model tests and verify GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_product_registry.py tests/test_thu_dau_mot_map_sources.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add config/city_map_products.py config/thu_dau_mot_map_product.py config/map_products/*_product.json map_products/models.py tests/test_city_map_product_registry.py tests/test_thu_dau_mot_map_sources.py
git commit -m "Add city map product registry"
```

### Task 2: Build deterministic legacy/current boundary snapshots

**Files:**
- Create: `scripts/build_city_map_boundaries.py`
- Create: `config/map_products/thuan_an_legacy_boundaries.geojson`
- Create: `config/map_products/di_an_legacy_boundaries.geojson`
- Create: `config/map_products/ben_cat_legacy_boundaries.geojson`
- Create: `config/map_products/thuan_an_legacy_ward_centers.geojson`
- Create: `config/map_products/di_an_legacy_ward_centers.geojson`
- Create: `config/map_products/ben_cat_legacy_ward_centers.geojson`
- Create: `static/maps/thuan-an/legacy-10-wards.geojson`
- Create: `static/maps/thuan-an/current-5-wards.geojson`
- Create: `static/maps/di-an/legacy-7-wards.geojson`
- Create: `static/maps/di-an/current-3-wards.geojson`
- Create: `static/maps/ben-cat/legacy-8-units.geojson`
- Create: `static/maps/ben-cat/current-6-wards.geojson`
- Test: `tests/test_city_map_boundaries.py`

**Interfaces:**
- Consumes: `get_city_map_page(city_slug)`
- Produces: `build_city_boundaries(city_slug: str, source_features: list[dict]) -> tuple[dict, dict, dict]`
- Produces: public GeoJSON properties compatible with `_map_areas_from_static_geojson`

- [ ] **Step 1: Write failing data-builder tests**

```python
@pytest.mark.parametrize(
    ("slug", "legacy_count", "current_count", "derived"),
    [
        ("thuan-an", 10, 5, {"Vĩnh Phú"}),
        ("di-an", 7, 3, {"An Bình"}),
        ("ben-cat", 8, 6, set()),
    ],
)
def test_builder_returns_exact_valid_boundaries(
    slug, legacy_count, current_count, derived, stanford_fixture
):
    legacy, current, centers = build_city_boundaries(slug, stanford_fixture)
    assert len(legacy["features"]) == legacy_count
    assert len(current["features"]) == current_count
    assert len(centers["features"]) == legacy_count
    assert {
        feature["properties"]["name"]
        for feature in legacy["features"]
        if feature["properties"]["boundary_source"] == "derived_boundary"
    } == derived
    assert all(shape(feature["geometry"]).is_valid for feature in legacy["features"])
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_boundaries.py -q
```

Expected: import failure for `scripts.build_city_map_boundaries`.

- [ ] **Step 3: Implement source-name aliases, group filtering, and residual derivation**

The name normalizer strips accents and common administrative prefixes, so the
Stanford spellings `Ân Phú` and `Ân Sơn` resolve to canonical `An Phú` and
`An Sơn`. Derive missing geometry using:

```python
residual = polygonal(
    unary_union(current_geometries).difference(unary_union(sourced_geometries)),
    f"{city_name} residual",
)
```

Reject a derived result if it is empty, invalid, outside the current city union,
or overlaps sourced geometry beyond a tiny numerical tolerance.

- [ ] **Step 4: Run builder against the pinned Stanford source and write snapshots**

Run:

```powershell
& $py -X utf8 scripts/build_city_map_boundaries.py --city thuan-an
& $py -X utf8 scripts/build_city_map_boundaries.py --city di-an
& $py -X utf8 scripts/build_city_map_boundaries.py --city ben-cat
```

Expected literal summaries:

```text
thuan-an legacy=10 current=5 derived=Vĩnh Phú
di-an legacy=7 current=3 derived=An Bình
ben-cat legacy=8 current=6 derived=none
```

- [ ] **Step 5: Run data tests and inspect topology**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_boundaries.py -q
```

Expected: PASS with only Vĩnh Phú and An Bình derived.

- [ ] **Step 6: Commit**

```powershell
git add scripts/build_city_map_boundaries.py config/map_products/*_legacy_boundaries.geojson config/map_products/*_legacy_ward_centers.geojson static/maps/thuan-an static/maps/di-an static/maps/ben-cat tests/test_city_map_boundaries.py
git commit -m "Add city map boundary snapshots"
```

### Task 3: Generalize GIS normalization, scenes, and renderers

**Files:**
- Modify: `map_products/geometry.py`
- Modify: `map_products/scene.py`
- Modify: `map_products/renderers.py`
- Modify: `tests/test_thu_dau_mot_map_sources.py`
- Modify: `tests/test_thu_dau_mot_map_renderers.py`
- Create: `tests/test_city_map_renderers.py`

**Interfaces:**
- Consumes: `MapProductSpec`
- Produces: `build_scene(layers, edition, spec) -> MapScene`
- Produces: `render_kml(layers, edition, path, spec) -> Path`

- [ ] **Step 1: Write failing variable-count renderer tests**

```python
def test_scene_uses_city_name_and_spec_counts(thuan_an_layers, thuan_an_spec):
    legacy = build_scene(thuan_an_layers, "legacy", thuan_an_spec)
    current = build_scene(thuan_an_layers, "current", thuan_an_spec)
    assert legacy.title == "BẢN ĐỒ THUẬN AN"
    assert legacy.subtitle == "10 phường cũ — ranh tham khảo"
    assert current.subtitle == "5 phường hiện hành — địa giới hành chính"
    assert "Vĩnh Phú" in legacy.disclaimer

def test_wrong_boundary_count_is_rejected(thuan_an_layers, thuan_an_spec):
    broken = replace(thuan_an_layers, current_boundaries=thuan_an_layers.current_boundaries[:-1])
    with pytest.raises(ValueError, match="exactly 5"):
        build_scene(broken, "current", thuan_an_spec)
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_renderers.py -q
```

Expected: `build_scene()` does not accept the spec argument.

- [ ] **Step 3: Replace hard-coded counts/copy with spec-derived behavior**

Change every `14`/`5` validation in geometry, scene, and KML renderer to:

```python
legacy_count = len(spec.legacy_wards)
current_count = len(spec.current_wards)
```

Use a deterministic palette for city wards not present in the existing Thủ Dầu
Một color mapping. Create disclaimer text from `spec.derived_legacy_wards`.
Keep Thủ Dầu Một visual colors and output compatible.

- [ ] **Step 4: Run renderer/geometry suites and verify GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_renderers.py tests/test_thu_dau_mot_map_renderers.py tests/test_thu_dau_mot_map_sources.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add map_products/geometry.py map_products/scene.py map_products/renderers.py tests/test_city_map_renderers.py tests/test_thu_dau_mot_map_renderers.py tests/test_thu_dau_mot_map_sources.py
git commit -m "Generalize city map renderers"
```

### Task 4: Generalize release validation and generate the three products

**Files:**
- Modify: `map_products/release.py`
- Create: `scripts/build_city_map_product.py`
- Create: `config/map_products/thuan_an_sources.json`
- Create: `config/map_products/di_an_sources.json`
- Create: `config/map_products/ben_cat_sources.json`
- Create: `config/map_products/thuan_an_neighborhoods.geojson`
- Create: `config/map_products/di_an_neighborhoods.geojson`
- Create: `config/map_products/ben_cat_neighborhoods.geojson`
- Create: `static/images/seo/thuan-an-map-before.webp`
- Create: `static/images/seo/thuan-an-map-after.webp`
- Create: `static/images/seo/di-an-map-before.webp`
- Create: `static/images/seo/di-an-map-after.webp`
- Create: `static/images/seo/ben-cat-map-before.webp`
- Create: `static/images/seo/ben-cat-map-after.webp`
- Test: `tests/test_city_map_release.py`
- Modify: `tests/test_thu_dau_mot_map_release.py`

**Interfaces:**
- Produces: `MapReleaseProfile.from_spec(spec) -> MapReleaseProfile`
- Produces: `validate_candidate(candidate_dir, profile) -> ValidationResult`
- Produces: `package_release(candidate_dir, approval_path, output_zip, profile) -> Path`

- [ ] **Step 1: Write failing profile/release tests**

```python
def test_release_profile_names_files_from_city_spec(thuan_an_spec):
    profile = MapReleaseProfile.from_spec(thuan_an_spec)
    assert profile.product_name == "radarbds-thuan-an-map"
    assert profile.legacy_pdf == "thuan-an-truoc-2025-a0.pdf"
    assert profile.current_kml == "thuan-an-sau-2025.kml"

def test_validator_uses_profile_counts(thuan_an_candidate, thuan_an_profile):
    result = validate_candidate(thuan_an_candidate, thuan_an_profile)
    assert result.ok, result.errors
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_release.py -q
```

Expected: import failure for `MapReleaseProfile`.

- [ ] **Step 3: Add profile-driven filenames, copy, counts, and manifest checks**

All release functions retain a default Thủ Dầu Một profile for backward
compatibility, but the generic builder always passes an explicit profile.
`HUONG-DAN.pdf` and `GIAY-PHEP.txt` use `profile.city_name`,
`profile.legacy_count`, `profile.current_count`, and derived-boundary notes.

- [ ] **Step 4: Add city source registries and neighborhood snapshots**

Each source registry contains repo snapshots for current/legacy/centers, a dated
Overpass bbox for roads/water/amenity/tourism/place, and the existing two Be
Vietnam Pro font URLs. Neighborhood files accept only named Point features with
source URL, confidence, and `boundary_claim: false`.

- [ ] **Step 5: Render and validate candidate releases**

Run:

```powershell
& $py -X utf8 scripts/build_city_map_product.py --city thuan-an --stage validate
& $py -X utf8 scripts/build_city_map_product.py --city di-an --stage validate
& $py -X utf8 scripts/build_city_map_product.py --city ben-cat --stage validate
```

Expected: each candidate reports zero validation errors.

- [ ] **Step 6: Visually inspect six previews and create manual approvals**

Render each before/after preview and inspect:

- Vietnamese labels;
- boundary/road legibility;
- adjacent colors;
- no major label collision;
- visible source/disclaimer;
- correct city/count.

Only after inspection, write each ignored
`artifacts/map-products/<city>/release-approval.json` with all five required
booleans true and a timezone-aware timestamp.

- [ ] **Step 7: Package the three releases**

Run:

```powershell
& $py -X utf8 scripts/build_city_map_product.py --city thuan-an --stage package
& $py -X utf8 scripts/build_city_map_product.py --city di-an --stage package
& $py -X utf8 scripts/build_city_map_product.py --city ben-cat --stage package
```

Expected ZIP names:

```text
radarbds-thuan-an-map-v1.0.zip
radarbds-di-an-map-v1.0.zip
radarbds-ben-cat-map-v1.0.zip
```

- [ ] **Step 8: Run release suites and verify GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_release.py tests/test_thu_dau_mot_map_release.py tests/test_city_map_renderers.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit code, registries, and public previews**

```powershell
git add map_products/release.py scripts/build_city_map_product.py config/map_products/*_sources.json config/map_products/*_neighborhoods.geojson static/images/seo/*-map-before.webp static/images/seo/*-map-after.webp tests/test_city_map_release.py tests/test_thu_dau_mot_map_release.py
git commit -m "Build paid city map packages"
```

Do not add `artifacts/`, candidate files, source caches, approvals, or ZIP files.

### Task 5: Register products and harden checkout/download for multiple products

**Files:**
- Modify: `services/digital_products.py`
- Modify: `routes/digital_products.py`
- Modify: `templates/thu_dau_mot_map_order.html`
- Modify: `static/js/thu_dau_mot_map_checkout.js`
- Modify: `tests/test_digital_product_checkout.py`
- Modify: `tests/test_digital_product_orders.py`
- Modify: `tests/test_thu_dau_mot_map_checkout_js.py`
- Create: `tests/test_city_map_checkout.py`

**Interfaces:**
- Produces: four entries in `get_digital_product(slug)`
- Produces: `checkout_city_map(city_slug: str)`
- Produces: `city_map_order_page(city_slug: str, public_id: str)`
- Produces: `product_for_order(order) -> DigitalProduct`

- [ ] **Step 1: Write failing cross-product abuse tests**

```python
def test_checkout_route_uses_server_side_city_product(client, order_repo):
    response = client.post("/ban-do-thuan-an/checkout")
    assert response.status_code == 201
    order = order_repo.latest()
    assert order.product_slug == "thuan-an-map-bundle"
    assert order.expected_amount == 99_000

def test_retry_cookie_cannot_cross_products(client):
    client.get("/ban-do-thuan-an")
    first = client.post("/ban-do-thuan-an/checkout")
    crossed = client.post("/ban-do-ben-cat/checkout")
    assert first.get_json()["public_id"] != crossed.get_json()["public_id"]

def test_download_uses_order_product_not_global_product(paid_di_an_order, client):
    response = client.get(
        f"/api/digital-products/orders/{paid_di_an_order.public_id}/download"
    )
    assert response.headers["Content-Disposition"].endswith(
        'filename=radarbds-di-an-map-v1.0.zip'
    )
```

- [ ] **Step 2: Run security tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_checkout.py -q
```

Expected: new routes return 404 and download still resolves the Thủ Dầu Một
constant.

- [ ] **Step 3: Add immutable product definitions using generated checksums**

For each generated ZIP and manifest, calculate SHA-256 from the actual bytes and
insert only the hashes and filenames into the registry. Never put package bytes
inside git.

- [ ] **Step 4: Generalize checkout/order route handling**

Map the allowlisted route to `page["product_slug"]`. Bind retry state to both
`public_id` and `product_slug`, scope cookies to `page["path"]`, and construct
complete/cancel/order URLs from the page path.

Unknown city slugs abort 404 before reading cookies, storage, or files.

- [ ] **Step 5: Resolve download product from immutable order**

Use:

```python
product = get_digital_product(order.product_slug)
if (
    order.product_version != product.version
    or order.expected_amount != product.price_vnd
    or order.currency != "VND"
):
    return _download_denied_response()
```

Catch unknown product slugs and return the generic denied response.

- [ ] **Step 6: Run checkout/order tests and verify GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_checkout.py tests/test_digital_product_checkout.py tests/test_digital_product_orders.py tests/test_thu_dau_mot_map_checkout_js.py -q
```

Expected: PASS.

- [ ] **Step 7: Scan staged changes for secrets**

Run:

```powershell
git diff --cached | Select-String -Pattern 'PAYOS_CLIENT_ID|PAYOS_API_KEY|PAYOS_CHECKSUM_KEY|recovery_token' -CaseSensitive:$false
```

Expected: no credential value and no raw recovery token fixture resembling a
real secret.

- [ ] **Step 8: Commit**

```powershell
git add services/digital_products.py routes/digital_products.py templates/thu_dau_mot_map_order.html static/js/thu_dau_mot_map_checkout.js tests/test_city_map_checkout.py tests/test_digital_product_checkout.py tests/test_digital_product_orders.py tests/test_thu_dau_mot_map_checkout_js.py
git commit -m "Support multi-product map checkout"
```

### Task 6: Render the three public pages, schemas, and GeoJSON routes

**Files:**
- Modify: `app.py`
- Modify: `templates/thu_dau_mot_map_product.html`
- Modify: `static/js/thu_dau_mot_map_product.js`
- Modify: `static/css/thu_dau_mot_map_product.css`
- Modify: `routes/digital_products.py`
- Create: `tests/test_city_map_product_pages.py`
- Modify: `tests/test_thu_dau_mot_map_product_page.py`
- Modify: `tests/test_public_seo.py`

**Interfaces:**
- Produces: `city_map_product_schema(page, product, availability, legacy_areas, current_areas) -> dict`
- Produces: `city_map_product_page(city_slug: str)`
- Produces: `city_map_geojson(city_slug: str, edition: str)`

- [ ] **Step 1: Write failing page/schema/GeoJSON tests**

```python
@pytest.mark.parametrize(
    ("path", "city", "legacy_count", "current_count"),
    [
        ("/ban-do-thuan-an", "Thuận An", 10, 5),
        ("/ban-do-di-an", "Dĩ An", 7, 3),
        ("/ban-do-ben-cat", "Bến Cát", 8, 6),
    ],
)
def test_city_page_has_unique_content_and_schema(
    client, path, city, legacy_count, current_count
):
    response = client.get(path)
    assert response.status_code == 200
    soup = BeautifulSoup(response.get_data(as_text=True), "html.parser")
    assert soup.h1.get_text(" ", strip=True).startswith(f"Bản đồ TP {city}")
    graph = json.loads(soup.select_one('script[type="application/ld+json"]').string)["@graph"]
    item_lists = [item for item in graph if item.get("@type") == "ItemList"]
    assert [item["numberOfItems"] for item in item_lists] == [
        legacy_count, current_count
    ]
```

Also assert no page other than Thủ Dầu Một contains `Hòa Phú`, `Phú Tân`, or a
Thủ Dầu Một checkout action.

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_product_pages.py -q
```

Expected: all three page routes return 404.

- [ ] **Step 3: Generalize Flask view-model and schema**

Replace `_thu_dau_mot_map_product_schema` with a data-driven function. Dataset
IDs include literal counts and city slug; FAQ schema includes only visible FAQ.
Set `Offer.availability` independently from the current product package.

- [ ] **Step 4: Generalize Jinja copy/actions without hiding city-specific facts**

Use registry fields for:

- proof bullets;
- preview alt/caption;
- map/directory headings;
- search examples;
- derived boundary warning;
- package content;
- purchase form action;
- dashboard copy;
- machine-readable GeoJSON links.

Keep TDM CSS class names if renaming them would add no consumer value, but remove
all hard-coded visible TDM text and route values.

- [ ] **Step 5: Add six allowlisted GeoJSON routes**

Serve with:

```text
Content-Type: application/geo+json; charset=utf-8
Cache-Control: public, max-age=86400
```

Reject unknown edition/city with 404.

- [ ] **Step 6: Run page/SEO tests and verify GREEN**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_product_pages.py tests/test_thu_dau_mot_map_product_page.py tests/test_public_seo.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add app.py routes/digital_products.py templates/thu_dau_mot_map_product.html static/js/thu_dau_mot_map_product.js static/css/thu_dau_mot_map_product.css tests/test_city_map_product_pages.py tests/test_thu_dau_mot_map_product_page.py tests/test_public_seo.py
git commit -m "Add paid city map product pages"
```

### Task 7: Add discovery surfaces, tracking allowlists, and browser behavior

**Files:**
- Modify: `app.py`
- Modify: `templates/binh_duong_map.html`
- Modify: `templates/planning_hub.html`
- Modify: `templates/partials/seo_footer.html`
- Modify: `static/js/thu_dau_mot_map_product.js`
- Modify: `tests/test_binh_duong_map_page.py`
- Modify: `tests/test_planning_pages.py`
- Modify: `tests/test_city_map_product_pages.py`
- Modify: `tests/test_public_seo.py`

**Interfaces:**
- Consumes: `CITY_MAP_PRODUCTS`
- Produces: sitemap, `llms.txt`, footer, hub, and sibling links for all four map products
- Produces: safe analytics contexts for every city product event

- [ ] **Step 1: Write failing discovery/tracking tests**

```python
def test_all_city_maps_are_discoverable(client):
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    llms = client.get("/llms.txt").get_data(as_text=True)
    for path in (
        "/ban-do-thu-dau-mot",
        "/ban-do-thuan-an",
        "/ban-do-di-an",
        "/ban-do-ben-cat",
    ):
        assert path in sitemap
        assert path in llms

def test_tracking_context_accepts_only_registered_map_products():
    safe = sanitize_public_tracking_context({
        "path": "/ban-do-di-an",
        "page_slug": "ban-do-di-an",
        "product_slug": "di-an-map-bundle",
    })
    assert safe == {
        "path": "/ban-do-di-an",
        "page_slug": "ban-do-di-an",
        "product_slug": "di-an-map-bundle",
    }
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_city_map_product_pages.py tests/test_binh_duong_map_page.py tests/test_planning_pages.py tests/test_public_seo.py -q
```

Expected: new paths missing from discovery surfaces and tracking context.

- [ ] **Step 3: Add registry-driven links and tracking allowlists**

Render all four products from the registry. Tracking accepts only exact known
path/page/product triples and continues to drop raw order identifiers, tokens,
query text, or PayOS values.

- [ ] **Step 4: Run JavaScript tests for map/search/hash and syntax**

Run:

```powershell
node --check static/js/thu_dau_mot_map_product.js
node --check static/js/thu_dau_mot_map_checkout.js
& $py -X utf8 -m pytest tests/test_city_map_product_pages.py tests/test_thu_dau_mot_map_checkout_js.py -q
```

Expected: PASS.

- [ ] **Step 5: Run browser QA at four widths**

For each of the three new pages at 375, 768, 1024, and 1440px:

- assert document width equals viewport width;
- use legacy/current buttons and confirm status/count;
- switch street/satellite;
- search with accented and unaccented unit names;
- open fullscreen and exit with Escape;
- select a directory item and verify URL hash/back/forward;
- confirm all actionable targets are at least 44px;
- confirm no console errors.

- [ ] **Step 6: Commit**

```powershell
git add app.py templates/binh_duong_map.html templates/planning_hub.html templates/partials/seo_footer.html static/js/thu_dau_mot_map_product.js tests/test_binh_duong_map_page.py tests/test_planning_pages.py tests/test_city_map_product_pages.py tests/test_public_seo.py
git commit -m "Expose city map products to search"
```

### Task 8: Install local protected packages and run the release gate

**Files:**
- Modify only if tests expose a defect: files already listed in Tasks 1-7
- Do not commit: `.env`, `artifacts/`, protected storage ZIP/manifest files

**Interfaces:**
- Consumes: generated ZIPs, manifests, `.env` storage root
- Produces: local `can_sell=True` for all four products when sales are enabled

- [ ] **Step 1: Copy each package and manifest to the configured protected root**

Resolve `DIGITAL_PRODUCT_STORAGE_DIR` without printing it. Copy into:

```text
<storage>/thuan-an-map-bundle/1.0/
<storage>/di-an-map-bundle/1.0/
<storage>/ben-cat-map-bundle/1.0/
```

Use explicit `Copy-Item -LiteralPath`; do not delete or overwrite unrelated
products.

- [ ] **Step 2: Verify package availability with real local files**

Run a Python check that prints only product slug, boolean availability, byte
size, and SHA-256 match. Do not print `.env` values.

Expected: all three new products report `package_valid=True`; `can_sell` mirrors
the existing sales-enabled flag.

- [ ] **Step 3: Run syntax and targeted suites**

Run:

```powershell
& $py -X utf8 -m py_compile app.py routes/digital_products.py services/digital_products.py map_products/models.py map_products/geometry.py map_products/scene.py map_products/renderers.py map_products/release.py scripts/build_city_map_boundaries.py scripts/build_city_map_product.py
node --check static/js/binh_duong_map.js
node --check static/js/thu_dau_mot_map_product.js
node --check static/js/thu_dau_mot_map_checkout.js
& $py -X utf8 -m pytest tests/test_city_map_product_registry.py tests/test_city_map_boundaries.py tests/test_city_map_renderers.py tests/test_city_map_release.py tests/test_city_map_checkout.py tests/test_city_map_product_pages.py tests/test_thu_dau_mot_map_product_page.py tests/test_digital_product_checkout.py tests/test_digital_product_orders.py tests/test_thu_dau_mot_map_checkout_js.py tests/test_public_seo.py -q
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 4: Run the broader public/product suite**

Run:

```powershell
& $py -X utf8 -m pytest tests/test_binh_duong_map_page.py tests/test_planning_pages.py tests/test_public_content_hubs.py tests/test_public_seo.py tests/test_payos_client.py tests/test_digital_product_reconciliation.py -q
```

Expected: PASS.

- [ ] **Step 5: Perform a final secret and untracked artifact audit**

Run:

```powershell
git status --short
git diff --cached | Select-String -Pattern '65fec45e|f5c55030|fb23486f|PAYOS_.*=' -CaseSensitive:$false
git ls-files .env artifacts
```

Expected: no secret values; no `.env`, artifacts, approval, or protected ZIP
tracked.

- [ ] **Step 6: Commit only if verification required a repair**

Stage explicit repaired source/test paths and commit:

```powershell
git commit -m "Verify city map product release"
```

Do not commit an empty verification-only commit.
