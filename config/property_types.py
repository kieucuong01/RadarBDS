ACTIVE_PROPERTY_TYPE_LABELS = {
    "dat_nen": "Đất",
    "nha_dat": "Nhà đất",
    "chung_cu": "Chung cư",
    "nha_tro": "Nhà trọ",
}

LEGACY_PROPERTY_TYPE_ALIASES = {
    "dat_vuon": "dat_nen",
    "dat_lon": "dat_nen",
}

PROPERTY_TYPE_LABELS = ACTIVE_PROPERTY_TYPE_LABELS


def normalize_property_type(value):
    raw = str(value or "").strip()
    if not raw:
        return raw
    return LEGACY_PROPERTY_TYPE_ALIASES.get(raw, raw)


def normalize_property_types(values):
    normalized = []
    for value in values or []:
        prop_type = normalize_property_type(value)
        if prop_type and prop_type not in normalized:
            normalized.append(prop_type)
    return normalized
