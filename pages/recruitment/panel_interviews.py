import streamlit as st

from db import (
    APPLICATION_STAGE_LABELS,
    count_applicant_documents_for,
    get_applicant_document_bytes,
    get_application,
    get_panel_assignment,
    is_panelist,
    list_applicant_documents,
    list_applications,
    list_interview_qa_aggregated,
    list_interview_qa_for_panelist,
    list_panel_assignments_for_user,
    list_positions,
    upsert_interview_answer,
)
from theme import apply_theme, clear_query_params_url

ALLOWED_STAGES = ("shortlisting", "interview", "hired")
CANDIDATES_PAGE_SIZE = 25
PANEL_ROLE_LABELS = {"chairman": "Chairman", "secretary": "Secretary", "member": "Member"}

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>My Interview Panel</h4>",
    unsafe_allow_html=True,
)

role = st.session_state.role
username = st.session_state.username

if role != "admin" and not is_panelist(username):
    st.info("You are not currently assigned to any interview panel. Contact an admin.")
    st.stop()

# ── Position picker ──────────────────────────────────────────────────────────
if role == "admin":
    position_options = [p["title"] for p in list_positions()]
    position_labels = {p: p for p in position_options}
else:
    my_assignments = list_panel_assignments_for_user(username)
    if not my_assignments:
        st.info("You are not currently assigned to any interview panel. Contact an admin.")
        st.stop()
    position_options = [a["position"] for a in my_assignments]
    position_labels = {
        a["position"]: (
            f"{a['position']} — {a['panel_role'].capitalize()}"
            + (f" ({a['interview_date']})" if a.get("interview_date") else "")
        )
        for a in my_assignments
    }

if not position_options:
    st.info("No recruitment positions available.")
    st.stop()


def _cell(val):
    text = str(val) if val not in (None, "") else "—"
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
    return f"<td title='{safe}'>{safe}</td>"


def _render_candidate_card(app_id: str):
    if st.button("⬅ Back to candidates"):
        st.session_state.panel_viewing_id = None
        st.rerun()

    application = get_application(app_id)
    if not application:
        st.error("Candidate not found.")
        return

    # Use the candidate's own position, not the list page's selected-position
    # filter — "View" is a full page navigation (target="_top"), which can
    # land here before that selectbox has ever run in this session.
    position = application.get("position") or ""

    with st.container(key="card_panel_candidate"):
        st.markdown(
            f"### {application.get('surname') or ''} {application.get('other_names') or ''}".strip()
        )
        st.caption(
            f"Position: {application.get('position') or '—'} · "
            f"Stage: {APPLICATION_STAGE_LABELS.get(application.get('stage'), application.get('stage'))}"
        )
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Email**  \n{application.get('email') or '—'}")
            st.markdown(f"**Phone number**  \n{application.get('phone_number') or '—'}")
            st.markdown(f"**Gender**  \n{application.get('gender') or '—'}")
        with col2:
            dob = application.get("date_of_birth")
            st.markdown(f"**Date of birth**  \n{dob if dob else '—'}")
            st.markdown(
                "**Location**  \n"
                f"{application.get('county') or '—'} / "
                f"{application.get('sub_county') or '—'} / "
                f"{application.get('ward') or '—'}"
            )

    with st.container(key="card_panel_attachments"):
        st.markdown(
            "<h4 style='font-size:1.3rem !important; margin:0 0 0.75rem;'>Attachments</h4>",
            unsafe_allow_html=True,
        )
        docs = list_applicant_documents(app_id)
        if not docs:
            st.caption("No attachments.")
        else:
            for d in docs:
                col_doc, col_dl = st.columns([5, 1])
                uploaded_at = str(d.get("uploaded_at") or "")[:16]
                col_doc.markdown(f"📄 **{d['title']}** — {d['original_filename']} · {uploaded_at}")
                result = get_applicant_document_bytes(d["id"])
                if result:
                    file_bytes, display_name = result
                    col_dl.download_button(
                        "⬇", file_bytes, file_name=display_name,
                        key=f"panel_dl_appdoc_{app_id}_{d['id']}", use_container_width=True,
                    )

    my_assignment = get_panel_assignment(username, position)
    show_own_answers = my_assignment is not None
    show_aggregate = role == "admin" or (my_assignment and my_assignment["panel_role"] == "secretary")

    if show_own_answers:
        with st.container(key="card_panel_my_answers"):
            st.markdown(
                "<h4 style='font-size:1.3rem !important; margin:0 0 0.75rem;'>My answers</h4>",
                unsafe_allow_html=True,
            )
            st.caption("Only you can see these answers.")
            qa_rows = list_interview_qa_for_panelist(app_id, position, username)
            if not qa_rows:
                st.caption(
                    "No interview questions configured for this position. "
                    "Ask an admin to add some under Recruitment ➜ Interview Questions."
                )
            else:
                with st.form(f"panel_answers_form_{app_id}"):
                    answers = {}
                    for qa in qa_rows:
                        qid = qa["question_id"]
                        type_label = "Oral" if qa.get("question_type") == "oral" else "Written"
                        answers[qid] = st.text_area(
                            f"{qa['question']}  ·  _{type_label}_", value=qa.get("answer") or "",
                            key=f"panel_answer_{app_id}_{qid}", height=100,
                        )
                        if qa.get("answered_at"):
                            st.caption(f"Last saved · {str(qa['answered_at'])[:16]}")
                    if st.form_submit_button("💾 Save answers", type="primary", use_container_width=True):
                        for qid, answer_text in answers.items():
                            upsert_interview_answer(app_id, qid, answer_text.strip(), username)
                        st.success("Your answers have been saved.")
                        st.rerun()

    if show_aggregate:
        with st.container(key="card_panel_aggregate"):
            st.markdown(
                "<h4 style='font-size:1.3rem !important; margin:0 0 0.75rem;'>All panelists' answers</h4>",
                unsafe_allow_html=True,
            )
            qa_rows = list_interview_qa_aggregated(app_id, position)
            if not qa_rows:
                st.caption("No interview questions configured for this position.")
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
                                f"- **{a['panelist_name']}** _({PANEL_ROLE_LABELS.get(a['panel_role'], a['panel_role'])})_ "
                                f"· {answered_at}  \n{a['answer'] or '_No answer recorded._'}"
                            )
                    st.divider()


if "panel_viewing_id" not in st.session_state:
    st.session_state.panel_viewing_id = None

# ── URL-triggered "view" action (row links can't call Python directly) ──────
_CONSUMED = "_panel_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_url_key = st.query_params.get("panel_view")
if _url_key and _url_key != st.session_state[_CONSUMED]:
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
    st.session_state.panel_viewing_id = _url_key
    st.rerun()
elif not _url_key:
    st.session_state[_CONSUMED] = None

if st.session_state.panel_viewing_id:
    _render_candidate_card(st.session_state.panel_viewing_id)
else:
    with st.container(key="card_panel_list"):
        col_pos, col_search = st.columns([3, 5])
        selected_position = col_pos.selectbox(
            "Position", position_options, format_func=lambda p: position_labels.get(p, p),
            key="panel_selected_position",
        )
        search = col_search.text_input(
            "Filter Table Records", placeholder="Search candidates by name or email",
             key="panel_search",
        )

        all_candidates = list_applications(search, positions=[selected_position])
        candidates = [c for c in all_candidates if c.get("stage") in ALLOWED_STAGES]

        if "panel_page" not in st.session_state:
            st.session_state.panel_page = 0
        total_pages = max(1, (len(candidates) + CANDIDATES_PAGE_SIZE - 1) // CANDIDATES_PAGE_SIZE)
        st.session_state.panel_page = min(st.session_state.panel_page, total_pages - 1)
        page = st.session_state.panel_page
        page_candidates = candidates[page * CANDIDATES_PAGE_SIZE: (page + 1) * CANDIDATES_PAGE_SIZE]

        if not candidates:
            st.info("No shortlisted or interview-stage candidates for this position yet.")
        else:
            doc_counts = count_applicant_documents_for([str(c["id"]) for c in page_candidates])
            rows_html = ""
            for c in page_candidates:
                cid = str(c["id"])
                actions = f'<a class="view-btn" href="?panel_view={cid}" target="_top">👁 View</a>'
                rows_html += f"""<tr>
                    <td class="actions-cell">{actions}</td>
                    {_cell(c.get('surname'))} {_cell(c.get('other_names'))}
                    {_cell(c.get('email'))}
                    {_cell(APPLICATION_STAGE_LABELS.get(c.get('stage'), c.get('stage')))}
                    {_cell(doc_counts.get(cid, 0))}
                </tr>"""

            st.html(f"""
            <style>
                .panel-tbl-wrap{{overflow-x:auto;width:100%}}
                .panel-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
                .panel-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
                .panel-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937}}
                .panel-tbl tr:hover td{{background:#f9fafb}}
                .actions-cell{{white-space:nowrap;display:flex;gap:4px;align-items:center;
                    position:sticky;left:0;background:#fff;z-index:1}}
                .panel-tbl tr:hover .actions-cell{{background:#f9fafb}}
                .view-btn{{border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;
                    display:inline-block;background:#2563eb;color:white!important}}
                .view-btn:hover{{background:#1d4ed8}}
            </style>
            <div class="panel-tbl-wrap">
                <table class="panel-tbl">
                    <thead><tr>
                        <th>Actions</th><th>Surname</th><th>Other names</th>
                        <th>Email</th><th>Stage</th><th>Documents</th>
                    </tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
            """)

            col_prev, col_info, col_next = st.columns([1, 3, 1])
            if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True, key="panel_prev"):
                st.session_state.panel_page -= 1
                st.rerun()
            col_info.markdown(
                f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {len(candidates)} candidate(s)</div>",
                unsafe_allow_html=True,
            )
            if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True, key="panel_next"):
                st.session_state.panel_page += 1
                st.rerun()
