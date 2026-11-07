import os
from pathlib import Path

import pandas as pd
import streamlit as st

from parser import get_vision_api_key
from mobile_camera import camera_uploader
from processor import commit_form, parse_form, save_upload
from theme import apply_theme

apply_theme()
st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Upload Form</h4>",
    unsafe_allow_html=True,
)

api_key, api_key_var = get_vision_api_key()
if not api_key:
    st.error(f"{api_key_var} is not set — cannot parse uploaded forms.")
    st.stop()

if "parsed_form"   not in st.session_state:
    st.session_state.parsed_form   = None
if "submit_result" not in st.session_state:
    st.session_state.submit_result = None   # {"form_id": int, "station": str}

# ── Step 3: success screen ────────────────────────────────────────────────────
if st.session_state.submit_result is not None:
    res = st.session_state.submit_result
    with st.container(key="card_success"):
        st.success(
            f"Form submitted successfully!  \n"
            f"**Form ID:** {res['form_id']}  \n"
            f"**Polling station:** {res['station'] or 'N/A'}"
        )
        col_a, col_b, _ = st.columns([2.6, 2.6, 6])
        if col_a.button("Upload Another Form", type="primary", use_container_width=True):
            st.session_state.submit_result = None
            st.rerun()
        if col_b.button("Go To Dashboard", use_container_width=True):
            st.switch_page("pages/dashboard.py")

           

# ── Step 2: preview + confirm ─────────────────────────────────────────────────
elif st.session_state.parsed_form is not None:
    parsed = st.session_state.parsed_form

    with st.container(key="card_preview"):
        st.markdown(
            "<h5 style='font-size:2.25rem !important; margin:0;'>Review extracted data</h5>",
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns(2)
        col1.text_input("Form number",     value=parsed.get("form_number") or "",     disabled=True)
        col2.text_input("Polling station", value=parsed.get("polling_station") or "", disabled=True)

        col3, col4 = st.columns(2)
        col3.text_input("Ward",            value=parsed.get("ward") or "",            disabled=True)
        col4.text_input("Constituency",    value=parsed.get("constituency") or "",    disabled=True)

        col5, col6 = st.columns(2)
        col5.text_input("County",          value=parsed.get("county") or "",          disabled=True)
        col6.text_input("Date",            value=parsed.get("date") or "",            disabled=True)

        col7, col8, col9 = st.columns(3)
        col7.number_input("Registered voters", value=int(parsed.get("registered_voters") or 0), disabled=True)
        col8.number_input("Valid votes",        value=int(parsed.get("total_valid_votes") or 0), disabled=True)
        col9.number_input("Rejected ballots",   value=int(parsed.get("rejected_ballots") or 0),  disabled=True)

        candidates = parsed.get("candidates", [])
        if candidates:   
            st.markdown(
                "<h5 style='font-size:2.25rem !important; margin:0;'>Candidates</h5>",
                unsafe_allow_html=True,
            )

            st.dataframe(
                pd.DataFrame(candidates).rename(
                    columns={"number": "#", "name": "Candidate", "votes": "Votes"}
                ),
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        col_submit, col_discard, _ = st.columns([1.5, 1.5, 7])
        if col_submit.button("Submit", type="primary", use_container_width=True):
            try:
                with st.spinner("Saving…"):
                    form_id = commit_form(parsed, uploaded_by=st.session_state.get("username", ""))
                st.session_state.submit_result = {
                    "form_id": form_id,
                    "station": parsed.get("polling_station"),
                }
                st.session_state.parsed_form = None
                st.rerun()
            except (ValueError, RuntimeError) as e:
                st.error(str(e))
        if col_discard.button("Discard", use_container_width=True):
            st.session_state.parsed_form = None
            st.rerun()

# ── Step 1: upload + extract ───────────────────────────────────────────────────
else:
    with st.container(key="card_upload"):
        st.caption(
            "Take a photo of the form or upload a scan. Keep the whole form flat, "
            "well lit and in frame — the form type (34A–39A) and polling station "
            "are read from the form itself, so any filename works."
        )
        tab_photo, tab_file = st.tabs(["📷 Take photo", "📁 Upload file"])
        with tab_photo:
            photo = camera_uploader(
                "Take a photo of the form",
                key="form_camera",
                help="On a phone this opens the camera. Use the back camera and fill the frame with the form.",
            )
        with tab_file:
            file = st.file_uploader(
                "Choose a form file (PDF, PNG, JPG, JPEG, TIFF, BMP, WEBP)",
                type=["pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"],
                key="form_file",
            )
        uploaded = photo or file
        if photo and file:
            st.info(f"Both a photo and a file are selected — the photo ({photo.name}) will be processed.")
        force = st.checkbox("Re-process if already in DB", value=False)

        # Always show the button (disabled until a file arrives) so agents
        # know what comes next. A failed upload (red ⓘ on the file) happens
        # entirely in the browser — the server never sees the file, so the
        # best we can do is explain what that icon means.
        process = st.button("Process", type="primary", disabled=uploaded is None)
        if uploaded is None:
            st.caption(
                "The Process button turns on once your photo or file has finished uploading. "
                "If the file shows a red ⓘ, the upload didn't reach the server — tap the ⓘ to "
                "see why, remove the file (✕) and try again. If it keeps failing, try another "
                "browser such as Chrome, or a stronger network connection."
            )

        if uploaded and process:
            dest = save_upload(uploaded.read(), uploaded.name)
            try:
                with st.spinner(f"Extracting data from {uploaded.name} — this takes ~20 s…"):
                    result = parse_form(Path(dest), api_key, force=force)
                st.session_state.parsed_form = result
                st.rerun()
            except (ValueError, RuntimeError) as e:
                st.error(str(e))
