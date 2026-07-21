"""Opinion Polls page: CRUD-managed polls with a per-candidate/party breakdown."""

from urllib.parse import quote

import pandas as pd
import streamlit as st

from db import (
    CANDIDATE_POSITIONS,
    OPINION_POLL_SOURCES,
    count_opinion_polls,
    count_opinion_polls_by_publish_state,
    create_opinion_poll,
    delete_opinion_poll,
    get_opinion_poll,
    list_opinion_poll_results,
    list_opinion_polls,
    list_parties,
    set_opinion_poll_published,
    update_opinion_poll,
)
from theme import apply_theme, clear_query_params_url

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Opinion Polls</h4>",
    unsafe_allow_html=True,
)
st.caption(
    "Track pollster-reported standings, or run our own poll and let visitors vote "
    "on the public site — both share the same candidate/party breakdown."
)

PAGE_SIZE = 25

OPINION_POLL_SOURCE_LABELS = {
    "pollster": "Pollster-reported (we enter the %)",
    "self_hosted": "Our own poll (public votes on the site)",
}

# Which dialog (if any) is open, e.g. ("edit", "12") — kept in session_state
# rather than a transient local variable, because the "Add row"/"Remove row"
# buttons inside the results editor call st.rerun() to redraw the dialog with
# the updated row list; on that rerun the toolbar's st.button(...) calls all
# return False again, so a local "was a button just clicked" variable would
# forget the dialog was open and it would vanish out from under the user.
if "op_dialog" not in st.session_state:
    st.session_state.op_dialog = None


# ── Results editor (reactive — add/remove rows need reruns, which st.form can't do) ──
def _results_editor(state_key: str, parties: list[dict], source: str):
    """For source='pollster' the admin types in each option's percentage. For
    source='self_hosted' percentage is computed from public votes, so that
    input is replaced with a read-only vote count instead — editing/adding
    options here never overwrites vote_count (see _replace_opinion_poll_results)."""
    party_name_by_id = {p["id"]: p["name"] for p in parties}
    party_choices = [None] + list(party_name_by_id.keys())
    rows = st.session_state[state_key]
    is_self_hosted = source == "self_hosted"

    for i, row in enumerate(rows):
        col_name, col_party, col_val, col_rm = st.columns([3, 2.5, 1.5, 0.6])
        row["candidate_name"] = col_name.text_input(
            "Candidate / label", value=row.get("candidate_name", ""),
            placeholder="Candidate name (or 'Undecided')",
            key=f"{state_key}_name_{i}", label_visibility="visible" if i == 0 else "collapsed",
        )
        party_idx = party_choices.index(row.get("party_id")) if row.get("party_id") in party_choices else 0
        row["party_id"] = col_party.selectbox(
            "Party", party_choices, index=party_idx,
            format_func=lambda p: party_name_by_id.get(p, "— none —"),
            key=f"{state_key}_party_{i}", label_visibility="visible" if i == 0 else "collapsed",
        )
        if is_self_hosted:
            col_val.text_input(
                "Votes", value=str(row.get("vote_count", 0)), disabled=True,
                key=f"{state_key}_votes_{i}", label_visibility="visible" if i == 0 else "collapsed",
            )
        else:
            row["percentage"] = col_val.number_input(
                "%", min_value=0.0, max_value=100.0, step=0.1, value=float(row.get("percentage") or 0),
                key=f"{state_key}_pct_{i}", label_visibility="visible" if i == 0 else "collapsed",
            )
        if col_rm.button("🗑", key=f"{state_key}_rm_{i}", use_container_width=True):
            rows.pop(i)
            st.rerun()

    if is_self_hosted:
        total_votes = sum(row.get("vote_count", 0) for row in rows)
        st.caption(f"{len(rows)} option(s) · {total_votes} public vote(s) cast so far")
    else:
        total = sum(r.get("percentage") or 0 for r in rows)
        st.caption(f"{len(rows)} row(s) · {total:.1f}% total")

    if st.button("➕ Add row", key=f"{state_key}_add"):
        rows.append({"candidate_name": "", "party_id": None, "percentage": 0.0})
        st.rerun()


def _clean_results(state_key: str) -> list[dict]:
    return [r for r in st.session_state[state_key] if r["candidate_name"].strip()]


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Add opinion poll", width="large")
def _create_dialog():
    if "op_create_results" not in st.session_state:
        st.session_state.op_create_results = [{"candidate_name": "", "party_id": None, "percentage": 0.0}]

    source = st.selectbox(
        "Poll type *", OPINION_POLL_SOURCES, format_func=lambda s: OPINION_POLL_SOURCE_LABELS[s],
    )
    is_self_hosted = source == "self_hosted"
    if is_self_hosted:
        st.caption(
            "Published, this poll shows a vote button on the public site instead of a chart — "
            "percentages are computed live from real votes, one per visitor (IP-limited)."
        )

    col1, col2 = st.columns(2)
    title = col1.text_input("Poll title *", placeholder="e.g. Presidential race — July 2026")
    position = col2.selectbox("Position", [""] + CANDIDATE_POSITIONS)

    col3, col4, col5 = st.columns(3)
    pollster = col3.text_input(
        "Pollster / organization", disabled=is_self_hosted,
        value="RazeTally" if is_self_hosted else "",
        help="Not applicable — votes come from site visitors." if is_self_hosted else None,
    )
    sample_size = col4.number_input(
        "Sample size", min_value=0, step=1, value=0, disabled=is_self_hosted,
        help="Not applicable — grows automatically with votes." if is_self_hosted else None,
    )
    margin_of_error = col5.number_input(
        "Margin of error (%)", min_value=0.0, step=0.1, value=0.0, disabled=is_self_hosted,
    )

    col6, col7 = st.columns(2)
    date_conducted = col6.date_input("Date conducted", value=None, disabled=is_self_hosted)
    source_url = col7.text_input("Source URL", disabled=is_self_hosted)

    methodology = st.text_area("Methodology", height=80)
    notes = st.text_area("Notes", height=80)

    st.markdown("##### Candidate / party breakdown")
    _results_editor("op_create_results", list_parties(), source)

    col_save, col_cancel = st.columns(2)
    if col_save.button("Create poll", type="primary", use_container_width=True):
        if not title.strip():
            st.error("Poll title is required.")
        else:
            try:
                create_opinion_poll(
                    title=title.strip(), position=position, source=source,
                    pollster="" if is_self_hosted else pollster.strip(),
                    sample_size=None if is_self_hosted else (int(sample_size) or None),
                    margin_of_error=margin_of_error or None,
                    date_conducted=None if is_self_hosted else date_conducted,
                    methodology=methodology.strip(),
                    source_url="" if is_self_hosted else source_url.strip(), notes=notes.strip(),
                    results=_clean_results("op_create_results"),
                )
                st.success(f"Poll '{title}' created.")
                del st.session_state.op_create_results
                st.session_state.op_dialog = None
                st.rerun()
            except Exception as e:
                st.error(f"Failed to create poll: {e}")
    if col_cancel.button("Cancel", use_container_width=True):
        del st.session_state.op_create_results
        st.session_state.op_dialog = None
        st.rerun()


@st.dialog("Edit opinion poll", width="large")
def _edit_dialog(id: str):
    poll = get_opinion_poll(id)
    if not poll:
        st.error("Opinion poll not found.")
        st.stop()

    state_key = f"op_edit_results_{id}"
    if state_key not in st.session_state:
        st.session_state[state_key] = [
            {"id": r["id"], "candidate_name": r["candidate_name"], "party_id": r["party_id"],
             "percentage": float(r["percentage"]), "vote_count": r.get("vote_count", 0)}
            for r in list_opinion_poll_results(id)
        ] or [{"candidate_name": "", "party_id": None, "percentage": 0.0}]

    source_options = list(OPINION_POLL_SOURCES)
    source_index = source_options.index(poll["source"]) if poll.get("source") in source_options else 0
    source = st.selectbox(
        "Poll type *", source_options, index=source_index,
        format_func=lambda s: OPINION_POLL_SOURCE_LABELS[s],
    )
    is_self_hosted = source == "self_hosted"
    if is_self_hosted:
        st.caption(
            "Published, this poll shows a vote button on the public site instead of a chart — "
            "percentages are computed live from real votes, one per visitor (IP-limited)."
        )

    col1, col2 = st.columns(2)
    title = col1.text_input("Poll title *", value=poll["title"] or "")
    position_options = [""] + CANDIDATE_POSITIONS
    position_index = position_options.index(poll["position"]) if poll.get("position") in position_options else 0
    position = col2.selectbox("Position", position_options, index=position_index)

    col3, col4, col5 = st.columns(3)
    pollster = col3.text_input(
        "Pollster / organization", value=poll.get("pollster") or "", disabled=is_self_hosted,
    )
    sample_size = col4.number_input(
        "Sample size", min_value=0, step=1, value=int(poll.get("sample_size") or 0), disabled=is_self_hosted,
    )
    margin_of_error = col5.number_input(
        "Margin of error (%)", min_value=0.0, step=0.1, value=float(poll.get("margin_of_error") or 0),
        disabled=is_self_hosted,
    )

    col6, col7 = st.columns(2)
    date_conducted = col6.date_input("Date conducted", value=poll.get("date_conducted"), disabled=is_self_hosted)
    source_url = col7.text_input("Source URL", value=poll.get("source_url") or "", disabled=is_self_hosted)

    methodology = st.text_area("Methodology", value=poll.get("methodology") or "", height=80)
    notes = st.text_area("Notes", value=poll.get("notes") or "", height=80)

    st.markdown("##### Candidate / party breakdown")
    _results_editor(state_key, list_parties(), source)

    col_save, col_cancel = st.columns(2)
    if col_save.button("Save", type="primary", use_container_width=True):
        if not title.strip():
            st.error("Poll title is required.")
        else:
            update_opinion_poll(
                id, title=title.strip(), position=position, source=source,
                pollster="" if is_self_hosted else pollster.strip(),
                sample_size=None if is_self_hosted else (int(sample_size) or None),
                margin_of_error=margin_of_error or None,
                date_conducted=None if is_self_hosted else date_conducted,
                methodology=methodology.strip(),
                source_url="" if is_self_hosted else source_url.strip(), notes=notes.strip(),
                results=_clean_results(state_key),
            )
            del st.session_state[state_key]
            st.session_state.op_dialog = None
            st.rerun()
    if col_cancel.button("Cancel", use_container_width=True):
        del st.session_state[state_key]
        st.session_state.op_dialog = None
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(id: str):
    poll = get_opinion_poll(id)
    title = poll["title"] if poll else id
    st.write(f"Delete poll **{title}**? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_opinion_poll(id)
        st.session_state.op_dialog = None
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.session_state.op_dialog = None
        st.rerun()


@st.dialog("Bulk import opinion polls (topline only — no per-candidate breakdown)", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{
        "title": "Presidential race — July 2026", "position": "President",
        "pollster": "Infotrak", "sample_size": 2400, "margin_of_error": 2.1,
        "date_conducted": "2026-07-01", "source_url": "", "notes": "",
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="opinion_polls_template.csv", mime="text/csv",
    )
    st.caption(
        "Required column: `title`. Optional: `position` (must match an office, e.g. 'President'), "
        "`pollster`, `sample_size`, `margin_of_error`, `date_conducted`, `source_url`, `notes`. "
        "Bulk-imported polls have no candidate breakdown — add one afterwards via Edit."
    )

    if "op_upload_key" not in st.session_state:
        st.session_state.op_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"], key=f"op_bulk_{st.session_state.op_upload_key}",
    )
    if not uploaded:
        if st.button("Close", use_container_width=True):
            st.session_state.op_dialog = None
            st.rerun()
        return

    try:
        df = pd.read_csv(uploaded, dtype=str).fillna("")
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    if "title" not in df.columns:
        st.error("Missing required column: title")
        return

    st.caption(f"{len(df)} row(s) — preview:")
    st.dataframe(df.head(200), use_container_width=True, hide_index=True)

    if st.button("Import polls", type="primary", use_container_width=True):
        def _parse_opt_date(v):
            v = str(v or "").strip()
            if not v:
                return None
            parsed = pd.to_datetime(v, errors="coerce")
            return parsed.date() if not pd.isna(parsed) else None

        def _parse_opt_float(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def _parse_opt_int(v):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return None

        imported, errors = 0, []
        for idx, row in df.iterrows():
            line = idx + 2
            title = str(row.get("title", "") or "").strip()
            if not title:
                errors.append(f"Row {line}: title is required.")
                continue
            position = str(row.get("position", "") or "").strip()
            if position and position not in CANDIDATE_POSITIONS:
                errors.append(f"Row {line}: unknown position '{position}', skipping that field.")
                position = ""
            create_opinion_poll(
                title=title, position=position,
                pollster=str(row.get("pollster", "") or "").strip(),
                sample_size=_parse_opt_int(row.get("sample_size")),
                margin_of_error=_parse_opt_float(row.get("margin_of_error")),
                date_conducted=_parse_opt_date(row.get("date_conducted")),
                source_url=str(row.get("source_url", "") or "").strip(),
                notes=str(row.get("notes", "") or "").strip(),
            )
            imported += 1

        if imported:
            st.success(f"Imported {imported} poll(s).")
        if errors:
            st.error("\n\n".join(errors))
        if imported:
            st.session_state.op_upload_key += 1
            st.rerun()


# ── URL-triggered actions (row links can't call Python directly) ────────────
_CONSUMED = "_opinion_polls_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_url_key = None
for _param, _kind in (
    ("edit_poll", "edit"), ("delete_poll", "delete"),
    ("publish_poll", "publish"), ("unpublish_poll", "unpublish"),
):
    if st.query_params.get(_param):
        _url_key = (_kind, st.query_params[_param])
        break

if _url_key and _url_key != st.session_state[_CONSUMED]:
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
    _kind, _arg = _url_key
    if _kind == "publish":
        set_opinion_poll_published(_arg, True)
        st.rerun()
    elif _kind == "unpublish":
        set_opinion_poll_published(_arg, False)
        st.rerun()
    else:
        st.session_state.op_dialog = _url_key
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Toolbar: add / bulk import / search / position filter ──────────────────
with st.container(key="card_opinion_polls_toolbar"):
    col_a, col_b, col_pos, col_search = st.columns([1.8, 1.8, 2, 3.4])
    if col_a.button("➕ Add Poll", use_container_width=True):
        st.session_state.op_dialog = ("create", None)
    if col_b.button("📥 Bulk import", use_container_width=True):
        st.session_state.op_dialog = ("bulk", None)

    def _reset_page():
        st.session_state["op_page_published"] = 0
        st.session_state["op_page_draft"] = 0

    position_filter = col_pos.selectbox(
        "Position", ["All positions"] + CANDIDATE_POSITIONS,
        label_visibility="collapsed", key="op_position_filter", on_change=_reset_page,
    )
    if position_filter == "All positions":
        position_filter = ""

    search = col_search.text_input(
        "Search", placeholder="Search by title or pollster",
        label_visibility="collapsed", key="op_search", on_change=_reset_page,
    )

    if st.session_state.op_dialog:
        kind, arg = st.session_state.op_dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "create": _create_dialog()
        elif kind == "bulk":   _bulk_import_dialog()


def _safe(v):
    text = str(v) if v is not None else ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")


def _render_status_tab(published: bool, search: str, position: str):
    status_key = "published" if published else "draft"
    page_key = f"op_page_{status_key}"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    total = count_opinion_polls(search, position or None, published=published)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state[page_key] = min(st.session_state[page_key], total_pages - 1)
    page = st.session_state[page_key]

    polls = list_opinion_polls(
        search, position or None, published=published, limit=PAGE_SIZE, offset=page * PAGE_SIZE,
    )

    if not polls:
        st.info(f"No {status_key} opinion polls found. Use **+ Add Poll** or **Bulk import** to get started.")
        return

    rows_html = ""
    for poll in polls:
        enc = quote(str(poll["id"]), safe="")
        pub_link = (
            f'<a class="pub-off-btn" href="?unpublish_poll={enc}" target="_top" title="Unpublish">🔒</a>'
            if poll["published"] else
            f'<a class="pub-on-btn" href="?publish_poll={enc}" target="_top" title="Publish">📢</a>'
        )
        is_self_hosted = poll.get("source") == "self_hosted"
        results = list_opinion_poll_results(poll["id"])
        leader = results[0] if results else None
        if leader and is_self_hosted:
            leader_text = f"{leader['candidate_name']} ({leader['percentage']}%, {leader.get('vote_count', 0)} votes)"
        elif leader:
            leader_text = f"{leader['candidate_name']} ({leader['percentage']}%)"
        else:
            leader_text = "—"
        type_text = "🗳 Public vote" if is_self_hosted else "📋 Pollster"
        pollster_or_votes = (
            f"{sum(r.get('vote_count', 0) for r in results)} votes" if is_self_hosted else poll["pollster"]
        )
        rows_html += f"""<tr>
            <td class="actions-cell">
                <a class="edit-btn" href="?edit_poll={enc}" target="_top" title="Edit">✏</a>
                {pub_link}
                <a class="del-btn"  href="?delete_poll={enc}" target="_top" title="Delete">🗑</a>
            </td>
            <td>{_safe(poll['title'])}</td>
            <td>{_safe(poll['position'])}</td>
            <td>{_safe(type_text)}</td>
            <td>{_safe(pollster_or_votes)}</td>
            <td>{_safe(poll.get('date_conducted') or '—')}</td>
            <td>{_safe(leader_text)}</td>
        </tr>"""

    st.html(f"""
    <style>
        .op-tbl-wrap{{overflow-x:auto;width:100%}}
        .op-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
        .op-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
        .op-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;max-width:260px;overflow:hidden;text-overflow:ellipsis}}
        .op-tbl tr:hover td{{background:#f9fafb}}
        .op-tbl td.actions-cell{{white-space:nowrap;display:flex;gap:6px;align-items:center;max-width:none;overflow:visible}}
        .edit-btn,.del-btn,.pub-on-btn,.pub-off-btn{{
            border-radius:5px;width:26px;height:26px;font-size:13px;line-height:1;text-decoration:none;
            display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto}}
        .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
        .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        .pub-on-btn{{background:#16a34a;color:white!important}}.pub-on-btn:hover{{background:#15803d}}
        .pub-off-btn{{background:#6b7280;color:white!important}}.pub-off-btn:hover{{background:#4b5563}}
    </style>
    <div class="op-tbl-wrap">
        <table class="op-tbl">
            <thead><tr>
                <th>Actions</th><th>Title</th><th>Position</th><th>Type</th><th>Pollster / Votes</th>
                <th>Date</th><th>Leading</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
    """)

    col_prev, col_info, col_next = st.columns([1, 3, 1])
    if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True, key=f"op_prev_{status_key}"):
        st.session_state[page_key] -= 1
        st.rerun()
    col_info.markdown(
        f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} poll(s)</div>",
        unsafe_allow_html=True,
    )
    if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True, key=f"op_next_{status_key}"):
        st.session_state[page_key] += 1
        st.rerun()


with st.container(key="card_opinion_polls_list"):
    status_counts = count_opinion_polls_by_publish_state(search)
    tab_unpub, tab_pub = st.tabs([
        f"Unpublished ({status_counts['draft']})",
        f"Published ({status_counts['published']})",
    ])
    with tab_unpub:
        _render_status_tab(False, search, position_filter)
    with tab_pub:
        _render_status_tab(True, search, position_filter)
