from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

LISTING_MAP_RESOLVER_VERSION = "osm-binh-duong-20260729-v1"
LISTING_MAP_BOUNDS = (
    (10.75, 106.25),
    (11.65, 107.10),
)
LISTING_MAP_SUPPORTED_CITIES = ("THỦ DẦU MỘT", "BẾN CÁT")

LISTING_MAP_REGISTRY_DIR = (
    PROJECT_ROOT / "static" / "maps" / "listing-locations"
)
LISTING_MAP_MANIFEST_PATH = LISTING_MAP_REGISTRY_DIR / "manifest.json"
LISTING_MAP_WARD_REGISTRY_PATH = LISTING_MAP_REGISTRY_DIR / "ward-centers.json"
LISTING_MAP_ROAD_REGISTRY_PATH = LISTING_MAP_REGISTRY_DIR / "road-centers.json"

LISTING_MAP_ALLOWED_PRECISIONS = frozenset({"exact", "road", "ward"})
