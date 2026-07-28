# Thu Dau Mot Map Product Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, validate, and present a versioned paid-map bundle containing print-ready PDF, editable SVG, and KML maps with 14 sourced legacy reference centers plus the five post-2025 Thu Dau Mot boundaries, without enabling checkout yet.

**Architecture:** A build-only `map_products` package fetches licensed snapshots, normalizes WGS84 data, constructs one projected scene graph, and renders SVG/PDF/KML plus watermarked web previews. A release validator is the only component allowed to package a ZIP. The Flask product page reads a small immutable product registry and never exposes paid source files.

**Tech Stack:** Python 3.12, Requests, Shapely 2.1.2, PyProj 3.7.2, ReportLab 5.0.0, FontTools 4.63.0, Pillow, Playwright, Flask/Jinja, pytest.

## Global Constraints

- Preserve `/ban-do-binh-duong` as a free public lookup page.
- The new canonical product URL is `/ban-do-thu-dau-mot`.
- The bundle price metadata is exactly `99000` VND.
- The old edition must contain exactly 14 sourced Point reference centers, with `boundary_claim: false`: Chánh Mỹ, Chánh Nghĩa, Định Hòa, Hiệp An, Hiệp Thành, Hòa Phú, Phú Cường, Phú Hòa, Phú Lợi, Phú Mỹ, Phú Tân, Phú Thọ, Tân An, Tương Bình Hiệp.
- The post-2025 edition must contain exactly 5 Polygon/MultiPolygon wards in the Thu Dau Mot group: Thủ Dầu Một, Phú Lợi, Chánh Hiệp, Bình Dương, Phú An.
- Neighborhoods are Point features with source/confidence metadata; never create neighborhood polygons.
- Paid PDF/SVG/KML/ZIP files must never live under `static/`.
- Paid PDF and SVG contain no raster `<image>` layer or satellite imagery.
- PDF is the print master; SVG is the editable master; KML is geographic data, not print layout.
- All OSM-derived output includes `© OpenStreetMap contributors` and `https://www.openstreetmap.org/copyright`.
- Build outputs go under ignored `artifacts/map-products/`; only source registry, curated point data, tests, code, and watermarked WebP previews are committed.
- Never fetch, infer, draw, validate, or claim legacy ward polygons. Product
  copy, legends, metadata, guide, and tests must say the 14 legacy locations
  are reference center points and do not represent old ward boundaries.
- The checkout CTA remains disabled until the PayOS plan is complete and `DIGITAL_PRODUCT_SALES_ENABLED=1`.

---

## Planned File Structure

```text
requirements-map.txt
config/
  map_products/
    thu_dau_mot_product.json
    thu_dau_mot_sources.json
    thu_dau_mot_legacy_ward_centers.geojson
    thu_dau_mot_neighborhoods.geojson
  thu_dau_mot_map_product.py
map_products/
  __init__.py
  models.py
  sources.py
  geometry.py
  scene.py
  renderers.py
  release.py
scripts/
  build_thu_dau_mot_map_product.py
services/
  digital_products.py
routes/
  digital_products.py
templates/
  thu_dau_mot_map_product.html
static/
  css/thu_dau_mot_map_product.css
  js/thu_dau_mot_map_product.js
  images/seo/thu-dau-mot-map-before.webp
  images/seo/thu-dau-mot-map-after.webp
tests/
  test_thu_dau_mot_map_sources.py
  test_thu_dau_mot_map_renderers.py
  test_thu_dau_mot_map_release.py
  test_thu_dau_mot_map_product_page.py
```

The `map_products` package is build-time only. Flask runtime imports only
`config.thu_dau_mot_map_product` and `services.digital_products`.

---

### Task 1: Lock Product Metadata, Units, Sources, and Font License

**Files:**
- Create: `requirements-map.txt`
- Create: `config/map_products/thu_dau_mot_product.json`
- Create: `config/map_products/thu_dau_mot_sources.json`
- Create: `config/map_products/thu_dau_mot_legacy_ward_centers.geojson`
- Create: `config/map_products/thu_dau_mot_neighborhoods.geojson`
- Create: `map_products/__init__.py`
- Create: `map_products/models.py`
- Test: `tests/test_thu_dau_mot_map_sources.py`

**Interfaces:**
- Produces: `load_product_spec(path: Path) -> MapProductSpec`
- Produces: `load_source_registry(path: Path) -> tuple[MapSource, ...]`
- Produces: `load_neighborhood_points(path: Path) -> tuple[MapPoint, ...]`
- `MapProductSpec` fields: `slug`, `version`, `price_vnd`, `legacy_wards`, `current_wards`, `formats`, `font_family`.

- [ ] **Step 1: Add pinned build-only dependencies**

```text
shapely==2.1.2
pyproj==3.7.2
reportlab==5.0.0
fonttools==4.63.0
```

Do not add these four packages to `requirements.txt`; production serves already
built files and does not render maps.

- [ ] **Step 2: Write failing registry tests**

```python
from pathlib import Path

from map_products.models import (
    load_neighborhood_points,
    load_product_spec,
    load_source_registry,
)

ROOT = Path(__file__).resolve().parents[1]


def test_thu_dau_mot_product_has_exact_units_and_price():
    spec = load_product_spec(
        ROOT / "config/map_products/thu_dau_mot_product.json"
    )
    assert spec.price_vnd == 99_000
    assert spec.formats == ("pdf", "svg", "kml")
    assert set(spec.legacy_wards) == {
        "Chánh Mỹ", "Chánh Nghĩa", "Định Hòa", "Hiệp An", "Hiệp Thành",
        "Hòa Phú", "Phú Cường", "Phú Hòa", "Phú Lợi", "Phú Mỹ",
        "Phú Tân", "Phú Thọ", "Tân An", "Tương Bình Hiệp",
    }
    assert set(spec.current_wards) == {
        "Thủ Dầu Một", "Phú Lợi", "Chánh Hiệp", "Bình Dương", "Phú An",
    }


def test_every_source_has_license_and_snapshot_contract():
    sources = load_source_registry(
        ROOT / "config/map_products/thu_dau_mot_sources.json"
    )
    assert {"legacy_ward_centers", "current_boundaries", "osm_detail", "font"} <= {
        source.key for source in sources
    }
    assert "legacy_boundaries" not in {source.key for source in sources}
    assert all(source.license_name and source.license_url for source in sources)
    assert all(source.snapshot_strategy in {"fixed_url", "dated_query", "repo_snapshot"} for source in sources)


def test_neighborhoods_are_named_points_not_claimed_boundaries():
    points = load_neighborhood_points(
        ROOT / "config/map_products/thu_dau_mot_neighborhoods.geojson"
    )
    assert points
    assert all(point.geometry_type == "Point" for point in points)
    assert all(point.name and point.source and point.confidence in {"high", "medium"} for point in points)


def test_legacy_centers_are_exact_sourced_points_not_boundaries(product_spec):
    points = load_neighborhood_points(
        ROOT / "config/map_products/thu_dau_mot_legacy_ward_centers.geojson"
    )
    assert len(points) == 14
    assert {point.name for point in points} == set(product_spec.legacy_wards)
    assert all(point.geometry_type == "Point" for point in points)
```

- [ ] **Step 3: Run tests and confirm RED**

Run:

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$env:PYTHONPATH = @((Resolve-Path '.').Path, (Resolve-Path '.venv312\Lib\site-packages').Path) -join [IO.Path]::PathSeparator
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_sources.py -q
```

Expected: import/file failures because the package and registries do not exist.

- [ ] **Step 4: Implement immutable dataclasses and strict loaders**

```python
@dataclass(frozen=True)
class MapSource:
    key: str
    source_url: str
    license_name: str
    license_url: str
    snapshot_strategy: str
    snapshot_at: str


@dataclass(frozen=True)
class MapProductSpec:
    slug: str
    version: str
    price_vnd: int
    legacy_wards: tuple[str, ...]
    current_wards: tuple[str, ...]
    formats: tuple[str, ...]
    font_family: str


@dataclass(frozen=True)
class MapPoint:
    name: str
    lon: float
    lat: float
    source: str
    confidence: str
    geometry_type: str = "Point"
    source_url: str = ""
    boundary_claim: bool = False
```

Load JSON with UTF-8, reject unknown/missing required keys, duplicate unit names,
invalid coordinates, polygon neighborhood geometry, or non-positive prices.

Use Poppins Regular/SemiBold from the Google Fonts OFL directory. Record the
OFL URL and exact upstream raw font URLs in `thu_dau_mot_sources.json`; the
fetcher will record downloaded SHA-256 values in the build manifest.

- [ ] **Step 5: Populate curated source and neighborhood registries**

The source registry must include:

- the existing Radar BDS 36-unit repo snapshot for current boundaries;
- the committed CC0 curated snapshot containing exactly 14 legacy ward
  reference-center Points and no legacy boundary geometry;
- an OSM dated query contract for streets/hydro/POI;
- Google Fonts Poppins Regular/SemiBold plus OFL license.

The legacy-center and neighborhood GeoJSON files must include only verified
named locations. Every feature properties object has exactly five keys:
`name`, `source`, `source_url`, `confidence`, and `boundary_claim`. The first
three values are non-empty strings copied from the reviewed source record;
`confidence` is one of `high` or `medium`; `boundary_claim` is always the JSON
boolean `false`.

If the exact 14 legacy center points or neighborhood source cannot be verified,
stop and report the exact missing point; do not weaken the tests or substitute
legacy polygons.

- [ ] **Step 6: Run tests and commit**

Run the Task 1 pytest command, then:

```powershell
git add requirements-map.txt config/map_products map_products/__init__.py map_products/models.py tests/test_thu_dau_mot_map_sources.py
git commit -m "feat: define Thu Dau Mot map product sources"
```

---

### Task 2: Fetch and Normalize Licensed GIS Snapshots

**Files:**
- Modify: `config/map_products/thu_dau_mot_sources.json`
- Create: `config/map_products/thu_dau_mot_legacy_ward_centers.geojson`
- Modify: `map_products/models.py`
- Create: `map_products/sources.py`
- Create: `map_products/geometry.py`
- Create: `scripts/build_thu_dau_mot_map_product.py`
- Modify: `tests/test_thu_dau_mot_map_sources.py`

**Interfaces:**
- Consumes: `MapProductSpec`, `MapSource`, `MapPoint`
- Produces: `fetch_source_snapshots(registry, cache_dir, refresh=False) -> dict[str, Path]`
- Produces: `build_normalized_layers(spec, snapshots, neighborhoods) -> NormalizedMapLayers`
- `NormalizedMapLayers` contains WGS84 GeoJSON-like tuples for five current
  boundaries, 14 legacy reference-center Points, streets, hydro, POI, and
  neighborhood points.

- [ ] **Step 1: Add failing normalization tests with in-memory fixtures**

```python
def test_normalizer_requires_exact_legacy_points_and_current_boundaries(product_spec, source_payloads):
    layers = build_normalized_layers(
        product_spec,
        source_payloads,
        neighborhood_points=sample_neighborhoods(),
    )
    assert {point.name for point in layers.legacy_ward_centers} == set(product_spec.legacy_wards)
    assert {f.name for f in layers.current_boundaries} == set(product_spec.current_wards)
    assert not hasattr(layers, "legacy_boundaries")


def test_osm_details_are_clipped_and_classified(product_spec, source_payloads):
    layers = build_normalized_layers(
        product_spec,
        source_payloads,
        neighborhood_points=sample_neighborhoods(),
    )
    assert {road.road_class for road in layers.streets} <= {
        "trunk", "primary", "secondary", "tertiary", "local",
    }
    assert all(product_spec.bounds.contains(feature.geometry) for feature in layers.streets)
    assert all(feature.name for feature in layers.poi)


def test_invalid_or_polygon_neighborhood_is_rejected(product_spec, source_payloads):
    bad = MapPoint(
        name="Khu phố giả",
        lon=106.7,
        lat=11.0,
        source="test",
        confidence="high",
        geometry_type="Polygon",
    )
    with pytest.raises(ValueError, match="Point"):
        build_normalized_layers(product_spec, source_payloads, (bad,))
```

Generate minimal square polygons in test helpers rather than committing a large
copied fixture.

- [ ] **Step 2: Run focused tests and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_sources.py -q
```

Expected: missing `sources`/`geometry` modules and functions.

- [ ] **Step 3: Implement snapshot fetching with cache-first behavior**

```python
def fetch_source_snapshots(
    registry: tuple[MapSource, ...],
    cache_dir: Path,
    *,
    refresh: bool = False,
    http_get: Callable[[str], bytes] = _http_get,
) -> dict[str, Path]:
    """Fetch only when refresh=True or cache is absent; write via temp + replace."""
```

Requirements:

- send the Radar BDS User-Agent;
- 60-second timeout;
- never replace a valid cache after HTTP/JSON failure;
- write `source-snapshots.json` containing URL, fetched timestamp, byte length,
  SHA-256, license, and query timestamp;
- issue the OSM detailed query at a recorded timestamp;
- current five wards come from
  `static/maps/binh-duong/current-36-wards.geojson`;
- the curated legacy snapshot must resolve to exactly 14 named Point features
  with source URL/label, confidence, and `boundary_claim: false`;
- there is no historical legacy-boundary runtime source or fetch;
- Overpass/Nominatim failure aborts the build without touching a release.

- [ ] **Step 4: Implement WGS84 normalization and clipping**

```python
@dataclass(frozen=True)
class NormalizedMapLayers:
    current_boundaries: tuple[NamedGeometry, ...]
    legacy_ward_centers: tuple[MapPoint, ...]
    streets: tuple[StreetGeometry, ...]
    hydro: tuple[NamedGeometry, ...]
    poi: tuple[MapPoint, ...]
    neighborhoods: tuple[MapPoint, ...]
    source_manifest: dict[str, dict]
```

Use Shapely to repair only safe current-boundary ring issues with `make_valid`,
reject empty geometry, clip details to the union of the five current
boundaries, deduplicate POI by normalized name plus 25-meter proximity, and
preserve original WGS84 coordinates for KML.

- [ ] **Step 5: Add the build CLI**

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-sources", action="store_true")
    parser.add_argument("--work-dir", type=Path, default=Path("artifacts/map-products/thu-dau-mot"))
    parser.add_argument("--stage", choices=("sources", "render", "validate", "package", "all"), default="all")
    args = parser.parse_args(argv)
    ...
```

`--stage sources` writes normalized GeoJSON and a source manifest only. It must
print counts and paths, never secrets or full third-party payloads.

- [ ] **Step 6: Verify deterministic normalization and commit**

Run the focused tests twice and compare normalized file SHA-256 values when
`--refresh-sources` is absent.

```powershell
git add config/map_products/thu_dau_mot_sources.json config/map_products/thu_dau_mot_legacy_ward_centers.geojson map_products/models.py map_products/sources.py map_products/geometry.py scripts/build_thu_dau_mot_map_product.py tests/test_thu_dau_mot_map_sources.py
git commit -m "feat: normalize Thu Dau Mot map data"
```

---

### Task 3: Build a Shared Scene Graph and Render SVG, PDF, and KML

**Files:**
- Create: `map_products/scene.py`
- Create: `map_products/renderers.py`
- Create: `tests/test_thu_dau_mot_map_renderers.py`
- Modify: `scripts/build_thu_dau_mot_map_product.py`

**Interfaces:**
- Consumes: `NormalizedMapLayers`
- Produces: `build_scene(layers, edition: Literal["legacy", "current"]) -> MapScene`
- Produces: `render_svg(scene, path, fonts) -> Path`
- Produces: `render_pdf(scene, path, fonts) -> Path`
- Produces: `render_kml(layers, edition, path) -> Path`

- [ ] **Step 1: Write failing renderer contract tests**

```python
def test_svg_is_vector_layered_and_text_editable(tmp_path, sample_scene):
    output = render_svg(sample_scene, tmp_path / "map.svg", test_fonts())
    root = ElementTree.parse(output).getroot()
    assert not root.findall(".//{http://www.w3.org/2000/svg}image")
    assert root.findall(".//{http://www.w3.org/2000/svg}text")
    layer_ids = {node.attrib["id"] for node in root.findall(".//{http://www.w3.org/2000/svg}g") if "id" in node.attrib}
    assert {"boundaries", "legacy-reference-centers", "streets", "hydro", "poi", "neighborhoods", "labels"} <= layer_ids


def test_pdf_is_landscape_a0_vector_with_embedded_font(tmp_path, sample_scene):
    output = render_pdf(sample_scene, tmp_path / "map.pdf", test_fonts())
    with pdfplumber.open(output) as pdf:
        assert len(pdf.pages) == 1
        assert pdf.pages[0].images == []
        assert sorted(round(value) for value in pdf.pages[0].mediabox[2:]) == [2384, 3370]
    raw = output.read_bytes()
    assert b"/FontFile2" in raw


def test_kml_contains_geographic_layers_not_print_artifacts(tmp_path, sample_layers):
    output = render_kml(sample_layers, "legacy", tmp_path / "map.kml")
    root = ElementTree.parse(output).getroot()
    assert root.findall(".//{http://www.opengis.net/kml/2.2}Placemark")
    assert len(root.findall(".//{http://www.opengis.net/kml/2.2}Point")) == 14
    assert not root.findall(".//{http://www.opengis.net/kml/2.2}Polygon")
    assert b"watermark" not in output.read_bytes().lower()
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_renderers.py -q
```

- [ ] **Step 3: Implement the projected scene graph**

```python
@dataclass(frozen=True)
class MapScene:
    edition: str
    page_width_pt: float
    page_height_pt: float
    bounds_m: tuple[float, float, float, float]
    layers: tuple[SceneLayer, ...]
    labels: tuple[SceneLabel, ...]
    attribution: str
```

Project WGS84 to EPSG:32648 with `always_xy=True`. Use one scene for both SVG
and PDF so geometry, colors, label anchors, scale bar, and legend cannot drift.
The legacy and current scenes share roads/hydro/POI clipped to the current-five
union. The current scene has five ward fills/labels. The legacy scene has no
ward fills: it renders 14 Point symbols/labels plus a prominent note that they
are reference centers, not old administrative boundaries.

- [ ] **Step 4: Implement deterministic label and style rules**

Priority order:

1. current ward labels or legacy reference-center labels;
2. major roads;
3. rivers/canals;
4. neighborhood labels;
5. POI.

Reject a candidate label when its measured box overlaps a higher-priority label.
Use Poppins SemiBold for ward labels and Poppins Regular elsewhere. Store style
constants in `scene.py`; do not hard-code colors separately in renderers.

- [ ] **Step 5: Implement three renderers**

- SVG: `xml.etree.ElementTree`, named `<g>` layers, editable `<text>`, no
  embedded raster.
- PDF: ReportLab canvas, registered Poppins TTF, landscape A0, vector paths,
  text, legend, scale bar, attribution.
- KML: WGS84 placemarks/folders for five current administrative boundaries or
  14 legacy reference Points, plus roads, hydro, POI, and neighborhoods;
  include source/edition and `boundary_claim=false` in legacy ExtendedData.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_sources.py tests\test_thu_dau_mot_map_renderers.py -q
& $py -X utf8 -m py_compile map_products\*.py scripts\build_thu_dau_mot_map_product.py
git diff --check
```

Commit:

```powershell
git add map_products/scene.py map_products/renderers.py scripts/build_thu_dau_mot_map_product.py tests/test_thu_dau_mot_map_renderers.py
git commit -m "feat: render Thu Dau Mot vector maps"
```

---

### Task 4: Validate, Preview, Approve, and Package Release v1.0

**Files:**
- Create: `map_products/release.py`
- Create: `tests/test_thu_dau_mot_map_release.py`
- Modify: `scripts/build_thu_dau_mot_map_product.py`
- Create: `static/images/seo/thu-dau-mot-map-before.webp`
- Create: `static/images/seo/thu-dau-mot-map-after.webp`

**Interfaces:**
- Consumes: rendered candidate directory and source manifest
- Produces: `validate_candidate(candidate_dir: Path) -> ReleaseValidation`
- Produces: `package_release(candidate_dir, approval_path, output_zip) -> Path`
- Produces: two watermarked WebP previews committed under `static/images/seo/`.

- [ ] **Step 1: Write failing release-gate tests**

```python
def test_release_requires_all_files_and_manual_approval(candidate_dir):
    validation = validate_candidate(candidate_dir)
    assert validation.ok
    with pytest.raises(ReleaseBlocked, match="approval"):
        package_release(candidate_dir, candidate_dir / "missing-approval.json", candidate_dir / "bundle.zip")


def test_manifest_hashes_every_distributed_file(candidate_dir, approval_file):
    bundle = package_release(candidate_dir, approval_file, candidate_dir / "bundle.zip")
    with ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("MANIFEST.json"))
        names = set(archive.namelist()) - {"MANIFEST.json"}
        assert names == set(manifest["files"])
        for name, metadata in manifest["files"].items():
            assert sha256(archive.read(name)).hexdigest() == metadata["sha256"]


def test_candidate_with_raster_svg_or_unlicensed_font_is_rejected(candidate_dir):
    (candidate_dir / "thu-dau-mot-truoc-2025.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="x.png"/></svg>',
        encoding="utf-8",
    )
    assert not validate_candidate(candidate_dir).ok
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_release.py -q
```

- [ ] **Step 3: Implement strict candidate validation**

Validate:

- exact six map files, two font files, `OFL.txt`, `HUONG-DAN.pdf`,
  `GIAY-PHEP.txt`;
- exactly 14 legacy Point placemarks with no legacy Polygon and exactly 5
  current Polygon/MultiPolygon boundaries in distributed KML;
- no SVG `<image>`;
- no PDF images;
- `/FontFile2` exists in each PDF;
- Vietnamese glyph coverage in both font files using FontTools;
- source/license/attribution strings;
- checksum and byte length for every file;
- approval JSON includes all boolean checks and a non-empty reviewer/timestamp.

- [ ] **Step 4: Generate watermarked previews without publishing source**

Create a preview-only copy of each SVG with repeated
`RADAR BDS • BẢN XEM TRƯỚC` text. Use the bundled Playwright Chromium to
screenshot each preview-only SVG to PNG, then Pillow converts it to WebP. Delete
preview SVG/PNG intermediates after the WebP passes a size/dimension check.

- [ ] **Step 5: Inspect candidate visually and create approval**

Render both PDFs to images using the PDF skill/Poppler during execution and
inspect at full page plus two detail crops. Then write
`artifacts/map-products/thu-dau-mot/release-approval.json`:

```json
{
  "reviewer": "Radar BDS release review",
  "reviewed_at": "ISO-8601 timestamp",
  "legacy_reference_points_checked": true,
  "current_labels_checked": true,
  "a0_layout_checked": true,
  "vietnamese_text_checked": true,
  "sources_and_license_checked": true
}
```

The file is runtime evidence and remains ignored.

- [ ] **Step 6: Package and verify ZIP**

Run:

```powershell
& $py -X utf8 scripts\build_thu_dau_mot_map_product.py --stage all
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_release.py -q
```

Expected output:

`artifacts/map-products/thu-dau-mot/releases/radarbds-thu-dau-mot-map-v1.0.zip`

- [ ] **Step 7: Commit code and only watermarked previews**

```powershell
git add map_products/release.py scripts/build_thu_dau_mot_map_product.py tests/test_thu_dau_mot_map_release.py static/images/seo/thu-dau-mot-map-before.webp static/images/seo/thu-dau-mot-map-after.webp
git commit -m "feat: validate Thu Dau Mot map bundle"
```

Confirm `git status --short` does not show PDF/SVG/KML/ZIP/font binaries.

---

### Task 5: Add the SEO Product Page with Checkout Disabled

**Files:**
- Create: `config/thu_dau_mot_map_product.py`
- Create: `services/digital_products.py`
- Create: `routes/digital_products.py`
- Modify: `routes/__init__.py`
- Modify: `app.py:1329-1360`
- Modify: `app.py:1408-1475`
- Modify: `app.py:2852-2960`
- Create: `templates/thu_dau_mot_map_product.html`
- Create: `static/css/thu_dau_mot_map_product.css`
- Create: `static/js/thu_dau_mot_map_product.js`
- Modify: `templates/binh_duong_map.html`
- Modify: `templates/planning_hub.html`
- Modify: `templates/partials/seo_footer.html`
- Test: `tests/test_thu_dau_mot_map_product_page.py`

**Interfaces:**
- Produces: `get_digital_product(slug: str) -> DigitalProduct`
- Produces: `get_release_availability(product, storage_root, sales_enabled) -> ProductAvailability`
- Produces route: `GET /ban-do-thu-dau-mot`
- PayOS plan consumes `DigitalProduct.slug`, `.version`, `.price_vnd`,
  `.package_filename`, and `ProductAvailability.can_sell`.

- [ ] **Step 1: Write failing page, schema, and exposure tests**

```python
def test_product_page_is_indexable_but_checkout_is_disabled_without_sales_flag(client):
    response = client.get("/ban-do-thu-dau-mot")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert '<link rel="canonical" href="https://radarbds.vn/ban-do-thu-dau-mot">' in html
    assert "99.000" in html
    assert "Sắp mở bán" in html
    assert 'action="/ban-do-thu-dau-mot/checkout"' not in html
    assert "/static/images/seo/thu-dau-mot-map-before.webp" in html
    assert ".svg" not in html and ".kml" not in html and ".zip" not in html


def test_product_schema_is_not_in_stock_until_valid_package_and_sales_enabled(client):
    graph = extract_schema(client.get("/ban-do-thu-dau-mot"))
    product = next(node for node in graph if node["@type"] == "Product")
    assert product["offers"]["price"] == "99000"
    assert product["offers"]["priceCurrency"] == "VND"
    assert product["offers"]["availability"].endswith("/OutOfStock")


def test_product_discovery_surfaces_include_one_canonical_url(client):
    sitemap = client.get("/sitemap.xml").get_data(as_text=True)
    llms = client.get("/llms.txt").get_data(as_text=True)
    assert sitemap.count("<loc>https://radarbds.vn/ban-do-thu-dau-mot</loc>") == 1
    assert llms.count("https://radarbds.vn/ban-do-thu-dau-mot") == 1
```

- [ ] **Step 2: Run tests and confirm RED**

Run:

```powershell
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_product_page.py -q
```

- [ ] **Step 3: Implement immutable runtime product registry**

```python
@dataclass(frozen=True)
class DigitalProduct:
    slug: str
    version: str
    price_vnd: int
    package_filename: str
    download_filename: str


@dataclass(frozen=True)
class ProductAvailability:
    package_valid: bool
    sales_enabled: bool
    can_sell: bool
    reason: str
```

`get_release_availability` reads only the package manifest and ZIP checksum from
the protected storage path. It never scans or serves `artifacts/`.

- [ ] **Step 4: Implement product route and template**

Use a dedicated blueprint registered in `routes/__init__.py`. The page may
delegate shared `_site_meta`, `_page_breadcrumbs`, and schema construction to
small functions in `app.py`, matching current public-route conventions.

The template includes:

- price and disabled `Sắp mở bán` CTA;
- two watermarked previews with an accessible before/after switch;
- exact bundle contents;
- explicit copy that the legacy edition contains 14 sourced reference center
  points, not old ward boundaries, while the current edition contains five
  verified ward polygons;
- vector/font/print claims phrased according to the design spec;
- license, sources, date, FAQ;
- secondary `/?tab=signals&city=Th%E1%BB%A7%20D%E1%BA%A7u%20M%E1%BB%99t` CTA;
- shared header/footer/tracking.

- [ ] **Step 5: Add JS behavior and tracking**

```javascript
export function setEdition(root, edition) {
  const normalized = edition === "current" ? "current" : "legacy";
  root.querySelectorAll("[data-product-edition]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.productEdition === normalized));
  });
  root.querySelectorAll("[data-product-preview]").forEach((preview) => {
    preview.hidden = preview.dataset.productPreview !== normalized;
  });
}
```

Add allowlisted actions:

- `thu_dau_mot_map_product_viewed`
- `thu_dau_mot_map_preview_selected`
- `thu_dau_mot_map_purchase_clicked`
- `thu_dau_mot_map_dashboard_clicked`

Do not include filename, package path, order data, or token in tracking context.

- [ ] **Step 6: Add SEO/discovery links and tests**

Add the page once to sitemap and `llms.txt`, and add contextual links from
`/ban-do-binh-duong`, `/quy-hoach-binh-duong`, and the SEO footer. Product schema
uses `OutOfStock` until the PayOS plan enables sales.

- [ ] **Step 7: Verify responsive page and commit**

Run:

```powershell
node --check static\js\thu_dau_mot_map_product.js
& $py -X utf8 -m py_compile app.py config\thu_dau_mot_map_product.py services\digital_products.py routes\digital_products.py
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_product_page.py tests\test_binh_duong_map_page.py tests\test_planning_pages.py tests\test_public_seo.py -q
git diff --check
```

Browser QA at 375, 768, 1024, and 1440 px. Confirm no paid source URL appears
in HTML/network, no overflow, controls are at least 44 px, keyboard toggling
works, and there are no console errors.

Commit:

```powershell
git add config/thu_dau_mot_map_product.py services/digital_products.py routes/digital_products.py routes/__init__.py app.py templates/thu_dau_mot_map_product.html static/css/thu_dau_mot_map_product.css static/js/thu_dau_mot_map_product.js templates/binh_duong_map.html templates/planning_hub.html templates/partials/seo_footer.html tests/test_thu_dau_mot_map_product_page.py
git commit -m "feat: add Thu Dau Mot map product page"
```

---

### Task 6: Final Asset-Plan Verification Gate

**Files:**
- Modify only if verification reveals an asset-plan defect.

**Interfaces:**
- Produces the exact inputs required by the PayOS plan:
  - a validated ZIP v1.0;
  - a matching `MANIFEST.json`;
  - a runtime `DigitalProduct`;
  - a product page whose checkout is still disabled.

- [ ] **Step 1: Run the complete asset test set**

```powershell
& $py -X utf8 -m pytest tests\test_thu_dau_mot_map_sources.py tests\test_thu_dau_mot_map_renderers.py tests\test_thu_dau_mot_map_release.py tests\test_thu_dau_mot_map_product_page.py tests\test_binh_duong_map_page.py tests\test_planning_pages.py tests\test_public_seo.py -q
```

- [ ] **Step 2: Re-run release validation from a clean candidate**

Delete only the explicit ignored candidate directory after resolving and
printing its absolute path, rebuild without refreshing sources, and confirm the
new ZIP hash matches the previous deterministic build.

- [ ] **Step 3: Confirm repository hygiene**

```powershell
git diff --check
git status --short
git ls-files "artifacts/*" "*.pdf" "*.kml" "*.zip"
```

Expected: no paid release artifact is tracked.

- [ ] **Step 4: Stop before deployment**

Do not deploy the product page yet. Continue with
`docs/superpowers/plans/2026-07-29-thu-dau-mot-payos-commerce.md`; release both
subsystems together only after the payment gate passes.
