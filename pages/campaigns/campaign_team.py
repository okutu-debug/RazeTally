import datetime
from urllib.parse import quote

import pandas as pd
import streamlit as st

from db import (
    add_campaign_team,
    add_campaign_team_member,
    add_user_document,
    assign_material_to_team,
    assign_user_polling_stations,
    assign_user_to_team,
    count_user_polling_stations,
    count_users_by_team_type,
    create_user,
    delete_campaign_team,
    delete_user,
    delete_user_document,
    find_ward_by_names,
    get_campaign_team,
    get_user,
    get_user_document_bytes,
    get_user_polling_station_codes,
    get_user_team_position,
    list_materials,
    list_campaign_team_members,
    list_campaign_teams,
    list_polling_stations,
    list_polling_stations_by_codes,
    list_positions,
    list_team_assignments_for_user,
    list_team_material_assignments,
    list_user_documents,
    list_users,
    list_users_by_team_type,
    remove_campaign_team_member,
    remove_material_assignment,
    remove_user_from_team,
    save_user_document_file,
    update_campaign_team,
    update_password,
    update_user_profile,
)
from location_picker import location_picker
from theme import apply_theme, clear_query_params_url

TEAM_TYPE = "campaign"
GENDER_OPTIONS = ["", "Male", "Female", "Other", "Prefer not to say"]


def _documents_section(username: str, uploaded_by: str):
    """Shared list + upload UI for a user's attached documents (ID scans,
    certificates, etc.), used from both the admin Edit dialog and Profile."""
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
                    key=f"dl_doc_ct_{username}_{d['id']}", use_container_width=True,
                )
            if col_del.button("🗑", key=f"del_doc_ct_{username}_{d['id']}", use_container_width=True):
                delete_user_document(d["id"])
                st.rerun()

    with st.form(f"upload_doc_form_ct_{username}", clear_on_submit=True):
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

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Event / Rally Team</h4>",
    unsafe_allow_html=True,
)


def _station_picker(sel_key: str, search_key: str, widget_key: str) -> list[str]:
    """Search-driven multiselect for assigning polling stations. `sel_key` holds
    the currently-selected codes across reruns; already-selected stations stay
    visible in the options list even once the search text no longer matches them."""
    search = st.text_input(
        "Search polling stations to assign",
        placeholder="Search by county, constituency, ward, station name or code",
        key=search_key,
    )
    search_results    = list_polling_stations(search, limit=50) if search.strip() else []
    selected_stations = list_polling_stations_by_codes(st.session_state[sel_key])
    station_lookup    = {s["polling_station_code"]: s for s in (search_results + selected_stations)}

    def _label(code):
        s = station_lookup[code]
        return f"{s['polling_station_code']} — {s['polling_station_name']} ({s['county']}/{s['constituency']}/{s['ward']})"

    st.session_state[sel_key] = st.multiselect(
        "Assigned polling stations",
        options=list(station_lookup.keys()),
        default=st.session_state[sel_key],
        format_func=_label,
        key=widget_key,
    )
    if st.session_state[sel_key]:
        st.caption(f"{len(st.session_state[sel_key])} station(s) selected.")
    return st.session_state[sel_key]


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Remove team member")
def _confirm_remove(username: str):
    other_teams = sorted({
        a["team_type"] for a in list_team_assignments_for_user(username) if a["team_type"] != TEAM_TYPE
    })
    st.write(f"Remove **{username}** from the Campaign Team?")
    if other_teams:
        st.caption(
            f"This account is also on: {', '.join(t.capitalize() for t in other_teams)}. "
            "Removing from the campaign team only unassigns their campaign position — "
            "their account and other team membership(s) stay intact."
        )
    col1, col2, col3 = st.columns(3)
    if col1.button("Remove from team", type="primary", use_container_width=True):
        remove_user_from_team(username, TEAM_TYPE)
        st.rerun()
    if col2.button("Delete account entirely", use_container_width=True):
        delete_user(username)
        st.rerun()
    if col3.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Reset password")
def _reset_password_dialog(username: str):
    st.write(f"Set a new password for **{username}**.")
    with st.form("dlg_ct_reset_password_form"):
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


@st.dialog("Edit Campaign Team Member", width="large")
def _edit_dialog(username: str):
    positions_data = list_positions(team_type=TEAM_TYPE)
    position_options = [""] + [p["title"] for p in positions_data]
    user = get_user(username)
    if not user:
        st.error("User not found.")
        st.stop()
    team_position = get_user_team_position(username, TEAM_TYPE)
    current_pos = team_position["position"] if team_position else ""
    pos_index = position_options.index(current_pos) if current_pos in position_options else 0
    col1, col2 = st.columns(2)
    surname     = col1.text_input("Surname",     value=user.get("surname")     or "")
    other_names = col2.text_input("Other names", value=user.get("other_names") or "")
    email      = st.text_input("Email",        value=user.get("email")      or "")
    position   = st.selectbox("Position (campaign) *", position_options, index=pos_index)

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
    location = location_picker(f"edit_ct_user_{username}", current_ward_id)
    if location is None:
        st.caption(
            f"Currently unlinked: {user.get('county') or '—'} / "
            f"{user.get('sub_county') or '—'} / {user.get('ward') or '—'}. "
            "Pick all three levels above to (re)link this profile."
        )

    sel_key = f"dlg_ct_edit_stations_selected_{username}"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = get_user_polling_station_codes(username)
    selected_stations = _station_picker(
        sel_key, f"dlg_ct_edit_station_search_{username}", f"dlg_ct_edit_stations_widget_{username}",
    )

    col3, col4 = st.columns(2)
    if col3.button("Save", type="primary", use_container_width=True):
        if not position:
            st.error("Position is required.")
        else:
            loc = location or {
                "county": user.get("county"), "constituency": user.get("sub_county"),
                "ward": user.get("ward"), "ward_id": user.get("ward_id"),
            }
            update_user_profile(
                username, other_names, surname, email, user.get("position") or "",
                id_passport_number=id_passport_number, phone_number=phone_number,
                gender=gender, date_of_birth=date_of_birth,
                county=loc["county"] or "", sub_county=loc["constituency"] or "", ward=loc["ward"] or "",
                ward_id=loc["ward_id"],
            )
            assign_user_to_team(username, TEAM_TYPE, position)
            assign_user_polling_stations(username, selected_stations)
            del st.session_state[sel_key]
            st.rerun()
    if col4.button("Cancel", use_container_width=True):
        del st.session_state[sel_key]
        st.rerun()

    _documents_section(username, uploaded_by=st.session_state.username)


@st.dialog("Add campaign team member", width="large")
def _create_dialog():
    positions_data    = list_positions(team_type=TEAM_TYPE)
    position_role_map = {p["title"]: p["role"] for p in positions_data}
    position_options  = [""] + [p["title"] for p in positions_data]

    if not positions_data:
        st.error("No campaign positions exist yet. Add one on the Positions page first.")
        st.stop()

    already_on_team = {u["username"] for u in list_users_by_team_type(TEAM_TYPE)}
    linkable_users = [u for u in list_users() if u["username"] not in already_on_team]

    account_mode = st.radio(
        "Team member account", ["Create new account", "Use an existing user account"],
        key="dlg_ct_mode", horizontal=True,
    )

    if account_mode == "Use an existing user account":
        if not linkable_users:
            st.info("Every existing user is already on the campaign team.")
            return
        labels = {"": "— Select —", **{
            u["username"]: f"{u.get('surname') or ''} {u.get('other_names') or ''} ({u['username']})".strip()
            for u in linkable_users
        }}
        selected_existing = st.selectbox(
            "Existing user", list(labels.keys()), format_func=lambda u: labels[u], key="dlg_ct_existing_user",
        )
        position = st.selectbox("Position (campaign) *", position_options, key="dlg_ct_existing_position")

        if st.button("Add to campaign team", type="primary", use_container_width=True):
            if not selected_existing:
                st.error("Select a user.")
            elif not position:
                st.error("Position is required.")
            else:
                assign_user_to_team(selected_existing, TEAM_TYPE, position)
                st.success(f"'{selected_existing}' added to the campaign team as {position}.")
                st.rerun()
        return

    col_pos, col_role = st.columns(2)
    selected_position = col_pos.selectbox("Position (campaign) *", position_options, key="dlg_ct_position")
    derived_role      = position_role_map.get(selected_position, "uploader")
    col_role.text_input("Role", value=derived_role, disabled=True)

    if "dlg_ct_stations_selected" not in st.session_state:
        st.session_state.dlg_ct_stations_selected = []
    selected_stations = _station_picker(
        "dlg_ct_stations_selected", "dlg_ct_station_search", "dlg_ct_stations_widget",
    )

    st.caption("County / Constituency (Sub-county) / Ward")
    location = location_picker("create_ct_user", None)

    with st.form("dlg_ct_create_user_form"):
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

        submitted  = st.form_submit_button("Create Member", type="primary", use_container_width=True)

    if submitted:
        position = st.session_state.get("dlg_ct_position", "")
        role     = position_role_map.get(position, "uploader")
        if not username or not password:
            st.error("Username and password are required.")
        elif not position:
            st.error("Position is required.")
        elif password != confirm:
            st.error("Passwords do not match.")
        else:
            try:
                create_user(username=username, password=password, role=role,
                            other_names=other_names, surname=surname,
                            email=email, position=position,
                            id_passport_number=id_passport_number, phone_number=phone_number,
                            gender=gender, date_of_birth=date_of_birth,
                            county=(location or {}).get("county", ""),
                            sub_county=(location or {}).get("constituency", ""),
                            ward=(location or {}).get("ward", ""),
                            ward_id=(location or {}).get("ward_id"))
                assign_user_to_team(username, TEAM_TYPE, position)
                assign_user_polling_stations(username, selected_stations)
                st.success(f"Team member '{username}' created as **{role}** ({position}).")
                st.session_state.dlg_ct_stations_selected = []
                st.session_state.dlg_ct_station_search = ""
                st.rerun()
            except Exception as e:
                msg = str(e)
                if "Duplicate entry" in msg and "username" in msg:
                    st.error(f"Username '{username}' is already taken.")
                elif "Duplicate entry" in msg and "email" in msg:
                    st.error(f"Email '{email}' is already registered.")
                else:
                    st.error(f"Failed to create member: {msg}")


@st.dialog("Bulk import Team Members", width="large")
def _bulk_import_dialog():
    campaign_positions = list_positions(team_type=TEAM_TYPE)
    _template = pd.DataFrame([{
        "username": "jane.doe", "password": "changeme123",
        "other_names": "Jane", "surname": "Doe",
        "email": "jane@example.com",
        "position": campaign_positions[0]["title"] if campaign_positions else "",
        "polling_stations": "001001000100101;001001000100102",
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="campaign_team_template.csv", mime="text/csv",
    )
    st.caption(
        "`position` must be a campaign position (see the Positions page). "
        "If `username` already exists, they're simply added to the campaign team with this "
        "position — `password` is ignored for existing accounts. "
        "`polling_stations` is optional — separate multiple station codes with a semicolon (`;`)."
    )

    if "ct_upload_key" not in st.session_state:
        st.session_state.ct_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"ct_bulk_{st.session_state.ct_upload_key}",
    )

    if not uploaded:
        return

    try:
        df = pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    missing = {"username", "password", "position"} - set(df.columns)
    if missing:
        st.error(f"Missing required columns: {', '.join(missing)}")
        return

    st.caption(f"{len(df)} row(s) — preview:")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("Import team members", type="primary", use_container_width=True):
        pos_role_map = {p["title"]: p["role"] for p in list_positions(team_type=TEAM_TYPE)}
        successes, errors, warnings = [], [], []
        for idx, row in df.iterrows():
            line  = idx + 2
            uname = str(row.get("username", "") or "").strip()
            pwd   = str(row.get("password", "") or "").strip()
            pos   = str(row.get("position", "") or "").strip()
            if not uname:
                errors.append(f"Row {line}: username is required.")
                continue
            if pos not in pos_role_map:
                errors.append(f"Row {line} ({uname}): unknown campaign position '{pos}'.")
                continue

            existing_user = get_user(uname)
            if existing_user:
                assign_user_to_team(uname, TEAM_TYPE, pos)
                successes.append(uname)
            elif not pwd:
                errors.append(f"Row {line}: password is required to create a new account.")
                continue
            else:
                try:
                    create_user(username=uname, password=pwd, role=pos_role_map[pos],
                                other_names=str(row.get("other_names", "") or ""),
                                surname    =str(row.get("surname",     "") or ""),
                                email      =str(row.get("email",       "") or ""),
                                position   =pos)
                    assign_user_to_team(uname, TEAM_TYPE, pos)
                    successes.append(uname)
                except Exception as e:
                    msg = str(e)
                    if "Duplicate entry" in msg and "email" in msg:
                        errors.append(f"Row {line}: email already registered.")
                    else:
                        errors.append(f"Row {line} ({uname}): {msg}")
                    continue

            raw_codes = str(row.get("polling_stations", "") or "").strip()
            if raw_codes:
                codes = [c.strip() for c in raw_codes.split(";") if c.strip()]
                valid_codes = {s["polling_station_code"] for s in list_polling_stations_by_codes(codes)}
                unknown = [c for c in codes if c not in valid_codes]
                if valid_codes:
                    assign_user_polling_stations(uname, [c for c in codes if c in valid_codes])
                if unknown:
                    warnings.append(f"Row {line} ({uname}): unknown station code(s) ignored: {', '.join(unknown)}.")

        if successes:
            st.success(f"Imported {len(successes)} team member(s): {', '.join(successes)}.")
        if warnings:
            st.warning("\n\n".join(warnings))
        if errors:
            st.error("\n\n".join(errors))
        if successes:
            st.session_state.ct_upload_key += 1
            st.rerun()


# ── Team-group dialogs (named sub-groups of the campaign roster, e.g. "Team
# Swat") ─────────────────────────────────────────────────────────────────────
@st.dialog("Add campaign team")
def _group_add_dialog():
    with st.form("dlg_ctg_add_form"):
        name = st.text_input("Campaign Team Name *")
        description = st.text_area("Description")
        submitted = st.form_submit_button("Add team", type="primary", use_container_width=True)
    if submitted:
        if not name.strip():
            st.error("Team name is required.")
        else:
            try:
                add_campaign_team(name.strip(), description.strip())
                st.success(f"Team '{name}' created.")
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"A team named '{name}' already exists.")
                else:
                    st.error(f"Failed to create team: {e}")


def _safe_html(v) -> str:
    text = str(v) if v is not None else ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")


_ACTION_TABLE_STYLE = """
<style>
    .grp-tbl-wrap{overflow-x:auto;width:100%}
    .grp-tbl{border-collapse:collapse;width:100%;font-family:sans-serif;font-size:14px}
    .grp-tbl th{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}
    .grp-tbl td{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937}
    .grp-tbl tr:hover td{background:#f9fafb}
    .actions-cell{white-space:nowrap;display:flex;gap:6px;align-items:center}
    .del-btn{border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block;background:#dc2626;color:white!important}
    .del-btn:hover{background:#b91c1c}
</style>
"""


def _render_group_manage(id: str):
    """Inline (non-popup) team management view, rendered in place of the
    Teams list when a team is selected — so editing name/description,
    membership and material assignments all happen on the page itself,
    across three cards, rather than in a dialog."""
    team = get_campaign_team(id)
    if not team:
        st.error("Team not found.")
        if st.button("⬅ Back to Teams", use_container_width=True):
            st.session_state.ctg_managing_id = None
            st.rerun()
        return

    if st.button("⬅ Back to Teams", key="back_to_teams_top"):
        st.session_state.ctg_managing_id = None
        st.rerun()

    st.markdown(
        f"<h4 style='font-size:1.6rem !important; margin:0.75rem 0 0.5rem;'>{team['name']}</h4>",
        unsafe_allow_html=True,
    )

    # ── Card: Team details ──────────────────────────────────────────────────
    with st.container(key="card_ctg_details"):
        st.markdown("##### Team details")
        with st.form(f"dlg_ctg_edit_form_{id}"):
            name = st.text_input("Campaign Team Name *", value=team["name"])
            description = st.text_area("Description", value=team["description"] or "")
            saved = st.form_submit_button("Save", type="primary", use_container_width=True)
        if saved:
            if not name.strip():
                st.error("Team name is required.")
            else:
                try:
                    update_campaign_team(id, name.strip(), description.strip())
                    st.rerun()
                except Exception as e:
                    if "Duplicate entry" in str(e):
                        st.error(f"A team named '{name}' already exists.")
                    else:
                        st.error(f"Failed to update: {e}")

    # ── Card: Team members (table view) ─────────────────────────────────────
    with st.container(key="card_ctg_members"):
        st.markdown("##### Team members")
        members = list_campaign_team_members(id)
        campaign_roster = list_users_by_team_type(TEAM_TYPE)
        assigned_usernames = {m["username"] for m in members}
        addable = [u for u in campaign_roster if u["username"] not in assigned_usernames]

        if not members:
            st.info("No members in this team yet.")
        else:
            team_enc = quote(str(id), safe="")
            rows_html_m = ""
            for m in members:
                name_disp = f"{m.get('surname') or ''} {m.get('other_names') or ''}".strip() or m["username"]
                enc = quote(m["username"], safe="")
                rows_html_m += f"""<tr>
                    <td>{_safe_html(name_disp)}</td>
                    <td>{_safe_html(m['username'])}</td>
                    <td>{_safe_html(m.get('email'))}</td>
                    <td class="actions-cell">
                        <a class="del-btn" href="?manage_ctg={team_enc}&rm_member={enc}" target="_top">🗑 Remove</a>
                    </td>
                </tr>"""

            st.html(f"""
            {_ACTION_TABLE_STYLE}
            <div class="grp-tbl-wrap">
                <table class="grp-tbl">
                    <thead><tr><th>Name</th><th>Username</th><th>Email</th><th>Actions</th></tr></thead>
                    <tbody>{rows_html_m}</tbody>
                </table>
            </div>
            """)

        if not campaign_roster:
            st.caption("No campaign team members exist yet — add some in the Roster tab.")
        elif addable:
            labels = {"": "— Select —", **{
                u["username"]: f"{u.get('surname') or ''} {u.get('other_names') or ''} ({u['username']})".strip()
                for u in addable
            }}
            col_pick, col_add = st.columns([3, 1])
            pick = col_pick.selectbox(
                "Add member", list(labels.keys()), format_func=lambda u: labels[u],
                key=f"pick_grp_member_{id}", label_visibility="collapsed",
            )
            if col_add.button("Add", type="primary", use_container_width=True, key=f"add_grp_member_{id}") and pick:
                add_campaign_team_member(id, pick)
                st.rerun()
        else:
            st.caption("Every campaign team member is already in this team.")

    # ── Card: Assigned materials (table view) ───────────────────────────────
    with st.container(key="card_ctg_materials"):
        st.markdown("##### Assigned materials")
        assignments = list_team_material_assignments(id)
        materials = list_materials(material_type="campaign")
        assigned_material_ids = {a["material_id"] for a in assignments}
        assignable = [m for m in materials if m["id"] not in assigned_material_ids]

        if not assignments:
            st.info("No materials assigned to this team yet.")
        else:
            team_enc = quote(str(id), safe="")
            rows_html_am = ""
            for a in assignments:
                enc = quote(str(a["material_id"]), safe="")
                rows_html_am += f"""<tr>
                    <td>{_safe_html(a['material_name'])}</td>
                    <td>{_safe_html(a.get('unit'))}</td>
                    <td>{a['quantity']}</td>
                    <td class="actions-cell">
                        <a class="del-btn" href="?manage_ctg={team_enc}&rm_material={enc}" target="_top">🗑 Remove</a>
                    </td>
                </tr>"""

            st.html(f"""
            {_ACTION_TABLE_STYLE}
            <div class="grp-tbl-wrap">
                <table class="grp-tbl">
                    <thead><tr><th>Material</th><th>Unit</th><th>Qty</th><th>Actions</th></tr></thead>
                    <tbody>{rows_html_am}</tbody>
                </table>
            </div>
            """)

        if not materials:
            st.caption("No campaign materials exist yet — add some on the Campaign Materials page.")
        elif assignable:
            mat_labels = {
                m["id"]: f"{m['name']} ({m.get('unit') or 'unit'} — {m['quantity']} in stock)"
                for m in assignable
            }
            col_mat, col_qty, col_go = st.columns([3, 2, 1])
            mat_id = col_mat.selectbox(
                "Assign material", list(mat_labels.keys()), format_func=lambda i: mat_labels[i],
                key=f"pick_material_{id}",
            )
            qty = col_qty.number_input("Qty", min_value=0, step=1, value=0, key=f"qty_material_{id}")
            if col_go.button("Assign", type="primary", use_container_width=True, key=f"assign_material_{id}"):
                if qty == 0:
                    st.error("Enter a quantity greater than 0.")
                else:
                    assign_material_to_team(mat_id, id, int(qty))
                    st.rerun()
        else:
            st.caption("Every campaign material is already assigned to this team.")

    if st.button("⬅ Back to Teams", key="back_to_teams_bottom"):
        st.session_state.ctg_managing_id = None
        st.rerun()


@st.dialog("Confirm removal")
def _group_delete_dialog(id: str):
    team = get_campaign_team(id)
    name = team["name"] if team else id
    st.write(
        f"Delete team **{name}**? Members keep their campaign team membership — "
        "only this grouping is removed. This cannot be undone."
    )
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_campaign_team(id)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_dialog: tuple | None = None

# Consume URL params only once per session using a "last consumed" tracker.
# Even if st.query_params persists across the X-button rerun, the tracker
# prevents re-triggering the dialog a second time.
_CONSUMED = "_ct_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_url_key = None
if st.query_params.get("delete_ct"):
    _url_key = ("delete", st.query_params["delete_ct"])
elif st.query_params.get("edit_ct"):
    _url_key = ("edit", st.query_params["edit_ct"])
elif st.query_params.get("reset_pw_ct"):
    _url_key = ("reset_pw", st.query_params["reset_pw_ct"])
# rm_member / rm_material must be checked before manage_ctg: their links carry
# both params at once (?manage_ctg=<team>&rm_member=<user>), and manage_ctg
# alone only re-enters the management view without performing the removal.
elif st.query_params.get("rm_member"):
    _url_key = ("group_rm_member", st.query_params["rm_member"], st.query_params.get("manage_ctg"))
elif st.query_params.get("rm_material"):
    _url_key = ("group_rm_material", st.query_params["rm_material"], st.query_params.get("manage_ctg"))
elif st.query_params.get("manage_ctg"):
    _url_key = ("group_manage", st.query_params["manage_ctg"])
elif st.query_params.get("delete_ctg"):
    _url_key = ("group_delete", st.query_params["delete_ctg"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None   # reset so same user can be re-edited after a new page load

# "Manage campaign team" renders inline on the page rather than as a popup, so
# which team is being managed has to persist in session_state across reruns
# triggered from inside that view (unlike a modal, which stays open on its own).
# Member/material removal from that view is also routed through this same
# top-level query-param dispatcher (rather than checked locally inside the
# render function) to match every other action-link on this page. Their links
# carry the team id in the URL itself (not just session_state), since the
# full-page navigation these action-links trigger resets st.session_state.
if "ctg_managing_id" not in st.session_state:
    st.session_state.ctg_managing_id = None
if _dialog and _dialog[0] == "group_manage":
    st.session_state.ctg_managing_id = _dialog[1]
    _dialog = None
elif _dialog and _dialog[0] == "group_rm_member":
    team_id = _dialog[2] or st.session_state.ctg_managing_id
    if team_id:
        remove_campaign_team_member(team_id, _dialog[1])
        st.session_state.ctg_managing_id = team_id
    _dialog = None
elif _dialog and _dialog[0] == "group_rm_material":
    team_id = _dialog[2] or st.session_state.ctg_managing_id
    if team_id:
        remove_material_assignment(_dialog[1], team_id)
        st.session_state.ctg_managing_id = team_id
    _dialog = None

TEAM_PAGE_SIZE = 25

if st.session_state.ctg_managing_id:
    _render_group_manage(st.session_state.ctg_managing_id)
else:
    tab_groups, tab_roster = st.tabs(["🧩 Teams", "👤 Roster"])

    # ── Roster tab: toolbar + table ─────────────────────────────────────────────
    with tab_roster:
      with st.container(key="card_campaign_team"):
        col_a, col_b, col_search = st.columns([1.8, 1.8, 4.4])
        if col_a.button("➕ Add Member", use_container_width=True) and _dialog is None:
            _dialog = ("create", None)
        if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
            _dialog = ("bulk", None)

        if "ct_page" not in st.session_state:
            st.session_state.ct_page = 0

        def _reset_ct_page():
            st.session_state.ct_page = 0

        search = col_search.text_input(
            "Search", placeholder="Search by username, name, email, position or role",
            label_visibility="collapsed", key="ct_search", on_change=_reset_ct_page,
        )

        # ── Team HTML table ────────────────────────────────────────────────
        me = st.session_state.username

        total = count_users_by_team_type(TEAM_TYPE, search)
        total_pages = max(1, (total + TEAM_PAGE_SIZE - 1) // TEAM_PAGE_SIZE)
        st.session_state.ct_page = min(st.session_state.ct_page, total_pages - 1)
        page = st.session_state.ct_page

        users = list_users_by_team_type(TEAM_TYPE, search, limit=TEAM_PAGE_SIZE, offset=page * TEAM_PAGE_SIZE)

        def _cell(val):
            text = str(val) if val is not None else ""
            safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
            return f"<td title='{safe}'>{safe}</td>"

        if not users:
            st.info("No campaign team members found. Use **+ Add Member** or **Bulk import** to get started.")
        else:
            station_counts = count_user_polling_stations()
            rows_html = ""
            for u in users:
                created = str(u.get("created_at") or "")[:16]
                stations = "All" if u.get("role") == "admin" else str(station_counts.get(u["username"], 0))
                actions = ""
                if u["username"] != me:
                    actions = f"""
                        <a class="edit-btn" href="?edit_ct={u['username']}" target="_top">✏ Edit</a>
                        <a class="reset-btn" href="?reset_pw_ct={u['username']}" target="_top">🔑 Reset PW</a>
                        <a class="del-btn"  href="?delete_ct={u['username']}" target="_top">🗑 Remove</a>"""

                else:
                    actions = f"""
                        <a class="edit-btn disabled" href="#" target="_top">✏ Edit</a>
                        <a class="reset-btn disabled" href="#" target="_top">🔑 Reset PW</a>
                        <a class="del-btn disabled"  href="#" target="_top">🗑 Remove</a>"""


                rows_html += f"""<tr>
                    <td class="actions-cell">{actions}</td>
                    {_cell(u.get('username'))} {_cell(u.get('surname'))}
                    {_cell(u.get('other_names'))}{_cell(u.get('email'))}
                    {_cell(u.get('position'))} {_cell(u.get('role'))}
                    {_cell(stations)}
                    {_cell(created)}
                </tr>"""

            st.html(f"""
            <style>
                .user-tbl-wrap{{overflow-x:auto;width:100%}}
                .user-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
                .user-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
                .user-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;max-width:220px;overflow:hidden;text-overflow:ellipsis}}
                .user-tbl tr:hover td{{background:#f9fafb}}
                .actions-cell{{white-space:nowrap;display:flex;gap:4px;padding:6px 10px;align-items:center;
                    position:sticky;left:0;background:#fff;z-index:1}}
                .user-tbl tr:hover .actions-cell{{background:#f9fafb}}
                .edit-btn,.del-btn,.reset-btn{{border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block}}
                .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
                .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
                .reset-btn{{background:#d97706;color:white!important}}.reset-btn:hover{{background:#b45309}}
                .edit-btn.disabled,.del-btn.disabled,.reset-btn.disabled{{
                    background:#e5e7eb;color:#9ca3af!important;pointer-events:none;cursor:default}}
                .edit-btn.disabled:hover,.del-btn.disabled:hover,.reset-btn.disabled:hover{{background:#e5e7eb}}
            </style>
            <div class="user-tbl-wrap">
                <table class="user-tbl">
                    <thead><tr>
                        <th>Actions</th>
                        <th>Username</th><th>Surname</th><th>Other names</th>
                        <th>Email</th><th>Position</th><th>Role</th>
                        <th>Stations</th><th>Created</th>
                    </tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
            """)

            col_prev, col_info, col_next = st.columns([1, 3, 1])
            if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True, key="ct_prev"):
                st.session_state.ct_page -= 1
                st.rerun()
            col_info.markdown(
                f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} team member(s)</div>",
                unsafe_allow_html=True,
            )
            if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True, key="ct_next"):
                st.session_state.ct_page += 1
                st.rerun()

    # ── Teams tab: named sub-groups of the campaign roster ──────────────────────
    with tab_groups:
      with st.container(key="card_campaign_team_groups"):
        col_a, col_search = st.columns([2, 6])
        if col_a.button("➕ Add Team", use_container_width=True) and _dialog is None:
            _dialog = ("group_add", None)

        search_g = col_search.text_input(
            "Search", placeholder="Search by team name or description",
            label_visibility="collapsed", key="ctg_search",
        )

        teams = list_campaign_teams(search_g)

        if not teams:
            st.info("No campaign teams yet. Use **+ Add Team** to group roster members together.")
        else:
            def _safe_g(v):
                text = str(v) if v is not None else ""
                return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")

            rows_html_g = ""
            for t in teams:
                enc = quote(str(t["id"]), safe="")
                desc = (t.get("description") or "")[:120]
                rows_html_g += f"""<tr>
                    <td>{_safe_g(t['name'])}</td>
                    <td>{_safe_g(desc)}</td>
                    <td>{t['member_count']}</td>
                    <td class="actions-cell">
                        <a class="edit-btn" href="?manage_ctg={enc}" target="_top">🧩 Manage</a>
                        <a class="del-btn"  href="?delete_ctg={enc}" target="_top">🗑 Delete</a>
                    </td>
                </tr>"""

            st.html(f"""
            <style>
                .ctg-tbl-wrap{{overflow-x:auto;width:100%}}
                .ctg-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
                .ctg-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
                .ctg-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;max-width:320px;overflow:hidden;text-overflow:ellipsis}}
                .ctg-tbl tr:hover td{{background:#f9fafb}}
                .actions-cell{{white-space:nowrap;display:flex;gap:6px;align-items:center}}
                .edit-btn,.del-btn{{border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block}}
                .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
                .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
            </style>
            <div class="ctg-tbl-wrap">
                <table class="ctg-tbl">
                    <thead><tr>
                        <th>Team</th><th>Description</th><th>Members</th><th>Actions</th>
                    </tr></thead>
                    <tbody>{rows_html_g}</tbody>
                </table>
            </div>
            """)

# ── Dialog dispatch (shared across both tabs) ────────────────────────────────
if _dialog:
    kind, arg = _dialog
    if   kind == "delete":        _confirm_remove(arg)
    elif kind == "edit":          _edit_dialog(arg)
    elif kind == "reset_pw":      _reset_password_dialog(arg)
    elif kind == "create":        _create_dialog()
    elif kind == "bulk":          _bulk_import_dialog()
    elif kind == "group_add":     _group_add_dialog()
    elif kind == "group_delete":  _group_delete_dialog(arg)
