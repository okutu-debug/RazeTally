import pandas as pd
import streamlit as st

from db import POSITION_TEAM_TYPES, add_position, delete_position, list_positions, update_position
from theme import apply_theme, clear_query_params_url

apply_theme()

ROLES = ["admin", "uploader", "viewer"]
TEAM_TYPE_LABELS = {"campaign": "Campaign", "election": "Election", "both": "Both"}

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Positions</h4>",
    unsafe_allow_html=True,
)

# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Edit position")
def _edit_dialog(title: str):
    positions = {p["title"]: p for p in list_positions()}
    pos = positions.get(title)
    if not pos:
        st.error("Position not found.")
        st.stop()
    new_title = st.text_input("Title", value=pos["title"])
    col_role, col_team = st.columns(2)
    role_idx  = ROLES.index(pos["role"]) if pos["role"] in ROLES else 1
    new_role  = col_role.selectbox("Default role", ROLES, index=role_idx)
    team_idx  = POSITION_TEAM_TYPES.index(pos["team_type"]) if pos["team_type"] in POSITION_TEAM_TYPES else 1
    new_team_type = col_team.selectbox(
        "Team", POSITION_TEAM_TYPES, index=team_idx, format_func=lambda t: TEAM_TYPE_LABELS[t],
    )
    col1, col2 = st.columns(2)
    if col1.button("Save", type="primary", use_container_width=True):
        if not new_title.strip():
            st.error("Title is required.")
        else:
            try:
                update_position(title, new_title.strip(), new_role, new_team_type)
                st.rerun()
            except Exception as e:
                st.error(f"Failed to update: {e}")
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(title: str):
    st.write(f"Delete position **{title}**? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_position(title)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Add position")
def _add_dialog():
    with st.form("dlg_add_position_form"):
        col1, col2, col3 = st.columns(3)
        new_title = col1.text_input("Title *")
        new_role  = col2.selectbox("Default role *", ROLES, index=1)
        new_team_type = col3.selectbox(
            "Team *", POSITION_TEAM_TYPES, index=1, format_func=lambda t: TEAM_TYPE_LABELS[t],
        )
        submitted = st.form_submit_button("Add position", type="primary", use_container_width=True)
    if submitted:
        if not new_title.strip():
            st.error("Title is required.")
        else:
            try:
                add_position(new_title.strip(), new_role, new_team_type)
                st.success(f"Position '{new_title}' added.")
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"'{new_title}' already exists.")
                else:
                    st.error(f"Failed: {e}")


@st.dialog("Bulk import positions", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([
        {"title": "Field Coordinator",   "role": "uploader", "team_type": "campaign"},
        {"title": "Senior Commissioner", "role": "admin",    "team_type": "election"},
    ])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="positions_template.csv", mime="text/csv",
    )
    st.caption(f"`team_type` must be one of: {', '.join(POSITION_TEAM_TYPES)}.")

    if "positions_upload_key" not in st.session_state:
        st.session_state.positions_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"positions_bulk_{st.session_state.positions_upload_key}",
    )

    if not uploaded:
        return

    try:
        df = pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    missing = {"title", "role"} - set(df.columns)
    if missing:
        st.error(f"Missing required columns: {', '.join(missing)}")
        return

    st.caption(f"{len(df)} row(s) — preview:")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("Import positions", type="primary", use_container_width=True):
        successes, errors = [], []
        for idx, row in df.iterrows():
            line  = idx + 2
            title = str(row.get("title", "") or "").strip()
            role  = str(row.get("role",  "") or "").strip().lower()
            team_type = str(row.get("team_type", "") or "").strip().lower() or "election"
            if not title:
                errors.append(f"Row {line}: title is required.")
                continue
            if role not in ROLES:
                errors.append(f"Row {line} ('{title}'): role must be one of {ROLES}.")
                continue
            if team_type not in POSITION_TEAM_TYPES:
                errors.append(f"Row {line} ('{title}'): team_type must be one of {POSITION_TEAM_TYPES}.")
                continue
            try:
                add_position(title, role, team_type)
                successes.append(title)
            except Exception as e:
                if "Duplicate entry" in str(e):
                    errors.append(f"Row {line}: '{title}' already exists.")
                else:
                    errors.append(f"Row {line} ('{title}'): {e}")
        if successes:
            st.success(f"Imported {len(successes)} position(s): {', '.join(successes)}.")
        if errors:
            st.error("\n\n".join(errors))
        if successes:
            st.session_state.positions_upload_key += 1
            st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_CONSUMED = "_positions_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_dialog: tuple | None = None
_url_key = None

if st.query_params.get("edit_pos"):
    _url_key = ("edit", st.query_params["edit_pos"])
elif st.query_params.get("delete_pos"):
    _url_key = ("delete", st.query_params["delete_pos"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Main card: toolbar + table ─────────────────────────────────────────────
with st.container(key="card_positions"):
    col_a, col_b, col_rest = st.columns([1.8, 1.8, 6])
    if col_a.button("➕ Add position", use_container_width=True) and _dialog is None:
        _dialog = ("add", None)
    if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
        _dialog = ("bulk", None)

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "add":    _add_dialog()
        elif kind == "bulk":   _bulk_import_dialog()

    # ── Positions HTML table ──────────────────────────────────────────────
    positions = list_positions()

    ROLE_BADGE = {
        "admin":    "<span style='background:#ede9fe;color:#6d28d9;padding:2px 8px;border-radius:4px;font-size:12px'>admin</span>",
        "uploader": "<span style='background:#dbeafe;color:#1d4ed8;padding:2px 8px;border-radius:4px;font-size:12px'>uploader</span>",
        "viewer":   "<span style='background:#f1f5f9;color:#475569;padding:2px 8px;border-radius:4px;font-size:12px'>viewer</span>",
    }
    TEAM_TYPE_BADGE = {
        "campaign": "<span style='background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:12px'>campaign</span>",
        "election": "<span style='background:#dcfce7;color:#166534;padding:2px 8px;border-radius:4px;font-size:12px'>election</span>",
        "both":     "<span style='background:#e0e7ff;color:#3730a3;padding:2px 8px;border-radius:4px;font-size:12px'>both</span>",
    }

    if not positions:
        st.info("No positions defined yet.")
    else:
        import urllib.parse
        rows_html = ""
        for p in positions:
            title_safe = p["title"].replace("&", "&amp;").replace("<", "&lt;").replace("'", "&#39;")
            badge      = ROLE_BADGE.get(p["role"], p["role"])
            team_badge = TEAM_TYPE_BADGE.get(p["team_type"], p["team_type"])
            enc        = urllib.parse.quote(p["title"])
            rows_html += f"""<tr>
                <td>{title_safe}</td>
                <td>{badge}</td>
                <td>{team_badge}</td>
                <td class="actions-cell">
                    <a class="edit-btn" href="?edit_pos={enc}" target="_top">✏ Edit</a>
                    <a class="del-btn"  href="?delete_pos={enc}" target="_top">🗑 Delete</a>
                </td>
            </tr>"""

        st.html(f"""
        <style>
            .pos-tbl-wrap{{overflow-x:auto;width:100%}}
            .pos-tbl{{border-collapse:collapse;width:100%;font-family:sans-serif;font-size:14px}}
            .pos-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
            .pos-tbl td{{padding:9px 14px;border-bottom:1px solid #e5e7eb;color:#1f2937}}
            .pos-tbl tr:hover td{{background:#f9fafb}}
            .actions-cell{{display:flex;gap:6px;align-items:center}}
            .edit-btn,.del-btn{{border-radius:5px;padding:3px 8px;font-size:11px;text-decoration:none;display:inline-block}}
            .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
            .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        </style>
        <div class="pos-tbl-wrap">
            <table class="pos-tbl">
                <thead><tr><th>Title</th><th>Role</th><th>Team</th><th>Actions</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)