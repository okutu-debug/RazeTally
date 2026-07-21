import datetime

import streamlit as st

from auth import verify_password
from db import (
    add_user_document,
    delete_user_document,
    find_ward_by_names,
    get_user,
    get_user_document_bytes,
    get_user_polling_stations,
    list_positions,
    list_user_documents,
    save_user_document_file,
    update_password,
    update_user_profile,
)
from location_picker import location_picker
from theme import apply_theme

apply_theme()

POSITIONS = [""] + [p["title"] for p in list_positions()]
GENDER_OPTIONS = ["", "Male", "Female", "Other", "Prefer not to say"]

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>My Profile</h4>",
    unsafe_allow_html=True,
)

user = get_user(st.session_state.username)
if not user:
    st.error("Could not load profile.")
    st.stop()

# ── Profile details ────────────────────────────────────────────────────────────
with st.container(key="card_profile"):
    st.markdown(
        "<h4 style='font-size:2.5rem !important; margin:0;'>Personal details</h4>",
        unsafe_allow_html=True,
    )

    current_ward_id = user.get("ward_id") or find_ward_by_names(
        user.get("county"), user.get("sub_county"), user.get("ward"),
    )
    st.caption("County / Constituency (Sub-county) / Ward")
    location = location_picker("my_profile", current_ward_id)
    if location is None:
        st.caption(
            f"Currently unlinked: {user.get('county') or '—'} / "
            f"{user.get('sub_county') or '—'} / {user.get('ward') or '—'}. "
            "Pick all three levels above to (re)link your profile."
        )

    with st.form("profile_form"):
        col1, col2 = st.columns(2)
        surname = col1.text_input("Surname", value=user.get("surname") or "")
        other_names = col2.text_input("Other names", value=user.get("other_names") or "")

        col3, col4 = st.columns(2)
        email = col3.text_input("Email", value=user.get("email") or "")
        current_pos = user.get("position") or ""
        pos_index = POSITIONS.index(current_pos) if current_pos in POSITIONS else 0
        position = col4.selectbox("Position", POSITIONS, index=pos_index)

        col5, col6 = st.columns(2)
        id_passport_number = col5.text_input("ID/Passport number", value=user.get("id_passport_number") or "")
        phone_number       = col6.text_input("Phone number",       value=user.get("phone_number") or "")

        col7, col8 = st.columns(2)
        gender_idx    = GENDER_OPTIONS.index(user.get("gender")) if user.get("gender") in GENDER_OPTIONS else 0
        gender        = col7.selectbox("Gender", GENDER_OPTIONS, index=gender_idx)
        date_of_birth = col8.date_input(
            "Date of birth", value=user.get("date_of_birth"),
            min_value=datetime.date(1900, 1, 1), max_value=datetime.date.today(),
        )

        st.caption(f"Username: **{user['username']}** · Role: **{user['role']}**")

        if st.form_submit_button("Save changes", type="primary"):
            loc = location or {
                "county": user.get("county"), "constituency": user.get("sub_county"),
                "ward": user.get("ward"), "ward_id": user.get("ward_id"),
            }
            try:
                update_user_profile(
                    username=user["username"],
                    other_names=other_names,
                    surname=surname,
                    email=email,
                    position=position,
                    id_passport_number=id_passport_number,
                    phone_number=phone_number,
                    gender=gender,
                    date_of_birth=date_of_birth,
                    county=loc["county"] or "",
                    sub_county=loc["constituency"] or "",
                    ward=loc["ward"] or "",
                    ward_id=loc["ward_id"],
                )
                st.success("Profile updated.")
            except Exception as e:
                st.error(f"Failed to update profile: {e}")

# ── My documents ────────────────────────────────────────────────────────────────
with st.container(key="card_documents"):
    st.markdown(
        "<h4 style='font-size:2.5rem !important; margin:0;'>My documents</h4>",
        unsafe_allow_html=True,
    )
    docs = list_user_documents(user["username"])
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
                    key=f"profile_dl_doc_{d['id']}", use_container_width=True,
                )
            if col_del.button("🗑", key=f"profile_del_doc_{d['id']}", use_container_width=True):
                delete_user_document(d["id"])
                st.rerun()

    with st.form("profile_upload_doc_form", clear_on_submit=True):
        col_title, col_file = st.columns([2, 3])
        doc_title = col_title.text_input("Document title", placeholder="e.g. National ID, KCSE Certificate")
        doc_file  = col_file.file_uploader("File", label_visibility="collapsed")
        if st.form_submit_button("📎 Attach document"):
            if not doc_title.strip() or not doc_file:
                st.error("A title and a file are both required.")
            else:
                stored_name = save_user_document_file(user["username"], doc_file.name, doc_file.read())
                add_user_document(user["username"], doc_title.strip(), stored_name, doc_file.name, user["username"])
                st.success("Document attached.")
                st.rerun()

# ── Assigned polling stations ──────────────────────────────────────────────────
with st.container(key="card_stations"):
    st.markdown(
        "<h4 style='font-size:2.5rem !important; margin:0;'>My polling stations</h4>",
        unsafe_allow_html=True,
    )
    if user["role"] == "admin":
        st.caption("As an admin, you can upload for any polling station.")
    else:
        stations = get_user_polling_stations(user["username"])
        if not stations:
            st.info("No polling station has been assigned to you yet. Contact an admin to request access.")
        else:
            for s in stations:
                st.markdown(
                    f"- **{s['polling_station_name']}** ({s['polling_station_code']}) — "
                    f"{s['county']} / {s['constituency']} / {s['ward']}"
                )

# ── Change password ────────────────────────────────────────────────────────────
with st.container(key="card_password"):
    st.markdown(
        "<h4 style='font-size:2.5rem !important; margin:0;'>Change password</h4>",
        unsafe_allow_html=True,
    )
    with st.form("password_form"):
        current_pw = st.text_input("Current password", type="password")
        new_pw = st.text_input("New password", type="password")
        confirm_pw = st.text_input("Confirm new password", type="password")

        if st.form_submit_button("Update password"):
            if not verify_password(current_pw, user["password_hash"]):
                st.error("Current password is incorrect.")
            elif new_pw != confirm_pw:
                st.error("New passwords do not match.")
            elif len(new_pw) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                update_password(user["username"], new_pw)
                st.success("Password updated successfully.")