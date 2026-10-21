"""Bounded HTML archive; filters apply before slicing so every report is searchable."""
import math
import unicodedata
from urllib.parse import urlencode


REPORTS_PER_PAGE = 12


def _normalize(text):
    return "".join(
        char for char in unicodedata.normalize("NFD", str(text).casefold())
        if not unicodedata.combining(char)
    ).replace("đ", "d")


def report_archive(reports, options, args):
    """Return one page and canonical GET links; invalid page numbers raise ValueError."""
    city = args.get("city", "all")
    if city not in {"all", "tdm", "ben-cat"}:
        city = "all"
    wards = {ward["label"] for ward in options["wards"]
             if city == "all" or ward["city_key"] == city}
    ward = args.get("ward", "all")
    if ward not in wards:
        ward = "all"
    period = args.get("period", "all")
    if period not in {item["key"] for item in options["periods"]}:
        period = "all"
    query = args.get("q", "").strip()[:100]
    filters = {"city": city, "ward": ward, "period": period, "q": query}
    filtered = bool(query) or any(value != "all" for value in (city, ward, period))
    normalized_query = _normalize(query)
    matches = [report for report in (reports if filtered else reports[1:])
               if (city == "all" or report["hub_meta"]["city_key"] == city)
               and (ward == "all" or report["scope_label"] == ward)
               and (period == "all" or report["hub_meta"]["period_key"] == period)
               and (not query or normalized_query in _normalize(report["hub_meta"]["search_text"]))]
    raw_page = args.get("page", "1")
    if not raw_page.isascii() or not raw_page.isdecimal() or len(raw_page) > 6:
        raise ValueError("Invalid report page")
    number = int(raw_page)
    pages = max(1, math.ceil(len(matches) / REPORTS_PER_PAGE))
    if number < 1 or number > pages:
        raise ValueError("Report page out of range")

    def link(number=1, **overrides):
        values = {**filters, **overrides}
        params = {key: value for key, value in values.items()
                  if value and (key == "q" or value != "all")}
        if number > 1:
            params["page"] = number
        return "/bao-cao" + ("?" + urlencode(params) if params else "")

    start = (number - 1) * REPORTS_PER_PAGE
    city_links = {}
    for key in ("all", "tdm", "ben-cat"):
        keep_ward = ward if any(item["label"] == ward and
            (key == "all" or item["city_key"] == key) for item in options["wards"]) else "all"
        city_links[key] = link(city=key, ward=keep_ward)
    return {
        "items": matches[start:start + REPORTS_PER_PAGE],
        "featured": reports[0] if reports and not filtered and number == 1 else None,
        "filters": filters, "filtered": filtered, "number": number, "pages": pages,
        "total": len(matches), "start": start + 1 if matches else 0,
        "end": min(start + REPORTS_PER_PAGE, len(matches)),
        "url": link(number), "previous": link(number - 1) if number > 1 else None,
        "next": link(number + 1) if number < pages else None,
        "links": [{"number": n, "url": link(n)} for n in sorted(
            {1, pages, *range(max(1, number - 2), min(pages, number + 2) + 1)})],
        "city_links": city_links,
    }
