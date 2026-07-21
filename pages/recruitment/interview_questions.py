import pandas as pd
import streamlit as st

from db import (
    INTERVIEW_QUESTION_TYPES,
    count_interview_questions,
    create_interview_question,
    delete_interview_question,
    get_interview_question,
    list_interview_questions,
    list_positions,
    update_interview_question,
)
from theme import apply_theme, clear_query_params_url

QUESTIONS_PAGE_SIZE = 25
QUESTION_TYPE_LABELS = {"oral": "Oral", "written": "Written"}

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Interview Questions</h4>",
    unsafe_allow_html=True,
)
st.caption("Manage the question bank asked of shortlisted candidates during interviews, per position.")


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Confirm removal")
def _confirm_remove(id: str):
    st.write("Delete this interview question? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_interview_question(id)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Create interview question", width="large")
def _create_dialog():
    position_options = [p["title"] for p in list_positions()]
    position = st.selectbox("Position *", [""] + position_options)
    question = st.text_area("Question *", height=120)
    question_type = st.selectbox(
        "Type *", INTERVIEW_QUESTION_TYPES, format_func=lambda t: QUESTION_TYPE_LABELS[t],
    )

    col1, col2 = st.columns(2)
    if col1.button("Create", type="primary", use_container_width=True):
        if not position or not question.strip():
            st.error("Position and question are both required.")
        else:
            try:
                create_interview_question(position, question.strip(), question_type)
                st.success("Interview question created.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to create interview question: {e}")
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Edit interview question", width="large")
def _edit_dialog(id: str):
    q = get_interview_question(id)
    if not q:
        st.error("Interview question not found.")
        return

    position_options = [p["title"] for p in list_positions()]
    if q["position"] and q["position"] not in position_options:
        position_options = [q["position"]] + position_options
    pos_index = position_options.index(q["position"]) if q["position"] in position_options else 0
    position = st.selectbox("Position *", position_options, index=pos_index)
    question = st.text_area("Question *", value=q.get("question") or "", height=120)
    type_index = INTERVIEW_QUESTION_TYPES.index(q["question_type"]) if q.get("question_type") in INTERVIEW_QUESTION_TYPES else 0
    question_type = st.selectbox(
        "Type *", INTERVIEW_QUESTION_TYPES, index=type_index, format_func=lambda t: QUESTION_TYPE_LABELS[t],
    )

    col1, col2 = st.columns(2)
    if col1.button("Save", type="primary", use_container_width=True):
        if not question.strip():
            st.error("Question is required.")
        else:
            update_interview_question(id, position, question.strip(), question_type)
            st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Bulk import interview questions", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{
        "position": "Presiding Officer (PO)",
        "question": "Describe a time you handled a conflict at a polling station.",
        "question_type": "oral",
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="interview_questions_template.csv", mime="text/csv",
    )

    if "iq_upload_key" not in st.session_state:
        st.session_state.iq_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"iq_bulk_{st.session_state.iq_upload_key}",
    )

    if not uploaded:
        return

    try:
        df = pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    missing = {"position", "question"} - set(df.columns)
    if missing:
        st.error(f"Missing required columns: {', '.join(missing)}")
        return

    st.caption(f"{len(df)} row(s) — preview:")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("Import questions", type="primary", use_container_width=True):
        valid_positions = {p["title"] for p in list_positions()}
        successes, errors = [], []
        for idx, row in df.iterrows():
            line     = idx + 2
            position = str(row.get("position", "") or "").strip()
            question = str(row.get("question", "") or "").strip()
            qtype    = str(row.get("question_type", "") or "oral").strip().lower()
            if not question:
                errors.append(f"Row {line}: question is required.")
                continue
            if position not in valid_positions:
                errors.append(f"Row {line}: unknown position '{position}'.")
                continue
            if qtype not in INTERVIEW_QUESTION_TYPES:
                errors.append(f"Row {line}: invalid question_type '{qtype}' (must be 'oral' or 'written').")
                continue
            try:
                create_interview_question(position, question, qtype)
                successes.append(question)
            except Exception as e:
                errors.append(f"Row {line}: {e}")

        if successes:
            st.success(f"Imported {len(successes)} interview question(s).")
        if errors:
            st.error("\n\n".join(errors))
        if successes:
            st.session_state.iq_upload_key += 1
            st.rerun()


def _cell(val):
    text = str(val) if val not in (None, "") else "—"
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
    return f"<td>{safe}</td>"


def _render_questions(search: str, position_filter: str):
    page_key = "iq_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    position = position_filter or None
    total = count_interview_questions(search, position=position)
    total_pages = max(1, (total + QUESTIONS_PAGE_SIZE - 1) // QUESTIONS_PAGE_SIZE)
    st.session_state[page_key] = min(st.session_state[page_key], total_pages - 1)
    page = st.session_state[page_key]

    rows = list_interview_questions(
        search, position=position, limit=QUESTIONS_PAGE_SIZE, offset=page * QUESTIONS_PAGE_SIZE,
    )

    if not rows:
        st.info("No interview questions found.")
        return

    rows_html = ""
    for q in rows:
        rid = str(q["id"])
        created = str(q.get("created_at") or "")[:16]
        qtype = QUESTION_TYPE_LABELS.get(q.get("question_type"), q.get("question_type"))
        actions = f"""
            <a class="edit-btn" href="?iq_edit={rid}" target="_top">✏ Update</a>
            <a class="del-btn"  href="?iq_delete={rid}" target="_top">🗑 Delete</a>"""
        rows_html += f"""<tr>
            <td class="actions-cell">{actions}</td>
            {_cell(q.get('position'))}
            {_cell(q.get('question'))}
            {_cell(qtype)}
            {_cell(created)}
        </tr>"""

    st.html(f"""
    <style>
        .iq-tbl-wrap{{overflow-x:auto;width:100%}}
        .iq-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
        .iq-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
        .iq-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937}}
        .iq-tbl tr:hover td{{background:#f9fafb}}
        .actions-cell{{white-space:nowrap;display:flex;gap:4px;align-items:center;
            position:sticky;left:0;background:#fff;z-index:1}}
        .iq-tbl tr:hover .actions-cell{{background:#f9fafb}}
        .edit-btn,.del-btn{{
            border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block}}
        .edit-btn{{background:#d97706;color:white!important}}.edit-btn:hover{{background:#b45309}}
        .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
    </style>
    <div class="iq-tbl-wrap">
        <table class="iq-tbl">
            <thead><tr>
                <th>Actions</th><th>Position</th><th>Question</th><th>Type</th><th>Created</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
    """)

    col_prev, col_info, col_next = st.columns([1, 3, 1])
    if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True, key="iq_prev"):
        st.session_state[page_key] -= 1
        st.rerun()
    col_info.markdown(
        f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} question(s)</div>",
        unsafe_allow_html=True,
    )
    if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True, key="iq_next"):
        st.session_state[page_key] += 1
        st.rerun()


# ── URL-triggered actions (row links can't call Python directly) ────────────
_CONSUMED = "_iq_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_url_key = None
for _param, _kind in (("iq_edit", "edit"), ("iq_delete", "delete")):
    if st.query_params.get(_param):
        _url_key = (_kind, st.query_params[_param])
        break

_dialog: tuple | None = None
if _url_key and _url_key != st.session_state[_CONSUMED]:
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
    _dialog = _url_key
elif not _url_key:
    st.session_state[_CONSUMED] = None  # reset so the same row can be re-triggered after a new page load


# ── Main card: toolbar + list ────────────────────────────────────────────────
with st.container(key="card_interview_questions"):
    col_a, col_b, col_pos, col_search = st.columns([2.5, 2, 1.8, 3.6])
    if col_a.button("➕ Create interview question", use_container_width=True) and _dialog is None:
        _dialog = ("create", None)
    bulk_clicked = col_b.button("📥 Bulk import", use_container_width=True)

    position_options = [p["title"] for p in list_positions()]
    position_filter = col_pos.selectbox(
        "Position", ["All positions"] + position_options, label_visibility="collapsed",
    )
    if position_filter == "All positions":
        position_filter = ""

    search = col_search.text_input(
        "Search", placeholder="Search by position or question",
        label_visibility="collapsed", key="iq_search",
    )
    if st.session_state.get("_iq_prev_search") != (search, position_filter):
        st.session_state["iq_page"] = 0
        st.session_state["_iq_prev_search"] = (search, position_filter)

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _confirm_remove(arg)
        elif kind == "create": _create_dialog()
    elif bulk_clicked:
        _bulk_import_dialog()

    _render_questions(search, position_filter)
