import datetime

import pandas as pd
import streamlit as st

from db import (
    PANEL_ROLES,
    add_user_document,
    count_panelists,
    create_user,
    delete_user_document,
    find_ward_by_names,
    get_user,
    get_user_document_bytes,
    list_panel_assignments_for_user,
    list_panelists,
    list_positions,
    list_user_documents,
    list_users,
    save_user_document_file,
    set_panelist_assignments,
    update_password,
    update_user_profile,
)
from location_picker import location_picker
from theme import apply_theme, clear_query_params_url

GENDER_OPTIONS = ["", "Male", "Female", "Other", "Prefer not to say"]
PANEL_ROLE_LABELS = {"chairman": "Chairman", "secretary": "Secretary", "member": "Member"}
PANELISTS_PAGE_SIZE = 25


def _documents_section(username: str, uploaded_by: str):
    """Shared list + upload UI for a panelist's attached documents (ID scans,
    certificates, etc.)."""
    st.markdown(
        "<h5 style='font-size:1.15rem !important; margin:1rem 0 0.25rem;'>Documents</h5>",
        unsafe_allow_html=True,
    )
    docs = list_user_documents(username)
    if not docs:
        st.caption("No documents attached yet.")
    else:
        for d in docs:
            col_doc, col_dl, col_del = st.columns([5, 1, 1])
            uploaded_at = str(d.get("uploaded_at") or "")[:16]
            col_doc.markdown(f"📄 **{d['title']}** — {d['original_filename']} · {uploaded_at}")
            result = get_user_document_bytes(d["id"])
            if result:
                file_bytes, display_name = result
                col_dl.download_button(
                    "⬇", file_bytes, file_name=display_name,
                    key=f"dl_doc_{username}_{d['id']}", use_container_width=True,
                )
            if col_del.button("🗑", key=f"del_doc_{username}_{d['id']}", use_container_width=True):
                delete_user_document(d["id"])
                st.rerun()

    with st.form(f"upload_doc_form_{username}", clear_on_submit=True):
        col_title, col_file = st.columns([2, 3])
        doc_title = col_title.text_input("Document title", placeholder="e.g. National ID, KCSE Certificate")
        doc_file  = col_file.file_uploader("File", label_visibility="collapsed")
        if st.form_submit_button("📎 Attach document"):
            if not doc_title.strip() or not doc_file:
                st.error("A title and a file are both required.")
            else:
                stored_name = save_user_document_file(username, doc_file.name, doc_file.read())
                add_user_document(username, doc_title.strip(), stored_name, doc_file.name, uploaded_by)
                st.success("Document attached.")
                st.rerun()


def _assignments_editor(value_key: str, widget_key: str, existing: list[dict] | None = None) -> list[dict]:
    """Editable grid of position / panel role / interview date rows. Renders
    the grid and returns the current assignments as a list of dicts."""
    position_options = [p["title"] for p in list_positions()]
    if value_key not in st.session_state:
        rows = existing or []
        st.session_state[value_key] = pd.DataFrame(
            [{
                "Position": a["position"],
                "Panel role": a["panel_role"],
                "Interview date": a["interview_date"],
            } for a in rows],
            columns=["Position", "Panel role", "Interview date"],
        )
    st.caption("Positions this panelist will interview candidates for — add a row per position.")
    st.session_state[value_key] = st.data_editor(
        st.session_state[value_key],
        num_rows="dynamic", use_container_width=True, hide_index=True, key=widget_key,
        column_config={
            "Position": st.column_config.SelectboxColumn(options=position_options, required=True),
            "Panel role": st.column_config.SelectboxColumn(
                options=PANEL_ROLES, required=True, default="member",
            ),
            "Interview date": st.column_config.DateColumn(),
        },
    )
    assignments = []
    for _, row in st.session_state[value_key].iterrows():
        position = row.get("Position")
        if not position:
            continue
        interview_date = row.get("Interview date")
        assignments.append({
            "position": position,
            "panel_role": row.get("Panel role") or "member",
            "interview_date": interview_date if pd.notna(interview_date) else None,
        })
    return assignments


apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Interview Panelists</h4>",
    unsafe_allow_html=True,
)
st.caption(
    "Panelists log in themselves to answer interview questions privately for their "
    "assigned candidates. Removing a panelist here only clears their panel assignments — "
    "it does not delete their login account."
)


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Remove from panel")
def _confirm_remove(username: str):
    st.write(
        f"Remove **{username}** from all interview panels? "
        "Their login account and answers already recorded are kept."
    )
    col1, col2 = st.columns(2)
    if col1.button("Yes, remove", type="primary", use_container_width=True):
        set_panelist_assignments(username, [])
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Reset password")
def _reset_password_dialog(username: str):
    st.write(f"Set a new password for **{username}**.")
    with st.form("dlg_reset_password_form"):
        new_pw     = st.text_input("New password", type="password")
        confirm_pw = st.text_input("Confirm new password", type="password")
        submitted  = st.form_submit_button("Reset password", type="primary", use_container_width=True)

    if submitted:
        if len(new_pw) < 6:
            st.error("Password must be at least 6 characters.")
        elif new_pw != confirm_pw:
            st.error("Passwords do not match.")
        else:
            update_password(username, new_pw)
            st.success(f"Password for '{username}' has been reset.")

    if st.button("Close", use_container_width=True):
        st.rerun()


@st.dialog("Edit panelist", width="large")
def _edit_dialog(username: str):
    user = get_user(username)
    if not user:
        st.error("Panelist not found.")
        st.stop()

    col1, col2 = st.columns(2)
    surname     = col1.text_input("Surname",     value=user.get("surname")     or "")
    other_names = col2.text_input("Other names", value=user.get("other_names") or "")

    col_e, col_o = st.columns(2)
    email      = col_e.text_input("Email", value=user.get("email") or "")
    occupation = col_o.text_input("Occupation", value=user.get("occupation") or "")

    col5, col6 = st.columns(2)
    id_passport_number = col5.text_input("ID/Passport number", value=user.get("id_passport_number") or "")
    phone_number       = col6.text_input("Phone number",       value=user.get("phone_number") or "")

    col7, col8 = st.columns(2)
    gender_idx   = GENDER_OPTIONS.index(user.get("gender")) if user.get("gender") in GENDER_OPTIONS else 0
    gender       = col7.selectbox("Gender", GENDER_OPTIONS, index=gender_idx)
    date_of_birth = col8.date_input(
        "Date of birth", value=user.get("date_of_birth"),
        min_value=datetime.date(1900, 1, 1), max_value=datetime.date.today(),
    )

    current_ward_id = user.get("ward_id") or find_ward_by_names(
        user.get("county"), user.get("sub_county"), user.get("ward"),
    )
    st.caption("County / Constituency (Sub-county) / Ward")
    location = location_picker(f"edit_panelist_{username}", current_ward_id)
    if location is None:
        st.caption(
            f"Currently unlinked: {user.get('county') or '—'} / "
            f"{user.get('sub_county') or '—'} / {user.get('ward') or '—'}. "
            "Pick all three levels above to (re)link this profile."
        )

    assignments_key = f"dlg_ep_assignments_df_{username}"
    assignments = _assignments_editor(
        assignments_key, f"dlg_ep_assignments_widget_{username}",
        list_panel_assignments_for_user(username),
    )

    col3, col4 = st.columns(2)
    if col3.button("Save", type="primary", use_container_width=True):
        loc = location or {
            "county": user.get("county"), "constituency": user.get("sub_county"),
            "ward": user.get("ward"), "ward_id": user.get("ward_id"),
        }
        update_user_profile(
            username, other_names, surname, email, position=user.get("position") or "",
            id_passport_number=id_passport_number, phone_number=phone_number,
            gender=gender, date_of_birth=date_of_birth,
            county=loc["county"] or "", sub_county=loc["constituency"] or "", ward=loc["ward"] or "",
            ward_id=loc["ward_id"], occupation=occupation,
        )
        set_panelist_assignments(username, assignments)
        del st.session_state[assignments_key]
        st.rerun()
    if col4.button("Cancel", use_container_width=True):
        del st.session_state[assignments_key]
        st.rerun()

    _documents_section(username, uploaded_by=st.session_state.username)


@st.dialog("Add panelist", width="large")
def _create_dialog():
    existing_panelist_usernames = {p["username"] for p in list_panelists()}
    linkable_users = [u for u in list_users() if u["username"] not in existing_panelist_usernames]

    account_mode = st.radio(
        "Panelist account", ["Create new account", "Use an existing user account"],
        key="dlg_cp_mode", horizontal=True,
    )

    location = None
    selected_existing = ""
    if account_mode == "Use an existing user account":
        if not linkable_users:
            st.info("Every existing user is already a panelist.")
        else:
            labels = {"": "— Select —", **{
                u["username"]: f"{u.get('surname') or ''} {u.get('other_names') or ''} ({u['username']})".strip()
                for u in linkable_users
            }}
            selected_existing = st.selectbox(
                "Existing user", [""] + [u["username"] for u in linkable_users],
                format_func=lambda u: labels[u], key="dlg_cp_existing",
            )
    else:
        st.caption("County / Constituency (Sub-county) / Ward")
        location = location_picker("create_panelist", None)

    assignments = _assignments_editor("dlg_cp_assignments_df", "dlg_cp_assignments_widget")

    if account_mode == "Create new account":
        with st.form("dlg_create_panelist_form"):
            col1, col2 = st.columns(2)
            username   = col1.text_input("Username *")
            email      = col2.text_input("Email")
            col3, col4 = st.columns(2)
            surname     = col3.text_input("Surname")
            other_names = col4.text_input("Other names")
            col5, col6 = st.columns(2)
            password   = col5.text_input("Password *", type="password")
            confirm    = col6.text_input("Confirm password *", type="password")

            col7, col8 = st.columns(2)
            id_passport_number = col7.text_input("ID/Passport number")
            phone_number       = col8.text_input("Phone number")

            col9, col10 = st.columns(2)
            gender        = col9.selectbox("Gender", GENDER_OPTIONS)
            date_of_birth = col10.date_input(
                "Date of birth", value=None,
                min_value=datetime.date(1900, 1, 1), max_value=datetime.date.today(),
            )
            occupation = st.text_input("Occupation")

            submitted = st.form_submit_button("Add panelist", type="primary", use_container_width=True)

        if submitted:
            if not username or not password:
                st.error("Username and password are required.")
            elif password != confirm:
                st.error("Passwords do not match.")
            elif not assignments:
                st.error("Add at least one position assignment.")
            else:
                try:
                    create_user(
                        username=username, password=password, role="viewer",
                        other_names=other_names, surname=surname, email=email,
                        id_passport_number=id_passport_number, phone_number=phone_number,
                        gender=gender, date_of_birth=date_of_birth, occupation=occupation,
                        county=(location or {}).get("county", ""),
                        sub_county=(location or {}).get("constituency", ""),
                        ward=(location or {}).get("ward", ""),
                        ward_id=(location or {}).get("ward_id"),
                    )
                    set_panelist_assignments(username, assignments)
                    st.success(f"Panelist '{username}' added.")
                    del st.session_state["dlg_cp_assignments_df"]
                    st.rerun()
                except Exception as e:
                    msg = str(e)
                    if "Duplicate entry" in msg and "username" in msg:
                        st.error(f"Username '{username}' is already taken.")
                    elif "Duplicate entry" in msg and "email" in msg:
                        st.error(f"Email '{email}' is already registered.")
                    else:
                        st.error(f"Failed to add panelist: {msg}")
    else:
        col1, col2 = st.columns(2)
        if col1.button(
            "Add to panel", type="primary", use_container_width=True, disabled=not selected_existing,
        ):
            if not assignments:
                st.error("Add at least one position assignment.")
            else:
                set_panelist_assignments(selected_existing, assignments)
                st.success(f"'{selected_existing}' added as a panelist.")
                del st.session_state["dlg_cp_assignments_df"]
                st.rerun()
        if col2.button("Cancel", use_container_width=True):
            del st.session_state["dlg_cp_assignments_df"]
            st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_dialog: tuple | None = None

_CONSUMED = "_panelists_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_url_key = None
if st.query_params.get("remove_panel"):
    _url_key = ("remove", st.query_params["remove_panel"])
elif st.query_params.get("edit"):
    _url_key = ("edit", st.query_params["edit"])
elif st.query_params.get("reset_pw"):
    _url_key = ("reset_pw", st.query_params["reset_pw"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None   # reset so the same row can be re-triggered after a new page load

# ── Main card: toolbar + table ─────────────────────────────────────────────
with st.container(key="card_panelists"):
    col_a, col_search = st.columns([2, 6])
    if col_a.button("➕ Add panelist", use_container_width=True) and _dialog is None:
        _dialog = ("create", None)

    if "panelists_page" not in st.session_state:
        st.session_state.panelists_page = 0

    def _reset_panelists_page():
        st.session_state.panelists_page = 0

    search = col_search.text_input(
        "Search", placeholder="Search by name, email, occupation or position",
        label_visibility="collapsed", key="panelists_search", on_change=_reset_panelists_page,
    )

    if _dialog:
        kind, arg = _dialog
        if   kind == "remove":   _confirm_remove(arg)
        elif kind == "edit":     _edit_dialog(arg)
        elif kind == "reset_pw": _reset_password_dialog(arg)
        elif kind == "create":   _create_dialog()

    # ── Panelists HTML table ────────────────────────────────────────────
    total = count_panelists(search)
    total_pages = max(1, (total + PANELISTS_PAGE_SIZE - 1) // PANELISTS_PAGE_SIZE)
    st.session_state.panelists_page = min(st.session_state.panelists_page, total_pages - 1)
    page = st.session_state.panelists_page

    panelists = list_panelists(search, limit=PANELISTS_PAGE_SIZE, offset=page * PANELISTS_PAGE_SIZE)

    def _cell(val):
        text = str(val) if val not in (None, "") else "—"
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
        return f"<td title='{safe}'>{safe}</td>"

    def _assignments_label(assignments: list[dict]) -> str:
        parts = []
        for a in assignments:
            role = PANEL_ROLE_LABELS.get(a["panel_role"], a["panel_role"])
            date_part = f", {a['interview_date']}" if a.get("interview_date") else ""
            parts.append(f"{a['position']} ({role}{date_part})")
        return "; ".join(parts) if parts else "—"

    if not panelists:
        st.info("No panelists found. Click “Add panelist” to assign someone to an interview panel.")
    else:
        rows_html = ""
        for p in panelists:
            actions = f"""
                <a class="edit-btn" href="?edit={p['username']}" target="_top">✏ Edit</a>
                <a class="reset-btn" href="?reset_pw={p['username']}" target="_top">🔑 Reset PW</a>
                <a class="del-btn"  href="?remove_panel={p['username']}" target="_top">🚫 Remove</a>"""

            rows_html += f"""<tr>
                <td class="actions-cell">{actions}</td>
                {_cell(p.get('surname'))} {_cell(p.get('other_names'))}
                {_cell(p.get('email'))} {_cell(p.get('gender'))}
                {_cell(p.get('occupation'))}
                {_cell(f"{p.get('county') or ''} / {p.get('sub_county') or ''} / {p.get('ward') or ''}".strip(' /'))}
                {_cell(_assignments_label(p.get('assignments') or []))}
            </tr>"""

        st.html(f"""
        <style>
            .panelist-tbl-wrap{{overflow-x:auto;width:100%}}
            .panelist-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
            .panelist-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
            .panelist-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;max-width:260px;overflow:hidden;text-overflow:ellipsis}}
            .panelist-tbl tr:hover td{{background:#f9fafb}}
            .actions-cell{{white-space:nowrap;display:flex;gap:4px;padding:6px 10px;align-items:center;
                position:sticky;left:0;background:#fff;z-index:1}}
            .panelist-tbl tr:hover .actions-cell{{background:#f9fafb}}
            .edit-btn,.del-btn,.reset-btn{{border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block}}
            .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
            .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
            .reset-btn{{background:#d97706;color:white!important}}.reset-btn:hover{{background:#b45309}}
        </style>
        <div class="panelist-tbl-wrap">
            <table class="panelist-tbl">
                <thead><tr>
                    <th>Actions</th>
                    <th>Surname</th><th>Other names</th>
                    <th>Email</th><th>Gender</th><th>Occupation</th>
                    <th>County / Constituency / Ward</th>
                    <th>Panel assignments</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)

        col_prev, col_info, col_next = st.columns([1, 3, 1])
        if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True, key="panelists_prev"):
            st.session_state.panelists_page -= 1
            st.rerun()
        col_info.markdown(
            f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} panelist(s)</div>",
            unsafe_allow_html=True,
        )
        if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True, key="panelists_next"):
            st.session_state.panelists_page += 1
            st.rerun()
