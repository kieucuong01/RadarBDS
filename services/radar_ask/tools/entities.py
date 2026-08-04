"""Deterministic listing, market-location, and road entity resolution."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

from db.radar_ask_connection import get_radar_ask_read_conn

from ..contracts import EvidenceItem, SourceKind
from ..evidence import EvidenceBuilder, stable_evidence_id
from ..registry import (
    ResolveListingArgs,
    ResolveLocationArgs,
    ResolveRoadArgs,
    ToolContext,
)


CANONICAL_CITY_WARDS: dict[str, tuple[str, ...]] = {
    "THỦ DẦU MỘT": (
        "Tân An",
        "Hiệp An",
        "Tương Bình Hiệp",
        "Định Hòa",
        "Chánh Mỹ",
        "Phú Mỹ",
        "Phú Cường",
        "Phú Hòa",
        "Phú Lợi",
        "Hiệp Thành",
        "Chánh Nghĩa",
        "Phú Tân",
        "Phú Thọ",
        "Hòa Phú",
    ),
    "BẾN CÁT": (
        "Phú An",
        "An Tây",
        "An Điền",
        "Thới Hòa",
        "Mỹ Phước",
        "Mỹ Phước 1",
        "Mỹ Phước 2",
        "Mỹ Phước 3",
        "Mỹ Phước 4",
        "Chánh Phú Hòa",
        "Tân Định",
        "Hòa Lợi",
    ),
    "THUẬN AN": (
        "An Phú",
        "An Thạnh",
        "Bình Chuẩn",
        "Bình Hòa",
        "Bình Nhâm",
        "Hưng Định",
        "Lái Thiêu",
        "Thuận Giao",
        "Vĩnh Phú",
        "An Sơn",
    ),
    "DĨ AN": (
        "An Bình",
        "Bình An",
        "Bình Thắng",
        "Dĩ An",
        "Đông Hòa",
        "Tân Bình",
        "Tân Đông Hiệp",
    ),
    "TÂN UYÊN": (
        "Hội Nghĩa",
        "Khánh Bình",
        "Phú Chánh",
        "Tân Hiệp",
        "Tân Phước Khánh",
        "Tân Vĩnh Hiệp",
        "Thạnh Hội",
        "Thạnh Phước",
        "Uyên Hưng",
        "Vĩnh Tân",
    ),
}
CITY_ALIASES = {
    "thu dau mot": "THỦ DẦU MỘT",
    "tdm": "THỦ DẦU MỘT",
    "ben cat": "BẾN CÁT",
    "thuan an": "THUẬN AN",
    "di an": "DĨ AN",
    "tan uyen": "TÂN UYÊN",
}
EXPLICIT_WARD_ALIASES = {
    "tdc phu chanh": "Phú Tân",
    "khu tdc phu chanh": "Phú Tân",
    "kdc hiep thanh": "Hiệp Thành",
    "khu dan cu hiep thanh": "Hiệp Thành",
}
POST_MERGER_WARD_COMPONENTS = {
    "binh duong": ("Phú Mỹ", "Hòa Phú", "Phú Tân", "Phú Chánh"),
    "chanh hiep": ("Định Hòa", "Tương Bình Hiệp", "Hiệp An", "Chánh Mỹ"),
    "thu dau mot": ("Phú Cường", "Phú Thọ", "Chánh Nghĩa", "Hiệp Thành", "Chánh Mỹ"),
    "phu an": ("Tân An", "Phú An", "Hiệp An"),
    "long nguyen": ("An Điền", "Mỹ Phước"),
    "ben cat": ("Tân Hưng", "Lai Hưng", "Mỹ Phước"),
}


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value or "").lower().replace("đ", "d")
    ascii_text = "".join(
        char for char in normalized if unicodedata.category(char) != "Mn"
    )
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _strip_location_prefix(value: str) -> str:
    return re.sub(r"^(?:phuong|xa|thi tran)\s+", "", _fold(value)).strip()


def _strip_road_prefix(value: str) -> str:
    folded = re.sub(r"^(?:duong|d)\s+", "", _fold(value)).strip()
    return re.sub(r"\s+", "", folded)


def _read_context(context: ToolContext):
    factory = context.read_conn_factory or get_radar_ask_read_conn
    return factory()


def _row_dict(cursor, row) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    description = getattr(cursor, "description", None) or ()
    names = [getattr(item, "name", item[0]) for item in description]
    return dict(zip(names, row, strict=True))


def _as_of(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dataset_version(prefix: str, as_of: datetime) -> str:
    return f"{prefix}:{as_of.isoformat(timespec='seconds')}"


def _public_ref(kind: str, *parts: str) -> str:
    normalized = ":".join(_fold(part).replace(" ", "-") for part in parts)
    return f"{kind}:{normalized}"


def _listing_missing(question: str):
    return (
        EvidenceBuilder(question_snapshot=question)
        .missing("listing_not_found_or_not_visible")
        .build()
    )


def resolve_listing(*, args: ResolveListingArgs, context: ToolContext):
    listing_id = args.listing_id or context.ask.page.listing_id
    question = f"resolve listing {listing_id or 'current'}"
    if listing_id is None:
        return (
            EvidenceBuilder(question_snapshot=question)
            .missing("listing_reference_required")
            .clarify(["Mở trang chi tiết tin hoặc nhập mã tin Radar"])
            .build()
        )

    with _read_context(context) as conn:
        cursor = conn.execute(
            """
            SELECT listing_id, source, title, ward, property_type, road_name,
                   is_active, probably_sold, public_visible, crawled_at
            FROM public.radar_ask_v_listings
            WHERE listing_id=%s
            LIMIT 1
            """,
            (listing_id,),
        )
        raw = cursor.fetchone()
    if raw is None:
        return _listing_missing(question)
    row = _row_dict(cursor, raw)
    if context.ask.tier != "admin" and not bool(row.get("public_visible")):
        return _listing_missing(question)

    as_of = _as_of(row.get("crawled_at"))
    version = _dataset_version("listings", as_of)
    public_ref = f"radar-listing:{int(row['listing_id'])}"
    item = EvidenceItem(
        evidence_id=stable_evidence_id("listing", public_ref, version),
        source_kind=SourceKind.LISTING,
        source_ref=public_ref,
        value={
            "listing_ref": public_ref,
            "source": row.get("source") or "unknown",
            "ward": row.get("ward") or "unknown",
            "property_type": row.get("property_type") or "khac",
            "road_name": row.get("road_name"),
            "is_active": bool(row.get("is_active")),
        },
        as_of=as_of,
        dataset_version=version,
        provenance={"listing_id": str(row["listing_id"]), "method": "safe_view_exact"},
    )
    return (
        EvidenceBuilder(question_snapshot=question)
        .resolve(listing_ref=public_ref)
        .add(item)
        .build()
    )


def _available_locations(context: ToolContext) -> list[dict[str, Any]]:
    visibility = "TRUE" if context.ask.tier == "admin" else "public_visible"
    with _read_context(context) as conn:
        cursor = conn.execute(
            f"""
            SELECT ward, MAX(crawled_at) AS as_of, COUNT(*)::integer AS sample_size
            FROM public.radar_ask_v_listings
            WHERE ward IS NOT NULL AND {visibility}
            GROUP BY ward
            ORDER BY ward
            LIMIT 100
            """
        )
        rows = cursor.fetchall()
    return [_row_dict(cursor, row) for row in rows]


def _canonical_city(value: str | None) -> str | None:
    if not value:
        return None
    folded = _strip_location_prefix(value)
    if folded in CITY_ALIASES:
        return CITY_ALIASES[folded]
    for city in CANONICAL_CITY_WARDS:
        if _fold(city) == folded:
            return city
    return None


def _ward_city(ward: str) -> str | None:
    for city, wards in CANONICAL_CITY_WARDS.items():
        if ward in wards:
            return city
    return None


def _resolved_location_bundle(
    *,
    question: str,
    ward: str,
    city: str | None,
    rows: list[dict[str, Any]],
):
    row = next(item for item in rows if item["ward"] == ward)
    as_of = _as_of(row.get("as_of"))
    version = _dataset_version("locations", as_of)
    source_ref = _public_ref("ward", city or _ward_city(ward) or "unknown", ward)
    item = EvidenceItem(
        evidence_id=stable_evidence_id("market_stat", source_ref, version),
        source_kind=SourceKind.MARKET_STAT,
        source_ref=source_ref,
        value={
            "ward": ward,
            "city": city or _ward_city(ward),
            "eligible_listing_count": int(row.get("sample_size") or 0),
        },
        unit="listings",
        as_of=as_of,
        dataset_version=version,
        sample_size=int(row.get("sample_size") or 0),
        provenance={"method": "canonical_ward_vocabulary"},
    )
    return (
        EvidenceBuilder(question_snapshot=question)
        .resolve(ward=ward, city=city or _ward_city(ward))
        .add(item)
        .build()
    )


def resolve_location(*, args: ResolveLocationArgs, context: ToolContext):
    question = f"resolve location {args.ward}"
    rows = _available_locations(context)
    available = {str(row["ward"]): row for row in rows if row.get("ward")}
    city = _canonical_city(args.city)
    if city:
        allowed = set(CANONICAL_CITY_WARDS[city])
        available = {ward: row for ward, row in available.items() if ward in allowed}
        rows = list(available.values())
    folded = _strip_location_prefix(args.ward)

    exact = [ward for ward in available if _fold(ward) == folded]
    if len(exact) == 1:
        return _resolved_location_bundle(
            question=question,
            ward=exact[0],
            city=city,
            rows=rows,
        )

    alias = EXPLICIT_WARD_ALIASES.get(folded)
    if alias and alias in available:
        return _resolved_location_bundle(
            question=question,
            ward=alias,
            city=city,
            rows=rows,
        )

    merger_candidates = [
        ward for ward in POST_MERGER_WARD_COMPONENTS.get(folded, ()) if ward in available
    ]
    if merger_candidates:
        return (
            EvidenceBuilder(question_snapshot=question)
            .clarify(merger_candidates)
            .missing("old_canonical_valuation_ward_required")
            .build()
        )

    candidates = [
        ward
        for ward in available
        if folded in _fold(ward) or _fold(ward) in folded
    ]
    if len(candidates) == 1:
        return _resolved_location_bundle(
            question=question,
            ward=candidates[0],
            city=city,
            rows=rows,
        )
    builder = EvidenceBuilder(question_snapshot=question)
    if candidates:
        builder.clarify(sorted(candidates)).missing("location_is_ambiguous")
    else:
        builder.missing("location_not_found")
    return builder.build()


def _available_roads(context: ToolContext) -> list[dict[str, Any]]:
    visibility = "TRUE" if context.ask.tier == "admin" else "public_visible"
    with _read_context(context) as conn:
        cursor = conn.execute(
            f"""
            SELECT ward, road_name, MAX(crawled_at) AS as_of,
                   COUNT(*)::integer AS sample_size
            FROM public.radar_ask_v_listings
            WHERE road_name IS NOT NULL AND {visibility}
            GROUP BY ward, road_name
            ORDER BY ward, road_name
            LIMIT 500
            """
        )
        rows = cursor.fetchall()
    return [_row_dict(cursor, row) for row in rows]


def resolve_road(*, args: ResolveRoadArgs, context: ToolContext):
    question = f"resolve road {args.road}"
    requested = _strip_road_prefix(args.road)
    requested_ward = _strip_location_prefix(args.ward) if args.ward else None
    requested_city = _canonical_city(args.city)
    matches = []
    for row in _available_roads(context):
        road = str(row.get("road_name") or "")
        ward = str(row.get("ward") or "")
        if _strip_road_prefix(road) != requested:
            continue
        if requested_ward and _fold(ward) != requested_ward:
            continue
        if requested_city and ward not in CANONICAL_CITY_WARDS[requested_city]:
            continue
        matches.append(row)

    if len(matches) != 1:
        builder = EvidenceBuilder(question_snapshot=question)
        if matches:
            candidates = [
                f"{row['road_name']}, {row['ward']}" for row in matches
            ]
            builder.clarify(candidates).missing("road_location_is_ambiguous")
        else:
            builder.missing("road_not_found")
        return builder.build()

    row = matches[0]
    as_of = _as_of(row.get("as_of"))
    version = _dataset_version("roads", as_of)
    source_ref = _public_ref("road", str(row["ward"]), str(row["road_name"]))
    item = EvidenceItem(
        evidence_id=stable_evidence_id("market_stat", source_ref, version),
        source_kind=SourceKind.MARKET_STAT,
        source_ref=source_ref,
        value={
            "road": row["road_name"],
            "ward": row["ward"],
            "eligible_listing_count": int(row.get("sample_size") or 0),
        },
        unit="listings",
        as_of=as_of,
        dataset_version=version,
        sample_size=int(row.get("sample_size") or 0),
        provenance={"method": "safe_view_exact_road"},
    )
    return (
        EvidenceBuilder(question_snapshot=question)
        .resolve(road=row["road_name"], ward=row["ward"])
        .add(item)
        .build()
    )
