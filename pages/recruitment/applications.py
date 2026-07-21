import base64
import datetime
import os

import pandas as pd
import streamlit as st

from db import (
    APPLICATION_STAGE_LABELS,
    APPLICATION_STAGES,
    add_applicant_document,
    count_applicant_documents_for,
    count_applications,
    count_applications_by_stage,
    create_application,
    delete_applicant_document,
    delete_applications,
    find_ward_by_names,
    get_applicant_document_bytes,
    get_application,
    list_applicant_documents,
    list_applications,
    list_interview_qa_aggregated,
    list_positions,
    save_applicant_document_file,
    update_application_profile,
    update_applications_stage,
)
from location_picker import location_picker
from screening import apply_screening_result, screen_application
from theme import apply_theme, clear_query_params_url

GENDER_OPTIONS = ["", "Male", "Female", "Other", "Prefer not to say"]
APPLICATIONS_PAGE_SIZE = 25

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Applications</h4>",
    unsafe_allow_html=True,
)

# Color the bulk-action-bar buttons (below each stage's table) by targeting
# Streamlit's auto-generated "st-key-<key>" class. Per-row actions are HTML
# links rendered inside the table itself (styled inline in _render_stage_tab)
# so the table can scroll horizontally — native st.columns can't do that.
st.markdown("""
<style>
[class*="st-key-bulk_del_"] button {
    background:#dc2626; color:#fff !important; border-color:#dc2626;
}
[class*="st-key-bulk_del_"] button:hover { background:#b91c1c; border-color:#b91c1c; }
[class*="st-key-bulk_analyze_"] button {
    background:#7c3aed; color:#fff !important; border-color:#7c3aed;
}
[class*="st-key-bulk_analyze_"] button:hover { background:#6d28d9; border-color:#6d28d9; }
[class*="st-key-bulk_move_"] button {
    background:#16a34a; color:#fff !important; border-color:#16a34a;
}
[class*="st-key-bulk_move_"] button:hover { background:#15803d; border-color:#15803d; }
</style>
""", unsafe_allow_html=True)


@st.dialog("Document preview", width="large")
def _document_preview_dialog(doc_id: int):
    result = get_applicant_document_bytes(doc_id)
    if not result:
        st.error("File not found.")
        if st.button("Close", use_container_width=True):
            st.rerun()
        return

    file_bytes, display_name = result
    ext = display_name.rsplit(".", 1)[-1].lower() if "." in display_name else ""

    st.markdown(f"**{display_name}**")
    if ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp"):
        st.image(file_bytes, use_container_width=True)
    elif ext == "pdf":
        b64 = base64.b64encode(file_bytes).decode()
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="600" '
            'style="border:none;"></iframe>',
            unsafe_allow_html=True,
        )
    else:
        st.info("Preview isn't available for this file type — download it instead.")

    st.download_button("⬇ Download", file_bytes, file_name=display_name, use_container_width=True)
    if st.button("Close", use_container_width=True):
        st.rerun()


def _attachments_section(application_id, uploaded_by: str):
    """Shared list + upload UI for an application's attachments (CVs, ID
    scans, certificates, etc.), used from the Edit page."""
    st.markdown(
        "<h5 style='font-size:1.15rem !important; margin:1rem 0 0.25rem;'>Attachments</h5>",
        unsafe_allow_html=True,
    )
    docs = list_applicant_documents(application_id)
    if not docs:
        st.caption("No attachments yet.")
    else:
        for d in docs:
            col_doc, col_view, col_dl, col_del = st.columns([5, 1, 1, 1])
            uploaded_at = str(d.get("uploaded_at") or "")[:16]
            col_doc.markdown(f"📄 **{d['title']}** — {d['original_filename']} · {uploaded_at}")
            if col_view.button("👁", key=f"view_appdoc_{application_id}_{d['id']}", use_container_width=True, help="View"):
                _document_preview_dialog(d["id"])
            result = get_applicant_document_bytes(d["id"])
            if result:
                file_bytes, display_name = result
                col_dl.download_button(
                    "⬇", file_bytes, file_name=display_name,
                    key=f"dl_appdoc_{application_id}_{d['id']}", use_container_width=True,
                )
            if col_del.button("🗑", key=f"del_appdoc_{application_id}_{d['id']}", use_container_width=True):
                delete_applicant_document(d["id"])
                st.rerun()

    with st.form(f"upload_appdoc_form_{application_id}", clear_on_submit=True):
        col_title, col_file = st.columns([2, 3])
        doc_title = col_title.text_input("Document title", placeholder="e.g. CV, National ID, Certificate")
        doc_file  = col_file.file_uploader("File", label_visibility="collapsed")
        if st.form_submit_button("📎 Attach document"):
            if not doc_title.strip() or not doc_file:
                st.error("A title and a file are both required.")
            else:
                stored_name = save_applicant_document_file(application_id, doc_file.name, doc_file.read())
                add_applicant_document(application_id, doc_title.strip(), stored_name, doc_file.name, uploaded_by)
                st.success("Document attached.")
                st.rerun()


# ── Dialogs ───────────────────────────────────────────────────────────────────
def _render_view_page(id: str):
    """Full-page (non-modal) read-only view of an application, split into
    three cards: Applicant details, Attachments, and Analysis. Attachments
    open in their own modal (_document_preview_dialog) for a quick look
    without leaving this page."""
    if st.button("⬅ Back to list"):
        st.session_state.apps_viewing_id = None
        st.rerun()

    application = get_application(id)
    if not application:
        st.error("Application not found.")
        return

    with st.container(key="card_view_details"):
        st.markdown(f"### {application.get('surname') or ''} {application.get('other_names') or ''}".strip())
        st.caption(f"Stage: {APPLICATION_STAGE_LABELS.get(application.get('stage'), application.get('stage'))}")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Email**  \n{application.get('email') or '—'}")
            st.markdown(f"**Position**  \n{application.get('position') or '—'}")
            st.markdown(f"**ID/Passport number**  \n{application.get('id_passport_number') or '—'}")
            st.markdown(f"**Phone number**  \n{application.get('phone_number') or '—'}")
        with col2:
            st.markdown(f"**Gender**  \n{application.get('gender') or '—'}")
            dob = application.get("date_of_birth")
            st.markdown(f"**Date of birth**  \n{dob if dob else '—'}")
            st.markdown(
                "**Location**  \n"
                f"{application.get('county') or '—'} / "
                f"{application.get('sub_county') or '—'} / "
                f"{application.get('ward') or '—'}"
            )
            created = str(application.get("created_at") or "")[:16]
            st.markdown(f"**Created**  \n{created or '—'}")

    with st.container(key="card_view_attachments"):
        st.markdown(
            "<h4 style='font-size:1.3rem !important; margin:0 0 0.75rem;'>Attachments</h4>",
            unsafe_allow_html=True,
        )
        docs = list_applicant_documents(id)
        if not docs:
            st.caption("No attachments.")
        else:
            for d in docs:
                col_doc, col_view, col_dl, col_del = st.columns([5, 1, 1, 1])
                uploaded_at = str(d.get("uploaded_at") or "")[:16]
                col_doc.markdown(f"📄 **{d['title']}** — {d['original_filename']} · {uploaded_at}")
                if col_view.button("👁", key=f"view_pg_appdoc_{id}_{d['id']}", use_container_width=True, help="View"):
                    _document_preview_dialog(d["id"])
                result = get_applicant_document_bytes(d["id"])
                if result:
                    file_bytes, display_name = result
                    col_dl.download_button(
                        "⬇", file_bytes, file_name=display_name,
                        key=f"view_dl_appdoc_{id}_{d['id']}", use_container_width=True,
                    )
                if col_del.button("🗑", key=f"view_del_appdoc_{id}_{d['id']}", use_container_width=True, help="Delete"):
                    delete_applicant_document(d["id"])
                    st.rerun()

    with st.container(key="card_view_analysis"):
        st.markdown(
            "<h4 style='font-size:1.3rem !important; margin:0 0 0.75rem;'>Analysis</h4>",
            unsafe_allow_html=True,
        )
        verified, qualified = _verified_qualified(application)
        col3, col4, col5 = st.columns(3)
        col3.markdown(f"**Verified**  \n{verified}")
        col4.markdown(f"**Qualified**  \n{qualified}")
        analyzed_at = str(application.get("analyzed_at") or "")[:16]
        col5.markdown(f"**Analyzed**  \n{analyzed_at or '—'}")
        if application.get("qualification_reason"):
            st.markdown(f"**Reason**  \n{application['qualification_reason']}")
        elif not application.get("analyzed_at"):
            st.caption("Not yet analyzed.")

    if application.get("stage") in ("shortlisting", "interview", "hired"):
        with st.container(key="card_view_interview"):
            st.markdown(
                "<h4 style='font-size:1.3rem !important; margin:0 0 0.75rem;'>Interview</h4>",
                unsafe_allow_html=True,
            )
            st.caption("Aggregated answers from every panelist. Panelists record their own "
                       "answers privately under My Interview Panel.")
            qa_rows = list_interview_qa_aggregated(id, application.get("position") or "")
            if not qa_rows:
                st.caption(
                    "No interview questions configured for this position. "
                    "Add some under Recruitment ➜ Interview Questions."
                )
            else:
                for qa in qa_rows:
                    type_label = "Oral" if qa.get("question_type") == "oral" else "Written"
                    st.markdown(f"**{qa['question']}**  ·  _{type_label}_")
                    if not qa["answers"]:
                        st.caption("No panelist has answered yet.")
                    else:
                        for a in qa["answers"]:
                            answered_at = str(a.get("answered_at") or "")[:16]
                            st.markdown(
                                f"- **{a['panelist_name']}** _({a['panel_role']})_ · {answered_at}  \n"
                                f"{a['answer'] or '_No answer recorded._'}"
                            )
                    st.divider()


@st.dialog("Confirm removal")
def _confirm_remove(ids: list[str]):
    n = len(ids)
    st.write(f"Remove {n} application{'s' if n != 1 else ''}? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, remove", type="primary", use_container_width=True):
        delete_applications(ids)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


def _analyze_one(application_id: str):
    """Screen a single application against its position's published job
    description, moving it to Shortlisting if it qualifies."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        st.error("ANTHROPIC_API_KEY is not configured — cannot analyze applications.")
        return
    with st.spinner("Analyzing application..."):
        try:
            result = screen_application(application_id, api_key)
        except ValueError as e:
            st.session_state["apps_flash"] = ("error", str(e))
            st.rerun()
        except Exception as e:
            st.session_state["apps_flash"] = ("error", f"Analysis failed: {e}")
            st.rerun()
        apply_screening_result(application_id, result)
    if result["qualifies"]:
        st.session_state["apps_flash"] = ("success", "Applicant qualifies — moved to Shortlisting.")
    else:
        st.session_state["apps_flash"] = ("warning", f"Applicant does not qualify: {result['reason']}")
    st.rerun()


def _analyze_all_pending(search: str):
    """Bulk-screen every application still sitting in the Application stage
    (matching the current search), moving qualifying ones to Shortlisting."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        st.error("ANTHROPIC_API_KEY is not configured — cannot analyze applications.")
        return

    pending = list_applications(search, stage="application")
    if not pending:
        st.session_state["apps_flash"] = ("info", "No applications waiting to be analyzed.")
        st.rerun()

    status = st.status(f"Analyzing {len(pending)} application(s)...", expanded=True)
    qualified = disqualified = errors = 0
    for i, app in enumerate(pending, start=1):
        rid = str(app["id"])
        label = f"{app.get('surname') or ''} {app.get('other_names') or ''}".strip() or f"#{rid}"
        status.write(f"({i}/{len(pending)}) {label}...")
        try:
            result = screen_application(rid, api_key)
            apply_screening_result(rid, result)
            if result["qualifies"]:
                qualified += 1
                status.write("  ✅ Qualifies — moved to Shortlisting.")
            else:
                disqualified += 1
                status.write(f"  ❌ {result['reason']}")
        except Exception as e:
            errors += 1
            status.write(f"  ⚠️ {e}")

    summary = f"{qualified} moved to Shortlisting, {disqualified} did not qualify"
    if errors:
        summary += f", {errors} error(s)"
    status.update(label=f"Done: {summary}.", state="complete")
    st.session_state["apps_flash"] = ("success", f"Analysis complete: {summary}.")
    st.rerun()


def _render_edit_page(id: str):
    """Full-page (non-modal) editor. Unlike a dialog, this stays open across
    reruns triggered from within it — e.g. attaching a document — so the
    admin can add several attachments without the view closing on them."""
    if st.button("⬅ Back to list"):
        st.session_state.apps_editing_id = None
        st.rerun()

    positions_data = list_positions()
    position_options = [""] + [p["title"] for p in positions_data]
    application = get_application(id)
    if not application:
        st.error("Application not found.")
        return

    st.markdown(
        f"<h3 style='margin:0.5rem 0 1rem;'>Edit application — "
        f"{application.get('surname') or ''} {application.get('other_names') or ''}</h3>",
        unsafe_allow_html=True,
    )
    current_pos = application.get("position") or ""
    pos_index = position_options.index(current_pos) if current_pos in position_options else 0
    col1, col2 = st.columns(2)
    surname     = col1.text_input("Surname",     value=application.get("surname")     or "")
    other_names = col2.text_input("Other names", value=application.get("other_names") or "")
    email      = st.text_input("Email",        value=application.get("email")      or "")
    position   = st.selectbox("Position", position_options, index=pos_index)

    col5, col6 = st.columns(2)
    id_passport_number = col5.text_input("ID/Passport number", value=application.get("id_passport_number") or "")
    phone_number       = col6.text_input("Phone number",       value=application.get("phone_number") or "")

    col7, col8 = st.columns(2)
    gender_idx   = GENDER_OPTIONS.index(application.get("gender")) if application.get("gender") in GENDER_OPTIONS else 0
    gender       = col7.selectbox("Gender", GENDER_OPTIONS, index=gender_idx)
    date_of_birth = col8.date_input(
        "Date of birth", value=application.get("date_of_birth"),
        min_value=datetime.date(1900, 1, 1), max_value=datetime.date.today(),
    )

    current_ward_id = application.get("ward_id") or find_ward_by_names(
        application.get("county"), application.get("sub_county"), application.get("ward"),
    )
    st.caption("County / Constituency (Sub-county) / Ward")
    location = location_picker(f"edit_application_{id}", current_ward_id)
    if location is None:
        st.caption(
            f"Currently unlinked: {application.get('county') or '—'} / "
            f"{application.get('sub_county') or '—'} / {application.get('ward') or '—'}. "
            "Pick all three levels above to (re)link this application."
        )

    col3, col4 = st.columns(2)
    if col3.button("Save", type="primary", use_container_width=True):
        loc = location or {
            "county": application.get("county"), "constituency": application.get("sub_county"),
            "ward": application.get("ward"), "ward_id": application.get("ward_id"),
        }
        update_application_profile(
            id, other_names, surname, email, position,
            id_passport_number=id_passport_number, phone_number=phone_number,
            gender=gender, date_of_birth=date_of_birth,
            county=loc["county"] or "", sub_county=loc["constituency"] or "", ward=loc["ward"] or "",
            ward_id=loc["ward_id"],
        )
        st.success("Saved.")
        st.rerun()
    if col4.button("Cancel", use_container_width=True):
        st.session_state.apps_editing_id = None
        st.rerun()

    _attachments_section(id, uploaded_by=st.session_state.username)


@st.dialog("Create application", width="large")
def _create_dialog():
    positions_data    = list_positions()
    position_options  = [""] + [p["title"] for p in positions_data]

    st.selectbox("Position *", position_options, key="dlg_ca_position")

    st.caption("County / Constituency (Sub-county) / Ward")
    location = location_picker("create_application", None)

    with st.form("dlg_create_application_form"):
        col1, col2 = st.columns(2)
        surname     = col1.text_input("Surname")
        other_names = col2.text_input("Other names")
        email       = st.text_input("Email")

        col5, col6 = st.columns(2)
        id_passport_number = col5.text_input("ID/Passport number")
        phone_number       = col6.text_input("Phone number")

        col7, col8 = st.columns(2)
        gender        = col7.selectbox("Gender", GENDER_OPTIONS)
        date_of_birth = col8.date_input(
            "Date of birth", value=None,
            min_value=datetime.date(1900, 1, 1), max_value=datetime.date.today(),
        )

        attachments = st.file_uploader(
            "Attachments (CV, ID, certificates, etc.)", accept_multiple_files=True,
        )

        submitted = st.form_submit_button("Create application", type="primary", use_container_width=True)

    if submitted:
        position = st.session_state.get("dlg_ca_position", "")
        if not position:
            st.error("Position is required.")
        else:
            try:
                new_id = create_application(
                    other_names=other_names, surname=surname,
                    email=email, position=position,
                    id_passport_number=id_passport_number, phone_number=phone_number,
                    gender=gender, date_of_birth=date_of_birth,
                    county=(location or {}).get("county", ""),
                    sub_county=(location or {}).get("constituency", ""),
                    ward=(location or {}).get("ward", ""),
                    ward_id=(location or {}).get("ward_id"),
                )
                for f in (attachments or []):
                    stored_name = save_applicant_document_file(new_id, f.name, f.read())
                    add_applicant_document(new_id, f.name, stored_name, f.name, st.session_state.username)
                st.success(f"Application for '{surname} {other_names}' created ({position}).")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to create application: {e}")


@st.dialog("Bulk import applications", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{
        "other_names": "Jane", "surname": "Doe",
        "email": "jane@example.com", "position": "Presiding Officer (PO)",
        "id_passport_number": "", "phone_number": "",
        "gender": "", "county": "", "sub_county": "", "ward": "",
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="applications_template.csv", mime="text/csv",
    )

    if "applications_upload_key" not in st.session_state:
        st.session_state.applications_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"applications_bulk_{st.session_state.applications_upload_key}",
    )

    if not uploaded:
        return

    try:
        df = pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    missing = {"surname", "position"} - set(df.columns)
    if missing:
        st.error(f"Missing required columns: {', '.join(missing)}")
        return

    st.caption(f"{len(df)} row(s) — preview:")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("Import applications", type="primary", use_container_width=True):
        valid_positions = {p["title"] for p in list_positions()}
        successes, errors = [], []
        for idx, row in df.iterrows():
            line    = idx + 2
            surname = str(row.get("surname", "") or "").strip()
            pos     = str(row.get("position", "") or "").strip()
            if not surname:
                errors.append(f"Row {line}: surname is required.")
                continue
            if pos not in valid_positions:
                errors.append(f"Row {line} ({surname}): unknown position '{pos}'.")
                continue
            try:
                create_application(
                    other_names=str(row.get("other_names", "") or ""),
                    surname=surname,
                    email=str(row.get("email", "") or ""),
                    position=pos,
                    id_passport_number=str(row.get("id_passport_number", "") or ""),
                    phone_number=str(row.get("phone_number", "") or ""),
                    gender=str(row.get("gender", "") or ""),
                    county=str(row.get("county", "") or ""),
                    sub_county=str(row.get("sub_county", "") or ""),
                    ward=str(row.get("ward", "") or ""),
                )
                successes.append(surname)
            except Exception as e:
                errors.append(f"Row {line} ({surname}): {e}")

        if successes:
            st.success(f"Imported {len(successes)} application(s): {', '.join(successes)}.")
        if errors:
            st.error("\n\n".join(errors))
        if successes:
            st.session_state.applications_upload_key += 1
            st.rerun()


def _verified_qualified(row: dict) -> tuple[str, str]:
    """(Verified, Qualified) as Yes/No strings for an application row/dict."""
    verified = "Yes" if row.get("analyzed_at") else "No"
    qualified = "Yes" if row.get("analyzed_at") and not row.get("qualification_reason") else "No"
    return verified, qualified


def _cell(val):
    text = str(val) if val not in (None, "") else "—"
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
    return f"<td>{safe}</td>"


def _apply_select_all(ids: set[str], sel_key: str, select_all_key: str):
    """Callback for the 'select all visible' checkbox above the table."""
    if st.session_state[select_all_key]:
        st.session_state[sel_key] |= ids
    else:
        st.session_state[sel_key] -= ids


def _render_stage_tab(stage: str, search: str):
    """Per-record HTML table — actions (select/view/edit/[analyze]/delete)
    are pinned at the start of each row via a sticky column, and the table
    scrolls horizontally instead of truncating long values."""
    page_key = f"apps_page_{stage}"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    total = count_applications(search, stage=stage)
    total_pages = max(1, (total + APPLICATIONS_PAGE_SIZE - 1) // APPLICATIONS_PAGE_SIZE)
    st.session_state[page_key] = min(st.session_state[page_key], total_pages - 1)
    page = st.session_state[page_key]

    rows = list_applications(search, limit=APPLICATIONS_PAGE_SIZE, offset=page * APPLICATIONS_PAGE_SIZE, stage=stage)

    if not rows:
        st.info("No applications in this stage.")
        return

    sel_key = f"apps_selected_{stage}"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = set()
    visible_ids = {str(r["id"]) for r in rows}
    st.session_state[sel_key] &= visible_ids  # drop selections that scrolled off this page

    select_all_key = f"select_all_{stage}"
    if select_all_key not in st.session_state:
        st.session_state[select_all_key] = False

    is_application_stage = stage == "application"

    st.checkbox(
        "Select all visible", value=st.session_state[select_all_key], key=select_all_key,
        on_change=_apply_select_all, args=(visible_ids, sel_key, select_all_key),
    )

    doc_counts = count_applicant_documents_for(list(visible_ids))

    selected = st.session_state[sel_key]
    rows_html = ""
    for r in rows:
        rid = str(r["id"])
        is_selected = rid in selected
        toggle_icon = "✅" if is_selected else "⬜"
        # The link encodes the *resulting* full selected set (not just this row's id) —
        # a plain "toggle this id" link can't survive the fact that each row-action
        # click is a full page navigation, which starts a brand-new Streamlit session
        # and loses whatever was previously accumulated in session_state.
        new_selected = (selected - {rid}) if is_selected else (selected | {rid})
        toggle_href = ",".join(sorted(new_selected, key=int))
        actions = (
            f'<a class="sel-btn" href="?app_selected_{stage}={toggle_href}" target="_top" title="Select">{toggle_icon}</a>'
            f'<a class="view-btn" href="?app_view={rid}" target="_top" title="Details">👁</a>'
            f'<a class="edit-btn" href="?app_edit={rid}" target="_top" title="Update">✏</a>'
        )
        if is_application_stage:
            actions += f'<a class="analyze-btn" href="?app_analyze={rid}" target="_top" title="Analyze">🔍</a>'
        actions += f'<a class="del-btn" href="?app_delete={rid}" target="_top" title="Delete">🗑</a>'

        cells = (
            f"{_cell(r.get('surname'))}{_cell(r.get('other_names'))}"
            f"{_cell(r.get('email'))}{_cell(r.get('position'))}"
            f"{_cell(doc_counts.get(rid, 0))}"
        )
        if is_application_stage:
            verified, qualified = _verified_qualified(r)
            reason = r.get("qualification_reason") or ("Not yet analyzed" if not r.get("analyzed_at") else "")
            cells += f"{_cell(verified)}{_cell(qualified)}{_cell(reason)}"
        cells += _cell(str(r.get("created_at") or "")[:16])

        rows_html += f'<tr><td class="actions-cell">{actions}</td>{cells}</tr>'

    extra_headers = "<th>Verified</th><th>Qualified</th><th>Reason</th>" if is_application_stage else ""

    st.html(f"""
    <style>
        .apps-tbl-wrap{{overflow-x:auto;width:100%}}
        .apps-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
        .apps-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
        .apps-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937}}
        .apps-tbl tr:hover td{{background:#f9fafb}}
        .actions-cell{{white-space:nowrap;display:flex;gap:4px;align-items:center;
            position:sticky;left:0;background:#fff;z-index:1}}
        .apps-tbl tr:hover .actions-cell{{background:#f9fafb}}
        .sel-btn,.view-btn,.edit-btn,.del-btn,.analyze-btn{{
            border-radius:5px;padding:3px 7px;font-size:12px;white-space:nowrap;text-decoration:none;display:inline-block}}
        .sel-btn{{background:#f1f5f9}}.sel-btn:hover{{background:#e2e8f0}}
        .view-btn{{background:#2563eb;color:white!important}}.view-btn:hover{{background:#1d4ed8}}
        .edit-btn{{background:#d97706;color:white!important}}.edit-btn:hover{{background:#b45309}}
        .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        .analyze-btn{{background:#7c3aed;color:white!important}}.analyze-btn:hover{{background:#6d28d9}}
    </style>
    <div class="apps-tbl-wrap">
        <table class="apps-tbl">
            <thead><tr>
                <th>Actions</th><th>Surname</th><th>Other names</th>
                <th>Email</th><th>Position</th><th>Documents</th>{extra_headers}<th>Created</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
    """)

    selected_ids = sorted(st.session_state[sel_key], key=int)
    col_count, col_stage, col_move, col_del_sel = st.columns([1.5, 2, 1, 1])
    col_count.markdown(f"{len(selected_ids)} selected" if selected_ids else "")
    other_stages = [s for s in APPLICATION_STAGES if s != stage]
    target_stage = col_stage.selectbox(
        "Move selected to", other_stages, format_func=lambda s: APPLICATION_STAGE_LABELS[s],
        label_visibility="collapsed", key=f"move_target_{stage}", disabled=not selected_ids,
    )
    if col_move.button("Move ➜", disabled=not selected_ids, use_container_width=True, key=f"bulk_move_btn_{stage}"):
        update_applications_stage(selected_ids, target_stage)
        st.session_state[sel_key] = set()
        st.success(f"Moved {len(selected_ids)} application(s) to {APPLICATION_STAGE_LABELS[target_stage]}.")
        st.rerun()
    if col_del_sel.button("🗑 Delete selected", disabled=not selected_ids, use_container_width=True, key=f"bulk_del_btn_{stage}"):
        _confirm_remove(selected_ids)

    col_prev, col_info, col_next = st.columns([1, 3, 1])
    if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True, key=f"apps_prev_{stage}"):
        st.session_state[page_key] -= 1
        st.rerun()
    col_info.markdown(
        f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} application(s)</div>",
        unsafe_allow_html=True,
    )
    if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True, key=f"apps_next_{stage}"):
        st.session_state[page_key] += 1
        st.rerun()


if "apps_editing_id" not in st.session_state:
    st.session_state.apps_editing_id = None
if "apps_viewing_id" not in st.session_state:
    st.session_state.apps_viewing_id = None

# ── URL-triggered row actions (HTML table links can't call Python directly) ─
_CONSUMED = "_apps_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_url_key = None
if st.query_params.get("app_view"):
    _url_key = ("view", st.query_params["app_view"])
elif st.query_params.get("app_edit"):
    _url_key = ("edit", st.query_params["app_edit"])
elif st.query_params.get("app_delete"):
    _url_key = ("delete", st.query_params["app_delete"])
elif st.query_params.get("app_analyze"):
    _url_key = ("analyze", st.query_params["app_analyze"])
else:
    for _stage in APPLICATION_STAGES:
        _pname = f"app_selected_{_stage}"
        if _pname in st.query_params:
            _url_key = (f"selset:{_stage}", st.query_params[_pname])
            break

if _url_key and _url_key != st.session_state[_CONSUMED]:
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
    _kind, _arg = _url_key
    if _kind == "view":
        st.session_state.apps_viewing_id = _arg
        st.rerun()
    elif _kind == "edit":
        st.session_state.apps_editing_id = _arg
        st.rerun()
    elif _kind == "delete":
        _confirm_remove([_arg])
    elif _kind == "analyze":
        _analyze_one(_arg)
    elif _kind.startswith("selset:"):
        _sel_stage = _kind.split(":", 1)[1]
        _sel_key = f"apps_selected_{_sel_stage}"
        st.session_state[_sel_key] = set(_arg.split(",")) if _arg else set()
        st.rerun()
elif not _url_key:
    st.session_state[_CONSUMED] = None  # reset so the same row can be re-triggered after a new page load

# ── Edit/View page (full page, not a modal) or the main list ────────────────
if st.session_state.apps_editing_id:
    with st.container(key="card_applications"):
        _render_edit_page(st.session_state.apps_editing_id)
elif st.session_state.apps_viewing_id:
    _render_view_page(st.session_state.apps_viewing_id)
else:
    with st.container(key="card_applications"):
        if "apps_flash" in st.session_state:
            _kind, _msg = st.session_state.pop("apps_flash")
            getattr(st, _kind)(_msg)

        col_a, col_b, col_c, col_search = st.columns([1.8, 1.8, 2, 3.6])
        create_clicked   = col_a.button("➕ Create application", use_container_width=True)
        bulk_clicked     = col_b.button("📥 Bulk import", use_container_width=True)
        analyze_clicked  = col_c.button("🔍 Analyse Applications", use_container_width=True, key="bulk_analyze_btn")

        search = col_search.text_input(
            "Search", placeholder="Search by name, email or position",
            label_visibility="collapsed", key="applications_search",
        )
        if st.session_state.get("_apps_prev_search") != search:
            for s in APPLICATION_STAGES:
                st.session_state[f"apps_page_{s}"] = 0
            st.session_state["_apps_prev_search"] = search

        if create_clicked:
            _create_dialog()
        elif bulk_clicked:
            _bulk_import_dialog()
        elif analyze_clicked:
            _analyze_all_pending(search)

        stage_counts = count_applications_by_stage(search)
        tab_labels = [f"{APPLICATION_STAGE_LABELS[s]} ({stage_counts.get(s, 0)})" for s in APPLICATION_STAGES]
        for stage, tab in zip(APPLICATION_STAGES, st.tabs(tab_labels)):
            with tab:
                _render_stage_tab(stage, search)
