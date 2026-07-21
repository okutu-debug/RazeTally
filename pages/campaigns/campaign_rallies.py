"""Campaign Routes page: CRUD-managed campaign locations with list and map views."""

from urllib.parse import quote

import pandas as pd
import pydeck as pdk
import streamlit as st

from db import (
    CAMPAIGN_LOCATION_STATUSES,
    add_campaign_location,
    add_campaign_location_media,
    add_location_team_member,
    count_campaign_locations,
    count_campaign_locations_by_publish_state,
    delete_campaign_location,
    delete_campaign_location_media,
    find_ward_by_names,
    get_campaign_location,
    get_campaign_location_banner_bytes,
    get_campaign_location_media_bytes,
    list_all_wards,
    list_campaign_location_media,
    list_campaign_locations,
    list_location_team_members,
    list_users_by_team_type,
    remove_campaign_location_banner,
    remove_location_team_member,
    save_campaign_media_file,
    set_campaign_location_banner,
    set_campaign_location_published,
    set_campaign_location_status,
    update_campaign_location,
)
from location_picker import location_picker
from theme import apply_theme, clear_query_params_url

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Events / Rallies</h4>",
    unsafe_allow_html=True,
)

PAGE_SIZE = 25
_REQUIRED_COLS = {"name", "latitude", "longitude"}


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Add campaign location", width="large")
def _add_dialog():
    col1, col2 = st.columns(2)
    name = col1.text_input("Location name *")
    campaign = col2.text_input("Campaign Purpose")

    description = st.text_area("Description")
    address = st.text_input("Address")

    st.caption("County / Constituency / Ward")
    location = location_picker("add_campaign_location", None)

    col3, col4, col5 = st.columns(3)
    lat = col3.number_input(
        "Latitude", value=0.0, format="%.6f", min_value=-90.0, max_value=90.0,
    )
    lon = col4.number_input(
        "Longitude", value=0.0, format="%.6f", min_value=-180.0, max_value=180.0,
    )
    status = col5.selectbox("Status", CAMPAIGN_LOCATION_STATUSES)

    col_date1, col_date2 = st.columns(2)
    date_from = col_date1.date_input("Date From", value=None)
    date_to = col_date2.date_input("Date To", value=None)

    notes = st.text_area("Notes")

    banner = st.file_uploader("Banner photo (optional)", type=["png", "jpg", "jpeg", "webp"])

    if st.button("Add location", type="primary", use_container_width=True):
        if not name.strip():
            st.error("Location name is required.")
        elif lat == 0.0 and lon == 0.0:
            st.error("Please set a valid latitude/longitude.")
        elif date_from and date_to and date_to < date_from:
            st.error("Date To cannot be before Date From.")
        else:
            loc = location or {}
            new_id = add_campaign_location(
                name=name.strip(), campaign=campaign.strip(), description=description.strip(),
                address=address.strip(),
                county=loc.get("county") or "", county_code=loc.get("county_code") or "",
                constituency=loc.get("constituency") or "", constituency_code=loc.get("constituency_code") or "",
                ward=loc.get("ward") or "", ward_code=loc.get("ward_code") or "", ward_id=loc.get("ward_id"),
                latitude=lat, longitude=lon, status=status, notes=notes.strip(),
                date_from=date_from, date_to=date_to,
            )
            if banner is not None:
                set_campaign_location_banner(new_id, banner.name, banner.read())
            st.success(f"Location '{name}' added.")
            st.rerun()


@st.dialog("Edit campaign location", width="large")
def _edit_dialog(id: str):
    loc_row = get_campaign_location(id)
    if not loc_row:
        st.error("Location not found.")
        st.stop()

    col1, col2 = st.columns(2)
    name = col1.text_input("Location name *", value=loc_row["name"] or "")
    campaign = col2.text_input("Campaign", value=loc_row["campaign"] or "")

    description = st.text_area("Description", value=loc_row["description"] or "")
    address = st.text_input("Address", value=loc_row["address"] or "")

    current_ward_id = loc_row.get("ward_id") or find_ward_by_names(
        loc_row.get("county"), loc_row.get("constituency"), loc_row.get("ward"),
    )
    st.caption("County / Constituency / Ward")
    location = location_picker(f"edit_campaign_location_{id}", current_ward_id)
    if location is None:
        st.caption(
            f"Currently unlinked: {loc_row.get('county') or '—'} / "
            f"{loc_row.get('constituency') or '—'} / {loc_row.get('ward') or '—'}. "
            "Pick all three levels above to (re)link this location."
        )

    col3, col4, col5 = st.columns(3)
    lat = col3.number_input(
        "Latitude", value=float(loc_row["latitude"] or 0.0),
        format="%.6f", min_value=-90.0, max_value=90.0,
    )
    lon = col4.number_input(
        "Longitude", value=float(loc_row["longitude"] or 0.0),
        format="%.6f", min_value=-180.0, max_value=180.0,
    )
    status_index = (
        CAMPAIGN_LOCATION_STATUSES.index(loc_row["status"])
        if loc_row["status"] in CAMPAIGN_LOCATION_STATUSES else 0
    )
    status = col5.selectbox("Status", CAMPAIGN_LOCATION_STATUSES, index=status_index)

    col_date1, col_date2 = st.columns(2)
    date_from = col_date1.date_input("Date From", value=loc_row.get("date_from"))
    date_to = col_date2.date_input("Date To", value=loc_row.get("date_to"))

    notes = st.text_area("Notes", value=loc_row["notes"] or "")

    st.markdown("**Banner photo**")
    if loc_row.get("banner_image"):
        banner_result = get_campaign_location_banner_bytes(id)
        if banner_result:
            st.image(banner_result[0], width=320)
        if st.button("🗑 Remove banner", key=f"remove_banner_{id}"):
            remove_campaign_location_banner(id)
            st.rerun()
    else:
        st.caption("No banner photo set yet.")
    banner = st.file_uploader(
        "Upload/replace banner photo", type=["png", "jpg", "jpeg", "webp"], key=f"banner_upload_{id}",
    )

    col_save, col_cancel = st.columns(2)
    if col_save.button("Save", type="primary", use_container_width=True):
        if not name.strip():
            st.error("Location name is required.")
        elif date_from and date_to and date_to < date_from:
            st.error("Date To cannot be before Date From.")
        else:
            loc = location or {
                "county": loc_row.get("county"), "county_code": loc_row.get("county_code"),
                "constituency": loc_row.get("constituency"), "constituency_code": loc_row.get("constituency_code"),
                "ward": loc_row.get("ward"), "ward_code": loc_row.get("ward_code"),
                "ward_id": loc_row.get("ward_id"),
            }
            update_campaign_location(
                id,
                name=name.strip(), campaign=campaign.strip(), description=description.strip(),
                address=address.strip(),
                county=loc.get("county") or "", county_code=loc.get("county_code") or "",
                constituency=loc.get("constituency") or "", constituency_code=loc.get("constituency_code") or "",
                ward=loc.get("ward") or "", ward_code=loc.get("ward_code") or "", ward_id=loc.get("ward_id"),
                latitude=lat, longitude=lon, status=status, notes=notes.strip(),
                date_from=date_from, date_to=date_to,
            )
            if banner is not None:
                set_campaign_location_banner(id, banner.name, banner.read())
            st.rerun()
    if col_cancel.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(id: str):
    loc_row = get_campaign_location(id)
    name = loc_row["name"] if loc_row else id
    st.write(f"Delete location **{name}**? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_campaign_location(id)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Location team", width="large")
def _team_dialog(id: str):
    loc_row = get_campaign_location(id)
    if not loc_row:
        st.error("Location not found.")
        st.stop()
    st.markdown(f"#### {loc_row['name']}")

    st.markdown("##### Team members")
    members = list_location_team_members(id)
    campaign_roster = list_users_by_team_type("campaign")
    assigned_usernames = {m["username"] for m in members}
    addable = [u for u in campaign_roster if u["username"] not in assigned_usernames]

    if members:
        for m in members:
            name = f"{m.get('surname') or ''} {m.get('other_names') or ''}".strip() or m["username"]
            col1, col2 = st.columns([4, 1])
            col1.markdown(f"**{name}** ({m['username']})")
            if col2.button("Remove", key=f"rm_member_{id}_{m['username']}", use_container_width=True):
                remove_location_team_member(id, m["username"])
                st.rerun()
    else:
        st.caption("No team members assigned to this location yet.")

    if not campaign_roster:
        st.caption("No campaign team members exist yet — add some on the Campaign Team page.")
    elif addable:
        labels = {"": "— Select —", **{
            u["username"]: f"{u.get('surname') or ''} {u.get('other_names') or ''} ({u['username']})".strip()
            for u in addable
        }}
        col_pick, col_add = st.columns([3, 1])
        pick = col_pick.selectbox(
            "Add campaign team member", list(labels.keys()), format_func=lambda u: labels[u],
            key=f"pick_member_{id}", label_visibility="collapsed",
        )
        if col_add.button("Add member", use_container_width=True, key=f"add_member_{id}") and pick:
            add_location_team_member(id, pick)
            st.rerun()
    else:
        st.caption("Every campaign team member is already assigned to this location.")

    if st.button("Close", use_container_width=True):
        st.rerun()


@st.dialog("Rally media gallery", width="large")
def _media_dialog(id: str):
    loc_row = get_campaign_location(id)
    if not loc_row:
        st.error("Location not found.")
        st.stop()
    st.markdown(f"#### {loc_row['name']}")

    media = list_campaign_location_media(id)
    if media:
        cols = st.columns(3)
        for i, m in enumerate(media):
            result = get_campaign_location_media_bytes(m["id"])
            with cols[i % 3]:
                if result:
                    st.image(result[0], use_container_width=True)
                st.caption(m.get("original_filename") or "")
                if st.button("🗑 Remove", key=f"del_media_{id}_{m['id']}", use_container_width=True):
                    delete_campaign_location_media(m["id"])
                    st.rerun()
    else:
        st.caption("No media uploaded yet.")

    uploads = st.file_uploader(
        "Upload photos", type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True, key=f"media_upload_{id}",
    )
    if st.button("Upload", type="primary", use_container_width=True) and uploads:
        for f in uploads:
            stored = save_campaign_media_file(id, f.name, f.read())
            add_campaign_location_media(id, stored, f.name, st.session_state.username)
        st.success(f"Uploaded {len(uploads)} photo(s).")
        st.rerun()

    if st.button("Close", use_container_width=True):
        st.rerun()


@st.dialog("Bulk import campaign locations", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{
        "name": "Uhuru Park Rally Ground", "campaign": "2027 Presidential",
        "description": "Main rally venue", "address": "Uhuru Highway, Nairobi",
        "county": "NAIROBI", "county_code": "047",
        "constituency": "STAREHE", "constituency_code": "274",
        "ward": "NAIROBI CENTRAL", "ward_code": "1400",
        "latitude": -1.2864, "longitude": 36.8172,
        "status": "Planned", "notes": "",
        "date_from": "2026-08-01", "date_to": "2026-08-01",
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="campaign_locations_template.csv", mime="text/csv",
    )
    st.caption(
        "Required columns: `name`, `latitude`, `longitude`. "
        "Optional: `campaign`, `description`, `address`, `county`, `county_code`, "
        "`constituency`, `constituency_code`, `ward`, `ward_code`, `status`, `notes`, "
        "`date_from`, `date_to`."
    )

    if "campaign_locations_upload_key" not in st.session_state:
        st.session_state.campaign_locations_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"campaign_locations_bulk_{st.session_state.campaign_locations_upload_key}",
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

    if st.button("Import locations", type="primary", use_container_width=True):
        ward_lookup = {
            (w["county_name"], w["constituency_name"], w["ward_name"]): w["ward_id"]
            for w in list_all_wards()
        }

        def _parse_opt_date(v):
            v = str(v or "").strip()
            if not v:
                return None
            parsed = pd.to_datetime(v, errors="coerce")
            return parsed.date() if not pd.isna(parsed) else None

        imported, errors = 0, []
        for idx, row in df.iterrows():
            line = idx + 2
            name = str(row.get("name", "") or "").strip()
            try:
                lat = float(row.get("latitude"))
                lon = float(row.get("longitude"))
            except (TypeError, ValueError):
                errors.append(f"Row {line}: latitude/longitude must be numbers.")
                continue
            if not name:
                errors.append(f"Row {line}: name is required.")
                continue
            status = str(row.get("status", "Planned") or "Planned").strip()
            if status not in CAMPAIGN_LOCATION_STATUSES:
                status = "Planned"
            county = str(row.get("county", "") or "").strip()
            constituency = str(row.get("constituency", "") or "").strip()
            ward = str(row.get("ward", "") or "").strip()
            add_campaign_location(
                name=name, campaign=str(row.get("campaign", "") or "").strip(),
                description=str(row.get("description", "") or "").strip(),
                address=str(row.get("address", "") or "").strip(),
                county=county, county_code=str(row.get("county_code", "") or "").strip(),
                constituency=constituency, constituency_code=str(row.get("constituency_code", "") or "").strip(),
                ward=ward, ward_code=str(row.get("ward_code", "") or "").strip(),
                ward_id=ward_lookup.get((county, constituency, ward)),
                latitude=lat, longitude=lon, status=status,
                notes=str(row.get("notes", "") or "").strip(),
                date_from=_parse_opt_date(row.get("date_from")),
                date_to=_parse_opt_date(row.get("date_to")),
            )
            imported += 1

        if imported:
            st.success(f"Imported {imported} location(s).")
        if errors:
            st.error("\n\n".join(errors))
        if imported:
            st.session_state.campaign_locations_upload_key += 1
            st.rerun()


# ── URL-triggered actions (row links can't call Python directly) ────────────
_CONSUMED = "_campaign_locations_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_url_key = None
for _param, _kind in (
    ("edit_location", "edit"), ("delete_location", "delete"), ("team_location", "team"),
    ("media_location", "media"),
    ("publish_location", "publish"), ("unpublish_location", "unpublish"),
    ("complete_location", "complete"),
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
        set_campaign_location_published(_arg, True)
        st.rerun()
    elif _kind == "unpublish":
        set_campaign_location_published(_arg, False)
        st.rerun()
    elif _kind == "complete":
        set_campaign_location_status(_arg, "Completed")
        st.rerun()
    else:
        _dialog = _url_key
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Toolbar: add / bulk import / search ─────────────────────────────────────
with st.container(key="card_campaign_routes_toolbar"):
    col_a, col_b, col_search = st.columns([1.8, 1.8, 4.4])
    if col_a.button("➕ Add Location", use_container_width=True) and _dialog is None:
        _dialog = ("add", None)
    if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
        _dialog = ("bulk", None)

    def _reset_page():
        st.session_state["cl_page_published"] = 0
        st.session_state["cl_page_draft"] = 0

    search = col_search.text_input(
        "Search", placeholder="Search by name, campaign, address, county, constituency or ward",
        label_visibility="collapsed", key="campaign_locations_search", on_change=_reset_page,
    )

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "team":   _team_dialog(arg)
        elif kind == "media":  _media_dialog(arg)
        elif kind == "add":    _add_dialog()
        elif kind == "bulk":   _bulk_import_dialog()

# ── List / Map views ──────────────────────────────────────────────────────────
tab_list, tab_map = st.tabs(["📋 List View", "🗺️ Map View"])


def _safe(v):
    text = str(v) if v is not None else ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")


def _render_status_tab(published: bool, search: str):
    status_key = "published" if published else "draft"
    page_key = f"cl_page_{status_key}"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    total = count_campaign_locations(search, published=published)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state[page_key] = min(st.session_state[page_key], total_pages - 1)
    page = st.session_state[page_key]

    locations = list_campaign_locations(
        search, published=published, limit=PAGE_SIZE, offset=page * PAGE_SIZE,
    )

    if not locations:
        st.info(f"No {status_key} campaign locations found. Use **+ Add Location** or **Bulk import** to get started.")
        return

    rows_html = ""
    for loc in locations:
        enc = quote(str(loc["id"]), safe="")
        dates = f"{loc.get('date_from') or '—'} → {loc.get('date_to') or '—'}"
        pub_link = (
            f'<a class="pub-off-btn" href="?unpublish_location={enc}" target="_top" title="Unpublish">🔒</a>'
            if loc["published"] else
            f'<a class="pub-on-btn" href="?publish_location={enc}" target="_top" title="Publish">📢</a>'
        )
        complete_link = (
            f'<a class="complete-btn" href="?complete_location={enc}" target="_top" title="Complete">✅</a>'
            if loc["status"] != "Completed" else ""
        )
        media_link = (
            f'<a class="media-btn" href="?media_location={enc}" target="_top" title="Media">🖼</a>'
            if loc["status"] == "Completed" else ""
        )
        rows_html += f"""<tr>
            <td class="actions-cell">
                <a class="edit-btn" href="?edit_location={enc}" target="_top" title="Edit">✏</a>
                <a class="team-btn" href="?team_location={enc}" target="_top" title="Team">👥</a>
                {media_link}
                {complete_link}
                {pub_link}
                <a class="del-btn"  href="?delete_location={enc}" target="_top" title="Delete">🗑</a>
            </td>
            <td>{_safe(loc['name'])}</td>
            <td>{_safe(loc['campaign'])}</td>
            <td>{_safe(loc['county'])}</td>
            <td>{_safe(loc['constituency'])}</td>
            <td>{_safe(loc['ward'])}</td>
            <td>{_safe(loc['status'])}</td>
            <td>{_safe(dates)}</td>
        </tr>"""

    st.html(f"""
    <style>
        .cl-tbl-wrap{{overflow-x:auto;width:100%}}
        .cl-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
        .cl-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
        .cl-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;max-width:260px;overflow:hidden;text-overflow:ellipsis}}
        .cl-tbl tr:hover td{{background:#f9fafb}}
        .cl-tbl td.actions-cell{{white-space:nowrap;display:flex;gap:6px;align-items:center;max-width:none;overflow:visible}}
        .edit-btn,.team-btn,.del-btn,.pub-on-btn,.pub-off-btn,.complete-btn,.media-btn{{
            border-radius:5px;width:26px;height:26px;font-size:13px;line-height:1;text-decoration:none;
            display:inline-flex;align-items:center;justify-content:center;flex:0 0 auto}}
        .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
        .team-btn{{background:#7c3aed;color:white!important}}.team-btn:hover{{background:#6d28d9}}
        .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        .pub-on-btn{{background:#16a34a;color:white!important}}.pub-on-btn:hover{{background:#15803d}}
        .pub-off-btn{{background:#6b7280;color:white!important}}.pub-off-btn:hover{{background:#4b5563}}
        .complete-btn{{background:#0d9488;color:white!important}}.complete-btn:hover{{background:#0f766e}}
        .media-btn{{background:#ea580c;color:white!important}}.media-btn:hover{{background:#c2410c}}
    </style>
    <div class="cl-tbl-wrap">
        <table class="cl-tbl">
            <thead><tr>
                <th>Actions</th><th>Name</th><th>Campaign</th><th>County</th><th>Constituency</th>
                <th>Ward</th><th>Status</th><th>Dates</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
    </div>
    """)

    col_prev, col_info, col_next = st.columns([1, 3, 1])
    if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True, key=f"cl_prev_{status_key}"):
        st.session_state[page_key] -= 1
        st.rerun()
    col_info.markdown(
        f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} location(s)</div>",
        unsafe_allow_html=True,
    )
    if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True, key=f"cl_next_{status_key}"):
        st.session_state[page_key] += 1
        st.rerun()


with tab_list:
    with st.container(key="card_campaign_routes_list"):
        status_counts = count_campaign_locations_by_publish_state(search)
        tab_unpub, tab_pub = st.tabs([
            f"Unpublished ({status_counts['draft']})",
            f"Published ({status_counts['published']})",
        ])
        with tab_unpub:
            _render_status_tab(False, search)
        with tab_pub:
            _render_status_tab(True, search)

with tab_map:
    with st.container(key="card_campaign_routes_map"):
        all_matching = list_campaign_locations(search)
        valid = [l for l in all_matching if l["latitude"] is not None and l["longitude"] is not None]

        if not valid:
            st.info("No mapped locations yet. Add coordinates to a location to see it here.")
        else:
            PIN_SVG = (
                "<svg xmlns='http://www.w3.org/2000/svg' width='60' height='80' viewBox='0 0 60 80'>"
                "<path d='M30 0C13.4 0 0 13.4 0 30c0 22.5 30 50 30 50s30-27.5 30-50C60 13.4 46.6 0 30 0z' "
                "fill='#dc2626'/><circle cx='30' cy='30' r='11' fill='white'/></svg>"
            )
            PIN_ICON = {
                "url": f"data:image/svg+xml;utf8,{quote(PIN_SVG)}",
                "width": 60,
                "height": 80,
                "anchorY": 80,
                "mask": False,
            }

            df = pd.DataFrame(valid)[["latitude", "longitude", "name", "campaign", "status", "address"]]
            df["icon_data"] = [PIN_ICON] * len(df)

            pin_layer = pdk.Layer(
                "IconLayer",
                data=df,
                get_icon="icon_data",
                get_position=["longitude", "latitude"],
                get_size=4,
                size_scale=7,
                get_color=[255, 255, 255],
                pickable=True,
            )

            view_state = pdk.ViewState(
                latitude=df["latitude"].mean(),
                longitude=df["longitude"].mean(),
                zoom=11,
                pitch=0,
            )

            st.pydeck_chart(
                pdk.Deck(
                    layers=[pin_layer],
                    initial_view_state=view_state,
                    map_style="light",
                    tooltip={
                        "html": "<b>{name}</b><br/>{address}<br/>Campaign: {campaign}<br/>Status: {status}",
                        "style": {"backgroundColor": "white", "color": "#1f2937"},
                    },
                )
            )

            st.dataframe(
                df[["name", "campaign", "status", "address", "latitude", "longitude"]].rename(
                    columns={
                        "name": "Name", "campaign": "Campaign", "status": "Status",
                        "address": "Address", "latitude": "Latitude", "longitude": "Longitude",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
