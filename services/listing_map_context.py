from __future__ import annotations

from dataclasses import dataclass
import re

from services.listing_location_resolver import (
    normalize_location_token,
    normalize_road_token,
)


@dataclass(frozen=True)
class MapLocationContext:
    direct_road: str = ""
    nearby_road: str = ""
    landmark: str = ""
    relation: str = ""
    distance_m: float | None = None
    evidence_text: str = ""


_DISTANCE_RE = re.compile(
    r"\b(?:cach|gan|khoang)?\s*(\d{1,4}(?:[.,]\d+)?)\s*m\b",
    re.IGNORECASE,
)
_NEAR_PREFIX_RE = re.compile(
    r"\b(?:cach|gan|sat|ke|canh|doi dien|ra|thong ra|noi ra)\s+"
    r"(?:duong\s+)?",
    re.IGNORECASE,
)
_ALLEY_PREFIX_RE = re.compile(
    r"\b(?:\d+\s*/|1\s*(?:x|s)(?:ec|et)|mot\s*(?:x|s)(?:ec|et)|"
    r"(?:x|s)(?:ec|et)|nhanh|hem)\s+"
    r"(?:duong\s+)?",
    re.IGNORECASE,
)
_DIRECT_PREFIX_RE = re.compile(
    r"\b(?:mat tien|mtkd|mt|duong)\s+",
    re.IGNORECASE,
)
_ROAD_CODE_RE = re.compile(
    r"^(?:duong\s+)?(?P<prefix>dx|da|db|dh|dt|dl|tl|ql|na|nb|ne|nf|"
    r"nh|nj|nk|nl|ni|dj|dk|n|d)\s*"
    r"[-./_]?\s*0*(?P<number>\d{1,4})(?P<suffix>[a-z]?)\b",
    re.IGNORECASE,
)
_NUMBERED_ROAD_RE = re.compile(
    r"^(?:duong\s+)?(?:so\s+)?0*(?P<number>\d{1,4})"
    r"(?P<suffix>[a-z]?)\b",
    re.IGNORECASE,
)
_LANDMARK_RE = re.compile(
    r"\b(?P<kind>tdc|tai dinh cu|kdc|khu dan cu|khu do thi|du an)\s+"
    r"(?P<name>[a-z0-9][a-z0-9\s-]{0,100})",
    re.IGNORECASE,
)
_ROAD_STOP_RE = re.compile(
    r"\b(?:khoang|tam|khu|phuong|xa|thi tran|thanh pho|tp|"
    r"tphcm|hcm|tdc|tai dinh cu|dan cu|o to|xe hoi|"
    r"truong|thcs|thpt|tieu hoc|mam non|phut|nha tret|nha lau|nha moi|"
    r"moi xay|xay dung|hoan cong|dang thi cong|"
    r"duong nhua|duong be tong|duong dat|"
    r"gia|dien tich|dt|ban|can ban|chinh chu|chu gui|gui|"
    r"vi tri|kinh doanh|thong|noi dai|rong|gan|sat|cach|ngay|doi dien|"
    r"kdc|vao|nay|"
    r"tuong binh hiep|dinh hoa|tan an|hiep an|phu hoa|phu loi|"
    r"phu my|hiep thanh|chanh nghia|chanh my|phu tho|phu cuong|hoa phu|"
    r"(?<!nguyen )(?<!le )(?<!ho )(?<!mac )chi)\b|"
    r"\b\d{1,4}(?:[.,]\d+)?\s*m\b",
    re.IGNORECASE,
)
_LANDMARK_STOP_RE = re.compile(
    r"\b(?:phuong|xa|thi tran|thanh pho|tp|thu dau mot|tdm|"
    r"binh duong|ho chi minh|hcm|nay la|truoc sap nhap|"
    r"gia|dien tich|dt|"
    r"ban|can ban|mat tien|hem|duong|so do|tho cu|ngang|dai|"
    r"gan|sat|cach|vi tri|hang hiem|dg|khu tdc|tdc|tai dinh cu|"
    r"kdc|khu dan cu|khu do thi|du an|khu dan cu dong|dan cu dong)\b",
    re.IGNORECASE,
)
_NON_ROAD_NAMES = {
    "be tong",
    "dat",
    "nhua",
    "lon",
    "oto",
    "o to",
    "xe hoi",
    "chinh",
}
_ROAD_NAME_HINT_RE = re.compile(
    r"^(?:"
    r"dx|da|d|db|dh|dt|dl|tl|ql|na|nb|ne|nf|nh|nj|nk|nl|ni|dj|dk|n|duong so|"
    r"nguyen|tran|le|ly|pham|phan|huynh|vo|dang|do|ngo|bui|thich|bach|"
    r"hoang|ho|mac|ton duc|cach mang|hung vuong|dien bien|quoc lo|"
    r"dai lo|bac si|yersin|yesin|"
    r"my phuoc|mptv|phu loi|phu tan|phu an|an dien|tan dinh|hoa loi|vanh dai|vanh 4"
    r")\b",
    re.IGNORECASE,
)
_KNOWN_ROAD_PREFIXES = (
    "nguyen van be",
    "bach dang",
    "hai ba trung",
    "ly thuong kiet",
    "ngo quyen",
    "tran tu binh",
    "nguyen thi minh khai",
    "le hong phong",
    "thich quang duc",
    "tran van on",
    "nguyen chi thanh",
    "nguyen duc canh",
    "le chi dan",
    "mac dinh chi",
    "nguyen tri phuong",
    "huynh van luy",
    "hung vuong",
    "dong khoi",
    "pham ngoc thach",
    "nguyen hue",
    "dien bien phu",
    "tran ngoc len",
    "dong cay viet",
    "my phuoc tan van",
    "le loi",
    "nguyen binh",
    "ho van cong",
    "pham thi tan",
    "le thi trung",
    "huynh van nghe",
    "nguyen van troi",
    "nguyen thai binh",
    "nguyen van tiet",
    "nguyen van cu",
    "le van tach",
    "nguyen van long",
    "huynh van cu",
    "huynh thi hieu",
    "huynh thi chau",
    "phan dang luu",
    "nguyen huu canh",
    "phan boi chau",
    "tran binh trong",
    "bui ngoc thu",
    "nguyen an ninh",
    "bac si yersin",
    "nguyen van linh",
    "nguyen van thanh",
    "nguyen duc thuan",
    "pham ngu lao",
    "nguyen binh khiem",
    "cach mang thang tam",
    "dai lo binh duong",
    "bui quoc khanh",
    "phan dinh giot",
    "ngo gia tu",
    "hoang van thu",
    "thich quang duc",
    "vo minh duc",
    "lao cai",
    "lo chen",
    "vo van kiet",
)

_NON_LOCATION_RELATION_PREFIXES = (
    "bac si dien",
    "le kip",
    "le con kip",
    "le nua kip",
    "le cho kip",
    "phan giap",
    "phan nha",
    "vo nha",
    "vo thoai",
    "ly tuong",
    "ngo truoc",
    "le c dat",
    "nguyen ch hang",
    "nguyen chi dat",
    "ho va dat",
    "le dat",
    "phan ho van",
    "ho ca san",
    "ho van long",
    "vo va mat tien nhua",
    "do khong",
)

_GENERIC_LANDMARK_PREFIXES = (
    "dong duc",
    "dong dan",
    "hien huu",
    "on dinh",
    "an ninh",
    "an nin",
    "nha lau",
    "yen tinh",
    "kin",
    "van minh",
    "song",
    "thiet ke",
    "ten tinh",
    "moi trung tam",
    "o kin",
    "van phong",
    "xay dung",
    "abc",
    "hoan thien",
)

_GENERIC_LANDMARK_NAMES = {
    "dong",
}

_KNOWN_LANDMARK_PREFIXES = (
    ("my phuoc 3 ben cat", "my phuoc 3"),
    ("my phuoc iii", "my phuoc 3"),
    ("my phuoc 3", "my phuoc 3"),
    ("rach bap", "rach bap"),
    ("chanh nghia", "chanh nghia"),
    ("chanh nghi", "chanh nghia"),
    ("hiep thanh 1", "hiep thanh 1"),
    ("hiep thanh i ", "hiep thanh 1"),
    ("hiep thanh 2", "hiep thanh 2"),
    ("hiep thanh ii", "hiep thanh 2"),
    ("hiep thanh 3", "hiep thanh 3"),
    ("hiep thanh iii", "hiep thanh 3"),
    ("ht1", "hiep thanh 1"),
    ("ht2", "hiep thanh 2"),
    ("ht3", "hiep thanh 3"),
    ("k8", "k8 thanh le"),
    ("hiep phat 1", "hiep phat 1"),
    ("hiep phat 2", "hiep phat 2"),
    ("hiep phat", "hiep phat"),
    ("phu hoa 1", "phu hoa 1"),
    ("phu hoa 2", "phu hoa 2"),
    ("hoang nam 2", "hoang nam 2"),
    ("tuong binh hiep", "tuong binh hiep"),
    ("p dinh hoa", "dinh hoa"),
    ("dinh hoa", "dinh hoa"),
    ("thanh le", "thanh le"),
    ("becamex dinh hoa", "becamex dinh hoa"),
    ("hud chanh my", "chanh my"),
    ("sinh thai chanh my", "chanh my"),
    ("chanh my", "chanh my"),
)

_KNOWN_EXPLICIT_LANDMARKS = (
    ("pho di bo bach dang", "pho di bo bach dang"),
    ("cho chanh my", "cho chanh my"),
)


def _bounded_evidence(title: str, description: str) -> str:
    evidence = " — ".join(
        part.strip() for part in (title or "", description or "") if part.strip()
    )
    return evidence[:180]


def _distance(text: str) -> float | None:
    match = _DISTANCE_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _cut_at_stop(value: str, stop_re: re.Pattern[str]) -> str:
    match = stop_re.search(value)
    if match:
        value = value[: match.start()]
    return " ".join(value.strip(" -_,.;:").split())


def _normalize_road_candidate(value: str) -> str:
    candidate = " ".join(value.strip().split())
    if re.match(
        r"^dai\s+lo\s+\d{1,4}(?:\s+\d+)?\s*m(?:\s*2\b|\b)",
        candidate,
        re.IGNORECASE,
    ):
        return ""
    if re.match(
        r"^\d{1,2}\s+\d{1,2}\s*m\b",
        candidate,
        re.IGNORECASE,
    ):
        return ""
    if re.match(
        r"^(?:duong\s+)?nhua\s+\d{1,2}\s+(?:xe|o\s*to)\b",
        candidate,
        re.IGNORECASE,
    ):
        return ""
    if re.match(
        r"^(?:nhua|be\s*tong|dat)\s+\d{1,2}(?:\s+\d+)?\s*(?:m|met)\b",
        candidate,
        re.IGNORECASE,
    ):
        return ""
    if re.match(
        r"^(?:duong\s+)?(?:dx|db|dh|dt|dl|tl|ql|nl|ni|n|d)\s*"
        r"[-./_]?\s*0*\d{1,2}\s+(?:m|met)\b",
        candidate,
        re.IGNORECASE,
    ):
        return ""
    if candidate.startswith(_NON_LOCATION_RELATION_PREFIXES):
        return ""
    if candidate.startswith(("cmt8", "cmt 8", "cach mang thang 8")):
        return "cach mang thang tam"
    if candidate.startswith("ntmk"):
        return "nguyen thi minh khai"
    if candidate.startswith(("dai lo bd", "dai lo b d")):
        return "dai lo binh duong"
    if re.match(r"^vanh(?:\s+dai)?\s+4\b", candidate, re.IGNORECASE):
        return "vanh dai 4"
    if candidate.startswith(("dl binh duong", "dl bd")):
        return "dai lo binh duong"
    if candidate.startswith("mptv"):
        return "my phuoc tan van"
    if candidate.startswith("hvl"):
        return "huynh van luy"
    if candidate.startswith("lhp"):
        return "le hong phong"
    if re.match(r"^quoc\s+lo\s*13\b", candidate, re.IGNORECASE):
        return "dai lo binh duong"
    if candidate.startswith("dai lo binh"):
        return "dai lo binh duong"
    if candidate.startswith(("yersin", "yesin", "bac si yersin")):
        return "bac si yersin"
    if candidate.startswith("ho van con"):
        return "ho van cong"
    if candidate.startswith("nguyen chi than"):
        return "nguyen chi thanh"
    if candidate.startswith("nguyen tri phuon"):
        return "nguyen tri phuong"
    if candidate.startswith("bui quoc khach"):
        return "bui quoc khanh"
    if candidate.startswith("phan di dat"):
        return "phan dinh giot"
    if candidate.startswith("tran ngoc lien"):
        return "tran ngoc len"
    if candidate.startswith("duc canh"):
        return "nguyen duc canh"
    if candidate == "huynh thi" or candidate.startswith("huynh thi nha"):
        return "huynh thi hieu"
    if candidate.startswith(("phan dang l ", "phan dang nha ")):
        return "phan dang luu"
    if candidate.startswith("quoc lo 1 phut"):
        return ""
    for leading_noise in (
        "pho ",
        "hem duong ",
        "hem ",
        "duong lon ",
        "duong ",
        "lon ",
        "nhua ",
    ):
        if candidate.startswith(leading_noise):
            stripped_candidate = _normalize_road_candidate(
                candidate[len(leading_noise) :]
            )
            if _looks_like_road_name(stripped_candidate):
                return stripped_candidate
    if candidate.startswith("huynh thi h "):
        return "huynh thi hieu"
    if candidate.startswith("le chi"):
        return "le chi dan"
    if candidate.startswith("le ch"):
        return "le chi dan"
    if candidate.startswith("nguyen chi t"):
        return "nguyen chi thanh"
    if candidate.startswith("nguyen thi minh "):
        return "nguyen thi minh khai"
    if candidate.startswith("nguyen thai "):
        return "nguyen thai binh"
    if candidate.startswith("le hong "):
        return "le hong phong"
    if candidate.startswith("d "):
        stripped_candidate = _normalize_road_candidate(candidate[2:])
        if _looks_like_road_name(stripped_candidate):
            return stripped_candidate
    if candidate.startswith("pham ngoc"):
        return normalize_road_token("pham ngoc thach")
    for known_name in _KNOWN_ROAD_PREFIXES:
        if candidate.startswith(known_name):
            return normalize_road_token(known_name)

    if re.match(r"^huyn(?:\s|$)", candidate):
        return ""

    alley_named_road = re.match(
        r"^(?:hem|nhanh)\s+\d{1,4}\s+(?:duong\s+)?"
        r"(?P<road>[a-z][a-z0-9\s]{2,80})",
        candidate,
        re.IGNORECASE,
    )
    if alley_named_road:
        named_road = _normalize_road_candidate(alley_named_road.group("road"))
        if _looks_like_road_name(named_road):
            return named_road
        return ""

    local_ward_road = re.match(
        r"^(?P<ward>phu\s+an|an\s+dien)\s+"
        r"(?P<number>0*\d{1,3})\b",
        candidate,
        re.IGNORECASE,
    )
    if local_ward_road:
        return normalize_road_token(
            f"{local_ward_road.group('ward')} {local_ward_road.group('number')}"
        )

    code_match = _ROAD_CODE_RE.match(candidate)
    if code_match:
        if code_match.group("suffix").lower() == "m":
            return ""
        code_prefix = code_match.group("prefix").lower()
        code_number = int(code_match.group("number"))
        is_dt7a = (
            code_prefix == "dt"
            and code_number == 7
            and code_match.group("suffix").lower() == "a"
        )
        if code_prefix == "dt" and not (700 <= code_number <= 799 or is_dt7a):
            return ""
        if (
            code_prefix in {
                "dx", "da", "db", "dh", "dl", "na", "nb", "ne", "nf",
                "nh", "nj", "nk", "nl", "ni", "dj", "dk", "n", "d",
            }
            and code_number > 999
        ):
            return ""
        raw = (
            f"{code_match.group('prefix')} "
            f"{code_number}{code_match.group('suffix')}"
        )
        normalized = normalize_road_token(raw)
        if normalized in {"ql 13", "quoc lo 13"}:
            return "dai lo binh duong"
        return normalized

    slash_date_match = re.match(
        r"^(?:duong\s+)?30\s*(?:/|thang\s*)?\s*4\b", candidate, re.IGNORECASE
    )
    if slash_date_match:
        return normalize_road_token("duong 30 thang 4")

    local_road_match = re.match(
        r"^(?P<prefix>phu an|an dien|tan dinh|hoa loi)\s+"
        r"(?P<number>\d{1,3})\b",
        candidate,
        re.IGNORECASE,
    )
    if local_road_match:
        return normalize_road_token(
            f"{local_road_match.group('prefix')} "
            f"{local_road_match.group('number')}"
        )

    alley_number_named_road = re.match(
        r"^\d{1,4}\s+(?P<road>[a-z][a-z0-9\s]{2,80})",
        candidate,
        re.IGNORECASE,
    )
    if alley_number_named_road:
        named_road = _normalize_road_candidate(alley_number_named_road.group("road"))
        starts_with_admin_area = bool(
            re.match(
                r"^(?:tuong binh hiep|dinh hoa|tan an|hiep an|phu tan|"
                r"phu hoa|phu loi|phu my|hiep thanh|chanh nghia|"
                r"chanh my|phu tho|phu cuong|hoa phu|thu dau mot)\b",
                named_road,
                re.IGNORECASE,
            )
        )
        if not starts_with_admin_area and _looks_like_road_name(named_road):
            return named_road

    number_match = _NUMBERED_ROAD_RE.match(candidate)
    if number_match:
        if number_match.group("suffix").lower() == "m":
            return ""
        suffix_context = candidate[number_match.end() :]
        explicit_numbered = bool(
            re.match(r"^(?:duong\s+)?so\s+", candidate, re.IGNORECASE)
        )
        if re.match(r"\s*(?:m|met)\b", suffix_context, re.IGNORECASE):
            return ""
        if not explicit_numbered and re.match(
            r"\s+(?:xe|o\s*to)\b",
            suffix_context,
            re.IGNORECASE,
        ):
            return ""
        if int(number_match.group("number")) > 500:
            return ""
        return (
            f"duong so {int(number_match.group('number'))}"
            f"{number_match.group('suffix').lower()}"
        )

    candidate = _cut_at_stop(candidate, _ROAD_STOP_RE)
    if candidate == "huynh thi":
        return "huynh thi hieu"
    if candidate in {"phan dang l", "phan dang"}:
        return "phan dang luu"
    if candidate.startswith("quoc lo 14 "):
        return "ql 14"
    words = candidate.split()
    if not words:
        return ""
    candidate = " ".join(words[:8])
    if candidate in _NON_ROAD_NAMES or len(candidate) < 3:
        return ""
    normalized = normalize_road_token(candidate)
    if normalized in {"ql 13", "quoc lo 13"}:
        return "dai lo binh duong"
    return normalized


def _looks_like_road_name(road: str) -> bool:
    if not road:
        return False
    if re.match(
        r"^(?:dx|da|d|db|dh|dt|dl|tl|ql|na|nb|ne|nf|nh|nj|nk|nl|ni|dj|dk|n)\b",
        road,
    ):
        return bool(
            re.match(
                r"^(?:dx|da|d|db|dh|dt|dl|tl|ql|na|nb|ne|nf|nh|nj|nk|nl|ni|dj|dk|n)"
                r"\s+\d{1,4}[a-z]?\b",
                road,
            )
        )
    if _ROAD_NAME_HINT_RE.match(road):
        return len(road.split()) >= 2
    return False


def _road_after(text: str, start: int) -> str:
    value = text[start : start + 100]
    value = re.sub(
        r"^\s*\d{1,4}(?:[.,]\d+)?\s*m\b\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return _normalize_road_candidate(value)


def _relation_road(
    text: str,
    prefix_re: re.Pattern[str],
) -> tuple[str, re.Match[str] | None]:
    for match in prefix_re.finditer(text):
        prefix_context = text[max(0, match.start() - 12) : match.start()]
        if (
            match.group(0).strip().lower() == "ke"
            and re.search(r"\bthiet\s*$", prefix_context)
        ):
            continue
        if (
            match.group(0).strip().lower() == "nhanh"
            and re.search(r"\bket\s+noi\s*$", prefix_context)
        ):
            continue
        road = _road_after(text, match.end())
        has_explicit_road_word = "duong" in match.group(0).lower()
        prefix = match.group(0).strip().lower()
        is_numbered_road = bool(
            re.fullmatch(r"duong so \d{1,4}[a-z]?", road or "")
        )
        is_unqualified_number = (
            not has_explicit_road_word
            and is_numbered_road
            and not (prefix_re is _ALLEY_PREFIX_RE and prefix.startswith("hem"))
        )
        if is_unqualified_number:
            continue
        if road and (has_explicit_road_word or _looks_like_road_name(road)):
            return road, match
    return "", None


def _known_named_road(text: str) -> str:
    if re.search(r"\bntmk\b", text, re.IGNORECASE):
        return normalize_road_token("nguyen thi minh khai")
    if re.search(r"\bcmt\s*8\b", text, re.IGNORECASE):
        return normalize_road_token("cach mang thang tam")
    for known_name in _KNOWN_ROAD_PREFIXES:
        known_match = re.search(
            rf"\b{re.escape(known_name)}\b",
            text,
            re.IGNORECASE,
        )
        if not known_match:
            continue
        prefix_context = text[
            max(0, known_match.start() - 35) : known_match.start()
        ]
        if re.search(
            r"\b(?:truong|thcs|thpt|tieu hoc|mam non)(?:\s+\w+){0,2}\s*$",
            prefix_context,
        ):
            continue
        return normalize_road_token(known_name)
    return ""


def _direct_road(text: str, *, include_known_fallback: bool = True) -> str:
    for match in _DIRECT_PREFIX_RE.finditer(text):
        prefix_context = text[max(0, match.start() - 20) : match.start()]
        if match.group(0).strip().lower() == "duong" and re.search(
            r"\bbinh\s*$",
            prefix_context,
        ):
            continue
        if re.search(
            r"\b(?:cach|gan|sat|ke|canh|ra|thong ra|noi ra)\s*$",
            prefix_context,
        ):
            continue
        road = _road_after(text, match.end())
        if road and _looks_like_road_name(road):
            return road

    numbered_address = re.search(
        r"\b\d{1,4}\s+(?P<road>dai\s+lo\s+b\s*d)\b",
        text,
        re.IGNORECASE,
    )
    if numbered_address:
        return _normalize_road_candidate(numbered_address.group("road"))

    code_match = re.search(
        r"\b(?:dx|da|db|dh|dt|dl|tl|ql|na|nb|ne|nf|nh|nj|nk|nl|ni|dj|dk)"
        r"\s*[-./_]?\s*0*\d{1,4}[a-z]?\b",
        text,
    )
    if code_match:
        prefix_context = text[max(0, code_match.start() - 28) : code_match.start()]
        suffix_context = text[code_match.end() : code_match.end() + 8]
        is_road_width = bool(
            re.match(r"\s+(?:m|met)\b", suffix_context, re.IGNORECASE)
        )
        if not is_road_width and not re.search(
            r"\b(?:cach|gan|sat|ke|canh|ra|thong ra|noi ra|nhanh|hem|"
            r"1 xec|1 xet|1 sec|1 set)\s+(?:duong\s+)?$",
            prefix_context,
        ):
            return _normalize_road_candidate(code_match.group(0))
    return _known_named_road(text) if include_known_fallback else ""


def _landmark(text: str) -> str:
    for phrase, canonical in _KNOWN_EXPLICIT_LANDMARKS:
        if re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE):
            return canonical
    match = _LANDMARK_RE.search(text)
    if not match:
        return ""
    name = _cut_at_stop(match.group("name"), _LANDMARK_STOP_RE)
    if not name:
        return ""
    normalized_name = normalize_location_token(name)
    if (
        normalized_name in _GENERIC_LANDMARK_NAMES
        or normalized_name.startswith(_GENERIC_LANDMARK_PREFIXES)
    ):
        return ""
    kind = match.group("kind").lower()
    if kind == "tai dinh cu":
        kind = "tdc"
    elif kind == "khu dan cu":
        kind = "kdc"
    if kind == "tdc" and normalized_name.startswith("phu my"):
        normalized_name = "phu my"
    for prefix, canonical in _KNOWN_LANDMARK_PREFIXES:
        if normalized_name.startswith(prefix):
            normalized_name = canonical
            break
    return normalize_location_token(f"{kind} {normalized_name}")


def extract_map_location_context(
    title: str,
    description: str,
    stored_road_name: str = "",
) -> MapLocationContext:
    """Extract map-only location clues without mutating canonical listing data."""
    combined = " ".join(part for part in (title or "", description or "") if part)
    combined = re.sub(
        r"\b30\s*/\s*0?4\b",
        "30 thang 4",
        combined,
        flags=re.IGNORECASE,
    )
    # Listings sometimes duplicate the road introducer ("duong duong 30/04").
    # Collapse only that introducer so the numbered-road parser sees the full
    # date name instead of stopping at the second generic "duong" token.
    combined = re.sub(
        r"\bduong\s+duong\s+(?=30\s+thang\s+0?4\b)",
        "duong ",
        combined,
        flags=re.IGNORECASE,
    )
    combined = re.sub(
        r"\b\d+\s*/\s*(?=[^\W\d_])",
        " hem ",
        combined,
        flags=re.IGNORECASE,
    )
    folded = normalize_location_token(combined)
    evidence = _bounded_evidence(title, description)
    # Keep title/description boundaries for landmarks so a short place name at
    # the end of the title cannot absorb the opening marketing copy from the
    # description after whitespace normalization.
    landmark = _landmark(normalize_location_token(title or "")) or _landmark(
        normalize_location_token(description or "")
    )

    explicit_direct_road = _direct_road(folded, include_known_fallback=False)
    direct_road = explicit_direct_road or _known_named_road(folded)
    alley_road, _ = _relation_road(folded, _ALLEY_PREFIX_RE)
    if alley_road:
        if not re.fullmatch(r"duong so \d{1,4}[a-z]?", alley_road):
            return MapLocationContext(
                nearby_road=alley_road,
                landmark=landmark,
                relation="alley",
                distance_m=_distance(folded),
                evidence_text=evidence,
            )
        named_parent_road = _known_named_road(folded)
        parent_road = named_parent_road or direct_road
        if parent_road and parent_road != alley_road:
            return MapLocationContext(
                nearby_road=parent_road,
                landmark=landmark,
                relation="alley",
                distance_m=_distance(folded),
                evidence_text=evidence,
            )
        nearby_road, _ = _relation_road(folded, _NEAR_PREFIX_RE)
        if nearby_road:
            return MapLocationContext(
                nearby_road=nearby_road,
                landmark=landmark,
                relation="near",
                distance_m=_distance(folded),
                evidence_text=evidence,
            )
        return MapLocationContext(
            nearby_road=alley_road,
            landmark=landmark,
            relation="alley",
            distance_m=_distance(folded),
            evidence_text=evidence,
        )

    nearby_road, _ = _relation_road(folded, _NEAR_PREFIX_RE)
    if explicit_direct_road:
        return MapLocationContext(
            direct_road=explicit_direct_road,
            nearby_road=nearby_road,
            landmark=landmark,
            relation="near" if nearby_road else "on",
            evidence_text=evidence,
        )

    if nearby_road:
        return MapLocationContext(
            nearby_road=nearby_road,
            landmark=landmark,
            relation="near",
            distance_m=_distance(folded),
            evidence_text=evidence,
        )

    if not direct_road and stored_road_name:
        stored_candidate = _normalize_road_candidate(
            normalize_location_token(stored_road_name)
        )
        is_unqualified_listing_code = re.fullmatch(
            r"d\s+\d{3,4}[a-z]?",
            stored_candidate or "",
        ) and not re.search(
            rf"\b(?:duong|mat tien|mt)\s+{re.escape(stored_candidate)}\b",
            folded,
        )
        if is_unqualified_listing_code:
            stored_candidate = ""
        if _looks_like_road_name(stored_candidate):
            direct_road = stored_candidate

    return MapLocationContext(
        direct_road=direct_road,
        landmark=landmark,
        relation="on" if direct_road else ("at" if landmark else ""),
        evidence_text=evidence,
    )
