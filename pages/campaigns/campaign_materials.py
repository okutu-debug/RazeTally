"""Campaign Materials page: CRUD-managed material inventory, assignable to
named campaign teams (see the Teams tab on the Campaign Team page). Backed by
the shared `materials` table — a material can be scoped to campaign-only or
shared with election teams via its `material_type`."""

from urllib.parse import quote

import pandas as pd
import streamlit as st

from db import (
    add_material,
    assign_material_to_team,
    assigned_material_quantity,
    delete_material,
    get_material,
    list_campaign_teams,
    list_material_assignments,
    list_materials,
    remove_material_assignment,
    update_material,
)
from theme import apply_theme, clear_query_params_url

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Event / Rally Materials</h4>",
    unsafe_allow_html=True,
)

_REQUIRED_COLS = {"name", "qty"}
_TYPE_OPTIONS = ["campaign", "both"]
_TYPE_LABELS = {"campaign": "Campaign only", "both": "Campaign & Election"}


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Add material")
def _add_dialog():
    with st.form("dlg_material_add_form"):
        name = st.text_input("Material Name *")
        col1, col2 = st.columns(2)
        unit = col1.text_input("Unit", placeholder="e.g. pcs, boxes, reams")
        qty = col2.number_input("Qty", min_value=0, step=1, value=0)
        material_type = st.selectbox(
            "Visible to", _TYPE_OPTIONS, format_func=lambda t: _TYPE_LABELS[t],
        )
        description = st.text_area("Description")
        submitted = st.form_submit_button("Add material", type="primary", use_container_width=True)
    if submitted:
        if not name.strip():
            st.error("Material name is required.")
        else:
            add_material(name.strip(), unit.strip(), int(qty), description.strip(), material_type)
            st.success(f"Material '{name}' added.")
            st.rerun()


@st.dialog("Edit material")
def _edit_dialog(id: str):
    material = get_material(id)
    if not material:
        st.error("Material not found.")
        st.stop()

    name = st.text_input("Material Name *", value=material["name"])
    col1, col2 = st.columns(2)
    unit = col1.text_input("Unit", value=material["unit"] or "")
    assigned = assigned_material_quantity(id)
    qty = col2.number_input("Qty", min_value=0, step=1, value=int(material["quantity"] or 0))
    if assigned:
        st.caption(f"{assigned} {unit or 'unit(s)'} currently assigned to team(s).")
    type_index = _TYPE_OPTIONS.index(material["material_type"]) if material["material_type"] in _TYPE_OPTIONS else 0
    material_type = st.selectbox(
        "Visible to", _TYPE_OPTIONS, index=type_index, format_func=lambda t: _TYPE_LABELS[t],
    )
    description = st.text_area("Description", value=material["description"] or "")

    col_save, col_cancel = st.columns(2)
    if col_save.button("Save", type="primary", use_container_width=True):
        if not name.strip():
            st.error("Material name is required.")
        elif qty < assigned:
            st.error(f"Qty can't be less than the {assigned} already assigned to teams.")
        else:
            update_material(id, name.strip(), unit.strip(), int(qty), description.strip(), material_type)
            st.rerun()
    if col_cancel.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(id: str):
    material = get_material(id)
    name = material["name"] if material else id
    st.write(f"Delete material **{name}**? This also removes any team assignments. This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_material(id)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Assign material to a campaign team", width="large")
def _assign_dialog(id: str):
    material = get_material(id)
    if not material:
        st.error("Material not found.")
        st.stop()

    unit = material["unit"] or "unit(s)"
    assigned = assigned_material_quantity(id)
    available = int(material["quantity"] or 0) - assigned
    st.markdown(f"#### {material['name']}")
    st.caption(f"Total: {material['quantity']} {unit} · Assigned: {assigned} {unit} · Available: {available} {unit}")

    assignments = list_material_assignments(id)
    if assignments:
        st.markdown("##### Assigned to")
        for a in assignments:
            col1, col2 = st.columns([4, 1])
            col1.markdown(f"**{a['team_name']}** — {a['quantity']} {unit}")
            if col2.button("Remove", key=f"rm_assign_{id}_{a['team_id']}", use_container_width=True):
                remove_material_assignment(id, a["team_id"])
                st.rerun()
    else:
        st.caption("Not assigned to any campaign team yet.")

    teams = list_campaign_teams()
    if not teams:
        st.caption("No campaign teams exist yet — create one on the Campaign Team page's Teams tab.")
        if st.button("Close", use_container_width=True):
            st.rerun()
        return

    st.markdown("##### Assign / update")
    team_labels = {t["id"]: t["name"] for t in teams}
    col_team, col_qty, col_go = st.columns([3, 2, 1])
    team_id = col_team.selectbox("Campaign team", list(team_labels.keys()), format_func=lambda i: team_labels[i])
    qty = col_qty.number_input("Qty", min_value=0, step=1, value=0)
    if col_go.button("Assign", type="primary", use_container_width=True):
        if qty == 0:
            st.error("Enter a quantity greater than 0.")
        else:
            assign_material_to_team(id, team_id, int(qty))
            st.rerun()

    if st.button("Close", use_container_width=True):
        st.rerun()


@st.dialog("Bulk import materials", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{
        "name": "Campaign T-Shirts", "unit": "pcs", "qty": 500,
        "material_type": "campaign",
        "description": "Branded t-shirts for volunteers",
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="campaign_materials_template.csv", mime="text/csv",
    )
    st.caption(
        "Required columns: `name`, `qty`. Optional: `unit`, `description`, "
        "`material_type` (`campaign` or `both` — defaults to `campaign`)."
    )

    if "materials_upload_key" not in st.session_state:
        st.session_state.materials_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"materials_bulk_{st.session_state.materials_upload_key}",
    )

    if not uploaded:
        return

    try:
        df = pd.read_csv(uploaded)
    except Exception as e:
        st.error(f"Could not read file: {e}")
        return

    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        st.error(f"Missing required columns: {', '.join(sorted(missing))}")
        return

    st.caption(f"{len(df)} row(s) — preview:")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if st.button("Import materials", type="primary", use_container_width=True):
        imported, errors = 0, []
        for idx, row in df.iterrows():
            line = idx + 2
            name = str(row.get("name", "") or "").strip()
            if not name:
                errors.append(f"Row {line}: name is required.")
                continue
            try:
                qty = int(float(row.get("qty", 0) or 0))
            except (TypeError, ValueError):
                errors.append(f"Row {line} ('{name}'): qty must be a number.")
                continue
            material_type = str(row.get("material_type", "") or "").strip().lower() or "campaign"
            if material_type not in _TYPE_OPTIONS:
                material_type = "campaign"
            add_material(
                name, str(row.get("unit", "") or "").strip(), qty,
                str(row.get("description", "") or "").strip(), material_type,
            )
            imported += 1

        if imported:
            st.success(f"Imported {imported} material(s).")
        if errors:
            st.error("\n\n".join(errors))
        if imported:
            st.session_state.materials_upload_key += 1
            st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_CONSUMED = "_campaign_materials_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_dialog: tuple | None = None
_url_key = None

if st.query_params.get("edit_material"):
    _url_key = ("edit", st.query_params["edit_material"])
elif st.query_params.get("delete_material"):
    _url_key = ("delete", st.query_params["delete_material"])
elif st.query_params.get("assign_material"):
    _url_key = ("assign", st.query_params["assign_material"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Main card: toolbar + search + table ────────────────────────────────────────
with st.container(key="card_campaign_materials"):
    col_a, col_b, col_search = st.columns([1.8, 1.8, 4.4])
    if col_a.button("➕ Add Material", use_container_width=True) and _dialog is None:
        _dialog = ("add", None)
    if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
        _dialog = ("bulk", None)

    search = col_search.text_input(
        "Search", placeholder="Search by name or description",
        label_visibility="collapsed", key="materials_search",
    )

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "assign": _assign_dialog(arg)
        elif kind == "add":    _add_dialog()
        elif kind == "bulk":   _bulk_import_dialog()

    materials = list_materials(search, material_type="campaign")

    if not materials:
        st.info("No campaign materials found. Use **+ Add Material** or **Bulk import** to get started.")
    else:
        def _safe(v):
            text = str(v) if v is not None else ""
            return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")

        rows_html = ""
        for m in materials:
            enc = quote(str(m["id"]), safe="")
            assigned = assigned_material_quantity(m["id"])
            desc = (m.get("description") or "")[:120]
            type_label = _TYPE_LABELS.get(m.get("material_type"), m.get("material_type"))
            rows_html += f"""<tr>
                <td>{_safe(m['name'])}</td>
                <td>{_safe(m['unit'])}</td>
                <td>{m['quantity']}</td>
                <td>{assigned}</td>
                <td>{_safe(type_label)}</td>
                <td>{_safe(desc)}</td>
                <td class="actions-cell">
                    <a class="edit-btn"   href="?edit_material={enc}" target="_top">✏ Edit</a>
                    <a class="assign-btn" href="?assign_material={enc}" target="_top">📦 Assign</a>
                    <a class="del-btn"    href="?delete_material={enc}" target="_top">🗑 Delete</a>
                </td>
            </tr>"""

        st.html(f"""
        <style>
            .mat-tbl-wrap{{overflow-x:auto;width:100%}}
            .mat-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
            .mat-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
            .mat-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;max-width:260px;overflow:hidden;text-overflow:ellipsis}}
            .mat-tbl tr:hover td{{background:#f9fafb}}
            .actions-cell{{white-space:nowrap;display:flex;gap:6px;align-items:center}}
            .edit-btn,.assign-btn,.del-btn{{border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block}}
            .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
            .assign-btn{{background:#7c3aed;color:white!important}}.assign-btn:hover{{background:#6d28d9}}
            .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        </style>
        <div class="mat-tbl-wrap">
            <table class="mat-tbl">
                <thead><tr>
                    <th>Name</th><th>Unit</th><th>Qty</th><th>Assigned</th>
                    <th>Visible to</th><th>Description</th><th>Actions</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)
