"""Allowlisted discovery sources for the public content hubs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicContentSource:
    key: str
    name: str
    source_type: str
    discovery_url: str
    allowed_hosts: frozenset[str]
    parser: str
    can_publish_pdf: bool = False


PUBLIC_CONTENT_SOURCES = (
    PublicContentSource(
        key="cafeland-binh-duong",
        name="CafeLand",
        source_type="hot_topic",
        discovery_url=(
            "https://cafeland.vn/chu-de-nong/bat-dong-san-binh-duong-70/"
        ),
        allowed_hosts=frozenset({"cafeland.vn", "www.cafeland.vn"}),
        parser="cafeland_topic",
    ),
    PublicContentSource(
        key="thuviennhadat-binh-duong",
        name="Thư Viện Nhà Đất",
        source_type="legal_discovery",
        discovery_url=(
            "https://thuviennhadat.vn/phap-luat/"
            "phe-duyet-ho-so-de-xuat-khu-vuc-phat-trien-do-thi-tan-an-"
            "phuong-tan-an-tpthu-dau-mot-690488.html"
        ),
        allowed_hosts=frozenset(
            {
                "thuviennhadat.vn",
                "www.thuviennhadat.vn",
                "cdn.thuviennhadat.vn",
            }
        ),
        parser="legal_discovery",
    ),
    PublicContentSource(
        key="congbao-chinhphu",
        name="Công báo Chính phủ",
        source_type="official_document",
        discovery_url="https://congbao.chinhphu.vn/van-ban/",
        allowed_hosts=frozenset(
            {"congbao.chinhphu.vn", "datafiles.chinhphu.vn"}
        ),
        parser="official_document",
        can_publish_pdf=True,
    ),
    PublicContentSource(
        key="congbao-tphcm",
        name="Công báo TP.HCM",
        source_type="official_document",
        discovery_url="https://congbao.hochiminhcity.gov.vn/",
        allowed_hosts=frozenset(
            {
                "congbao.hochiminhcity.gov.vn",
                "hochiminhcity.gov.vn",
                "www.hochiminhcity.gov.vn",
            }
        ),
        parser="official_document",
        can_publish_pdf=True,
    ),
)

_SOURCE_BY_KEY = {source.key: source for source in PUBLIC_CONTENT_SOURCES}


def get_public_content_source(key: str) -> PublicContentSource:
    normalized = str(key or "").strip().casefold()
    try:
        return _SOURCE_BY_KEY[normalized]
    except KeyError as exc:
        raise KeyError(normalized) from exc


def public_content_sources_for(kind: str) -> tuple[PublicContentSource, ...]:
    normalized = str(kind or "all").strip().casefold()
    if normalized == "all":
        return PUBLIC_CONTENT_SOURCES
    aliases = {
        "hot-topic": {"hot_topic"},
        "legal": {"legal_discovery", "official_document"},
        "legal-discovery": {"legal_discovery"},
        "official-document": {"official_document"},
    }
    if normalized not in aliases:
        raise ValueError(f"unknown public content source kind: {kind}")
    allowed_types = aliases[normalized]
    return tuple(
        source
        for source in PUBLIC_CONTENT_SOURCES
        if source.source_type in allowed_types
    )
