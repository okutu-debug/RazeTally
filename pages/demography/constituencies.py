import urllib.parse

import pandas as pd
import streamlit as st

from db import (
    add_constituency,
    bulk_upsert_constituencies,
    count_constituencies,
    delete_constituency,
    get_constituency,
    list_all_counties,
    list_constituencies,
    update_constituency,
)
from theme import apply_theme, clear_query_params_url

apply_theme()

PAGE_SIZE = 25
_REQUIRED_COLS = {"constituency_id", "constituency_name", "county_id"}

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Constituencies</h4>",
    unsafe_allow_html=True,
)


def _county_options() -> tuple[list[int], dict[int, str]]:
    counties = list_all_counties()
    ids = [c["county_id"] for c in counties]
    labels = {c["county_id"]: f"{c['county_name']} ({c['county_id']})" for c in counties}
    return ids, labels


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Edit constituency")
def _edit_dialog(constituency_id: str):
    constituency = get_constituency(int(constituency_id))
    if not constituency:
        st.error("Constituency not found.")
        st.stop()

    county_ids, county_labels = _county_options()
    if not county_ids:
        st.error("No counties exist yet. Add a county first.")
        st.stop()

    new_id   = st.number_input("Constituency ID", min_value=1, step=1,
                                value=int(constituency["constituency_id"]))
    new_name = st.text_input("Constituency name", value=constituency["constituency_name"] or "")
    cur_idx  = county_ids.index(constituency["county_id"]) if constituency["county_id"] in county_ids else 0
    county_id = st.selectbox("County", county_ids, index=cur_idx, format_func=lambda i: county_labels[i])

    col_save, col_cancel = st.columns(2)
    if col_save.button("Save", type="primary", use_container_width=True):
        if not new_name.strip():
            st.error("Constituency name is required.")
        else:
            try:
                update_constituency(int(constituency_id), int(new_id), new_name.strip(), int(county_id))
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"Constituency ID '{new_id}' is already in use.")
                else:
                    st.error(f"Failed to update: {e}")
    if col_cancel.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(constituency_id: str):
    constituency = get_constituency(int(constituency_id))
    name = constituency["constituency_name"] if constituency else constituency_id
    st.write(f"Delete constituency **{name}**? This also deletes all of its wards. "
             f"This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_constituency(int(constituency_id))
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Add constituency")
def _add_dialog():
    county_ids, county_labels = _county_options()
    if not county_ids:
        st.error("No counties exist yet. Add a county first.")
        st.stop()

    with st.form("dlg_add_constituency_form"):
        constituency_id   = st.number_input("Constituency ID *", min_value=1, step=1, value=1)
        constituency_name = st.text_input("Constituency name *")
        county_id = st.selectbox("County *", county_ids, format_func=lambda i: county_labels[i])
        submitted = st.form_submit_button("Add constituency", type="primary", use_container_width=True)

    if submitted:
        if not constituency_name.strip():
            st.error("Constituency name is required.")
        else:
            try:
                add_constituency(int(constituency_id), constituency_name.strip(), int(county_id))
                st.success(f"Constituency '{constituency_name}' added.")
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"Constituency ID '{constituency_id}' already exists.")
                else:
                    st.error(f"Failed: {e}")


@st.dialog("Bulk import constituencies", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{
        "constituency_id": 1, "constituency_name": "CHANGAMWE", "county_id": 1,
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="constituencies_template.csv", mime="text/csv",
    )

    if "constituencies_upload_key" not in st.session_state:
        st.session_state.constituencies_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"constituencies_bulk_{st.session_state.constituencies_upload_key}",
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

    if st.button("Import constituencies", type="primary", use_container_width=True):
        rows, errors = [], []
        for idx, row in df.iterrows():
            line = idx + 2
            name = str(row.get("constituency_name", "") or "").strip()
            raw_id = str(row.get("constituency_id", "") or "").strip()
            raw_county_id = str(row.get("county_id", "") or "").strip()
            if not raw_id or not name or not raw_county_id:
                errors.append(f"Row {line}: constituency_id, constituency_name and county_id are required.")
                continue
            try:
                cid = int(float(raw_id))
                county_id = int(float(raw_county_id))
            except ValueError:
                errors.append(f"Row {line} ('{name}'): constituency_id/county_id must be numbers.")
                continue
            rows.append({"constituency_id": cid, "constituency_name": name, "county_id": county_id})

        if rows:
            try:
                inserted, updated = bulk_upsert_constituencies(rows)
                st.success(f"Imported {inserted} new and updated {updated} existing constituency(ies).")
            except Exception as e:
                st.error(f"Import failed: {e}")
        if errors:
            st.error("\n\n".join(errors))
        if rows:
            st.session_state.constituencies_upload_key += 1
            st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_CONSUMED = "_constituencies_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_dialog: tuple | None = None
_url_key = None

if st.query_params.get("edit_constituency"):
    _url_key = ("edit", st.query_params["edit_constituency"])
elif st.query_params.get("delete_constituency"):
    _url_key = ("delete", st.query_params["delete_constituency"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Main card: toolbar + search + table ────────────────────────────────────────
with st.container(key="card_constituencies"):
    col_a, col_b, col_search = st.columns([1.8, 1.8, 4.4])
    if col_a.button("➕ Add constituency", use_container_width=True) and _dialog is None:
        _dialog = ("add", None)
    if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
        _dialog = ("bulk", None)

    if "constituencies_page" not in st.session_state:
        st.session_state.constituencies_page = 0

    def _reset_page():
        st.session_state.constituencies_page = 0

    search = col_search.text_input(
        "Search", placeholder="Search by county, constituency name or ID",
        label_visibility="collapsed", key="constituencies_search", on_change=_reset_page,
    )

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "add":    _add_dialog()
        elif kind == "bulk":   _bulk_import_dialog()

    total = count_constituencies(search)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state.constituencies_page = min(st.session_state.constituencies_page, total_pages - 1)
    page = st.session_state.constituencies_page

    constituencies = list_constituencies(search, limit=PAGE_SIZE, offset=page * PAGE_SIZE)

    if not constituencies:
        st.info("No constituencies found.")
    else:
        rows_html = ""
        for c in constituencies:
            def _safe(v):
                text = str(v) if v is not None else ""
                return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
            enc = urllib.parse.quote(str(c["constituency_id"]), safe="")
            rows_html += f"""<tr>
                <td>{_safe(c['constituency_id'])}</td>
                <td>{_safe(c['constituency_name'])}</td>
                <td>{_safe(c['county_name'])}</td>
                <td>{_safe(c['ward_count'])}</td>
                <td class="actions-cell">
                    <a class="edit-btn" href="?edit_constituency={enc}" target="_top">✏ Edit</a>
                    <a class="del-btn"  href="?delete_constituency={enc}" target="_top">🗑 Delete</a>
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
                    <th>ID</th><th>Constituency name</th><th>County</th><th>Wards</th><th>Actions</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)

        col_prev, col_info, col_next = st.columns([1, 3, 1])
        if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True):
            st.session_state.constituencies_page -= 1
            st.rerun()
        col_info.markdown(
            f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} constituency(ies)</div>",
            unsafe_allow_html=True,
        )
        if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True):
            st.session_state.constituencies_page += 1
            st.rerun()
