"""Canonical page and product metadata for paid Bình Dương city maps."""

from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from urllib.parse import quote


def _unit(name: str, unit_type: str = "Phường cũ", **extra) -> dict:
    return {"name": name, "unit_type": unit_type, **extra}


def _current(name: str, former_units: str) -> dict:
    return {
        "name": name,
        "unit_type": "Phường",
        "former_units": former_units,
    }


def _natural_join(values: tuple[str, ...]) -> str:
    if len(values) <= 1:
        return "".join(values)
    return ", ".join(values[:-1]) + " và " + values[-1]


def _dashboard(city_name: str, *, filtered: bool) -> tuple[str, str]:
    if filtered:
        return (
            f"/?tab=signals&city={quote(city_name)}",
            f"Lọc tin {city_name}",
        )
    return "/?tab=signals", "Xem toàn bộ tin đang bán"


def _faq(
    city_name: str,
    legacy_count: int,
    current_names: tuple[str, ...],
    derived_names: tuple[str, ...],
) -> tuple[dict, ...]:
    derived_answer = (
        "Có. "
        + _natural_join(derived_names)
        + " là ranh suy luận biên tập từ phần dư hình học giữa lớp hiện tại "
        "và các ranh lịch sử có nguồn. Các ranh này chỉ dùng để tham khảo."
        if derived_names
        else "Không. Toàn bộ ranh trước sắp xếp trên trang này đều lấy từ "
        "snapshot hành chính lịch sử có nguồn."
    )
    return (
        {
            "question": f"Bản trước năm 2025 của {city_name} có bao nhiêu đơn vị?",
            "answer": (
                f"Bản trước sắp xếp hiển thị {legacy_count} đơn vị hành chính "
                f"cũ của {city_name} ở mức tham khảo."
            ),
        },
        {
            "question": "Có ranh nào được suy luận không?",
            "answer": derived_answer,
        },
        {
            "question": "Bản hiện tại gồm những phường nào?",
            "answer": "Bản hiện tại gồm " + ", ".join(current_names) + ".",
        },
        {
            "question": "Tôi có thể chỉnh sửa và in bản đồ không?",
            "answer": (
                "Có. Bộ sản phẩm có hai PDF vector hoàn thiện để in A0, hai "
                "SVG giữ đối tượng chữ và nhóm lớp, cùng hai KML để mở trong "
                "phần mềm bản đồ tương thích."
            ),
        },
        {
            "question": "Bản đồ có thay thế hồ sơ địa chính hoặc quy hoạch không?",
            "answer": (
                "Không. Sản phẩm dùng để tham khảo, in ấn, trình bày và phân "
                "tích; không thay thế hồ sơ thửa đất, bản đồ địa chính, hồ sơ "
                "quy hoạch hoặc xác nhận của cơ quan có thẩm quyền."
            ),
        },
        {
            "question": "Mua xong nhận file như thế nào?",
            "answer": (
                "Khi PayOS xác nhận thanh toán VietQR, trang đơn hàng hiển thị "
                "link tải có hiệu lực 24 giờ. Link gắn với mã đơn hàng, không "
                "cần email hoặc tài khoản."
            ),
        },
    )


def _page(
    *,
    city_slug: str,
    city_name: str,
    legacy_units: tuple[dict, ...],
    current_units: tuple[dict, ...],
    derived_legacy_units: tuple[str, ...],
    legacy_filename: str,
    current_filename: str,
    filtered_dashboard: bool,
    search_examples: str,
    city_context: str,
) -> dict:
    legacy_count = len(legacy_units)
    current_count = len(current_units)
    path = f"/ban-do-{city_slug}"
    dashboard_href, dashboard_label = _dashboard(
        city_name,
        filtered=filtered_dashboard,
    )
    legacy_names = tuple(item["name"] for item in legacy_units)
    current_names = tuple(item["name"] for item in current_units)
    legacy_unit_label = (
        "đơn vị cũ"
        if any(item["unit_type"] == "Xã cũ" for item in legacy_units)
        else "phường cũ"
    )
    derived_note = (
        f"{_natural_join(derived_legacy_units)} là ranh suy luận biên tập từ phần "
        "dư hình học. Dùng để tra cứu định hướng, không dùng như hồ sơ pháp lý."
        if derived_legacy_units
        else "Toàn bộ ranh trước sắp xếp dùng snapshot hành chính lịch sử có "
        "nguồn và chỉ phục vụ tra cứu tham khảo."
    )
    return {
        "city_slug": city_slug,
        "city_name": city_name,
        "page_slug": f"ban-do-{city_slug}",
        "path": path,
        "product_slug": f"{city_slug}-map-bundle",
        "price_vnd": 99_000,
        "tracking_prefix": city_slug.replace("-", "_") + "_map",
        "title": (
            f"Bản đồ TP {city_name} Bình Dương trước và sau sáp nhập | Radar BDS"
        ),
        "description": (
            f"Tra cứu miễn phí bản đồ TP {city_name} Bình Dương trước và sau "
            f"sáp nhập: {legacy_count} đơn vị cũ, {current_count} phường hiện "
            "tại và bộ file PDF, SVG, KML hoàn thiện."
        ),
        "keywords": (
            f"bản đồ {city_name}, bản đồ TP {city_name}, bản đồ vector "
            f"{city_name}, bản đồ {city_name} trước sáp nhập, bản đồ "
            f"{city_name} sau sáp nhập"
        ),
        "breadcrumb_label": f"Bản đồ TP {city_name}",
        "hero_title": f"Bản đồ TP {city_name} trước và sau sáp nhập",
        "hero_text": (
            f"Tra cứu miễn phí {legacy_count} đơn vị cũ và {current_count} "
            f"phường hiện tại của {city_name}. Chọn khu vực trên bản đồ để đối "
            "chiếu tên địa bàn, sau đó mở dashboard Radar BDS xem tin nhà đất."
        ),
        "answer_block": (
            f"TP {city_name} hiện có 2 lớp tra cứu trên Radar BDS: bản trước năm "
            f"2025 gồm {legacy_count} đơn vị cũ ở mức tham khảo; bản sau sắp "
            f"xếp gồm {current_count} phường hiện tại là "
            f"{_natural_join(current_names)}."
        ),
        "city_context": city_context,
        "updated_at": "2026-07-29",
        "updated_label": "29/07/2026",
        "preview_before": f"/static/images/seo/{city_slug}-map-before.webp",
        "preview_after": f"/static/images/seo/{city_slug}-map-after.webp",
        "default_layer": "legacy",
        "legacy_geojson_url": (
            f"/static/maps/{city_slug}/{legacy_filename}"
        ),
        "current_geojson_url": (
            f"/static/maps/{city_slug}/{current_filename}"
        ),
        "legacy_data_url": (
            f"/du-lieu/ban-do-{city_slug}/truoc-sap-nhap.geojson"
        ),
        "current_data_url": (
            f"/du-lieu/ban-do-{city_slug}/sau-sap-nhap.geojson"
        ),
        "legacy_filename": legacy_filename,
        "current_filename": current_filename,
        "legacy_units": legacy_units,
        "current_units": current_units,
        "legacy_count": legacy_count,
        "current_count": current_count,
        "legacy_names": legacy_names,
        "current_names": current_names,
        "current_names_label": _natural_join(current_names),
        "current_wards": current_names,
        "legacy_unit_label": legacy_unit_label,
        "dataset_id_suffix": (
            "wards" if city_slug == "thu-dau-mot" else city_slug
        ),
        "derived_legacy_units": derived_legacy_units,
        "sourced_legacy_count": legacy_count - len(derived_legacy_units),
        "derived_note": derived_note,
        "search_examples": search_examples,
        "search_aria_label": (
            "Tìm phường Thủ Dầu Một"
            if city_slug == "thu-dau-mot"
            else f"Tìm khu vực {city_name}"
        ),
        "dashboard_signal_href": dashboard_href,
        "dashboard_label": dashboard_label,
        "dashboard_heading": f"Xem dữ liệu tin đang bán liên quan {city_name}",
        "dashboard_text": (
            "Dùng bản đồ để xác định khu vực quan tâm, sau đó mở dashboard "
            "để xem tin theo diện tích, giá và tín hiệu đáng kiểm tra."
        ),
        "checkout_path": f"{path}/checkout",
        "order_base_path": f"{path}/don-hang",
        "faq": _faq(
            city_name,
            legacy_count,
            current_names,
            derived_legacy_units,
        ),
    }


_THU_DAU_MOT = _page(
    city_slug="thu-dau-mot",
    city_name="Thủ Dầu Một",
    legacy_units=tuple(
        _unit(name)
        for name in (
            "Chánh Mỹ",
            "Chánh Nghĩa",
            "Định Hòa",
            "Hiệp An",
            "Hiệp Thành",
            "Hòa Phú",
            "Phú Cường",
            "Phú Hòa",
            "Phú Lợi",
            "Phú Mỹ",
            "Phú Tân",
            "Phú Thọ",
            "Tân An",
            "Tương Bình Hiệp",
        )
    ),
    current_units=(
        _current(
            "Thủ Dầu Một",
            "Phú Cường, Phú Thọ, Chánh Nghĩa, Chánh Mỹ và một phần Hiệp Thành",
        ),
        _current("Phú Lợi", "Phú Hòa, Phú Lợi và phần còn lại của Hiệp Thành"),
        _current(
            "Chánh Hiệp",
            "Định Hòa, Tương Bình Hiệp, một phần Hiệp An và phần còn lại của Chánh Mỹ",
        ),
        _current("Bình Dương", "Phú Mỹ, Hòa Phú, Phú Tân và Phú Chánh"),
        _current("Phú An", "Tân An, Phú An và phần còn lại của Hiệp An"),
    ),
    derived_legacy_units=("Hòa Phú", "Phú Tân"),
    legacy_filename="legacy-14-wards.geojson",
    current_filename="current-5-wards.geojson",
    filtered_dashboard=True,
    search_examples="Phú Tân, Phú An, Chánh Hiệp",
    city_context=(
        "Khu vực trung tâm hành chính và thị trường nhà đất lõi của Bình Dương cũ."
    ),
)

_THUAN_AN = _page(
    city_slug="thuan-an",
    city_name="Thuận An",
    legacy_units=tuple(
        _unit(name)
        for name in (
            "An Phú",
            "An Sơn",
            "An Thạnh",
            "Bình Chuẩn",
            "Bình Hòa",
            "Bình Nhâm",
            "Hưng Định",
            "Lái Thiêu",
            "Thuận Giao",
            "Vĩnh Phú",
        )
    ),
    current_units=(
        _current("An Phú", "An Phú và một phần Bình Chuẩn"),
        _current("Bình Hòa", "Bình Hòa và một phần Vĩnh Phú"),
        _current("Lái Thiêu", "Bình Nhâm, Lái Thiêu và phần còn lại của Vĩnh Phú"),
        _current("Thuận An", "Hưng Định, An Thạnh và An Sơn"),
        _current("Thuận Giao", "Thuận Giao và phần còn lại của Bình Chuẩn"),
    ),
    derived_legacy_units=("Vĩnh Phú",),
    legacy_filename="legacy-10-wards.geojson",
    current_filename="current-5-wards.geojson",
    filtered_dashboard=False,
    search_examples="Lái Thiêu, Vĩnh Phú, Bình Chuẩn",
    city_context=(
        "Vùng đô thị mật độ cao giáp Thành phố Hồ Chí Minh, phát triển dọc "
        "Quốc lộ 13 và các cụm công nghiệp - dịch vụ."
    ),
)

_DI_AN = _page(
    city_slug="di-an",
    city_name="Dĩ An",
    legacy_units=tuple(
        _unit(name)
        for name in (
            "An Bình",
            "Bình An",
            "Bình Thắng",
            "Dĩ An",
            "Đông Hòa",
            "Tân Bình",
            "Tân Đông Hiệp",
        )
    ),
    current_units=(
        _current("Đông Hòa", "Bình An, Bình Thắng và Đông Hòa"),
        _current("Dĩ An", "An Bình, Dĩ An và một phần Tân Đông Hiệp"),
        _current(
            "Tân Đông Hiệp",
            "Tân Bình, một phần Thái Hòa và phần còn lại của Tân Đông Hiệp",
        ),
    ),
    derived_legacy_units=("An Bình",),
    legacy_filename="legacy-7-wards.geojson",
    current_filename="current-3-wards.geojson",
    filtered_dashboard=False,
    search_examples="Dĩ An, An Bình, Tân Đông Hiệp",
    city_context=(
        "Cửa ngõ phía nam của Bình Dương cũ, kết nối trực tiếp Thủ Đức, Đồng "
        "Nai, ga Sóng Thần và các khu công nghiệp lâu năm."
    ),
)

_BEN_CAT = _page(
    city_slug="ben-cat",
    city_name="Bến Cát",
    legacy_units=(
        _unit("An Điền"),
        _unit("An Tây"),
        _unit("Chánh Phú Hòa"),
        _unit("Hòa Lợi"),
        _unit("Mỹ Phước"),
        _unit("Phú An", "Xã cũ"),
        _unit("Tân Định"),
        _unit("Thới Hòa"),
    ),
    current_units=(
        _current("Hòa Lợi", "Tân Định và Hòa Lợi"),
        _current("Tây Nam", "An Tây và một phần Thanh Tuyền, An Lập"),
        _current("Long Nguyên", "An Điền, Long Nguyên và một phần Mỹ Phước"),
        _current("Bến Cát", "Tân Hưng, Lai Hưng và phần còn lại của Mỹ Phước"),
        _current("Chánh Phú Hòa", "Chánh Phú Hòa và Hưng Hòa"),
        _current("Thới Hòa", "Đơn vị không thực hiện sắp xếp"),
    ),
    derived_legacy_units=(),
    legacy_filename="legacy-8-units.geojson",
    current_filename="current-6-wards.geojson",
    filtered_dashboard=True,
    search_examples="Mỹ Phước, An Điền, Chánh Phú Hòa",
    city_context=(
        "Vùng đô thị - công nghiệp phát triển dọc Quốc lộ 13, Mỹ Phước và các "
        "trục vành đai của Bình Dương cũ."
    ),
)


def _with_local_links(page: dict, siblings: tuple[dict, ...]) -> dict:
    result = dict(page)
    sibling_links = tuple(
        {
            "label": f"Bản đồ {sibling['city_name']}",
            "href": sibling["path"],
        }
        for sibling in siblings
        if sibling["city_slug"] != page["city_slug"]
    )
    result["local_links"] = (
        {"label": "Bản đồ Bình Dương", "href": "/ban-do-binh-duong"},
        {"label": "Bản đồ quy hoạch Bình Dương", "href": "/quy-hoach-binh-duong"},
        *sibling_links[:2],
    )
    return result


_RAW_PAGES = (_THU_DAU_MOT, _THUAN_AN, _DI_AN, _BEN_CAT)
CITY_MAP_PRODUCTS = MappingProxyType(
    {
        page["city_slug"]: _with_local_links(page, _RAW_PAGES)
        for page in _RAW_PAGES
    }
)
_CITY_MAP_PATHS = MappingProxyType(
    {page["path"]: page for page in CITY_MAP_PRODUCTS.values()}
)


def _validate_pages() -> None:
    pages = tuple(CITY_MAP_PRODUCTS.values())
    paths = tuple(page["path"] for page in pages)
    products = tuple(page["product_slug"] for page in pages)
    tracking = tuple(page["tracking_prefix"] for page in pages)
    if len(paths) != len(set(paths)):
        raise ValueError("city map paths must be unique")
    if len(products) != len(set(products)):
        raise ValueError("city map product slugs must be unique")
    if len(tracking) != len(set(tracking)):
        raise ValueError("city map tracking prefixes must be unique")
    for slug, page in CITY_MAP_PRODUCTS.items():
        if page["city_slug"] != slug:
            raise ValueError(f"city map registry key mismatch: {slug}")
        if page["price_vnd"] != 99_000:
            raise ValueError(f"invalid city map price: {slug}")
        for key in ("legacy_units", "current_units"):
            names = tuple(item["name"] for item in page[key])
            if not names or len(names) != len(set(names)):
                raise ValueError(f"invalid {key} taxonomy: {slug}")
        if not set(page["derived_legacy_units"]).issubset(
            set(page["legacy_names"])
        ):
            raise ValueError(f"invalid derived legacy taxonomy: {slug}")


_validate_pages()


def get_city_map_page(city_slug: str) -> dict:
    """Return an isolated copy of one allowlisted page configuration."""

    normalized = str(city_slug or "").strip().casefold()
    if normalized not in CITY_MAP_PRODUCTS:
        raise KeyError(normalized)
    return deepcopy(dict(CITY_MAP_PRODUCTS[normalized]))


def get_city_map_page_by_path(path: str) -> dict:
    """Return an isolated copy of a page selected by its exact canonical path."""

    normalized = str(path or "").strip()
    if normalized not in _CITY_MAP_PATHS:
        raise KeyError(normalized)
    return deepcopy(dict(_CITY_MAP_PATHS[normalized]))
