import base64
import urllib.parse

import pandas as pd
import streamlit as st

from db import (
    bulk_upsert_parties,
    count_parties,
    create_party,
    delete_party,
    get_party,
    get_party_logo_bytes,
    list_parties,
    remove_party_logo,
    set_party_logo,
    update_party,
)
from theme import apply_theme, clear_query_params_url

apply_theme()

PAGE_SIZE = 25

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Parties</h4>",
    unsafe_allow_html=True,
)


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Add party")
def _add_dialog():
    with st.form("dlg_add_party_form"):
        name = st.text_input("Party name *")
        logo = st.file_uploader("Logo (optional)", type=["png", "jpg", "jpeg", "webp"])
        submitted = st.form_submit_button("Add party", type="primary", use_container_width=True)
    if submitted:
        if not name.strip():
            st.error("Party name is required.")
        else:
            try:
                new_id = create_party(name.strip())
                if logo is not None:
                    set_party_logo(new_id, logo.name, logo.read())
                st.success(f"Party '{name}' added.")
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"'{name}' already exists.")
                else:
                    st.error(f"Failed to add party: {e}")


@st.dialog("Edit party")
def _edit_dialog(id: str):
    party = get_party(id)
    if not party:
        st.error("Party not found.")
        st.stop()

    name = st.text_input("Party name *", value=party.get("name") or "")

    if party.get("logo"):
        logo_result = get_party_logo_bytes(id)
        if logo_result:
            st.image(logo_result[0], width=160)
        if st.button("🗑 Remove logo", key=f"remove_logo_{id}"):
            remove_party_logo(id)
            st.rerun()
    else:
        st.caption("No logo set yet.")
    logo = st.file_uploader(
        "Upload/replace logo", type=["png", "jpg", "jpeg", "webp"], key=f"logo_upload_{id}",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button("Save", type="primary", use_container_width=True):
        if not name.strip():
            st.error("Party name is required.")
        else:
            try:
                update_party(id, name.strip())
                if logo is not None:
                    set_party_logo(id, logo.name, logo.read())
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"'{name}' already exists.")
                else:
                    st.error(f"Failed to update: {e}")
    if col_cancel.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(id: str):
    party = get_party(id)
    name = party["name"] if party else id
    st.write(f"Delete party **{name}**? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_party(id)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Bulk import parties", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{"name": "Sample Party"}])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="parties_template.csv", mime="text/csv",
    )
    st.caption(
        "`name` is the only required column. Logos can't be bulk-uploaded — "
        "add them individually via **Edit** after import."
    )

    if "parties_upload_key" not in st.session_state:
        st.session_state.parties_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"parties_bulk_{st.session_state.parties_upload_key}",
    )

    if not uploaded:
        return

    try:
        df = pd.read_csv(uploaded, dtype=str).fillna("")
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    if "name" not in df.columns:
        st.error("Missing required column: name")
        return

    st.caption(f"{len(df)} row(s) — preview:")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("Import parties", type="primary", use_container_width=True):
        names, errors = [], []
        for idx, row in df.iterrows():
            line = idx + 2
            name = str(row.get("name", "") or "").strip()
            if not name:
                errors.append(f"Row {line}: name is required.")
                continue
            names.append(name)

        if names:
            try:
                inserted, updated = bulk_upsert_parties(names)
                st.success(f"Imported {inserted} new part{'y' if inserted == 1 else 'ies'}; {updated} already existed.")
            except Exception as e:
                st.error(f"Import failed: {e}")
        if errors:
            st.error("\n\n".join(errors))
        if names:
            st.session_state.parties_upload_key += 1
            st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_CONSUMED = "_parties_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_dialog: tuple | None = None
_url_key = None

if st.query_params.get("edit_party"):
    _url_key = ("edit", st.query_params["edit_party"])
elif st.query_params.get("delete_party"):
    _url_key = ("delete", st.query_params["delete_party"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Main card: toolbar + search + table ────────────────────────────────────────
with st.container(key="card_parties"):
    if "party_page" not in st.session_state:
        st.session_state.party_page = 0

    def _reset_party_page():
        st.session_state.party_page = 0

    col_a, col_b, col_search = st.columns([1.8, 1.8, 5.4])

    search = col_search.text_input(
        "Search", placeholder="Search by party name",
        label_visibility="collapsed", key="party_search", on_change=_reset_party_page,
    )

    if col_a.button("➕ Add party", use_container_width=True) and _dialog is None:
        _dialog = ("add", None)
    if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
        _dialog = ("bulk", None)

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "add":    _add_dialog()
        elif kind == "bulk":   _bulk_import_dialog()

    total = count_parties(search)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state.party_page = min(st.session_state.party_page, total_pages - 1)
    page = st.session_state.party_page

    parties = list_parties(search, limit=PAGE_SIZE, offset=page * PAGE_SIZE)

    if not parties:
        st.info("No parties found. Use **+ Add party** or **Bulk import** to get started.")
    else:
        def _safe(v):
            text = str(v) if v not in (None, "") else "—"
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")

        def _logo_img(party_id) -> str:
            result = get_party_logo_bytes(party_id)
            if not result:
                return "<span style='color:#94a3b8'>—</span>"
            file_bytes, _ = result
            b64 = base64.b64encode(file_bytes).decode()
            return f"<img src='data:image/png;base64,{b64}' style='height:32px;width:32px;object-fit:contain;border-radius:4px' />"

        rows_html = ""
        for p in parties:
            enc = urllib.parse.quote(str(p["id"]), safe="")
            created = str(p.get("created_at") or "")[:16]
            rows_html += f"""<tr>
                <td>{_logo_img(p['id'])}</td>
                <td>{_safe(p['name'])}</td>
                <td>{_safe(created)}</td>
                <td class="actions-cell">
                    <a class="edit-btn" href="?edit_party={enc}" target="_top">✏ Edit</a>
                    <a class="del-btn"  href="?delete_party={enc}" target="_top">🗑 Delete</a>
                </td>
            </tr>"""

        st.html(f"""
        <style>
            .party-tbl-wrap{{overflow-x:auto;width:100%}}
            .party-tbl{{border-collapse:collapse;width:100%;font-family:sans-serif;font-size:14px}}
            .party-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
            .party-tbl td{{padding:9px 14px;border-bottom:1px solid #e5e7eb;color:#1f2937;vertical-align:middle}}
            .party-tbl tr:hover td{{background:#f9fafb}}
            .actions-cell{{display:flex;gap:6px;align-items:center}}
            .edit-btn,.del-btn{{border-radius:5px;padding:3px 8px;font-size:11px;text-decoration:none;display:inline-block}}
            .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
            .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        </style>
        <div class="party-tbl-wrap">
            <table class="party-tbl">
                <thead><tr><th>Logo</th><th>Name</th><th>Created</th><th>Actions</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)

        col_prev, col_info, col_next = st.columns([1, 3, 1])
        if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True):
            st.session_state.party_page -= 1
            st.rerun()
        col_info.markdown(
            f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} part{'y' if total == 1 else 'ies'}</div>",
            unsafe_allow_html=True,
        )
        if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True):
            st.session_state.party_page += 1
            st.rerun()
