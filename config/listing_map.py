from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

LISTING_MAP_RESOLVER_VERSION = "osm-binh-duong-20260807-v7"
LISTING_MAP_BOUNDS = (
    (10.75, 106.25),
    (11.65, 107.10),
)
LISTING_MAP_SUPPORTED_CITIES = (
    "THỦ DẦU MỘT",
    "BẾN CÁT",
    "THUẬN AN",
    "DĨ AN",
)
LISTING_MAP_WARD_ALIASES = {
    ("THỦ DẦU MỘT", "phu chanh"): "Phú Tân",
}

LISTING_MAP_FORCE_AGGREGATE_ROADS = frozenset({
    ("thu dau mot", "phu tan", "n 1"),
    ("thu dau mot", "phu tan", "n 2"),
    ("thu dau mot", "phu tan", "n 3"),
    ("thu dau mot", "phu tan", "n 5"),
    ("thu dau mot", "phu tan", "n 6"),
    ("thu dau mot", "tan an", "nguyen chi thanh"),
    ("thu dau mot", "hiep an", "nguyen chi thanh"),
    ("thu dau mot", "tuong binh hiep", "nguyen chi thanh"),
    ("thu dau mot", "phu my", "huynh van luy"),
    ("thu dau mot", "phu loi", "huynh van luy"),
    ("thu dau mot", "phu my", "pham ngoc thach"),
    ("thu dau mot", "hiep thanh", "pham ngoc thach"),
    ("thu dau mot", "phu hoa", "le hong phong"),
    ("thu dau mot", "phu tho", "le hong phong"),
    ("thu dau mot", "dinh hoa", "dx 71"),
    ("thu dau mot", "chanh nghia", "bui quoc khanh"),
    ("thu dau mot", "chanh my", "nguyen van long"),
    ("thu dau mot", "tuong binh hiep", "bui ngoc thu"),
    ("thu dau mot", "dinh hoa", "dai lo binh duong"),
    ("thu dau mot", "hiep an", "dai lo binh duong"),
    ("thu dau mot", "phu hoa", "dai lo binh duong"),
    ("thu dau mot", "dinh hoa", "nguyen van thanh"),
    ("thu dau mot", "phu loi", "my phuoc tan van"),
    ("thu dau mot", "phu loi", "hoang hoa tham"),
})

LISTING_MAP_REGISTRY_DIR = (
    PROJECT_ROOT / "static" / "maps" / "listing-locations"
)
LISTING_MAP_MANIFEST_PATH = LISTING_MAP_REGISTRY_DIR / "manifest.json"
LISTING_MAP_WARD_REGISTRY_PATH = LISTING_MAP_REGISTRY_DIR / "ward-centers.json"
LISTING_MAP_ROAD_REGISTRY_PATH = LISTING_MAP_REGISTRY_DIR / "road-centers.json"
LISTING_MAP_LANDMARK_REGISTRY_PATH = (
    LISTING_MAP_REGISTRY_DIR / "landmark-centers.json"
)
LISTING_MAP_OVERRIDE_PATH = (
    PROJECT_ROOT / "config" / "listing_map_location_overrides.json"
)
LISTING_MAP_AUTO_OVERRIDE_PATH = (
    PROJECT_ROOT / "config" / "listing_map_location_auto_overrides.json"
)
LISTING_MAP_AUTO_ACCEPT_THRESHOLD = 0.90
LISTING_MAP_LEGACY_COMPATIBILITY_ZONES = (
    {
        "city": "THỦ DẦU MỘT",
        "ward": "Phú Tân",
        "landmark_token": "tdc phu chanh",
        "bounds": ((11.04, 106.68), (11.08, 106.72)),
        "reason": (
            "TĐC Phú Chánh is mapped to the canonical Phú Tân valuation "
            "ward while the retained legacy ward polygon does not cover "
            "the resettlement zone."
        ),
    },
)
LISTING_MAP_WARD_BOUNDARY_PATHS = (
    PROJECT_ROOT
    / "config"
    / "map_products"
    / "thu_dau_mot_legacy_boundaries.geojson",
    PROJECT_ROOT
    / "config"
    / "map_products"
    / "ben_cat_legacy_boundaries.geojson",
    PROJECT_ROOT
    / "config"
    / "map_products"
    / "thuan_an_legacy_boundaries.geojson",
    PROJECT_ROOT
    / "config"
    / "map_products"
    / "di_an_legacy_boundaries.geojson",
)

LISTING_MAP_ALLOWED_PRECISIONS = frozenset(
    {"exact", "road", "landmark", "ward"}
)
