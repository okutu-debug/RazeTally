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


def detect_form_type(pdf_path: Path) -> str | None:
    """
    Detect IEBC form type from filename prefix.
    e.g. F35A-003-017-... -> '35a',  F36A-... -> '36a'
    Returns None if unrecognised.
    """
    m = re.match(r"[Ff](\d+[Aa])", pdf_path.stem)
    if m:
        key = m.group(1).lower()
        if key in FORM_TYPE_MAP:
            return key
    return None