"""Server-rendered news discovery: filter the complete archive before slicing."""
import math
import unicodedata
from urllib.parse import urlencode

ARTICLES_PER_PAGE = 12


def news_archive(articles, categories, args, *, path):
    category = args.get("category", "all")
    if category not in {item["key"] for item in categories}:
        category = "all"
    query = args.get("q", "").strip()[:100]
    filtered = bool(query) or category != "all"

    def normalize(value):
        return "".join(char for char in unicodedata.normalize("NFD", value.casefold())
                       if not unicodedata.combining(char)).replace("đ", "d")

    matches = [article for article in (articles if filtered else articles[1:])
               if (category == "all" or article.get("category_key") == category)
               and (not query or normalize(query) in normalize(article.get("search_text", "")))]
    raw = args.get("page", "1")
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 6:
        raise ValueError("Invalid news page")
    number = int(raw)
    pages = max(1, math.ceil(len(matches) / ARTICLES_PER_PAGE))
    if number < 1 or number > pages:
        raise ValueError("News page out of range")

    def link(number=1, **overrides):
        values = {"category": category, "q": query, **overrides}
        params = {key: value for key, value in values.items() if value and value != "all"}
        if number > 1:
            params["page"] = number
        return path + ("?" + urlencode(params) if params else "")

    start = (number - 1) * ARTICLES_PER_PAGE
    return {
        "items": matches[start:start + ARTICLES_PER_PAGE],
        "featured": articles[0] if articles and not filtered and number == 1 else None,
        "number": number, "pages": pages, "total": len(matches),
        "start": start + 1 if matches else 0, "end": min(start + ARTICLES_PER_PAGE, len(matches)),
        "filtered": filtered, "query": query, "category": category, "url": link(number),
        "previous": link(number - 1) if number > 1 else None,
        "next": link(number + 1) if number < pages else None,
        "category_links": {key: link(category=key) for key in ("all", *(item["key"] for item in categories))},
        "links": [{"number": n, "url": link(n)} for n in sorted(
            {1, pages, *range(max(1, number - 2), min(pages, number + 2) + 1)})],
    }
