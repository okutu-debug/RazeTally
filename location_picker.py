"""Shared cascading County -> Constituency -> Ward picker, backed by the
counties/constituencies/wards reference tables. Used anywhere a record needs
to be linked to the demography hierarchy (users, polling stations)."""

import streamlit as st

from db import list_all_constituencies, list_all_counties, list_all_wards

_NONE_LABEL = "— Select —"


def location_picker(
    prefix: str,
    current_ward_id: str | None,
    required_level: str = "ward",
    current_constituency_id: str | None = None,
    current_county_id: str | None = None,
) -> dict | None:
    """Render County/Constituency/Ward selects in up to three columns, defaulting
    to the chain implied by `current_ward_id` (if any) — or, for callers that
    only track a shallower level, by `current_constituency_id`/`current_county_id`.

    `required_level` ('county' | 'constituency' | 'ward', default 'ward') is the
    minimum depth the caller needs: selects beyond that depth are hidden, and a
    dict is returned as soon as that depth is picked rather than waiting for a
    full ward. Returns None if the selection hasn't reached the required depth
    (callers should treat None as "leave any existing location unchanged")."""
    counties = list_all_counties()
    constituencies = list_all_constituencies()
    wards = list_all_wards()

    county_by_id = {c["county_id"]: c for c in counties}
    constituency_by_id = {c["constituency_id"]: c for c in constituencies}
    ward_by_id = {w["ward_id"]: w for w in wards}

    cur_constituency_id = cur_county_id = None
    if current_ward_id and current_ward_id in ward_by_id:
        cur_constituency_id = ward_by_id[current_ward_id]["constituency_id"]
        cur_county_id = constituency_by_id.get(cur_constituency_id, {}).get("county_id")
    elif current_constituency_id and current_constituency_id in constituency_by_id:
        cur_constituency_id = current_constituency_id
        cur_county_id = constituency_by_id[current_constituency_id]["county_id"]
    elif current_county_id and current_county_id in county_by_id:
        cur_county_id = current_county_id

    n_cols = {"county": 1, "constituency": 2, "ward": 3}[required_level]
    cols = st.columns(n_cols)

    county_ids = [None] + [c["county_id"] for c in counties]
    county_labels = {None: _NONE_LABEL, **{c["county_id"]: c["county_name"] for c in counties}}
    county_index = county_ids.index(cur_county_id) if cur_county_id in county_ids else 0
    selected_county = cols[0].selectbox(
        "County", county_ids, index=county_index,
        format_func=lambda i: county_labels[i], key=f"{prefix}_county",
    )

    if required_level == "county":
        if not selected_county:
            return None
        co = county_by_id[selected_county]
        return {
            "ward_id": None,
            "county": co["county_name"], "county_code": co["county_id"],
            "constituency": "", "constituency_code": None,
            "ward": "", "ward_code": None,
        }

    constituency_opts = [c for c in constituencies if c["county_id"] == selected_county] if selected_county else []
    constituency_ids = [None] + [c["constituency_id"] for c in constituency_opts]
    constituency_labels = {None: _NONE_LABEL, **{c["constituency_id"]: c["constituency_name"] for c in constituency_opts}}
    cur_c_id = cur_constituency_id if selected_county == cur_county_id else None
    constituency_index = constituency_ids.index(cur_c_id) if cur_c_id in constituency_ids else 0
    selected_constituency = cols[1].selectbox(
        "Constituency", constituency_ids, index=constituency_index,
        format_func=lambda i: constituency_labels[i], key=f"{prefix}_constituency_{selected_county}",
    )

    if required_level == "constituency":
        if not selected_constituency:
            return None
        c = constituency_by_id[selected_constituency]
        co = county_by_id[selected_county]
        return {
            "ward_id": None,
            "county": co["county_name"], "county_code": co["county_id"],
            "constituency": c["constituency_name"], "constituency_code": c["constituency_id"],
            "ward": "", "ward_code": None,
        }

    ward_opts = [w for w in wards if w["constituency_id"] == selected_constituency] if selected_constituency else []
    ward_ids = [None] + [w["ward_id"] for w in ward_opts]
    ward_labels = {None: _NONE_LABEL, **{w["ward_id"]: w["ward_name"] for w in ward_opts}}
    cur_w_id = current_ward_id if selected_constituency == cur_constituency_id else None
    ward_index = ward_ids.index(cur_w_id) if cur_w_id in ward_ids else 0
    selected_ward = cols[2].selectbox(
        "Ward", ward_ids, index=ward_index,
        format_func=lambda i: ward_labels[i], key=f"{prefix}_ward_{selected_constituency}",
    )

    if not selected_ward:
        return None

    w = ward_by_id[selected_ward]
    c = constituency_by_id[selected_constituency]
    co = county_by_id[selected_county]
    return {
        "ward_id": selected_ward,
        "county": co["county_name"], "county_code": co["county_id"],
        "constituency": c["constituency_name"], "constituency_code": c["constituency_id"],
        "ward": w["ward_name"], "ward_code": w["ward_id"],
    }
