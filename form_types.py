"""IEBC form-type registry and filename detection."""

import re
from pathlib import Path

# Maps form type key → (forms table, votes table, human label)
FORM_TYPE_MAP = {
    "34a": ("forms_34a", "candidate_votes_34a", "President"),
    "35a": ("forms_35a", "candidate_votes_35a", "Member of National Assembly"),
    "36a": ("forms_36a", "candidate_votes_36a", "Member of County Assembly"),
    "37a": ("forms_37a", "candidate_votes_37a", "County Governor"),
    "38a": ("forms_38a", "candidate_votes_38a", "Senator"),
    "39a": ("forms_39a", "candidate_votes_39a", "County Woman Rep"),
}

# Maps form type key → (tally table, group key column, group name column)
# group_key_col = None means national/global tally (no geographic grouping)
TALLY_CONFIG = {
    "34a": ("tally_president", None,                None),
    "35a": ("tally_mp",        "constituency_code", "constituency"),
    "36a": ("tally_mca",       "ward_code",         "ward"),
    "37a": ("tally_governor",  "county_code",       "county"),
    "38a": ("tally_senator",   "county_code",       "county"),
    "39a": ("tally_woman_rep", "county_code",       "county"),
}


FORM_TYPE_CHOICES = ", ".join(f"F{k.upper()}" for k in FORM_TYPE_MAP)


def normalize_form_type(value) -> str | None:
    """
    Normalise a form-type string read off the form itself (e.g. 'Form 35A',
    'FORM 35 A', 'F35A', '35a') to a FORM_TYPE_MAP key like '35a'.
    Returns None if it isn't one of the supported types.
    """
    if not value:
        return None
    m = re.search(r"(?<!\d)(3[4-9])\s*-?\s*A(?![A-Za-z])", str(value), re.IGNORECASE)
    if m:
        key = f"{m.group(1)}a"
        if key in FORM_TYPE_MAP:
            return key
    return None


def detect_form_type(pdf_path: Path) -> str | None:
    """
    Detect IEBC form type from filename prefix — only a fallback/hint now;
    the type printed on the form (read by Claude Vision) takes precedence.
    e.g. F35A-003-017-... -> '35a',  F36A-... -> '36a'
    Returns None if unrecognised.
    """
    m = re.match(r"[Ff](\d+[Aa])", pdf_path.stem)
    if m:
        key = m.group(1).lower()
        if key in FORM_TYPE_MAP:
            return key
    return None


def canonical_form_name(form_type: str, structured: dict) -> str | None:
    """
    Standard file name (no extension) for a parsed form, built from the
    15-digit polling station code printed on it:
        018091045401702  ->  county 018, constituency 091, ward 0454,
                             polling centre 017, station 02
        form 35a         ->  'F35A-018-091-0454-017-02'
    Returns None if the code wasn't read as exactly 15 digits, or if it
    contradicts the separate county/constituency/ward codes on the form
    (a sign of a misread digit) — the caller then keeps the upload's name.
    """
    digits = re.sub(r"\D", "", str(structured.get("polling_station_code") or ""))
    if len(digits) != 15:
        return None
    parts = [digits[0:3], digits[3:6], digits[6:10], digits[10:13], digits[13:15]]

    for value, field in zip(parts[:3], ("county_code", "constituency_code", "ward_code")):
        other = re.sub(r"\D", "", str(structured.get(field) or ""))
        if other and other.zfill(len(value)) != value:
            return None

    return "-".join([f"F{form_type.upper()}", *parts])
