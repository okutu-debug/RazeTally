import urllib.parse

import pandas as pd
import streamlit as st

from db import (
    bulk_upsert_party_members,
    count_party_members,
    create_party_member,
    delete_party_member,
    find_ward_by_names,
    get_party_member,
    list_party_members,
    update_party_member,
)
from location_picker import location_picker
from theme import apply_theme, clear_query_params_url

apply_theme()

PAGE_SIZE = 25
GENDER_OPTIONS = ["", "Male", "Female", "Other", "Prefer not to say"]
_REQUIRED_COLS = {"name", "id_number"}
_EXPORT_COLUMNS = [
    ("name", "Name"), ("id_number", "ID Number"), ("email", "Email"), ("phone_number", "Phone"),
    ("age", "Age"), ("gender", "Gender"), ("county", "County"),
    ("constituency", "Constituency"), ("ward", "Ward"),
]

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Party Members</h4>",
    unsafe_allow_html=True,
)


def _export_df(search: str) -> pd.DataFrame:
    """All members matching the current search (unpaginated), plus a blank
    Signature column for a printed sign-off sheet."""
    rows = list_party_members(search)
    data = [
        {label: (r.get(key) if r.get(key) is not None else "") for key, label in _EXPORT_COLUMNS}
        for r in rows
    ]
    df = pd.DataFrame(data, columns=[label for _, label in _EXPORT_COLUMNS])
    df["Signature"] = ""
    return df


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Add party member", width="large")
def _add_dialog():
    st.caption("County / Constituency / Ward")
    location = location_picker("create_party_member", None)

    with st.form("dlg_add_party_member_form"):
        name = st.text_input("Full name *")
        col1, col2 = st.columns(2)
        id_number = col1.text_input("ID number *")
        age       = col2.number_input("Age", min_value=0, max_value=120, step=1, value=0)
        col3, col4 = st.columns(2)
        email        = col3.text_input("Email")
        phone_number = col4.text_input("Phone number")
        gender    = st.selectbox("Gender", GENDER_OPTIONS)
        submitted = st.form_submit_button("Add member", type="primary", use_container_width=True)

    if submitted:
        if not name.strip() or not id_number.strip():
            st.error("Full name and ID number are required.")
        else:
            try:
                create_party_member(
                    name.strip(), id_number.strip(),
                    email=email.strip(), phone_number=phone_number.strip(),
                    age=int(age) or None, gender=gender,
                    county=(location or {}).get("county", ""),
                    constituency=(location or {}).get("constituency", ""),
                    ward=(location or {}).get("ward", ""),
                    ward_id=(location or {}).get("ward_id"),
                )
                st.success(f"Party member '{name}' added.")
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"ID number '{id_number}' is already registered.")
                else:
                    st.error(f"Failed to add member: {e}")


@st.dialog("Edit party member", width="large")
def _edit_dialog(id: str):
    member = get_party_member(id)
    if not member:
        st.error("Party member not found.")
        st.stop()

    name = st.text_input("Full name *", value=member.get("name") or "")
    col1, col2 = st.columns(2)
    id_number = col1.text_input("ID number *", value=member.get("id_number") or "")
    age       = col2.number_input(
        "Age", min_value=0, max_value=120, step=1, value=int(member.get("age") or 0),
    )
    col3, col4 = st.columns(2)
    email        = col3.text_input("Email", value=member.get("email") or "")
    phone_number = col4.text_input("Phone number", value=member.get("phone_number") or "")
    gender_idx = GENDER_OPTIONS.index(member.get("gender")) if member.get("gender") in GENDER_OPTIONS else 0
    gender     = st.selectbox("Gender", GENDER_OPTIONS, index=gender_idx)

    current_ward_id = member.get("ward_id") or find_ward_by_names(
        member.get("county"), member.get("constituency"), member.get("ward"),
    )
    st.caption("County / Constituency / Ward")
    location = location_picker(f"edit_party_member_{id}", current_ward_id)
    if location is None:
        st.caption(
            f"Currently unlinked: {member.get('county') or '—'} / "
            f"{member.get('constituency') or '—'} / {member.get('ward') or '—'}. "
            "Pick all three levels above to (re)link this member."
        )

    col_save, col_cancel = st.columns(2)
    if col_save.button("Save", type="primary", use_container_width=True):
        if not name.strip() or not id_number.strip():
            st.error("Full name and ID number are required.")
        else:
            loc = location or {
                "county": member.get("county"), "constituency": member.get("constituency"),
                "ward": member.get("ward"), "ward_id": member.get("ward_id"),
            }
            try:
                update_party_member(
                    id, name.strip(), id_number.strip(),
                    email=email.strip(), phone_number=phone_number.strip(),
                    age=int(age) or None, gender=gender,
                    county=loc["county"] or "", constituency=loc["constituency"] or "",
                    ward=loc["ward"] or "", ward_id=loc["ward_id"],
                )
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"ID number '{id_number}' is already registered.")
                else:
                    st.error(f"Failed to update: {e}")
    if col_cancel.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(id: str):
    member = get_party_member(id)
    name = member["name"] if member else id
    st.write(f"Remove party member **{name}**? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, remove", type="primary", use_container_width=True):
        delete_party_member(id)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Bulk import party members", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{
        "name": "Jane Doe", "id_number": "12345678", "email": "jane@example.com",
        "phone_number": "0712345678", "age": 34,
        "gender": "Female", "county": "", "constituency": "", "ward": "",
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="party_members_template.csv", mime="text/csv",
    )
    st.caption(
        "`name` and `id_number` are required — `email` and `phone_number` are optional. "
        "`county`/`constituency`/`ward` are matched against the demography reference tables "
        "where possible — unmatched location text is still kept, just without a linked ward. "
        "Re-uploading a CSV updates existing members matched by `id_number`."
    )

    if "party_members_upload_key" not in st.session_state:
        st.session_state.party_members_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"party_members_bulk_{st.session_state.party_members_upload_key}",
    )

    if not uploaded:
        return

    try:
        df = pd.read_csv(uploaded, dtype=str).fillna("")
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        st.error(f"Missing required columns: {', '.join(sorted(missing))}")
        return

    st.caption(f"{len(df)} row(s) — preview:")
    st.dataframe(df.head(200), use_container_width=True, hide_index=True)

    if st.button("Import party members", type="primary", use_container_width=True):
        rows, errors = [], []
        for idx, row in df.iterrows():
            line      = idx + 2
            name      = str(row.get("name", "") or "").strip()
            id_number = str(row.get("id_number", "") or "").strip()
            if not name or not id_number:
                errors.append(f"Row {line}: name and id_number are required.")
                continue

            raw_age = str(row.get("age", "") or "").strip()
            age = None
            if raw_age:
                try:
                    age = int(float(raw_age))
                except ValueError:
                    errors.append(f"Row {line} ({name}): age must be a number.")
                    continue

            county       = str(row.get("county", "") or "").strip()
            constituency = str(row.get("constituency", "") or "").strip()
            ward         = str(row.get("ward", "") or "").strip()
            ward_id      = find_ward_by_names(county, constituency, ward) if (county and constituency and ward) else None

            rows.append({
                "name": name, "id_number": id_number,
                "email": str(row.get("email", "") or "").strip() or None,
                "phone_number": str(row.get("phone_number", "") or "").strip() or None,
                "age": age,
                "gender": str(row.get("gender", "") or "").strip() or None,
                "county": county or None, "constituency": constituency or None,
                "ward": ward or None, "ward_id": ward_id,
            })

        if rows:
            try:
                inserted, updated = bulk_upsert_party_members(rows)
                st.success(f"Imported {inserted} new and updated {updated} existing member(s).")
            except Exception as e:
                st.error(f"Import failed: {e}")
        if errors:
            st.error("\n\n".join(errors))
        if rows:
            st.session_state.party_members_upload_key += 1
            st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_CONSUMED = "_pm_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_dialog: tuple | None = None
_url_key = None

if st.query_params.get("edit_pm"):
    _url_key = ("edit", st.query_params["edit_pm"])
elif st.query_params.get("delete_pm"):
    _url_key = ("delete", st.query_params["delete_pm"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Main card: toolbar + search + table ────────────────────────────────────────
with st.container(key="card_party_members"):
    if "pm_page" not in st.session_state:
        st.session_state.pm_page = 0

    def _reset_pm_page():
        st.session_state.pm_page = 0

    col_a, col_b, col_c, col_search = st.columns([1.6, 1.6, 1.6, 3.8])

    search = col_search.text_input(
        "Search", placeholder="Search by name, ID number, email, phone, county, constituency or ward",
        label_visibility="collapsed", key="pm_search", on_change=_reset_pm_page,
    )

    if col_a.button("➕ Add member", use_container_width=True) and _dialog is None:
        _dialog = ("add", None)
    if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
        _dialog = ("bulk", None)
    col_c.download_button(
        "📤 Export", _export_df(search).to_csv(index=False).encode(),
        file_name="party_members_export.csv", mime="text/csv", use_container_width=True,
        help="Exports every member matching the current search, with a blank Signature column.",
    )

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "add":    _add_dialog()
        elif kind == "bulk":   _bulk_import_dialog()

    total = count_party_members(search)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state.pm_page = min(st.session_state.pm_page, total_pages - 1)
    page = st.session_state.pm_page

    members = list_party_members(search, limit=PAGE_SIZE, offset=page * PAGE_SIZE)

    if not members:
        st.info("No party members found. Use **+ Add member** or **Bulk import** to get started.")
    else:
        def _safe(v):
            text = str(v) if v not in (None, "") else "—"
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")

        rows_html = ""
        for m in members:
            enc = urllib.parse.quote(str(m["id"]), safe="")
            created = str(m.get("created_at") or "")[:16]
            rows_html += f"""<tr>
                <td>{_safe(m['name'])}</td>
                <td>{_safe(m['id_number'])}</td>
                <td>{_safe(m.get('email'))}</td>
                <td>{_safe(m.get('phone_number'))}</td>
                <td>{_safe(m.get('age'))}</td>
                <td>{_safe(m.get('gender'))}</td>
                <td>{_safe(m.get('county'))}</td>
                <td>{_safe(m.get('constituency'))}</td>
                <td>{_safe(m.get('ward'))}</td>
                <td>{_safe(created)}</td>
                <td class="actions-cell">
                    <a class="edit-btn" href="?edit_pm={enc}" target="_top">✏ Edit</a>
                    <a class="del-btn"  href="?delete_pm={enc}" target="_top">🗑 Delete</a>
                </td>
            </tr>"""

        st.html(f"""
        <style>
            .pm-tbl-wrap{{overflow-x:auto;width:100%}}
            .pm-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
            .pm-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
            .pm-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;max-width:220px;overflow:hidden;text-overflow:ellipsis}}
            .pm-tbl tr:hover td{{background:#f9fafb}}
            .actions-cell{{white-space:nowrap;display:flex;gap:6px;align-items:center}}
            .edit-btn,.del-btn{{border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block}}
            .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
            .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        </style>
        <div class="pm-tbl-wrap">
            <table class="pm-tbl">
                <thead><tr>
                    <th>Name</th><th>ID number</th><th>Email</th><th>Phone</th><th>Age</th><th>Gender</th>
                    <th>County</th><th>Constituency</th><th>Ward</th><th>Created</th><th>Actions</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)

        col_prev, col_info, col_next = st.columns([1, 3, 1])
        if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True):
            st.session_state.pm_page -= 1
            st.rerun()
        col_info.markdown(
            f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} party member(s)</div>",
            unsafe_allow_html=True,
        )
        if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True):
            st.session_state.pm_page += 1
            st.rerun()
