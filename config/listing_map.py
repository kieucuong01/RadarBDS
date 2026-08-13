from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent

LISTING_MAP_RESOLVER_VERSION = "osm-binh-duong-20260814-v64"
LISTING_MAP_BOUNDS = (
    (10.75, 106.25),
    (11.65, 107.10),
)
LISTING_MAP_SUPPORTED_CITIES = (
    "THỦ DẦU MỘT",
    "BẾN CÁT",
    "THUẬN AN",
    "DĨ AN",
    "TÂN UYÊN",
)
LISTING_MAP_WARD_ALIASES = {
    ("THỦ DẦU MỘT", "phu chanh"): "Phú Tân",
}

LISTING_MAP_FORCE_AGGREGATE_ROADS = frozenset({
    ("thuan an", "an phu", "duong tinh 743 a"),
    ("thuan an", "an phu", "duong so 22 thang 12"),
    ("thuan an", "an phu", "my phuoc tan van"),
    ("thuan an", "an thanh", "ho van men"),
    ("thuan an", "binh chuan", "duong tinh 743 a"),
    ("thuan an", "binh hoa", "dai lo binh duong"),
    ("thuan an", "binh nham", "cach mang thang tam"),
    ("thuan an", "binh nham", "nguyen chi thanh"),
    ("thuan an", "binh nham", "nguyen huu canh"),
    ("thuan an", "binh nham", "nguyen van long"),
    ("thuan an", "lai thieu", "cach mang thang tam"),
    ("thuan an", "lai thieu", "dai lo binh duong"),
    ("thuan an", "lai thieu", "nguyen huu canh"),
    ("thuan an", "thuan giao", "dai lo binh duong"),
    ("thuan an", "thuan giao", "duong thu khoa huan"),
    ("thuan an", "thuan giao", "duong so 22 thang 12"),
    ("thuan an", "thuan giao", "my phuoc tan van"),
    ("thuan an", "vinh phu", "dai lo binh duong"),
    ("thuan an", "an thanh", "cach mang thang tam"),
    ("thuan an", "an thanh", "dai lo binh duong"),
    ("thuan an", "hung dinh", "cach mang thang tam"),
    ("thuan an", "hung dinh", "duong so 22 thang 12"),
    ("thuan an", "hung dinh", "nguyen huu canh"),
    ("thuan an", "an son", "ho van men"),
    ("tan uyen", "phu chanh", "dt 742"),
    ("tan uyen", "phu chanh", "duong tinh 742"),
    ("tan uyen", "phu chanh", "ngo thoi nhiem"),
    ("tan uyen", "phu chanh", "huynh van luy"),
    ("tan uyen", "tan hiep", "duong nguyen tri phuong"),
    ("tan uyen", "tan phuoc khanh", "duong tinh 746"),
    ("tan uyen", "tan phuoc khanh", "duong to vinh dien"),
    ("tan uyen", "tan phuoc khanh", "duong vo thi sau"),
    ("tan uyen", "tan vinh hiep", "duong tinh 746"),
    ("tan uyen", "thai hoa", "duong tinh 747"),
    ("tan uyen", "vinh tan", "duong tran dai nghia"),
    ("ben cat", "an dien", "duong hung vuong"),
    ("ben cat", "an dien", "duong tinh 748"),
    ("ben cat", "an dien", "duong vanh dai 4 thanh pho ho chi minh"),
    ("ben cat", "an tay", "duong hung vuong"),
    ("ben cat", "an tay", "duong tinh 744"),
    ("ben cat", "an tay", "duong vanh dai 4 thanh pho ho chi minh"),
    ("ben cat", "phu an", "duong tinh 744"),
    ("ben cat", "thoi hoa", "dj 5"),
    ("ben cat", "thoi hoa", "duong my phuoc tan van"),
    ("ben cat", "thoi hoa", "my phuoc tan van"),
    ("ben cat", "thoi hoa", "na 7"),
    ("ben cat", "thoi hoa", "ne 2"),
    ("ben cat", "thoi hoa", "ne 8"),
    ("ben cat", "thoi hoa", "n 3"),
    ("ben cat", "thoi hoa", "n 5"),
    ("ben cat", "thoi hoa", "n 6"),
    ("ben cat", "thoi hoa", "n 7"),
    ("ben cat", "thoi hoa", "n 10"),
    ("ben cat", "thoi hoa", "na 2"),
    ("ben cat", "thoi hoa", "d 9"),
    ("ben cat", "thoi hoa", "d 11"),
    ("ben cat", "thoi hoa", "d 12"),
    ("ben cat", "thoi hoa", "d 13"),
    ("ben cat", "thoi hoa", "duong de 1"),
    ("ben cat", "thoi hoa", "duong de 4"),
    ("ben cat", "thoi hoa", "duong di 1"),
    ("ben cat", "thoi hoa", "di 1"),
    ("ben cat", "thoi hoa", "duong di 3"),
    ("ben cat", "thoi hoa", "duong kh 1"),
    ("ben cat", "thoi hoa", "duong vanh dai 4"),
    ("ben cat", "thoi hoa", "quoc lo 13"),
    ("ben cat", "tan dinh", "dai lo binh duong"),
    ("ben cat", "tan dinh", "my phuoc tan van"),
    ("ben cat", "tan dinh", "quoc lo 13"),
    ("ben cat", "hoa loi", "duong pham hung"),
    ("ben cat", "hoa loi", "my phuoc tan van"),
    ("ben cat", "chanh phu hoa", "duong my phuoc tan van"),
    ("ben cat", "chanh phu hoa", "na 3"),
    ("ben cat", "chanh phu hoa", "ne 3"),
    ("ben cat", "my phuoc", "quoc lo 13"),
    ("ben cat", "my phuoc", "na 3"),
    ("ben cat", "my phuoc", "n 5"),
    ("thu dau mot", "phu hoa", "tran van on"),
    ("thu dau mot", "phu hoa", "my phuoc tan van"),
    ("thu dau mot", "phu cuong", "bach dang"),
    ("thu dau mot", "phu cuong", "ly thuong kiet"),
    ("thu dau mot", "phu tan", "n 1"),
    ("thu dau mot", "phu tan", "n 2"),
    ("thu dau mot", "phu tan", "n 3"),
    ("thu dau mot", "phu tan", "n 5"),
    ("thu dau mot", "phu tan", "n 6"),
    ("thu dau mot", "phu tan", "dien bien phu"),
    ("thu dau mot", "phu tan", "nguyen van linh"),
    ("thu dau mot", "tan an", "nguyen chi thanh"),
    ("thu dau mot", "hiep an", "nguyen chi thanh"),
    ("thu dau mot", "tuong binh hiep", "nguyen chi thanh"),
    ("thu dau mot", "phu my", "huynh van luy"),
    ("thu dau mot", "phu loi", "huynh van luy"),
    ("thu dau mot", "phu loi", "dai lo binh duong"),
    ("thu dau mot", "phu loi", "duong tinh 743 a"),
    ("thu dau mot", "phu loi", "le hong phong"),
    ("thu dau mot", "phu my", "pham ngoc thach"),
    ("thu dau mot", "phu my", "dx 1"),
    ("thu dau mot", "phu my", "n 1"),
    ("thu dau mot", "phu my", "n 4"),
    ("thu dau mot", "phu my", "dien bien phu"),
    ("thu dau mot", "hiep thanh", "pham ngoc thach"),
    ("thu dau mot", "hiep thanh", "duong nguyen van troi"),
    ("thu dau mot", "phu hoa", "le hong phong"),
    ("thu dau mot", "phu hoa", "nguyen thi minh khai"),
    ("thu dau mot", "phu hoa", "ba muoi thang tu"),
    ("thu dau mot", "phu hoa", "duong so 30 thang 4"),
    ("thu dau mot", "phu tho", "le hong phong"),
    ("thu dau mot", "phu tho", "ba muoi thang tu"),
    ("thu dau mot", "phu tho", "cach mang thang tam"),
    ("thu dau mot", "phu tho", "duong so 30 thang 4"),
    ("thu dau mot", "hoa phu", "duong ly thai to"),
    ("thu dau mot", "hoa phu", "duong hung vuong"),
    ("thu dau mot", "hoa phu", "dong khoi"),
    ("thu dau mot", "phu cuong", "cach mang thang tam"),
    ("thu dau mot", "phu cuong", "huynh van cu"),
    ("thu dau mot", "hoa phu", "d 8"),
    ("thu dau mot", "dinh hoa", "dx 71"),
    ("thu dau mot", "dinh hoa", "dx 64"),
    ("thu dau mot", "dinh hoa", "my phuoc tan van"),
    ("thu dau mot", "dinh hoa", "vo van kiet"),
    ("thu dau mot", "chanh nghia", "bui quoc khanh"),
    ("thu dau mot", "chanh nghia", "cach mang thang tam"),
    ("thu dau mot", "chanh my", "nguyen van long"),
    ("thu dau mot", "tuong binh hiep", "bui ngoc thu"),
    ("thu dau mot", "dinh hoa", "dai lo binh duong"),
    ("thu dau mot", "hiep an", "dai lo binh duong"),
    ("thu dau mot", "phu hoa", "dai lo binh duong"),
    ("thu dau mot", "dinh hoa", "nguyen van thanh"),
    ("thu dau mot", "phu loi", "my phuoc tan van"),
    ("thu dau mot", "phu loi", "hoang hoa tham"),
    ("thu dau mot", "hiep thanh", "dai lo binh duong"),
    ("thu dau mot", "phu tho", "dai lo binh duong"),
    ("thu dau mot", "hiep thanh", "duong so 1"),
    ("thu dau mot", "hiep thanh", "duong so 2"),
    ("thu dau mot", "hiep thanh", "duong so 3"),
    ("thu dau mot", "hiep thanh", "hoang hoa tham"),
    ("thu dau mot", "hiep thanh", "pham ngu lao"),
    ("di an", "di an", "nguyen du"),
    ("di an", "di an", "duong tinh 743 b"),
    ("di an", "dong hoa", "hai ba trung"),
    ("di an", "dong hoa", "quoc lo 1 k"),
    ("di an", "dong hoa", "gs 1"),
    ("di an", "tan dong hiep", "duong tinh 743 a"),
    ("di an", "tan dong hiep", "duong tinh 743 b"),
    ("di an", "tan dong hiep", "duong tinh 743 c"),
    ("di an", "tan dong hiep", "duong my phuoc tan van"),
    ("di an", "tan dong hiep", "my phuoc tan van"),
    ("di an", "binh an", "duong tinh 743 a"),
    ("di an", "binh an", "duong so 30 thang 4"),
    ("di an", "binh an", "duong vanh dai 3 thanh pho ho chi minh"),
    ("di an", "tan binh", "bui thi xuan"),
    ("di an", "tan binh", "huynh thi tuoi"),
    ("di an", "tan binh", "le hong phong"),
    ("di an", "tan binh", "my phuoc tan van"),
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
