import urllib.parse

import pandas as pd
import streamlit as st

from db import (
    add_polling_station,
    bulk_upsert_polling_stations,
    count_polling_stations,
    delete_polling_station,
    find_ward_by_names,
    get_polling_station,
    list_all_wards,
    list_polling_stations,
    update_polling_station,
)
from location_picker import location_picker
from theme import apply_theme, clear_query_params_url

apply_theme()

PAGE_SIZE = 25
_REQUIRED_COLS = {
    "county", "county_code", "constituency", "constituency_code",
    "ward", "ward_code", "polling_station_code", "polling_station_name",
    "registered_voters",
}

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Polling Stations</h4>",
    unsafe_allow_html=True,
)


# ── Dialogs ───────────────────────────────────────────────────────────────────
@st.dialog("Edit polling station", width="large")
def _edit_dialog(code: str):
    station = get_polling_station(code)
    if not station:
        st.error("Polling station not found.")
        st.stop()

    current_ward_id = station.get("ward_id") or find_ward_by_names(
        station["county"], station["constituency"], station["ward"],
    )
    st.caption("County / Constituency / Ward")
    location = location_picker(f"edit_station_{code}", current_ward_id)
    if location is None:
        st.caption(
            f"Currently unlinked: {station['county'] or '—'} / "
            f"{station['constituency'] or '—'} / {station['ward'] or '—'}. "
            "Pick all three levels above to (re)link this station."
        )

    col7, col8 = st.columns(2)
    new_code           = col7.text_input("Station code", value=station["polling_station_code"] or "")
    registered_voters  = col8.number_input("Registered voters", min_value=0, step=1,
                                            value=int(station["registered_voters"] or 0))
    station_name       = st.text_input("Station name", value=station["polling_station_name"] or "")

    col_save, col_cancel = st.columns(2)
    if col_save.button("Save", type="primary", use_container_width=True):
        if not new_code.strip() or not station_name.strip():
            st.error("Station code and name are required.")
        else:
            loc = location or {
                "county": station["county"], "county_code": station["county_code"],
                "constituency": station["constituency"], "constituency_code": station["constituency_code"],
                "ward": station["ward"], "ward_code": station["ward_code"],
                "ward_id": station.get("ward_id"),
            }
            try:
                update_polling_station(
                    code,
                    county=loc["county"] or "", county_code=loc["county_code"] or "",
                    constituency=loc["constituency"] or "", constituency_code=loc["constituency_code"] or "",
                    ward=loc["ward"] or "", ward_code=loc["ward_code"] or "",
                    ward_id=loc["ward_id"],
                    polling_station_code=new_code.strip(), polling_station_name=station_name.strip(),
                    registered_voters=int(registered_voters),
                )
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"Station code '{new_code}' is already in use.")
                else:
                    st.error(f"Failed to update: {e}")
    if col_cancel.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Confirm removal")
def _delete_dialog(code: str):
    station = get_polling_station(code)
    name = station["polling_station_name"] if station else code
    st.write(f"Delete polling station **{name}** ({code})? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_polling_station(code)
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Add polling station", width="large")
def _add_dialog():
    st.caption("County / Constituency / Ward")
    location = location_picker("add_station", None)

    col7, col8 = st.columns(2)
    station_code       = col7.text_input("Station code *")
    registered_voters  = col8.number_input("Registered voters", min_value=0, step=1, value=0)
    station_name       = st.text_input("Station name *")

    if st.button("Add polling station", type="primary", use_container_width=True):
        if not station_code.strip() or not station_name.strip():
            st.error("Station code and name are required.")
        elif location is None:
            st.error("Select a County, Constituency, and Ward.")
        else:
            try:
                add_polling_station(
                    county=location["county"], county_code=location["county_code"],
                    constituency=location["constituency"], constituency_code=location["constituency_code"],
                    ward=location["ward"], ward_code=location["ward_code"],
                    ward_id=location["ward_id"],
                    polling_station_code=station_code.strip(), polling_station_name=station_name.strip(),
                    registered_voters=int(registered_voters),
                )
                st.success(f"Polling station '{station_name}' added.")
                st.rerun()
            except Exception as e:
                if "Duplicate entry" in str(e):
                    st.error(f"Station code '{station_code}' already exists.")
                else:
                    st.error(f"Failed: {e}")


@st.dialog("Bulk import polling stations", width="large")
def _bulk_import_dialog():
    _template = pd.DataFrame([{
        "county": "MOMBASA", "county_code": "001",
        "constituency": "CHANGAMWE", "constituency_code": "001",
        "ward": "PORT REITZ", "ward_code": "0001",
        "polling_station_code": "001001000100101", "polling_station_name": "BOMU PRIMARY SCHOOL",
        "registered_voters": 673,
    }])
    st.download_button(
        "📥 Download template", _template.to_csv(index=False).encode(),
        file_name="polling_stations_template.csv", mime="text/csv",
    )

    if "stations_upload_key" not in st.session_state:
        st.session_state.stations_upload_key = 0

    uploaded = st.file_uploader(
        "Upload filled CSV", type=["csv"],
        key=f"stations_bulk_{st.session_state.stations_upload_key}",
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

    CHUNK_SIZE = 2000

    if st.button("Import polling stations", type="primary", use_container_width=True):
        total = len(df)
        progress = st.progress(0.0, text=f"Preparing {total:,} row(s)...")

        # Resolve ward links from an in-memory lookup instead of a DB round trip
        # per row — with tens of thousands of rows, per-row queries are the
        # difference between this finishing instantly and appearing to hang.
        ward_lookup = {
            (w["county_name"], w["constituency_name"], w["ward_name"]): w["ward_id"]
            for w in list_all_wards()
        }

        rows, errors = [], []
        for i, (idx, row) in enumerate(df.iterrows()):
            line = idx + 2
            code = str(row.get("polling_station_code", "") or "").strip()
            name = str(row.get("polling_station_name", "") or "").strip()
            if not code or not name:
                errors.append(f"Row {line}: station code and name are required.")
                continue
            try:
                voters = int(float(row.get("registered_voters", 0) or 0))
            except ValueError:
                errors.append(f"Row {line} ('{code}'): registered_voters must be a number.")
                continue
            county       = str(row.get("county", "") or "").strip()
            constituency = str(row.get("constituency", "") or "").strip()
            ward         = str(row.get("ward", "") or "").strip()
            rows.append({
                "county": county,
                "county_code": str(row.get("county_code", "") or "").strip(),
                "constituency": constituency,
                "constituency_code": str(row.get("constituency_code", "") or "").strip(),
                "ward": ward,
                "ward_code": str(row.get("ward_code", "") or "").strip(),
                "ward_id": ward_lookup.get((county, constituency, ward)),
                "polling_station_code": code,
                "polling_station_name": name,
                "registered_voters": voters,
            })
            if i % 500 == 0 or i == total - 1:
                progress.progress(
                    (i + 1) / total * 0.3,
                    text=f"Preparing row {i + 1:,} of {total:,}...",
                )

        inserted_total = skipped_total = 0
        if rows:
            n_chunks = (len(rows) + CHUNK_SIZE - 1) // CHUNK_SIZE
            for ci in range(n_chunks):
                chunk = rows[ci * CHUNK_SIZE:(ci + 1) * CHUNK_SIZE]
                try:
                    inserted, skipped = bulk_upsert_polling_stations(chunk, skip_existing=True)
                except Exception as e:
                    progress.empty()
                    st.error(f"Import failed on rows {ci * CHUNK_SIZE + 1}-{ci * CHUNK_SIZE + len(chunk)}: {e}")
                    break
                inserted_total += inserted
                skipped_total += skipped
                progress.progress(
                    0.3 + 0.7 * (ci + 1) / n_chunks,
                    text=f"Writing to database... {min((ci + 1) * CHUNK_SIZE, len(rows)):,} of {len(rows):,}",
                )

        progress.empty()
        if rows:
            st.success(
                f"Imported {inserted_total} new polling station(s); "
                f"skipped {skipped_total} already in the database."
            )
        if errors:
            shown = errors[:50]
            more = f"\n\n...and {len(errors) - 50} more." if len(errors) > 50 else ""
            st.error("\n\n".join(shown) + more)
        if rows:
            st.session_state.stations_upload_key += 1
            st.rerun()


# ── Single dialog dispatcher (only one dialog may open per run) ───────────────
_CONSUMED = "_stations_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None

_dialog: tuple | None = None
_url_key = None

if st.query_params.get("edit_station"):
    _url_key = ("edit", st.query_params["edit_station"])
elif st.query_params.get("delete_station"):
    _url_key = ("delete", st.query_params["delete_station"])

if _url_key and _url_key != st.session_state[_CONSUMED]:
    _dialog = _url_key
    st.session_state[_CONSUMED] = _url_key
    st.query_params.clear()
    clear_query_params_url()
elif not _url_key:
    st.session_state[_CONSUMED] = None

# ── Main card: toolbar + search + table ────────────────────────────────────────
with st.container(key="card_polling_stations"):
    col_a, col_b, col_search = st.columns([1.8, 1.8, 4.4])
    if col_a.button("➕ Add polling station", use_container_width=True) and _dialog is None:
        _dialog = ("add", None)
    if col_b.button("📥 Bulk import", use_container_width=True) and _dialog is None:
        _dialog = ("bulk", None)

    if "stations_page" not in st.session_state:
        st.session_state.stations_page = 0

    def _reset_page():
        st.session_state.stations_page = 0

    search = col_search.text_input(
        "Search", placeholder="Search by county, constituency, ward, station name or code",
        label_visibility="collapsed", key="stations_search", on_change=_reset_page,
    )

    if _dialog:
        kind, arg = _dialog
        if   kind == "edit":   _edit_dialog(arg)
        elif kind == "delete": _delete_dialog(arg)
        elif kind == "add":    _add_dialog()
        elif kind == "bulk":   _bulk_import_dialog()

    total = count_polling_stations(search)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    st.session_state.stations_page = min(st.session_state.stations_page, total_pages - 1)
    page = st.session_state.stations_page

    stations = list_polling_stations(search, limit=PAGE_SIZE, offset=page * PAGE_SIZE)

    if not stations:
        st.info("No polling stations found.")
    else:
        rows_html = ""
        for s in stations:
            def _safe(v):
                text = str(v) if v is not None else ""
                return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;")
            enc = urllib.parse.quote(s["polling_station_code"], safe="")
            rows_html += f"""<tr>
                <td>{_safe(s['county'])}</td>
                <td>{_safe(s['constituency'])}</td>
                <td>{_safe(s['ward'])}</td>
                <td>{_safe(s['polling_station_code'])}</td>
                <td>{_safe(s['polling_station_name'])}</td>
                <td>{_safe(s['registered_voters'])}</td>
                <td class="actions-cell">
                    <a class="edit-btn" href="?edit_station={enc}" target="_top">✏ Edit</a>
                    <a class="del-btn"  href="?delete_station={enc}" target="_top">🗑 Delete</a>
                </td>
            </tr>"""

        st.html(f"""
        <style>
            .stn-tbl-wrap{{overflow-x:auto;width:100%}}
            .stn-tbl{{border-collapse:collapse;width:max-content;min-width:100%;font-family:sans-serif;font-size:14px}}
            .stn-tbl th{{background:#f1f5f9;text-align:left;padding:10px 14px;white-space:nowrap;border-bottom:2px solid #cbd5e1;font-weight:600;color:#374151}}
            .stn-tbl td{{padding:9px 14px;white-space:nowrap;border-bottom:1px solid #e5e7eb;color:#1f2937;max-width:260px;overflow:hidden;text-overflow:ellipsis}}
            .stn-tbl tr:hover td{{background:#f9fafb}}
            .actions-cell{{white-space:nowrap;display:flex;gap:6px;align-items:center}}
            .edit-btn,.del-btn{{border-radius:5px;padding:3px 8px;font-size:11px;white-space:nowrap;text-decoration:none;display:inline-block}}
            .edit-btn{{background:#2563eb;color:white!important}}.edit-btn:hover{{background:#1d4ed8}}
            .del-btn{{background:#dc2626;color:white!important}}.del-btn:hover{{background:#b91c1c}}
        </style>
        <div class="stn-tbl-wrap">
            <table class="stn-tbl">
                <thead><tr>
                    <th>County</th><th>Constituency</th><th>Ward</th>
                    <th>Station code</th><th>Station name</th><th>Registered voters</th>
                    <th>Actions</th>
                </tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)

        col_prev, col_info, col_next = st.columns([1, 3, 1])
        if col_prev.button("⬅ Previous", disabled=page <= 0, use_container_width=True):
            st.session_state.stations_page -= 1
            st.rerun()
        col_info.markdown(
            f"<div style='text-align:center'>Page {page + 1} of {total_pages} · {total} station(s)</div>",
            unsafe_allow_html=True,
        )
        if col_next.button("Next ➡", disabled=page >= total_pages - 1, use_container_width=True):
            st.session_state.stations_page += 1
            st.rerun()
