import base64
import urllib.parse

import pandas as pd
import streamlit as st

from db import (
    CANDIDATE_POSITIONS,
    bulk_upsert_candidates,
    count_candidates,
    create_candidate,
    delete_candidate,
    find_constituency_by_names,
    find_county_by_name,
    find_ward_by_names,
    get_candidate,
    get_candidate_photo_bytes,
    list_candidates,
    list_parties,
    remove_candidate_photo,
    set_candidate_photo,
    update_candidate,
)
from location_picker import location_picker
from theme import apply_theme, clear_query_params_url

apply_theme()

PAGE_SIZE = 25
_NONE_POSITION = "— Select —"
POSITION_OPTIONS = [_NONE_POSITION] + CANDIDATE_POSITIONS

# How deep the geography picker needs to go for each elective office —
# President is national (no geography); MP is constituency-level; MCA is
# ward-level; Governor/Senator/Woman Rep are county-level.
_GEO_LEVEL_BY_POSITION = {
    "President": None,
    "County Governor": "county",
    "Senator": "county",
    "County Woman Rep": "county",
    "Member of National Assembly": "constituency",
    "Member of County Assembly": "ward",
}
_GEO_CAPTION = {
    "county": "County",
    "constituency": "County / Constituency",
    "ward": "County / Constituency / Ward",
}

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Candidates</h4>",
    unsafe_allow_html=True,
)


def _party_options() -> tuple[list[int | None], dict]:
    parties = list_parties()
    ids = [None] + [p["id"] for p in parties]
    labels = {None: "— No party —", **{p["id"]: p["name"] for p in parties}}
    return ids, labels


def _render_geography(prefix: str, position: str, current: dict) -> dict:
    """Render the position-appropriate County/Constituency/Ward picker and
    return a fully-resolved {county, constituency, ward, ward_id} dict —
    never silently drops a shallower selection (e.g. county-only for a
    Governor) the way a bare three-level picker requiring a ward would."""
    level = _GEO_LEVEL_BY_POSITION.get(position, "ward")
    if level is None:
        st.caption("This office has no associated geography (national).")
        return {"county": "", "constituency": "", "ward": "", "ward_id": None}

    st.caption(_GEO_CAPTION[level])
    current_ward_id = current.get("ward_id") or find_ward_by_names(
        current.get("county"), current.get("constituency"), current.get("ward"),
    )
    current_constituency_id = find_constituency_by_names(current.get("county"), current.get("constituency"))
    current_county_id = find_county_by_name(current.get("county"))
    location = location_picker(
        prefix, current_ward_id, required_level=level,
        current_constituency_id=current_constituency_id, current_county_id=current_county_id,
    )
    if location is not None:
        return {
            "county": location.get("county") or "", "constituency": location.get("constituency") or "",
            "ward": location.get("ward") or "", "ward_id": location.get("ward_id"),
        }
    return {
        "county": current.get("county") or "", "constituency": current.get("constituency") or "",
        "ward": current.get("ward") or "", "ward_id": current.get("ward_id"),
    }


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Add candidate", width="large")
def _add_dialog():
    party_ids, party_labels = _party_options()

    name = st.text_input("Full name *")
    col1, col2, col3 = st.columns(3)
    party_id = col1.selectbox("Party", party_ids, format_func=lambda i: party_labels[i])
    position = col2.selectbox("Position", POSITION_OPTIONS)
    candidate_number = col3.text_input("Candidate number")
    photo = st.file_uploader("Photo (optional)", type=["png", "jpg", "jpeg", "webp"])

    geo = _render_geography("create_candidate", position, {})

    if st.button("Add candidate", type="primary", use_container_width=True):
        if not name.strip():
            st.error("Full name is required.")
        else:
            try:
                new_id = create_candidate(
                    name.strip(),
                    party_id=party_id,
                    position="" if position == _NONE_POSITION else position,
                    candidate_number=candidate_number.strip(),
                    county=geo["county"], constituency=geo["constituency"],
                    ward=geo["ward"], ward_id=geo["ward_id"],
                )
                if photo is not None:
                    set_candidate_photo(new_id, photo.name, photo.read())
                st.success(f"Candidate '{name}' added.")
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"'{name}' already has a candidate entry for this position.")
                else:
                    st.error(f"Failed to add candidate: {e}")


@st.dialog("Edit candidate", width="large")
def _edit_dialog(id: str):
    candidate = get_candidate(id)
    if not candidate:
        st.error("Candidate not found.")
        st.stop()

    party_ids, party_labels = _party_options()

    name = st.text_input("Full name *", value=candidate.get("name") or "")
    col1, col2, col3 = st.columns(3)
    party_index = party_ids.index(candidate.get("party_id")) if candidate.get("party_id") in party_ids else 0
    party_id = col1.selectbox("Party", party_ids, index=party_index, format_func=lambda i: party_labels[i])
    pos_index = POSITION_OPTIONS.index(candidate.get("position")) if candidate.get("position") in POSITION_OPTIONS else 0
    position = col2.selectbox("Position", POSITION_OPTIONS, index=pos_index)
    candidate_number = col3.text_input("Candidate number", value=candidate.get("candidate_number") or "")

    if candidate.get("photo"):
        photo_result = get_candidate_photo_bytes(id)
        if photo_result:
            st.image(photo_result[0], width=160)
        if st.button("🗑 Remove photo", key=f"remove_photo_{id}"):
            remove_candidate_photo(id)
            st.rerun()
    else:
        st.caption("No photo set yet.")
    photo = st.file_uploader(
        "Upload/replace photo", type=["png", "jpg", "jpeg", "webp"], key=f"photo_upload_{id}",
    )

    geo = _render_geography(f"edit_candidate_{id}", position, candidate)

    col_save, col_cancel = st.columns(2)
    if col_save.button("Save", type="primary", use_container_width=True):
        if not name.strip():
            st.error("Full name is required.")
        else:
            try:
                update_candidate(
                    id, name.strip(),
                    party_id=party_id,
                    position="" if position == _NONE_POSITION else position,
                    candidate_number=candidate_number.strip(),
                    county=geo["county"], constituency=geo["constituency"],
                    ward=geo["ward"], ward_id=geo["ward_id"],
                )
                if photo is not None:
                    set_candidate_photo(id, photo.name, photo.read())
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"'{name}' already has a candidate entry for this position.")
                else:
                    st.error(f"Failed to update: {e}")
    if col_cancel.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(id: str):
    candidate = get_candidate(id)
    name = candidate["name"] if candidate else id
    st.write(f"Remove candidate **{name}**? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, remove", type="primary", use_container_width=True):
        delete_candidate(id)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Bulk import candidates", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{
        "name": "Jane Doe", "party_name": "Sample Party", "position": "Member of County Assembly",
        "candidate_number": "1", "county": "", "constituency": "", "ward": "",
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="candidates_template.csv", mime="text/csv",
    )
    st.caption(
        "`name` and `position` are required — `position` must be one of: "
        f"{', '.join(CANDIDATE_POSITIONS)}. `party_name` is matched against existing parties "
        "(leave blank for none — bulk import won't create new parties). "
        "`county`/`constituency`/`ward` are matched against the demography reference tables "
        "where possible. Photos can't be bulk-uploaded — add them individually via **Edit**. "
        "Re-uploading a CSV updates existing candidates matched by (`name`, `position`)."
    )

    if "candidates_upload_key" not in st.session_state:
        st.session_state.candidates_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"candidates_bulk_{st.session_state.candidates_upload_key}",
    )

    if not uploaded:
        return

    try:
        df = pd.read_csv(uploaded, dtype=str).fillna("")
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    missing = {"name", "position"} - set(df.columns)
    if missing:
        st.error(f"Missing required columns: {', '.join(sorted(missing))}")
        return

    st.caption(f"{len(df)} row(s) — preview:")
    st.dataframe(df.head(200), use_container_width=True, hide_index=True)

    if st.button("Import candidates", type="primary", use_container_width=True):
        party_by_name = {p["name"]: p["id"] for p in list_parties()}
        rows, errors = [], []
        for idx, row in df.iterrows():
            line = idx + 2
            name = str(row.get("name", "") or "").strip()
            position = str(row.get("position", "") or "").strip()
            if not name or not position:
                errors.append(f"Row {line}: name and position are required.")
                continue
            if position not in CANDIDATE_POSITIONS:
                errors.append(f"Row {line} ({name}): position must be one of {CANDIDATE_POSITIONS}.")
                continue

            party_name = str(row.get("party_name", "") or "").strip()
            party_id = party_by_name.get(party_name) if party_name else None
            if party_name and party_id is None:
                errors.append(f"Row {line} ({name}): party '{party_name}' not found — leave blank or add the party first.")
                continue

            county       = str(row.get("county", "") or "").strip()
            constituency = str(row.get("constituency", "") or "").strip()
            ward         = str(row.get("ward", "") or "").strip()
            ward_id      = find_ward_by_names(county, constituency, ward) if (county and constituency and ward) else None

            rows.append({
                "name": name, "party_id": party_id, "position": position,
                "candidate_number": str(row.get("candidate_number", "") or "").strip() or None,
                "county": county or None, "constituency": constituency or None,
                "ward": ward or None, "ward_id": ward_id,
            })

        if rows:
            try:
                inserted, updated = bulk_upsert_candidates(rows)
                st.success(f"Imported {inserted} new and updated {updated} existing candidate(s).")
            except Exception as e:
                st.error(f"Import failed: {e}")
        if errors:
            st.error("\n\n".join(errors))
        if rows:
            st.session_state.candidates_upload_key += 1
            st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_CONSUMED = "_candidates_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_dialog: tuple | None = None
_url_key = None

if st.query_params.get("edit_cand"):
    _url_key = ("edit", st.query_params["edit_cand"])
elif st.query_params.get("delete_cand"):
    _url_key = ("delete", st.query_params["delete_cand"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Main card: toolbar + search + table ────────────────────────────────────────
with st.container(key="card_candidates"):
    if "cand_page" not in st.session_state:
        st.session_state.cand_page = 0

    def _reset_cand_page():
        st.session_state.cand_page = 0

    col_a, col_b, col_search = st.columns([1.8, 1.8, 5.4])

    search = col_search.text_input(
        "Search", placeholder="Search by name, county, constituency or ward",
        label_visibility="collapsed", key="cand_search", on_change=_reset_cand_page,
    )

    if col_a.button("➕ Add candidate", use_container_width=True) and _dialog is None:
        _dialog = ("add", None)
    if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
        _dialog = ("bulk", None)

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "add":    _add_dialog()
        elif kind == "bulk":   _bulk_import_dialog()

    total = count_candidates(search)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state.cand_page = min(st.session_state.cand_page, total_pages - 1)
    page = st.session_state.cand_page

    candidates = list_candidates(search, limit=PAGE_SIZE, offset=page * PAGE_SIZE)

    if not candidates:
        st.info("No candidates found. Use **+ Add candidate** or **Bulk import** to get started.")
    else:
        def _safe(v):
            text = str(v) if v not in (None, "") else "—"
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")

        def _photo_img(candidate_id) -> str:
            result = get_candidate_photo_bytes(candidate_id)
            if not result:
                return "<span style='color:#94a3b8'>—</span>"
            file_bytes, _ = result
            b64 = base64.b64encode(file_bytes).decode()
            return f"<img src='data:image/png;base64,{b64}' style='height:32px;width:32px;object-fit:cover;border-radius:50%' />"

        rows_html = ""
        for c in candidates:
            enc = urllib.parse.quote(str(c["id"]), safe="")
            location = " / ".join(v for v in (c.get("county"), c.get("constituency"), c.get("ward")) if v) or "—"
            rows_html += f"""<tr>
                <td>{_photo_img(c['id'])}</td>
                <td>{_safe(c['name'])}</td>
                <td>{_safe(c.get('party_name'))}</td>
                <td>{_safe(c.get('position'))}</td>
                <td>{_safe(c.get('candidate_number'))}</td>
                <td>{_safe(location)}</td>
                <td class="actions-cell">
                    <a class="edit-btn" href="?edit_cand={enc}" target="_top">✏ Edit</a>
                    <a class="del-btn"  href="?delete_cand={enc}" target="_top">🗑 Delete</a>
                </td>
            </tr>"""

        st.html(f"""
        <style>
            .cand-tbl-wrap{{overflow-x:auto;width:100%}}
            .cand-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
            .cand-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
            .cand-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;vertical-align:middle;max-width:220px;overflow:hidden;text-overflow:ellipsis}}
            .cand-tbl tr:hover td{{background:#f9fafb}}
            .actions-cell{{white-space:nowrap;display:flex;gap:6px;align-items:center}}
            .edit-btn,.del-btn{{border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block}}
            .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
            .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        </style>
        <div class="cand-tbl-wrap">
            <table class="cand-tbl">
                <thead><tr>
                    <th>Photo</th><th>Name</th><th>Party</th><th>Position</th>
                    <th>No.</th><th>Location</th><th>Actions</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)

        col_prev, col_info, col_next = st.columns([1, 3, 1])
        if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True):
            st.session_state.cand_page -= 1
            st.rerun()
        col_info.markdown(
            f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} candidate(s)</div>",
            unsafe_allow_html=True,
        )
        if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True):
            st.session_state.cand_page += 1
            st.rerun()
