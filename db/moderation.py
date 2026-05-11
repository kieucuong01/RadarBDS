"""Moderation helpers for admin control room."""
import re
from typing import Optional


def normalize_phone(phone: Optional[str]) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return ""
    if digits.startswith("84") and len(digits) >= 11:
        digits = "0" + digits[2:]
    if len(digits) >= 9:
        return digits[-9:]
    return digits


def is_phone_blacklisted(conn, phone: Optional[str]) -> tuple[bool, str]:
    norm = normalize_phone(phone)
    if not norm:
        return False, ""
    row = conn.execute(
        "SELECT phone_norm FROM broker_blacklist WHERE active=1 AND phone_norm=?",
        (norm,),
    ).fetchone()
    return (row is not None), norm
