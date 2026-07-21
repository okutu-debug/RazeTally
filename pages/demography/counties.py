import urllib.parse

import pandas as pd
import streamlit as st

from db import (
    add_county,
    bulk_upsert_counties,
    count_counties,
    delete_county,
    get_county,
    list_counties,
    update_county,
)
from theme import apply_theme, clear_query_params_url

apply_theme()

PAGE_SIZE = 25
_REQUIRED_COLS = {"county_id", "county_name"}

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Counties</h4>",
    unsafe_allow_html=True,
)


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Edit county")
def _edit_dialog(county_id: str):
    county = get_county(int(county_id))
    if not county:
        st.error("County not found.")
        st.stop()

    new_id   = st.number_input("County ID", min_value=1, step=1, value=int(county["county_id"]))
    new_name = st.text_input("County name", value=county["county_name"] or "")

    col_save, col_cancel = st.columns(2)
    if col_save.button("Save", type="primary", use_container_width=True):
        if not new_name.strip():
            st.error("County name is required.")
        else:
            try:
                update_county(int(county_id), int(new_id), new_name.strip())
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"County ID '{new_id}' is already in use.")
                else:
                    st.error(f"Failed to update: {e}")
    if col_cancel.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(county_id: str):
    county = get_county(int(county_id))
    name = county["county_name"] if county else county_id
    st.write(f"Delete county **{name}**? This also deletes all of its constituencies and wards. "
             f"This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_county(int(county_id))
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Add county")
def _add_dialog():
    with st.form("dlg_add_county_form"):
        county_id   = st.number_input("County ID *", min_value=1, step=1, value=1)
        county_name = st.text_input("County name *")
        submitted   = st.form_submit_button("Add county", type="primary", use_container_width=True)

    if submitted:
        if not county_name.strip():
            st.error("County name is required.")
        else:
            try:
                add_county(int(county_id), county_name.strip())
                st.success(f"County '{county_name}' added.")
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"County ID '{county_id}' already exists.")
                else:
                    st.error(f"Failed: {e}")


@st.dialog("Bulk import counties", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{"county_id": 1, "county_name": "MOMBASA"}])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="counties_template.csv", mime="text/csv",
    )

    if "counties_upload_key" not in st.session_state:
        st.session_state.counties_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"counties_bulk_{st.session_state.counties_upload_key}",
    )

    if not uploaded:
        return

    try:
        df = pd.read_csv(uploaded, dtype=str).fillna("")
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        st.error(f"Missing required columns: {', '.join(sorted(missing))}")
        return

    st.caption(f"{len(df)} row(s) — preview:")
    st.dataframe(df.head(200), use_container_width=True, hide_index=True)

    if st.button("Import counties", type="primary", use_container_width=True):
        rows, errors = [], []
        for idx, row in df.iterrows():
            line = idx + 2
            name = str(row.get("county_name", "") or "").strip()
            raw_id = str(row.get("county_id", "") or "").strip()
            if not raw_id or not name:
                errors.append(f"Row {line}: county_id and county_name are required.")
                continue
            try:
                cid = int(float(raw_id))
            except ValueError:
                errors.append(f"Row {line} ('{name}'): county_id must be a number.")
                continue
            rows.append({"county_id": cid, "county_name": name})

        if rows:
            try:
                inserted, updated = bulk_upsert_counties(rows)
                st.success(f"Imported {inserted} new and updated {updated} existing county(ies).")
            except Exception as e:
                st.error(f"Import failed: {e}")
        if errors:
            st.error("\n\n".join(errors))
        if rows:
            st.session_state.counties_upload_key += 1
            st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_CONSUMED = "_counties_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_dialog: tuple | None = None
_url_key = None

if st.query_params.get("edit_county"):
    _url_key = ("edit", st.query_params["edit_county"])
elif st.query_params.get("delete_county"):
    _url_key = ("delete", st.query_params["delete_county"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Main card: toolbar + search + table ────────────────────────────────────────
with st.container(key="card_counties"):
    col_a, col_b, col_search = st.columns([1.8, 1.8, 4.4])
    if col_a.button("➕ Add county", use_container_width=True) and _dialog is None:
        _dialog = ("add", None)
    if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
        _dialog = ("bulk", None)

    if "counties_page" not in st.session_state:
        st.session_state.counties_page = 0

    def _reset_page():
        st.session_state.counties_page = 0

    search = col_search.text_input(
        "Search", placeholder="Search by county name or ID",
        label_visibility="collapsed", key="counties_search", on_change=_reset_page,
    )

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "add":    _add_dialog()
        elif kind == "bulk":   _bulk_import_dialog()

    total = count_counties(search)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state.counties_page = min(st.session_state.counties_page, total_pages - 1)
    page = st.session_state.counties_page

    counties = list_counties(search, limit=PAGE_SIZE, offset=page * PAGE_SIZE)

    if not counties:
        st.info("No counties found.")
    else:
        rows_html = ""
        for c in counties:
            def _safe(v):
                text = str(v) if v is not None else ""
                return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
            enc = urllib.parse.quote(str(c["county_id"]), safe="")
            rows_html += f"""<tr>
                <td>{_safe(c['county_id'])}</td>
                <td>{_safe(c['county_name'])}</td>
                <td>{_safe(c['constituency_count'])}</td>
                <td class="actions-cell">
                    <a class="edit-btn" href="?edit_county={enc}" target="_top">✏ Edit</a>
                    <a class="del-btn"  href="?delete_county={enc}" target="_top">🗑 Delete</a>
                </td>
            </tr>"""

        st.html(f"""
        <style>
            .stn-tbl-wrap{{overflow-x:auto;width:100%}}
            .stn-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
            .stn-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
            .stn-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;max-width:260px;overflow:hidden;text-overflow:ellipsis}}
            .stn-tbl tr:hover td{{background:#f9fafb}}
            .actions-cell{{white-space:nowrap;display:flex;gap:6px;align-items:center}}
            .edit-btn,.del-btn{{border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block}}
            .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
            .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        </style>
        <div class="stn-tbl-wrap">
            <table class="stn-tbl">
                <thead><tr>
                    <th>ID</th><th>County name</th><th>Constituencies</th><th>Actions</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)

        col_prev, col_info, col_next = st.columns([1, 3, 1])
        if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True):
            st.session_state.counties_page -= 1
            st.rerun()
        col_info.markdown(
            f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} county(ies)</div>",
            unsafe_allow_html=True,
        )
        if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True):
            st.session_state.counties_page += 1
            st.rerun()
