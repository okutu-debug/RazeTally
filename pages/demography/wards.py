import urllib.parse

import pandas as pd
import streamlit as st

from db import (
    add_ward,
    bulk_upsert_wards,
    count_wards,
    delete_ward,
    get_ward,
    list_all_constituencies,
    list_wards,
    update_ward,
)
from theme import apply_theme, clear_query_params_url

apply_theme()

PAGE_SIZE = 25
_REQUIRED_COLS = {"ward_id", "ward_name", "constituency_id"}

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Wards</h4>",
    unsafe_allow_html=True,
)


def _constituency_options() -> tuple[list[int], dict[int, str]]:
    constituencies = list_all_constituencies()
    ids = [c["constituency_id"] for c in constituencies]
    labels = {
        c["constituency_id"]: f"{c['constituency_name']} — {c['county_name']} ({c['constituency_id']})"
        for c in constituencies
    }
    return ids, labels


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Edit ward")
def _edit_dialog(ward_id: str):
    ward = get_ward(int(ward_id))
    if not ward:
        st.error("Ward not found.")
        st.stop()

    constituency_ids, constituency_labels = _constituency_options()
    if not constituency_ids:
        st.error("No constituencies exist yet. Add a constituency first.")
        st.stop()

    new_id   = st.number_input("Ward ID", min_value=1, step=1, value=int(ward["ward_id"]))
    new_name = st.text_input("Ward name", value=ward["ward_name"] or "")
    cur_idx  = (constituency_ids.index(ward["constituency_id"])
                if ward["constituency_id"] in constituency_ids else 0)
    constituency_id = st.selectbox("Constituency", constituency_ids, index=cur_idx,
                                    format_func=lambda i: constituency_labels[i])

    col_save, col_cancel = st.columns(2)
    if col_save.button("Save", type="primary", use_container_width=True):
        if not new_name.strip():
            st.error("Ward name is required.")
        else:
            try:
                update_ward(int(ward_id), int(new_id), new_name.strip(), int(constituency_id))
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"Ward ID '{new_id}' is already in use.")
                else:
                    st.error(f"Failed to update: {e}")
    if col_cancel.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(ward_id: str):
    ward = get_ward(int(ward_id))
    name = ward["ward_name"] if ward else ward_id
    st.write(f"Delete ward **{name}**? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_ward(int(ward_id))
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Add ward")
def _add_dialog():
    constituency_ids, constituency_labels = _constituency_options()
    if not constituency_ids:
        st.error("No constituencies exist yet. Add a constituency first.")
        st.stop()

    with st.form("dlg_add_ward_form"):
        ward_id   = st.number_input("Ward ID *", min_value=1, step=1, value=1)
        ward_name = st.text_input("Ward name *")
        constituency_id = st.selectbox("Constituency *", constituency_ids,
                                        format_func=lambda i: constituency_labels[i])
        submitted = st.form_submit_button("Add ward", type="primary", use_container_width=True)

    if submitted:
        if not ward_name.strip():
            st.error("Ward name is required.")
        else:
            try:
                add_ward(int(ward_id), ward_name.strip(), int(constituency_id))
                st.success(f"Ward '{ward_name}' added.")
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"Ward ID '{ward_id}' already exists.")
                else:
                    st.error(f"Failed: {e}")


@st.dialog("Bulk import wards", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{
        "ward_id": 1, "ward_name": "PORT REITZ", "constituency_id": 1,
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="wards_template.csv", mime="text/csv",
    )

    if "wards_upload_key" not in st.session_state:
        st.session_state.wards_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"wards_bulk_{st.session_state.wards_upload_key}",
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

    if st.button("Import wards", type="primary", use_container_width=True):
        rows, errors = [], []
        for idx, row in df.iterrows():
            line = idx + 2
            name = str(row.get("ward_name", "") or "").strip()
            raw_id = str(row.get("ward_id", "") or "").strip()
            raw_constituency_id = str(row.get("constituency_id", "") or "").strip()
            if not raw_id or not name or not raw_constituency_id:
                errors.append(f"Row {line}: ward_id, ward_name and constituency_id are required.")
                continue
            try:
                wid = int(float(raw_id))
                constituency_id = int(float(raw_constituency_id))
            except ValueError:
                errors.append(f"Row {line} ('{name}'): ward_id/constituency_id must be numbers.")
                continue
            rows.append({"ward_id": wid, "ward_name": name, "constituency_id": constituency_id})

        if rows:
            try:
                inserted, updated = bulk_upsert_wards(rows)
                st.success(f"Imported {inserted} new and updated {updated} existing ward(s).")
            except Exception as e:
                st.error(f"Import failed: {e}")
        if errors:
            st.error("\n\n".join(errors))
        if rows:
            st.session_state.wards_upload_key += 1
            st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_CONSUMED = "_wards_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_dialog: tuple | None = None
_url_key = None

if st.query_params.get("edit_ward"):
    _url_key = ("edit", st.query_params["edit_ward"])
elif st.query_params.get("delete_ward"):
    _url_key = ("delete", st.query_params["delete_ward"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Main card: toolbar + search + table ────────────────────────────────────────
with st.container(key="card_wards"):
    col_a, col_b, col_search = st.columns([1.8, 1.8, 4.4])
    if col_a.button("➕ Add ward", use_container_width=True) and _dialog is None:
        _dialog = ("add", None)
    if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
        _dialog = ("bulk", None)

    if "wards_page" not in st.session_state:
        st.session_state.wards_page = 0

    def _reset_page():
        st.session_state.wards_page = 0

    search = col_search.text_input(
        "Search", placeholder="Search by county, constituency, ward name or ID",
        label_visibility="collapsed", key="wards_search", on_change=_reset_page,
    )

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "add":    _add_dialog()
        elif kind == "bulk":   _bulk_import_dialog()

    total = count_wards(search)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state.wards_page = min(st.session_state.wards_page, total_pages - 1)
    page = st.session_state.wards_page

    wards = list_wards(search, limit=PAGE_SIZE, offset=page * PAGE_SIZE)

    if not wards:
        st.info("No wards found.")
    else:
        rows_html = ""
        for w in wards:
            def _safe(v):
                text = str(v) if v is not None else ""
                return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
            enc = urllib.parse.quote(str(w["ward_id"]), safe="")
            rows_html += f"""<tr>
                <td>{_safe(w['ward_id'])}</td>
                <td>{_safe(w['ward_name'])}</td>
                <td>{_safe(w['constituency_name'])}</td>
                <td>{_safe(w['county_name'])}</td>
                <td class="actions-cell">
                    <a class="edit-btn" href="?edit_ward={enc}" target="_top">✏ Edit</a>
                    <a class="del-btn"  href="?delete_ward={enc}" target="_top">🗑 Delete</a>
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
                    <th>ID</th><th>Ward name</th><th>Constituency</th><th>County</th><th>Actions</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)

        col_prev, col_info, col_next = st.columns([1, 3, 1])
        if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True):
            st.session_state.wards_page -= 1
            st.rerun()
        col_info.markdown(
            f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} ward(s)</div>",
            unsafe_allow_html=True,
        )
        if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True):
            st.session_state.wards_page += 1
            st.rerun()
