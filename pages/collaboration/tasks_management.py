import datetime
import html
import re

import streamlit as st
from streamlit_sortables import sort_items

from db import (
    ACTIVITY_PRIORITIES,
    TASK_STATUSES,
    create_activity,
    create_task,
    delete_activity,
    delete_task,
    get_activity,
    get_task,
    list_activities_for_user,
    list_task_assignees,
    list_tasks_for_activity_and_user,
    list_users,
    update_activity,
    update_task,
    update_task_status,
)
from theme import apply_theme

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Activities & Tasks</h4>",
    unsafe_allow_html=True,
)

PRIORITY_LABELS = {
    "low": "🔵 Low",
    "medium": "🟡 Medium",
    "high": "🟠 High",
    "urgent": "🔴 Urgent",
}

today = datetime.date.today()

me = st.session_state.username
is_admin = st.session_state.get("role") == "admin"

all_users = list_users()
all_users_by_username = {u["username"]: u for u in all_users}


def _display_name(u: dict) -> str:
    name = f"{u.get('other_names') or ''} {u.get('surname') or ''}".strip()
    return name or u["username"]


def _format_date_range(start: datetime.date, end: datetime.date) -> str:
    if start == end:
        return start.strftime("%d %b %Y")
    return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"


def _assignee_names(usernames: list[str]) -> str:
    names = [_display_name(all_users_by_username[u]) for u in usernames if u in all_users_by_username]
    return ", ".join(names) if names else "—"


def _can_manage_activity(act: dict) -> bool:
    return is_admin or act["created_by"] == me


# ── Dialogs: Activities ──────────────────────────────────────────────────────

@st.dialog("New activity")
def _create_activity_dialog():
    title = st.text_input("Activity Title *")
    description = st.text_area("Description *", height=100)
    col1, col2 = st.columns(2)
    start_date = col1.date_input("Start Date *", value=today)
    end_date = col2.date_input("End Date *", value=today)
    priority = st.selectbox(
        "Priority *", options=ACTIVITY_PRIORITIES, index=1, format_func=lambda p: PRIORITY_LABELS[p],
    )

    col3, col4 = st.columns(2)
    if col3.button("Create", type="primary", use_container_width=True):
        if not title.strip():
            st.error("Title is required.")
        elif not description.strip():
            st.error("Description is required.")
        elif end_date < start_date:
            st.error("End date must be on or after the start date.")
        else:
            create_activity(title.strip(), description.strip(), start_date, end_date, priority, me)
            st.success("Activity created.")
            st.rerun()
    if col4.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Edit activity")
def _edit_activity_dialog(activity_id: int):
    act = get_activity(activity_id)
    if not act:
        st.error("Activity not found.")
        return
    if not _can_manage_activity(act):
        st.error("You don't have permission to edit this activity.")
        return

    title = st.text_input("Activity Title *", value=act.get("title") or "")
    description = st.text_area("Description *", value=act.get("description") or "", height=100)
    col1, col2 = st.columns(2)
    start_date = col1.date_input("Start Date *", value=act["start_date"])
    end_date = col2.date_input("End Date *", value=act["end_date"])
    priority = st.selectbox(
        "Priority *", options=ACTIVITY_PRIORITIES, index=ACTIVITY_PRIORITIES.index(act["priority"]),
        format_func=lambda p: PRIORITY_LABELS[p],
    )

    col3, col4 = st.columns(2)
    if col3.button("Save", type="primary", use_container_width=True):
        if not title.strip():
            st.error("Title is required.")
        elif not description.strip():
            st.error("Description is required.")
        elif end_date < start_date:
            st.error("End date must be on or after the start date.")
        else:
            update_activity(activity_id, title.strip(), description.strip(), start_date, end_date, priority)
            st.rerun()
    if col4.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Delete activity")
def _confirm_delete_activity(activity_id: int):
    act = get_activity(activity_id)
    if not act:
        st.error("Activity not found.")
        return
    if not _can_manage_activity(act):
        st.error("You don't have permission to delete this activity.")
        return
    st.write("Delete this activity? This also deletes **all of its tasks**. This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_activity(activity_id)
        if st.session_state.get("act_view_id") == activity_id:
            st.session_state["act_view_id"] = None
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


# ── Dialogs: Tasks ────────────────────────────────────────────────────────────

@st.dialog("New task")
def _create_task_dialog(activity_id: int):
    title = st.text_input("Task Title *")
    description = st.text_area("Description *", height=100)
    col1, col2 = st.columns(2)
    start_date = col1.date_input("Start Date *", value=today)
    end_date = col2.date_input("End Date *", value=today)
    priority = st.selectbox(
        "Priority *", options=ACTIVITY_PRIORITIES, index=1, format_func=lambda p: PRIORITY_LABELS[p],
    )
    assignee_usernames = st.multiselect(
        "Assign to",
        options=[u["username"] for u in all_users],
        format_func=lambda uname: _display_name(all_users_by_username[uname]),
    )

    col3, col4 = st.columns(2)
    if col3.button("Create", type="primary", use_container_width=True):
        if not title.strip():
            st.error("Title is required.")
        elif not description.strip():
            st.error("Description is required.")
        elif end_date < start_date:
            st.error("End date must be on or after the start date.")
        else:
            create_task(
                activity_id, title.strip(), description.strip(), start_date, end_date, priority,
                me, assignee_usernames,
            )
            st.success("Task created.")
            st.rerun()
    if col4.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Edit task")
def _edit_task_dialog(task_id: int):
    t = get_task(task_id)
    if not t:
        st.error("Task not found.")
        return

    title = st.text_input("Task Title *", value=t.get("title") or "")
    description = st.text_area("Description *", value=t.get("description") or "", height=100)
    col1, col2 = st.columns(2)
    start_date = col1.date_input("Start Date *", value=t["start_date"])
    end_date = col2.date_input("End Date *", value=t["end_date"])
    priority = st.selectbox(
        "Priority *", options=ACTIVITY_PRIORITIES, index=ACTIVITY_PRIORITIES.index(t["priority"]),
        format_func=lambda p: PRIORITY_LABELS[p],
    )
    existing_usernames = {a["username"] for a in list_task_assignees(task_id)}
    all_usernames = {u["username"] for u in all_users}
    assignee_usernames = st.multiselect(
        "Assign to",
        options=[u["username"] for u in all_users],
        default=[u for u in existing_usernames if u in all_usernames],
        format_func=lambda uname: _display_name(all_users_by_username[uname]),
    )

    col3, col4 = st.columns(2)
    if col3.button("Save", type="primary", use_container_width=True):
        if not title.strip():
            st.error("Title is required.")
        elif not description.strip():
            st.error("Description is required.")
        elif end_date < start_date:
            st.error("End date must be on or after the start date.")
        else:
            update_task(task_id, title.strip(), description.strip(), start_date, end_date, priority, assignee_usernames)
            st.rerun()
    if col4.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Delete task")
def _confirm_delete_task(task_id: int):
    t = get_task(task_id)
    if not t:
        st.error("Task not found.")
        return
    st.write("Delete this task? This cannot be undone.")
    col1, col2 = st.columns(2)
    if col1.button("Yes, delete", type="primary", use_container_width=True):
        delete_task(task_id)
        if st.session_state.get("task_view_id") == task_id:
            st.session_state["task_view_id"] = None
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


# ── Task detail page ────────────────────────────────────────────────────────

def _render_task_detail(task: dict, can_manage_tasks: bool):
    """Full task details (not a modal) — shown instead of the Kanban/List
    tabs whenever `st.session_state['task_view_id']` is set."""
    with st.container(key="card_task_detail"):
        col_back, col_edit, col_delete = st.columns([4, 1, 1])
        if col_back.button("← Back to Tasks", key="task_detail_back"):
            st.session_state["task_view_id"] = None
            st.rerun()
        if can_manage_tasks:
            if col_edit.button("✏ Edit", use_container_width=True, key="task_detail_edit_btn"):
                _edit_task_dialog(task["id"])
            if col_delete.button("🗑 Delete", use_container_width=True, key="task_detail_delete_btn"):
                _confirm_delete_task(task["id"])

        st.markdown(f"## {html.escape(task.get('title') or '(untitled task)')}")
        st.caption(
            f"{task['status']} · {PRIORITY_LABELS.get(task['priority'], task['priority'])} · "
            f"{_format_date_range(task['start_date'], task['end_date'])}"
        )
        st.markdown("**Description**")
        desc = task.get("description") or ""
        st.markdown(desc.replace("\n", "  \n") if desc else "—")

        creator = all_users_by_username.get(task["created_by"])
        st.markdown(f"**Created by:** {_display_name(creator) if creator else task['created_by']}")

    with st.container(key="card_task_detail_assignees"):
        st.markdown(
            "<div style='font-weight:600; font-size:1.1rem; margin-bottom:0.5rem;'>Assignees</div>",
            unsafe_allow_html=True,
        )
        assignees = list_task_assignees(task["id"])
        if not assignees:
            st.caption("No one assigned yet.")
        else:
            for a in assignees:
                st.write(f"👤 {_display_name(a)}" + (f" · {a['position']}" if a.get("position") else ""))


# ── Kanban board ────────────────────────────────────────────────────────────

@st.fragment
def _render_kanban_board(activity_id: int, visible_tasks: list[dict]):
    """Drag-and-drop status board. Runs as its own fragment so dropping a
    card only reruns this board (fast, no full-page rerun) instead of the
    whole page."""
    if not visible_tasks:
        st.caption("No tasks yet.")
        return

    st.caption("Drag a task card into another column to change its status. Use the List tab to view or edit a task.")
    tasks_by_id = {t["id"]: t for t in visible_tasks}
    containers = []
    for status in TASK_STATUSES:
        items = []
        for t in visible_tasks:
            if t["status"] != status:
                continue
            priority = PRIORITY_LABELS.get(t["priority"], t["priority"])
            assignees = _assignee_names(t.get("assignees", []))
            items.append(f"#{t['id']}  {t['title']}  ·  {priority}  ·  {assignees}")
        containers.append({"header": f"{status} ({len(items)})", "items": items})

    # The component keeps its own internal state once dragged and won't
    # re-sync its displayed header/grouping just because we send back new
    # props under the same key — so we force a remount (fresh key) every
    # time a drop actually changes a task's status, to guarantee the board
    # (including the per-column tallies) reflects the real DB state.
    version_key = f"kanban_version_{activity_id}"
    if version_key not in st.session_state:
        st.session_state[version_key] = 0

    # NOTE: the component's own `direction` naming is inverted from what it
    # sounds like — "vertical" is what lays the containers out side by side
    # (flex row, per its CSS); "horizontal" stacks them in a single column.
    sorted_containers = sort_items(
        containers, multi_containers=True, direction="vertical",
        key=f"kanban_sortable_{activity_id}_{st.session_state[version_key]}",
        custom_style="""
            .sortable-component.vertical { align-items: flex-start; gap: 12px; }
            .sortable-container { background: #f1f5f9; border-radius: 8px; padding: 10px; min-height: 220px; }
            .sortable-container-header { font-weight: 600; color: #374151; padding: 4px 6px 10px; }
            .sortable-item { background: white; border: 1px solid #e5e7eb; border-radius: 6px;
                padding: 10px 12px; margin-bottom: 8px; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
                font-size: 13px; color: #1f2937; }
        """,
    )

    for container, status in zip(sorted_containers, TASK_STATUSES):
        for label in container["items"]:
            match = re.match(r"^#(\d+)\s", label)
            if not match:
                continue
            task = tasks_by_id.get(int(match.group(1)))
            if task and task["status"] != status:
                update_task_status(task["id"], status)
                st.session_state[version_key] += 1
                st.rerun()


# ── Activity detail page ───────────────────────────────────────────────────────

def _render_activity_detail(activity_id: int):
    """Full-page activity details (not a modal) — shown instead of the
    activities list whenever `st.session_state['act_view_id']` is set."""
    act = get_activity(activity_id)

    with st.container(key="card_activity_detail"):
        if not act:
            st.error("Activity not found.")
            if st.button("← Back to Activities", key="act_detail_back_missing"):
                st.session_state["act_view_id"] = None
                st.rerun()
            return

        visible_tasks = list_tasks_for_activity_and_user(activity_id, me, is_admin)
        can_manage = _can_manage_activity(act)
        # A plain user can only reach this activity (via the list) if they're
        # assigned to at least one task in it, which is exactly `can_manage_tasks`.
        can_manage_tasks = is_admin or act["created_by"] == me or len(visible_tasks) > 0

        if not can_manage_tasks:
            st.error("Activity not found, or you don't have access to it.")
            if st.button("← Back to Activities", key="act_detail_back_denied"):
                st.session_state["act_view_id"] = None
                st.session_state["task_view_id"] = None
                st.rerun()
            return

        col_back, col_edit, col_delete = st.columns([4, 1, 1])
        if col_back.button("← Back to Activities", key="act_detail_back"):
            st.session_state["act_view_id"] = None
            st.session_state["task_view_id"] = None
            st.rerun()
        if can_manage:
            if col_edit.button("✏ Edit", use_container_width=True, key="act_detail_edit_btn"):
                _edit_activity_dialog(activity_id)
            if col_delete.button("🗑 Delete", use_container_width=True, key="act_detail_delete_btn"):
                _confirm_delete_activity(activity_id)

        st.markdown(f"## {html.escape(act.get('title') or '(untitled activity)')}")
        st.caption(
            f"{PRIORITY_LABELS.get(act['priority'], act['priority'])} · "
            f"{_format_date_range(act['start_date'], act['end_date'])}"
        )
        st.markdown("**Description**")
        desc = act.get("description") or ""
        st.markdown(desc.replace("\n", "  \n") if desc else "—")

        creator = all_users_by_username.get(act["created_by"])
        st.markdown(f"**Created by:** {_display_name(creator) if creator else act['created_by']}")

        task_count = len(visible_tasks)
        done_count = sum(1 for t in visible_tasks if t["status"] == "Done")
        st.progress(
            done_count / task_count if task_count else 0.0,
            text=f"{done_count}/{task_count} tasks done" if task_count else "No tasks yet",
        )

    if "task_view_id" not in st.session_state:
        st.session_state["task_view_id"] = None

    if st.session_state.get("task_view_id"):
        task = next((t for t in visible_tasks if t["id"] == st.session_state["task_view_id"]), None)
        if task:
            _render_task_detail(task, can_manage_tasks)
            return
        st.session_state["task_view_id"] = None

    with st.container(key="card_task_toolbar"):
        if can_manage_tasks:
            if st.button("➕ New Task", key="act_new_task_btn"):
                _create_task_dialog(activity_id)
        else:
            st.caption("No tasks assigned to you in this activity yet.")

    tab_kanban, tab_list = st.tabs(["🗂 Kanban", "📋 List"])

    with tab_kanban:
        with st.container(key="card_kanban"):
            _render_kanban_board(activity_id, visible_tasks)

    with tab_list:
        with st.container(key="card_task_list"):
            if not visible_tasks:
                st.info("No tasks yet.")
            else:
                widths = [2.3, 1.2, 1.0, 2, 2, 0.5, 0.5, 0.5] if can_manage_tasks else [2.6, 1.2, 1.0, 2.2, 2.2, 0.5]
                labels = ["Title", "Status", "Priority", "Dates", "Assignees", ""] + (["", ""] if can_manage_tasks else [])
                header = st.columns(widths)
                for c, label in zip(header, labels):
                    c.markdown(f"**{label}**")
                for t in visible_tasks:
                    row = st.columns(widths)
                    row[0].write(t["title"])
                    row[1].write(t["status"])
                    row[2].write(PRIORITY_LABELS.get(t["priority"], t["priority"]))
                    row[3].write(_format_date_range(t["start_date"], t["end_date"]))
                    row[4].write(_assignee_names(t.get("assignees", [])))
                    if row[5].button("👁", key=f"list_view_{t['id']}"):
                        st.session_state["task_view_id"] = t["id"]
                        st.rerun()
                    if can_manage_tasks:
                        if row[6].button("✏", key=f"list_edit_{t['id']}"):
                            _edit_task_dialog(t["id"])
                        if row[7].button("🗑", key=f"list_del_{t['id']}"):
                            _confirm_delete_task(t["id"])


# ── Dispatch: detail page short-circuits the list ──────────────────────────────

if "act_view_id" not in st.session_state:
    st.session_state["act_view_id"] = None

if st.session_state.get("act_view_id"):
    _render_activity_detail(st.session_state["act_view_id"])
    st.stop()

# ── Toolbar ──────────────────────────────────────────────────────────────────
with st.container(key="card_toolbar"):
    if st.button("➕ New Activity"):
        _create_activity_dialog()

# ── Activities list ─────────────────────────────────────────────────────────
activities = list_activities_for_user(me, is_admin)

with st.container(key="card_activity_list"):
    if not activities:
        st.info("No activities yet.")
    else:
        widths = [2.4, 1.1, 2, 0.9, 1.6, 0.6, 0.6, 0.6]
        header = st.columns(widths)
        for c, label in zip(header, ["Title", "Priority", "Dates", "Tasks", "Completion", "", "", ""]):
            c.markdown(f"**{label}**")
        for act in activities:
            row = st.columns(widths)
            row[0].write(act["title"])
            row[1].write(PRIORITY_LABELS.get(act["priority"], act["priority"]))
            row[2].write(_format_date_range(act["start_date"], act["end_date"]))
            row[3].write(str(act["task_count"]))
            row[4].write(f"{act['completion_rate']}%")
            if row[5].button("👁", key=f"act_view_{act['id']}"):
                st.session_state["act_view_id"] = act["id"]
                st.session_state["task_view_id"] = None
                st.rerun()
            if _can_manage_activity(act):
                if row[6].button("✏", key=f"act_edit_{act['id']}"):
                    _edit_activity_dialog(act["id"])
                if row[7].button("🗑", key=f"act_del_{act['id']}"):
                    _confirm_delete_activity(act["id"])
