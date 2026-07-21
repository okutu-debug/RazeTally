import calendar
import datetime
import html

import streamlit as st

from db import (
    add_event_member,
    create_event,
    delete_event,
    get_event,
    list_event_members,
    list_events_for_user,
    list_users,
    remove_event_member,
    update_event,
)
from theme import apply_theme, clear_query_params_url

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Events Calendar</h4>",
    unsafe_allow_html=True,
)

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

EVENT_TYPE_LABELS = {"general": "📢 General", "group": "👥 Group", "personal": "🔒 Personal"}
EVENT_TYPE_ICONS = {"general": "📢", "group": "👥", "personal": "🔒"}

REPEAT_DURATION_LABELS = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly", "custom": "Custom"}
REPEAT_UNIT_LABELS = {"day": "Day", "week": "Week", "month": "Month"}
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]  # index matches date.weekday()

WHOLE_DAY_START = datetime.time(8, 0)
WHOLE_DAY_END = datetime.time(17, 0)

today = datetime.date.today()

if "cal_year" not in st.session_state:
    st.session_state.cal_year = today.year
if "cal_month" not in st.session_state:
    st.session_state.cal_month = today.month

me = st.session_state.username
is_admin = st.session_state.get("role") == "admin"

all_users = [u for u in list_users() if u["username"] != me]
all_users_by_username = {u["username"]: u for u in list_users()}


def _display_name(u: dict) -> str:
    name = f"{u.get('other_names') or ''} {u.get('surname') or ''}".strip()
    return name or u["username"]


def _can_manage(ev: dict) -> bool:
    return is_admin or ev["created_by"] == me


def _can_view(ev: dict) -> bool:
    if ev["event_type"] == "general" or is_admin or ev["created_by"] == me:
        return True
    members = {m["username"] for m in list_event_members(ev["id"])}
    return me in members


def _format_date_range(start: datetime.date, end: datetime.date) -> str:
    if start == end:
        return start.strftime("%d %b %Y")
    return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"


def _format_time_range(whole_day: bool, start_time, end_time) -> str:
    if whole_day:
        return f"Whole day ({WHOLE_DAY_START.strftime('%I:%M %p')} – {WHOLE_DAY_END.strftime('%I:%M %p')})"
    if not start_time or not end_time:
        return "—"
    return f"{start_time.strftime('%I:%M %p')} – {end_time.strftime('%I:%M %p')}"


def _format_recurrence(ev: dict) -> str:
    freq = ev.get("recurrence_freq") or "none"
    if freq == "none":
        return "Does not repeat"
    until = ev.get("recurrence_until")
    until_str = f" until {until.strftime('%d %b %Y')}" if until else ""
    if freq in ("daily", "weekly", "monthly"):
        return f"Repeats {freq}{until_str}"

    interval = ev.get("recurrence_interval") or 1
    unit = ev.get("recurrence_unit") or "week"
    plural = "s" if interval != 1 else ""
    text = f"Repeats every {interval} {unit}{plural}"
    if unit == "week" and ev.get("recurrence_days_of_week"):
        dows = sorted(int(x) for x in ev["recurrence_days_of_week"].split(",") if x != "")
        text += " on " + ", ".join(WEEKDAY_LABELS[d] for d in dows)
    return text + until_str


def _cell(val):
    text = str(val) if val not in (None, "") else "—"
    safe = html.escape(text)
    return f"<td>{safe}</td>"


def _recurrence_fields(*, key_prefix: str, anchor_date: datetime.date, existing: dict | None = None):
    """Renders the Repeat toggle + duration/until/custom-interval/days-of-week
    widgets, returning (recurrence_freq, recurrence_interval, recurrence_unit,
    recurrence_days_of_week, recurrence_until) — all None/"none" when the
    toggle is off."""
    existing = existing or {}
    was_recurring = (existing.get("recurrence_freq") or "none") != "none"

    col_r1, col_r2, col_r3 = st.columns([1, 1.6, 1.6])
    recurs = col_r1.toggle("Repeat", value=was_recurring, key=f"{key_prefix}_recurs")

    recurrence_freq = "none"
    recurrence_interval = 1
    recurrence_unit = None
    recurrence_days_of_week = None
    recurrence_until = None

    if recurs:
        freq_keys = list(REPEAT_DURATION_LABELS.keys())
        default_freq = existing.get("recurrence_freq") if was_recurring else "daily"
        freq_index = freq_keys.index(default_freq) if default_freq in freq_keys else 0
        recurrence_freq = col_r2.selectbox(
            "Repeat Duration", options=freq_keys, index=freq_index,
            format_func=lambda k: REPEAT_DURATION_LABELS[k], key=f"{key_prefix}_freq",
        )
        default_until = existing.get("recurrence_until") or (anchor_date + datetime.timedelta(days=30))
        recurrence_until = col_r3.date_input(
            "Repeat Until *", value=default_until, min_value=anchor_date, key=f"{key_prefix}_until",
        )

        if recurrence_freq == "custom":
            col_c1, col_c2 = st.columns([1, 1])
            recurrence_interval = col_c1.number_input(
                "Repeat Every", min_value=1, max_value=52, step=1,
                value=int(existing.get("recurrence_interval") or 1), key=f"{key_prefix}_interval",
            )
            unit_keys = list(REPEAT_UNIT_LABELS.keys())
            default_unit = existing.get("recurrence_unit") or "week"
            unit_index = unit_keys.index(default_unit) if default_unit in unit_keys else 1
            recurrence_unit = col_c2.selectbox(
                "Unit", options=unit_keys, index=unit_index,
                format_func=lambda k: REPEAT_UNIT_LABELS[k], key=f"{key_prefix}_unit",
            )

            if recurrence_unit == "week":
                existing_dows_raw = existing.get("recurrence_days_of_week") or ""
                existing_dows = [int(x) for x in existing_dows_raw.split(",") if x != ""]
                default_dows = existing_dows or [anchor_date.weekday()]
                selected_dows = st.pills(
                    "Repeat On", options=list(range(7)), format_func=lambda d: WEEKDAY_LABELS[d],
                    selection_mode="multi", default=default_dows, key=f"{key_prefix}_dows",
                )
                recurrence_days_of_week = ",".join(str(d) for d in sorted(selected_dows)) if selected_dows else str(anchor_date.weekday())

    return recurrence_freq, int(recurrence_interval), recurrence_unit, recurrence_days_of_week, recurrence_until


def _time_fields(*, key_prefix: str, default_start=None, default_end=None, default_whole_day: bool = False):
    """Renders Whole Day + Start/End time inputs. When Whole Day is checked,
    the time inputs are locked (disabled) and forced to 8 AM – 5 PM."""
    col_t1, col_t2, col_t3 = st.columns([2, 2, 1.3])
    whole_day = col_t3.checkbox("Whole Day", value=default_whole_day, key=f"{key_prefix}_whole_day")
    start_time = col_t1.time_input(
        "Start Time *", value=WHOLE_DAY_START if whole_day else (default_start or WHOLE_DAY_START),
        disabled=whole_day, key=f"{key_prefix}_start_time",
    )
    end_time = col_t2.time_input(
        "End Time *", value=WHOLE_DAY_END if whole_day else (default_end or WHOLE_DAY_END),
        disabled=whole_day, key=f"{key_prefix}_end_time",
    )
    if whole_day:
        start_time, end_time = WHOLE_DAY_START, WHOLE_DAY_END
    return whole_day, start_time, end_time


# ── Dialogs ──────────────────────────────────────────────────────────────────

@st.dialog("New event")
def _create_event_dialog():
    event_type = st.selectbox(
        "Meeting/Event Type *", options=list(EVENT_TYPE_LABELS.keys()),
        format_func=lambda k: EVENT_TYPE_LABELS[k],
    )
    title = st.text_input("Title *")
    description = st.text_area("Description *", height=100)

    col1, col2 = st.columns(2)
    start_date = col1.date_input("Meeting/Event Date *", value=today)
    num_days = col2.number_input("Number of Days *", min_value=1, max_value=365, value=1, step=1)
    end_date = start_date + datetime.timedelta(days=int(num_days) - 1)

    whole_day, start_time, end_time = _time_fields(key_prefix="dlg_ca")

    recurrence_freq, recurrence_interval, recurrence_unit, recurrence_days_of_week, recurrence_until = (
        _recurrence_fields(key_prefix="dlg_ca", anchor_date=start_date)
    )

    member_usernames = []
    if event_type != "general":
        member_usernames = st.multiselect(
            "Add members",
            options=[u["username"] for u in all_users],
            format_func=lambda uname: _display_name(all_users_by_username[uname]),
        )

    col3, col4 = st.columns(2)
    if col3.button("Create", type="primary", use_container_width=True):
        if not title.strip():
            st.error("Title is required.")
        elif not description.strip():
            st.error("Description is required.")
        elif end_time <= start_time and not whole_day:
            st.error("End time must be after the start time.")
        elif recurrence_freq != "none" and recurrence_until < start_date:
            st.error("Repeat until date must be on or after the event date.")
        else:
            create_event(
                event_type, title.strip(), description.strip(), start_date, end_date, me, member_usernames,
                start_time=start_time, end_time=end_time, whole_day=whole_day,
                recurrence_freq=recurrence_freq, recurrence_interval=recurrence_interval,
                recurrence_unit=recurrence_unit, recurrence_days_of_week=recurrence_days_of_week,
                recurrence_until=recurrence_until,
            )
            st.success("Event created.")
            st.rerun()
    if col4.button("Cancel", use_container_width=True):
        st.rerun()


def _render_event_detail_page(event_id: int):
    """Full-page event details (not a modal) — shown instead of the
    calendar/list tabs whenever `st.session_state['ev_view_id']` is set."""
    ev = get_event(event_id)

    with st.container(key="card_event_detail"):
        if not ev or not _can_view(ev):
            st.error("Event not found, or you don't have access to it.")
            if st.button("← Back to Calendar", key="ev_detail_back_missing"):
                st.session_state["ev_view_id"] = None
                st.rerun()
            return

        can_manage = _can_manage(ev)

        col_back, col_edit, col_delete = st.columns([4, 1, 1])
        if col_back.button("← Back to Calendar", key="ev_detail_back"):
            st.session_state["ev_view_id"] = None
            st.rerun()
        if can_manage:
            if col_edit.button("✏ Edit", use_container_width=True, key="ev_detail_edit_btn"):
                _edit_event_dialog(event_id)
            if col_delete.button("🗑 Delete", use_container_width=True, key="ev_detail_delete_btn"):
                _confirm_delete_event(event_id)

        st.markdown(f"## {html.escape(ev.get('title') or '(untitled event)')}")
        st.caption(f"{EVENT_TYPE_LABELS.get(ev['event_type'], ev['event_type'])} · {_format_date_range(ev['start_date'], ev['end_date'])}")
        st.markdown(f"**Time:** {_format_time_range(bool(ev.get('whole_day')), ev.get('start_time'), ev.get('end_time'))}")
        st.markdown(f"**Repeats:** {_format_recurrence(ev)}")

        st.markdown("**Description**")
        desc = ev.get("description") or ""
        st.markdown(desc.replace("\n", "  \n") if desc else "—")

        creator = all_users_by_username.get(ev["created_by"])
        st.markdown(f"**Created by:** {_display_name(creator) if creator else ev['created_by']}")

    with st.container(key="card_event_members"):
        st.markdown(
            "<div style='font-weight:600; font-size:1.1rem; margin-bottom:0.5rem;'>Members</div>",
            unsafe_allow_html=True,
        )

        if ev["event_type"] == "general":
            st.info("🌐 This is a **General** event — it's visible to everyone, so there's no invite list.")
            return

        members = list_event_members(event_id)
        member_usernames = {m["username"] for m in members}

        if not members:
            st.caption("No members yet.")
        else:
            rows_html = ""
            for m in members:
                is_creator = m["username"] == ev["created_by"]
                name = html.escape(_display_name(m))
                if is_creator:
                    name += " <span style='color:#9ca3af;'>(creator)</span>"
                action = ""
                if can_manage and not is_creator:
                    action = (
                        f'<a class="mem-remove-btn" href="?ev_remove_member={event_id}:{m["username"]}" '
                        f'target="_top">🗑 Remove</a>'
                    )
                rows_html += f"""<tr>
                    <td>{name}</td>
                    <td>{html.escape(m.get('position') or '—')}</td>
                    <td>{html.escape(m.get('role') or '—')}</td>
                    <td class="actions-cell">{action}</td>
                </tr>"""

            st.html(f"""
            <style>
                .mem-tbl-wrap {{ overflow-x: auto; width: 100%; }}
                .mem-tbl {{ border-collapse: collapse; width: 100%; font-family: sans-serif; font-size: 14px; }}
                .mem-tbl th {{
                    background: #f1f5f9; text-align: left; padding: 10px 14px; white-space: nowrap;
                    border-bottom: 2px solid #cbd5e1; font-weight: 600; color: #374151;
                }}
                .mem-tbl td {{ padding: 9px 14px; border-bottom: 1px solid #e5e7eb; color: #1f2937; }}
                .mem-tbl tr:hover td {{ background: #f9fafb; }}
                .mem-remove-btn {{
                    border-radius: 5px; padding: 3px 8px; font-size: 11px; white-space: nowrap;
                    text-decoration: none; display: inline-block; background: #dc2626; color: white !important;
                }}
                .mem-remove-btn:hover {{ background: #b91c1c; }}
            </style>
            <div class="mem-tbl-wrap">
                <table class="mem-tbl">
                    <thead><tr><th>Name</th><th>Position</th><th>Role</th><th>Actions</th></tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
            """)

        if can_manage:
            candidates = [u for u in all_users if u["username"] not in member_usernames]
            if candidates:
                col_add1, col_add2 = st.columns([5, 1.4])
                add_username = col_add1.selectbox(
                    "Add a member", options=[u["username"] for u in candidates],
                    format_func=lambda uname: _display_name(all_users_by_username[uname]),
                    key="ev_detail_add_select", label_visibility="collapsed",
                )
                if col_add2.button("Add", key="ev_detail_add_btn", use_container_width=True):
                    add_event_member(event_id, add_username)
                    st.rerun()
            else:
                st.caption("Everyone is already a member.")


@st.dialog("Edit event")
def _edit_event_dialog(event_id: int):
    ev = get_event(event_id)
    if not ev:
        st.error("Event not found.")
        return
    if not _can_manage(ev):
        st.error("You don't have permission to edit this event.")
        return

    type_keys = list(EVENT_TYPE_LABELS.keys())
    event_type = st.selectbox(
        "Meeting/Event Type *", options=type_keys, index=type_keys.index(ev["event_type"]),
        format_func=lambda k: EVENT_TYPE_LABELS[k],
    )
    title = st.text_input("Title *", value=ev.get("title") or "")
    description = st.text_area("Description *", value=ev.get("description") or "", height=100)

    col1, col2 = st.columns(2)
    start_date = col1.date_input("Meeting/Event Date *", value=ev["start_date"])
    existing_num_days = (ev["end_date"] - ev["start_date"]).days + 1
    num_days = col2.number_input("Number of Days *", min_value=1, max_value=365, value=existing_num_days, step=1)
    end_date = start_date + datetime.timedelta(days=int(num_days) - 1)

    whole_day, start_time, end_time = _time_fields(
        key_prefix="dlg_ea", default_start=ev.get("start_time"), default_end=ev.get("end_time"),
        default_whole_day=bool(ev.get("whole_day")),
    )

    recurrence_freq, recurrence_interval, recurrence_unit, recurrence_days_of_week, recurrence_until = (
        _recurrence_fields(key_prefix="dlg_ea", anchor_date=start_date, existing=ev)
    )

    member_usernames = []
    if event_type != "general":
        existing_usernames = {m["username"] for m in list_event_members(event_id)}
        candidates = [u for u in all_users if u["username"] != ev["created_by"]]
        candidate_usernames = {u["username"] for u in candidates}
        member_usernames = st.multiselect(
            "Members",
            options=[u["username"] for u in candidates],
            default=[u for u in existing_usernames if u in candidate_usernames],
            format_func=lambda uname: _display_name(all_users_by_username[uname]),
        )

    col3, col4 = st.columns(2)
    if col3.button("Save", type="primary", use_container_width=True):
        if not title.strip():
            st.error("Title is required.")
        elif not description.strip():
            st.error("Description is required.")
        elif end_time <= start_time and not whole_day:
            st.error("End time must be after the start time.")
        elif recurrence_freq != "none" and recurrence_until < start_date:
            st.error("Repeat until date must be on or after the event date.")
        else:
            update_event(
                event_id, event_type, title.strip(), description.strip(), start_date, end_date, member_usernames,
                start_time=start_time, end_time=end_time, whole_day=whole_day,
                recurrence_freq=recurrence_freq, recurrence_interval=recurrence_interval,
                recurrence_unit=recurrence_unit, recurrence_days_of_week=recurrence_days_of_week,
                recurrence_until=recurrence_until,
            )
            st.rerun()
    if col4.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Delete event")
def _confirm_delete_event(event_id: int):
    ev = get_event(event_id)
    if not ev:
        st.error("Event not found.")
        return
    if not _can_manage(ev):
        st.error("You don't have permission to delete this event.")
        return
    if (ev.get("recurrence_freq") or "none") != "none":
        st.write("This is a repeating event. Deleting it removes the **entire series**, not just this occurrence.")
    else:
        st.write("Delete this event? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_event(event_id)
        st.session_state["ev_view_id"] = None
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


# ── URL-triggered actions (calendar badges / row links can't call Python directly) ──
_CONSUMED = "_ev_consumed_url"
if _CONSUMED not in st.session_state:
    st.session_state[_CONSUMED] = None
if "ev_view_id" not in st.session_state:
    st.session_state["ev_view_id"] = None

_url_key = None
for _param, _kind in (
    ("ev_view", "view"), ("ev_edit", "edit"), ("ev_delete", "delete"), ("ev_remove_member", "remove_member"),
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
    if _kind == "view":
        st.session_state["ev_view_id"] = int(_arg)
    elif _kind == "remove_member":
        # arg is "<event_id>:<username>" — encoded in the link itself so this
        # doesn't depend on ev_view_id having survived the page navigation.
        _ev_id_str, _username = _arg.split(":", 1)
        remove_event_member(int(_ev_id_str), _username)
        st.session_state["ev_view_id"] = int(_ev_id_str)
    else:
        _dialog = _url_key
elif not _url_key:
    st.session_state[_CONSUMED] = None  # reset so the same link can be re-triggered after a new page load


if st.session_state.get("ev_view_id"):
    # ── Full-page event details (replaces the toolbar + tabs entirely) ──────
    _render_event_detail_page(st.session_state["ev_view_id"])
    st.stop()

# ── Toolbar: new event + month navigation (shared by both views) ────────────
with st.container(key="card_toolbar"):
    col_new, col_prev, col_label, col_next, col_today = st.columns([1.6, 1, 4, 1, 1.4])

    if col_new.button("➕ New Event", use_container_width=True) and _dialog is None:
        _dialog = ("create", None)

    if col_prev.button("◀", use_container_width=True, key="cal_prev"):
        st.session_state.cal_month -= 1
        if st.session_state.cal_month < 1:
            st.session_state.cal_month = 12
            st.session_state.cal_year -= 1
        st.rerun()

    col_label.markdown(
        f"<div style='text-align:center; font-size:1.4rem; font-weight:600;'>"
        f"{MONTH_NAMES[st.session_state.cal_month - 1]} {st.session_state.cal_year}</div>",
        unsafe_allow_html=True,
    )

    if col_next.button("▶", use_container_width=True, key="cal_next"):
        st.session_state.cal_month += 1
        if st.session_state.cal_month > 12:
            st.session_state.cal_month = 1
            st.session_state.cal_year += 1
        st.rerun()

    if col_today.button("Today", use_container_width=True, key="cal_today"):
        st.session_state.cal_year = today.year
        st.session_state.cal_month = today.month
        st.rerun()

    if _dialog:
        kind, arg = _dialog
        if kind == "create":
            _create_event_dialog()
        elif kind == "edit":
            _edit_event_dialog(int(arg))
        elif kind == "delete":
            _confirm_delete_event(int(arg))

cal_year, cal_month = st.session_state.cal_year, st.session_state.cal_month
month_events = list_events_for_user(me, cal_year, cal_month)

tab_calendar, tab_list = st.tabs(["📅 Calendar View", "📋 List View"])

# ── Calendar view ─────────────────────────────────────────────────────────────
with tab_calendar:
    with st.container(key="card_calendar"):
        st.caption("🔒 Personal · 👥 Group · 📢 General — click an event to view details.")

        days_in_month = calendar.monthrange(cal_year, cal_month)[1]
        day_events: dict[int, list[dict]] = {}
        for day in range(1, days_in_month + 1):
            d = datetime.date(cal_year, cal_month, day)
            matches = [e for e in month_events if e["start_date"] <= d <= e["end_date"]]
            if matches:
                day_events[day] = matches

        cal = calendar.Calendar(firstweekday=0)  # Monday first
        weeks = cal.monthdayscalendar(cal_year, cal_month)
        weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        header_html = "".join(f"<th>{d}</th>" for d in weekday_labels)

        MAX_BADGES_PER_DAY = 3

        rows_html = ""
        for week in weeks:
            rows_html += "<tr>"
            for day in week:
                if day == 0:
                    rows_html += "<td class='empty'></td>"
                else:
                    is_today = (
                        day == today.day
                        and cal_month == today.month
                        and cal_year == today.year
                    )
                    cls = "day today" if is_today else "day"

                    badges_html = ""
                    events_today = day_events.get(day, [])
                    for e in events_today[:MAX_BADGES_PER_DAY]:
                        title_raw = e.get("title") or e.get("description") or ""
                        short_raw = title_raw if len(title_raw) <= 22 else title_raw[:21] + "…"
                        icon = EVENT_TYPE_ICONS.get(e["event_type"], "")
                        badges_html += (
                            f"<a class='ev-badge ev-{e['event_type']}' href='?ev_view={e['id']}' "
                            f"target='_top' title='{html.escape(title_raw)}'>"
                            f"{icon} {html.escape(short_raw)}</a>"
                        )
                    extra = len(events_today) - MAX_BADGES_PER_DAY
                    if extra > 0:
                        badges_html += f"<div class='ev-more'>+{extra} more</div>"

                    rows_html += (
                        f"<td class='{cls}'><span class='day-num'>{day}</span>{badges_html}</td>"
                    )
            rows_html += "</tr>"

        st.html(f"""
        <style>
            .cal-wrap {{ width: 100%; margin-top: 1rem; }}
            .cal-tbl {{ border-collapse: collapse; width: 100%; table-layout: fixed; font-family: sans-serif; }}
            .cal-tbl th {{
                background: #f1f5f9; text-align: center; padding: 10px 4px;
                font-weight: 600; color: #374151; border-bottom: 2px solid #cbd5e1;
            }}
            .cal-tbl td {{
                height: 90px; vertical-align: top; border: 1px solid #e5e7eb;
                padding: 6px; color: #1f2937; position: relative;
            }}
            .cal-tbl td.empty {{ background: #fafafa; }}
            .cal-tbl td.day:hover {{ background: #f9fafb; }}
            .day-num {{ font-size: 13px; font-weight: 500; }}
            .cal-tbl td.today {{ background: #eff6ff; }}
            .cal-tbl td.today .day-num {{
                background: #2563eb; color: white !important; border-radius: 50%;
                display: inline-flex; align-items: center; justify-content: center;
                width: 22px; height: 22px;
            }}
            .ev-badge {{
                display: block; font-size: 10px; padding: 1px 4px; border-radius: 4px;
                margin-top: 3px; text-decoration: none; white-space: nowrap;
                overflow: hidden; text-overflow: ellipsis; max-width: 100%;
            }}
            .ev-personal {{ background: #ede9fe; color: #6d28d9 !important; }}
            .ev-group    {{ background: #dbeafe; color: #1d4ed8 !important; }}
            .ev-general  {{ background: #dcfce7; color: #15803d !important; }}
            .ev-more {{ font-size: 9px; color: #9ca3af; margin-top: 2px; }}
        </style>
        <div class="cal-wrap">
            <table class="cal-tbl">
                <thead><tr>{header_html}</tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        """)

# ── List view ───────────────────────────────────────────────────────────────
with tab_list:
    with st.container(key="card_event_list"):
        st.markdown(
            f"<div style='font-weight:600; font-size:1.1rem; margin-bottom:0.5rem;'>"
            f"Events in {MONTH_NAMES[cal_month - 1]} {cal_year}</div>",
            unsafe_allow_html=True,
        )

        if not month_events:
            st.info("No events this month.")
        else:
            rows_html = ""
            for e in month_events:
                rid = e["id"]
                members = e.get("members") or []
                member_names = ", ".join(
                    _display_name(all_users_by_username[u]) for u in members if u in all_users_by_username
                )
                actions = f'<a class="view-btn" href="?ev_view={rid}" target="_top">👁 View</a>'
                if _can_manage(e):
                    actions += (
                        f'<a class="edit-btn" href="?ev_edit={rid}" target="_top">✏ Edit</a>'
                        f'<a class="del-btn" href="?ev_delete={rid}" target="_top">🗑 Delete</a>'
                    )
                time_range = _format_time_range(bool(e.get("whole_day")), e.get("start_time"), e.get("end_time"))
                repeats = "🔁 Repeats" if (e.get("recurrence_freq") or "none") != "none" else "—"
                rows_html += f"""<tr>
                    <td class="actions-cell">{actions}</td>
                    <td>{EVENT_TYPE_LABELS.get(e['event_type'], e['event_type'])}</td>
                    {_cell(e.get('title'))}
                    {_cell(_format_date_range(e['start_date'], e['end_date']))}
                    {_cell(time_range)}
                    {_cell(repeats)}
                    {_cell(member_names if e['event_type'] != 'general' else '—')}
                </tr>"""

            st.html(f"""
            <style>
                .ev-tbl-wrap {{ overflow-x: auto; width: 100%; }}
                .ev-tbl {{ border-collapse: collapse; width: max-content; min-width: 100%; font-family: sans-serif; font-size: 14px; }}
                .ev-tbl th {{ background: #f1f5f9; text-align: left; padding: 10px 14px; white-space: nowrap; border-bottom: 2px solid #cbd5e1; font-weight: 600; color: #374151; }}
                .ev-tbl td {{ padding: 9px 14px; white-space: nowrap; border-bottom: 1px solid #e5e7eb; color: #1f2937; }}
                .ev-tbl tr:hover td {{ background: #f9fafb; }}
                .actions-cell {{ white-space: nowrap; display: flex; gap: 4px; align-items: center; position: sticky; left: 0; background: #fff; z-index: 1; }}
                .ev-tbl tr:hover .actions-cell {{ background: #f9fafb; }}
                .view-btn, .edit-btn, .del-btn {{ border-radius: 5px; padding: 3px 8px; font-size: 11px; white-space: nowrap; text-decoration: none; display: inline-block; }}
                .view-btn {{ background: #2563eb; color: white !important; }} .view-btn:hover {{ background: #1d4ed8; }}
                .edit-btn {{ background: #d97706; color: white !important; }} .edit-btn:hover {{ background: #b45309; }}
                .del-btn {{ background: #dc2626; color: white !important; }} .del-btn:hover {{ background: #b91c1c; }}
            </style>
            <div class="ev-tbl-wrap">
                <table class="ev-tbl">
                    <thead><tr><th>Actions</th><th>Type</th><th>Title</th><th>Dates</th><th>Time</th><th>Repeats</th><th>Members</th></tr></thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
            """)
