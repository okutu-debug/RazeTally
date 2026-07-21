import datetime

import streamlit as st

from db import (
    ATTACHMENT_REQUIREMENT_OPTIONS,
    count_job_descriptions,
    count_job_descriptions_by_status,
    create_job_description,
    delete_job_description,
    get_job_description,
    list_job_descriptions,
    list_positions,
    set_job_description_published,
    update_job_description,
)
from theme import apply_theme, clear_query_params_url

JOB_DESC_PAGE_SIZE = 25

JOB_DESCRIPTION_TEMPLATE = """We are seeking qualified, reliable, and detail-oriented individuals for this role.

Key Responsibilities
-
-
-

Minimum Qualifications
- Minimum education:
- Minimum age:
- Must possess a valid National ID or Passport.
-

Required Skills
-
-
-

Disqualification Criteria
Applicants may be disqualified if:
- Required documents are missing.
- Educational qualifications do not meet the minimum requirement.
- Identity document is missing or invalid.
- Information provided is inconsistent across uploaded documents.
"""

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Job Descriptions</h4>",
    unsafe_allow_html=True,
)


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Job description", width="large")
def _view_dialog(id: str):
    jd = get_job_description(id)
    if not jd:
        st.error("Job description not found.")
        return

    st.markdown(f"### {jd.get('position') or ''}")
    st.caption(f"Status: {'Published' if jd['published'] else 'Draft'}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Vacancies**  \n{jd.get('num_applicants_required') or '—'}")
    with col2:
        deadline = jd.get("application_deadline")
        st.markdown(f"**Application deadline**  \n{deadline if deadline else '—'}")

    reqs = jd.get("attachment_requirements") or []
    st.markdown(f"**Attachment requirements**  \n{', '.join(reqs) if reqs else '—'}")

    st.markdown("**Description**")
    desc = jd.get("description") or ""
    # Force single newlines to render as line breaks (Markdown otherwise
    # collapses them), so plain multi-paragraph text displays as typed.
    st.markdown(desc.replace("\n", "  \n") if desc else "—")

    if st.button("Close", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _confirm_remove(id: str):
    st.write("Delete this job description? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_job_description(id)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Create job description", width="large")
def _create_dialog():
    position_options = [p["title"] for p in list_positions()]
    position = st.selectbox("Position *", [""] + position_options)

    col_desc_label, col_template = st.columns([4, 1.4])
    col_desc_label.markdown("**Description**")
    if col_template.button("📋 Use template", key="dlg_ca_use_template", use_container_width=True):
        st.session_state["dlg_ca_description"] = JOB_DESCRIPTION_TEMPLATE
    description = st.text_area(
        "Description", key="dlg_ca_description", height=350, label_visibility="collapsed",
    )

    col1, col2 = st.columns(2)
    num_required = col1.number_input("Number of applicants required *", min_value=1, step=1, value=1)
    deadline     = col2.date_input("Application deadline *", value=datetime.date.today())

    selected_reqs = st.multiselect(
        "Attachment requirements", ATTACHMENT_REQUIREMENT_OPTIONS,
        default=["CV", "Application Letter"],
    )
    other_reqs = st.text_input(
        "Other requirements (comma-separated)", placeholder="e.g. Portfolio, Work samples",
    )

    col3, col4 = st.columns(2)
    if col3.button("Create", type="primary", use_container_width=True):
        if not position:
            st.error("Position is required.")
        else:
            extra = [r.strip() for r in other_reqs.split(",") if r.strip()]
            try:
                create_job_description(
                    position=position, description=description,
                    num_applicants_required=int(num_required),
                    application_deadline=deadline,
                    attachment_requirements=selected_reqs + extra,
                )
                del st.session_state["dlg_ca_description"]
                st.success(f"Job description for '{position}' created as a draft.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to create job description: {e}")
    if col4.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Edit job description", width="large")
def _edit_dialog(id: str):
    jd = get_job_description(id)
    if not jd:
        st.error("Job description not found.")
        return

    position_options = [p["title"] for p in list_positions()]
    if jd["position"] and jd["position"] not in position_options:
        position_options = [jd["position"]] + position_options
    pos_index = position_options.index(jd["position"]) if jd["position"] in position_options else 0
    position = st.selectbox("Position *", position_options, index=pos_index)
    description = st.text_area("Description", value=jd.get("description") or "", height=350)

    col1, col2 = st.columns(2)
    num_required = col1.number_input(
        "Number of applicants required *", min_value=1, step=1,
        value=jd.get("num_applicants_required") or 1,
    )
    deadline = col2.date_input(
        "Application deadline *", value=jd.get("application_deadline") or datetime.date.today(),
    )

    current_reqs      = jd.get("attachment_requirements") or []
    standard_selected = [r for r in current_reqs if r in ATTACHMENT_REQUIREMENT_OPTIONS]
    custom_selected   = [r for r in current_reqs if r not in ATTACHMENT_REQUIREMENT_OPTIONS]
    selected_reqs = st.multiselect(
        "Attachment requirements", ATTACHMENT_REQUIREMENT_OPTIONS, default=standard_selected,
    )
    other_reqs = st.text_input("Other requirements (comma-separated)", value=", ".join(custom_selected))

    col3, col4 = st.columns(2)
    if col3.button("Save", type="primary", use_container_width=True):
        extra = [r.strip() for r in other_reqs.split(",") if r.strip()]
        update_job_description(
            id, position=position, description=description,
            num_applicants_required=int(num_required),
            application_deadline=deadline,
            attachment_requirements=selected_reqs + extra,
        )
        st.rerun()
    if col4.button("Cancel", use_container_width=True):
        st.rerun()


def _cell(val):
    text = str(val) if val not in (None, "") else "—"
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
    return f"<td>{safe}</td>"


def _render_status_tab(published: bool, search: str):
    status_key = "published" if published else "draft"
    page_key = f"jd_page_{status_key}"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    total = count_job_descriptions(search, published=published)
    total_pages = max(1, (total + JOB_DESC_PAGE_SIZE - 1) // JOB_DESC_PAGE_SIZE)
    st.session_state[page_key] = min(st.session_state[page_key], total_pages - 1)
    page = st.session_state[page_key]

    rows = list_job_descriptions(
        search, published=published, limit=JOB_DESC_PAGE_SIZE, offset=page * JOB_DESC_PAGE_SIZE,
    )

    if not rows:
        st.info(f"No {status_key} job descriptions.")
        return

    rows_html = ""
    for jd in rows:
        rid = str(jd["id"])
        created = str(jd.get("created_at") or "")[:16]
        reqs = ", ".join(jd.get("attachment_requirements") or [])
        deadline = jd.get("application_deadline") or ""
        pub_link = (
            f'<a class="pub-off-btn" href="?jd_unpublish={rid}" target="_top">🔒 Unpublish</a>'
            if published else
            f'<a class="pub-on-btn" href="?jd_publish={rid}" target="_top">📢 Publish</a>'
        )
        actions = f"""
            <a class="view-btn" href="?jd_view={rid}" target="_top">👁 Details</a>
            <a class="edit-btn" href="?jd_edit={rid}" target="_top">✏ Update</a>
            {pub_link}
            <a class="del-btn"  href="?jd_delete={rid}" target="_top">🗑 Delete</a>"""
        rows_html += f"""<tr>
            <td class="actions-cell">{actions}</td>
            {_cell(jd.get('position'))}
            {_cell(jd.get('num_applicants_required'))}
            {_cell(deadline)}
            {_cell(reqs)}
            {_cell(created)}
        </tr>"""

    st.html(f"""
    <style>
        .jd-tbl-wrap{{overflow-x:auto;width:100%}}
        .jd-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
        .jd-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
        .jd-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937}}
        .jd-tbl tr:hover td{{background:#f9fafb}}
        .actions-cell{{white-space:nowrap;display:flex;gap:4px;align-items:center;
            position:sticky;left:0;background:#fff;z-index:1}}
        .jd-tbl tr:hover .actions-cell{{background:#f9fafb}}
        .view-btn,.edit-btn,.del-btn,.pub-on-btn,.pub-off-btn{{
            border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block}}
        .view-btn{{background:#2563eb;color:white!important}}.view-btn:hover{{background:#1d4ed8}}
        .edit-btn{{background:#d97706;color:white!important}}.edit-btn:hover{{background:#b45309}}
        .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        .pub-on-btn{{background:#16a34a;color:white!important}}.pub-on-btn:hover{{background:#15803d}}
        .pub-off-btn{{background:#6b7280;color:white!important}}.pub-off-btn:hover{{background:#4b5563}}
    </style>
    <div class="jd-tbl-wrap">
        <table class="jd-tbl">
            <thead><tr>
                <th>Actions</th><th>Position</th><th>Vacancies</th>
                <th>Deadline</th><th>Requirements</th><th>Created</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
    """)

    col_prev, col_info, col_next = st.columns([1, 3, 1])
    if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True, key=f"jd_prev_{status_key}"):
        st.session_state[page_key] -= 1
        st.rerun()
    col_info.markdown(
        f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} job description(s)</div>",
        unsafe_allow_html=True,
    )
    if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True, key=f"jd_next_{status_key}"):
        st.session_state[page_key] += 1
        st.rerun()


# ── URL-triggered actions (row links can't call Python directly) ────────────
_CONSUMED = "_jd_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_url_key = None
for _param, _kind in (
    ("jd_view", "view"), ("jd_edit", "edit"), ("jd_delete", "delete"),
    ("jd_publish", "publish"), ("jd_unpublish", "unpublish"),
):
    if st.query_params.get(_param):
        _url_key = (_kind, st.query_params[_param])
        break

_dialog: tuple | None = None
if _url_key and _url_key != st.session_state[_CONSUMED]:
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
    _kind, _arg = _url_key
    if _kind == "publish":
        set_job_description_published(_arg, True)
        st.rerun()
    elif _kind == "unpublish":
        set_job_description_published(_arg, False)
        st.rerun()
    else:
        _dialog = _url_key
elif not _url_key:
    st.session_state[_CONSUMED] = None  # reset so the same row can be re-triggered after a new page load


# ── Main card: toolbar + status tabs ────────────────────────────────────────
with st.container(key="card_job_descriptions"):
    col_a, col_search = st.columns([2, 6])
    if col_a.button("➕ Create job description", use_container_width=True) and _dialog is None:
        _dialog = ("create", None)

    search = col_search.text_input(
        "Search", placeholder="Search by position or description",
        label_visibility="collapsed", key="jd_search",
    )
    if st.session_state.get("_jd_prev_search") != search:
        st.session_state["jd_page_published"] = 0
        st.session_state["jd_page_draft"] = 0
        st.session_state["_jd_prev_search"] = search

    if _dialog:
        kind, arg = _dialog
        if   kind == "view":   _view_dialog(arg)
        elif kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _confirm_remove(arg)
        elif kind == "create": _create_dialog()

    status_counts = count_job_descriptions_by_status(search)
    tab_pub, tab_draft = st.tabs([
        f"Published ({status_counts['published']})",
        f"Draft ({status_counts['draft']})",
    ])
    with tab_pub:
        _render_status_tab(True, search)
    with tab_draft:
        _render_status_tab(False, search)
