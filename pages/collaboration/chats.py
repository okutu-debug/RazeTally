import html
from datetime import datetime, timedelta

import streamlit as st
import streamlit.components.v1 as components

from db import (
    add_chat_group_members,
    create_chat_group,
    list_chat_messages,
    list_dm_conversations,
    list_group_chat_messages,
    list_group_members,
    list_online_usernames,
    list_user_groups,
    list_users,
    send_chat_message,
    send_group_chat_message,
)
from theme import apply_theme

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Chats</h4>",
    unsafe_allow_html=True,
)

# On mobile, st.columns stacks the chat-list and thread cards vertically —
# this tracks which one should be "front and center" so we can show only
# that one there (WhatsApp-style: list, then tap into a thread). Desktop
# ignores this and always shows both side by side.
if "mobile_view" not in st.session_state:
    st.session_state.mobile_view = "list"

me = st.session_state.username

if "active_chat_kind" not in st.session_state:
    st.session_state.active_chat_kind = None
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None
if "chat_filter" not in st.session_state:
    st.session_state.chat_filter = "All"

_dialog = None


def _display_name(u: dict) -> str:
    name = f"{u.get('other_names') or ''} {u.get('surname') or ''}".strip()
    return name or u["username"]


def _initials(name: str) -> str:
    parts = name.split()
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _select_user(username: str):
    st.session_state.active_chat_kind = "user"
    st.session_state.active_chat_id = username
    st.session_state.mobile_view = "thread"


def _select_group(group_id: int):
    st.session_state.active_chat_kind = "group"
    st.session_state.active_chat_id = group_id
    st.session_state.mobile_view = "thread"


def _format_conv_time(dt) -> str:
    if dt is None:
        return ""
    now = datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if dt.date() == (now - timedelta(days=1)).date():
        return "Yesterday"
    if (now.date() - dt.date()).days < 7:
        return dt.strftime("%a")
    return dt.strftime("%d/%m/%Y")


online_usernames = list_online_usernames()

everyone = [u for u in list_users() if u["username"] != me]
everyone_by_username = {u["username"]: u for u in everyone}
everyone_sorted = sorted(everyone, key=_display_name)

my_groups = list_user_groups(me)
dm_conversations = list_dm_conversations(me)

# ── Build a unified, WhatsApp-style conversation list (groups + DMs, sorted
# by most recent activity) ──────────────────────────────────────────────────
entries = []
for g in my_groups:
    last_at = g["last_message_at"] or g["created_at"]
    entries.append({
        "kind": "group", "id": g["id"], "name": g["name"],
        "last_at": last_at, "online": False,
    })

dm_peer_usernames = set()
for c in dm_conversations:
    peer = c["peer"]
    dm_peer_usernames.add(peer)
    other = everyone_by_username.get(peer)
    name = _display_name(other) if other else peer
    entries.append({
        "kind": "user", "id": peer, "name": name,
        "last_at": c["created_at"], "online": peer in online_usernames,
    })

entries.sort(key=lambda e: e["last_at"], reverse=True)

if st.session_state.active_chat_kind is None:
    if entries:
        st.session_state.active_chat_kind = entries[0]["kind"]
        st.session_state.active_chat_id = entries[0]["id"]
    elif everyone_sorted:
        _select_user(everyone_sorted[0]["username"])

_mobile_list_display = "block" if st.session_state.mobile_view == "list" else "none"
_mobile_thread_display = "none" if st.session_state.mobile_view == "list" else "block"

# Desktop: the list card scrolls as a whole (it's just a list). The thread
# card does NOT scroll as a whole — its header and input stay static, and
# only the message list in between scrolls (that div has its own fixed
# height + overflow, set in the Python below). If the thread card's total
# content still ends up taller than the screen, the page itself scrolls
# rather than the card growing a second, confusing scrollbar.
# Mobile: st.columns stacks the two cards, but hiding just the inner card
# (via display:none) left the *column* it sits in still reserving space —
# that's what showed up as blank space with nothing selectable. Instead we
# hide the whole column using :has(), scoped to mobile widths only so it
# never affects the desktop layout.
st.markdown(
    """
    <style>
    div[class*="st-key-mobile_back_wrap"] {
        display: none;
    }
    div[class*="st-key-mobile_back_wrap"] button {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        color: #2563eb !important;
        font-weight: 600;
        padding: 4px 0 !important;
    }

    @media (min-width: 769px) {
        html, body,
        [data-testid="stAppViewContainer"],
        [data-testid="stAppViewContainer"] > .main,
        section.main {
            overflow-y: auto !important;
        }
        div.block-container {
            padding-bottom: 0.5rem;
        }
        div[class*="st-key-card_chat_users"] {
            height: calc(100vh - 260px) !important;
            max-height: calc(100vh - 260px) !important;
        }
    }

    @media (max-width: 768px) {
        div[data-testid="column"]:has(div[class*="st-key-card_chat_users"]),
        div[data-testid="stColumn"]:has(div[class*="st-key-card_chat_users"]) {
            display: """ + _mobile_list_display + """ !important;
        }
        div[data-testid="column"]:has(div[class*="st-key-card_chat_thread"]),
        div[data-testid="stColumn"]:has(div[class*="st-key-card_chat_thread"]) {
            display: """ + _mobile_thread_display + """ !important;
        }
        div[class*="st-key-mobile_back_wrap"] {
            display: block !important;
            margin-bottom: 10px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Dialogs ──────────────────────────────────────────────────────────────────

@st.dialog("New group")
def _create_group_dialog():
    with st.form("dlg_new_group_form"):
        name = st.text_input("Group name *")
        member_usernames = st.multiselect(
            "Add members",
            options=[u["username"] for u in everyone],
            format_func=lambda uname: _display_name(everyone_by_username[uname]),
        )
        submitted = st.form_submit_button("Create group", type="primary", use_container_width=True)
    if submitted:
        if not name.strip():
            st.error("Group name is required.")
        elif not member_usernames:
            st.error("Select at least one member.")
        else:
            group_id = create_chat_group(name.strip(), me, member_usernames)
            _select_group(group_id)
            st.rerun()


@st.dialog("Contacts")
def _contacts_dialog():
    search = st.text_input(
        "Search", placeholder="🔍 Search contacts",
        label_visibility="collapsed", key="contacts_dialog_search",
    )
    term = search.strip().lower()
    contacts = (
        [u for u in everyone_sorted if term in _display_name(u).lower()]
        if term else everyone_sorted
    )
    if not contacts:
        st.caption("No contacts found.")
    for u in contacts:
        name = _display_name(u)
        icon = "🟢" if u["username"] in online_usernames else "⚪"
        if st.button(f"{icon}  {name}", key=f"contact_{u['username']}", use_container_width=True):
            _select_user(u["username"])
            st.rerun()


@st.dialog("Add members")
def _add_members_dialog(group_id: int):
    existing = {m["username"] for m in list_group_members(group_id)}
    candidates = [u for u in everyone if u["username"] not in existing]
    if not candidates:
        st.caption("Everyone is already in this group.")
        return
    with st.form("dlg_add_members_form"):
        member_usernames = st.multiselect(
            "People to add",
            options=[u["username"] for u in candidates],
            format_func=lambda uname: _display_name(everyone_by_username[uname]),
        )
        submitted = st.form_submit_button("Add", type="primary", use_container_width=True)
    if submitted:
        if not member_usernames:
            st.error("Select at least one person to add.")
        else:
            add_chat_group_members(group_id, member_usernames)
            st.rerun()


# ── Chat list panel, in its own fragment ────────────────────────────────────
# Search, filter, and "New group" only affect what's shown in this panel, so
# they're scoped to a fragment: clicking them reruns just this fragment, not
# the whole page. Picking a chat is different — it has to repaint the thread
# panel outside this fragment too, so that button calls st.rerun() itself to
# force a full app rerun. That's still a normal in-session Streamlit rerun
# (no browser navigation/reload) — not the same thing as the old query-param
# links, which caused an actual page reload.
@st.fragment
def _render_chat_list():
    st.text_input(
        "Search",
        placeholder="🔍 Search",
        label_visibility="collapsed",
        key="chat_search",
    )

    st.html(
        """
        <style>
        /* "Contacts" / "New Group" action buttons: keep label on one line */
        div[class*="st-key-contacts_btn"] button,
        div[class*="st-key-new_group_btn"] button {
            white-space: nowrap;
            font-size: 13px;
            padding: 0.4rem 0.35rem;
        }

        /* Chat list rows rendered as a plain list, not as buttons:
           no border, no background, no shadow — just left-aligned text
           with a light hover/selected tint. */
        div[class*="st-key-row_"] button {
            width: 100%;
            display: flex !important;
            align-items: center !important;
            text-align: left;
            justify-content: flex-start !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            border-radius: 8px;
            padding: 8px 8px !important;
            font-weight: 400;
        }
        div[class*="st-key-row_"] button div,
        div[class*="st-key-row_"] button p {
            text-align: left !important;
            justify-content: flex-start !important;
            width: 100%;
        }
        div[class*="st-key-row_"] button:hover {
            background: #f3f4f6 !important;
        }
        div[class*="st-key-row_"] button[kind="primary"] {
            background: #eff6ff !important;
            color: #1f2937 !important;
        }
        div[class*="st-key-row_"] button[kind="primary"]:hover {
            background: #e0edff !important;
        }
        div[class*="st-key-row_"] button p {
            font-weight: inherit;
        }

        .chat-section-label {
            font-size: 11px; font-weight: 600; color: #9ca3af; letter-spacing: .03em;
            padding: 10px 2px 2px;
        }
        </style>
        """
    )

    st.segmented_control(
        "Filter",
        options=["All", "Groups"],
        label_visibility="collapsed",
        key="chat_filter",
    )

    # "Contacts" + "New group" buttons, side by side on their own row.
    contacts_col, new_group_col = st.columns(2)
    with contacts_col:
        if st.button("👤 Contacts", use_container_width=True, key="contacts_btn"):
            _contacts_dialog()
    with new_group_col:
        if st.button("➕ New Group", use_container_width=True, key="new_group_btn"):
            _create_group_dialog()

    active_filter = st.session_state.get("chat_filter") or "All"
    search_term = st.session_state.get("chat_search", "").strip().lower()

    filtered_entries = entries
    if active_filter == "Groups":
        filtered_entries = [e for e in filtered_entries if e["kind"] == "group"]
    if search_term:
        filtered_entries = [e for e in filtered_entries if search_term in e["name"].lower()]

    new_chat_candidates = []
    if search_term and active_filter != "Groups":
        new_chat_candidates = [
            u for u in everyone_sorted
            if u["username"] not in dm_peer_usernames and search_term in _display_name(u).lower()
        ]

    if not filtered_entries and not new_chat_candidates:
        st.caption("No chats yet." if not search_term else "No matches.")
        return

    for e in filtered_entries:
        is_active = (
            st.session_state.active_chat_kind == e["kind"]
            and st.session_state.active_chat_id == e["id"]
        )
        icon = "👥" if e["kind"] == "group" else ("🟢" if e["online"] else "⚪")
        row_col, time_col = st.columns([4, 1], vertical_alignment="center")
        clicked = row_col.button(
            f"{icon}  {e['name']}",
            key=f"row_{e['kind']}_{e['id']}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        )
        time_col.caption(_format_conv_time(e["last_at"]))
        if clicked:
            if e["kind"] == "group":
                _select_group(e["id"])
            else:
                _select_user(e["id"])
            st.rerun()

    if new_chat_candidates:
        st.markdown("<div class='chat-section-label'>START NEW CHAT</div>", unsafe_allow_html=True)
        for u in new_chat_candidates:
            name = _display_name(u)
            icon = "🟢" if u["username"] in online_usernames else "⚪"
            if st.button(
                f"{icon}  {name}", key=f"row_newuser_{u['username']}", use_container_width=True,
            ):
                _select_user(u["username"])
                st.rerun()


col_list, col_thread = st.columns([1, 2], gap="medium")

# ── Chat list (groups + people, WhatsApp-style) ─────────────────────────────
# height=... turns the container into its own scroll area, so scrolling a
# long chat list never scrolls the outer page.
with col_list:
    with st.container(key="card_chat_users", height=640):
        _render_chat_list()

# ── Message thread ─────────────────────────────────────────────────────────
# Same idea here: the thread card scrolls internally (on top of the message
# box's own inner scroll), independent of the page and of the list card.
with col_thread:
    with st.container(key="card_chat_thread"):
        with st.container(key="mobile_back_wrap"):
            if st.button("← Chats", key="mobile_back_to_list"):
                st.session_state.mobile_view = "list"
                st.rerun()

        active_kind = st.session_state.active_chat_kind
        active_id = st.session_state.active_chat_id

        active_user = None
        active_group = None
        if active_kind == "user":
            active_user = everyone_by_username.get(active_id)
        elif active_kind == "group":
            active_group = next((g for g in my_groups if g["id"] == active_id), None)

        if active_user is None and active_group is None:
            st.markdown(
                "<div style='display:flex; align-items:center; justify-content:center; "
                "height:400px; color:#9ca3af; font-size:15px;'>"
                "Select a person or group to start chatting</div>",
                unsafe_allow_html=True,
            )
        elif active_user is not None:
            name = _display_name(active_user)
            subtitle = "Online" if active_id in online_usernames else (active_user.get("position") or active_user.get("role", ""))
            st.markdown(
                f"<div style='display:flex; align-items:center; gap:10px; "
                f"border-bottom:1px solid #e5e7eb; padding-bottom:12px; margin-bottom:12px;'>"
                f"<div style='width:38px; height:38px; border-radius:50%; background:#cbd5e1; "
                f"color:#1f2937; display:flex; align-items:center; justify-content:center; "
                f"font-weight:600; font-size:13px;'>{html.escape(_initials(name))}</div>"
                f"<div>"
                f"<div style='font-weight:600; font-size:16px; color:#1f2937;'>{html.escape(name)}</div>"
                f"<div style='font-size:12px; color:#9ca3af;'>{html.escape(subtitle)}</div>"
                f"</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            @st.fragment(run_every="3s")
            def _render_user_thread(me: str, other_username: str, other_name: str):
                """Reruns on its own timer so incoming messages appear without
                the recipient having to interact with or reload the page."""
                thread = list_chat_messages(me, other_username)
                if not thread:
                    bubbles_html = (
                        "<div style='color:#9ca3af; text-align:center; padding:40px 0;'>"
                        "No messages yet. Say hello 👋</div>"
                    )
                else:
                    bubbles_html = ""
                    for m in thread:
                        is_me = m["sender_username"] == me
                        align = "flex-end" if is_me else "flex-start"
                        bg = "#2563eb" if is_me else "#f1f5f9"
                        color = "white" if is_me else "#1f2937"
                        sender_label = (
                            ""
                            if is_me
                            else f"<div style='font-size:11px; color:#6b7280; margin-bottom:2px;'>{html.escape(other_name)}</div>"
                        )
                        time_label = m["created_at"].strftime("%H:%M")
                        bubbles_html += (
                            f"<div style='display:flex; flex-direction:column; align-items:{align}; margin-bottom:10px;'>"
                            f"{sender_label}"
                            f"<div style='background:{bg}; color:{color}; padding:9px 13px; border-radius:14px; "
                            f"max-width:70%; font-size:14px; line-height:1.4;'>{html.escape(m['message'])}</div>"
                            f"<div style='font-size:10px; color:#9ca3af; margin-top:3px;'>{time_label}</div>"
                            f"</div>"
                        )

                st.html(
                    f"""
                    <div id="chat-thread-box" style='height:420px;
                         overflow-y:auto; display:flex; flex-direction:column; padding:4px 6px;'>
                        {bubbles_html}
                    </div>
                    """
                )
                # The trailing comment embeds the last message id so this component's
                # content changes whenever the thread changes — otherwise Streamlit
                # sees identical markup on every 3s poll and never remounts the
                # iframe, so the scroll script would stop firing after the first run.
                last_id = thread[-1]["id"] if thread else 0
                components.html(
                    f"""
                    <script>
                    (function () {{
                        const scrollToBottom = () => {{
                            const box = window.parent.document.getElementById("chat-thread-box");
                            if (box) {{ box.scrollTop = box.scrollHeight; }}
                        }};
                        scrollToBottom();
                        setTimeout(scrollToBottom, 100);
                        setTimeout(scrollToBottom, 300);
                    }})();
                    </script>
                    <!-- last_id={last_id} -->
                    """,
                    height=0,
                )

                with st.form(key="chat_send_form", clear_on_submit=True):
                    fcol1, fcol2 = st.columns([5, 1])
                    fcol1.text_input(
                        "Message",
                        placeholder="Type a message…",
                        label_visibility="collapsed",
                        key="chat_draft",
                    )
                    sent = fcol2.form_submit_button("Send", use_container_width=True)
                    if sent:
                        text = st.session_state.get("chat_draft", "").strip()
                        if text:
                            send_chat_message(me, other_username, text)
                            st.rerun(scope="fragment")

            _render_user_thread(me, active_id, name)

        else:
            members = list_group_members(active_group["id"])
            member_names = ", ".join(_display_name(m) for m in members)
            header_col, add_col = st.columns([5, 1.6])
            with header_col:
                st.markdown(
                    f"<div style='display:flex; align-items:center; gap:10px; margin-bottom:2px;'>"
                    f"<div style='width:38px; height:38px; border-radius:50%; background:#c7d2fe; "
                    f"color:#1f2937; display:flex; align-items:center; justify-content:center; "
                    f"font-weight:600; font-size:16px;'>👥</div>"
                    f"<div>"
                    f"<div style='font-weight:600; font-size:16px; color:#1f2937;'>{html.escape(active_group['name'])}</div>"
                    f"<div style='font-size:12px; color:#9ca3af;'>{html.escape(member_names)}</div>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
            if add_col.button("➕ Members", key=f"add_members_{active_group['id']}", use_container_width=True):
                _dialog = ("add_members", active_group["id"])
            st.markdown(
                "<div style='border-bottom:1px solid #e5e7eb; margin-bottom:12px;'></div>",
                unsafe_allow_html=True,
            )

            @st.fragment(run_every="3s")
            def _render_group_thread(me: str, group_id: int):
                """Reruns on its own timer so incoming messages appear without
                the recipient having to interact with or reload the page."""
                thread = list_group_chat_messages(group_id)
                if not thread:
                    bubbles_html = (
                        "<div style='color:#9ca3af; text-align:center; padding:40px 0;'>"
                        "No messages yet. Say hello 👋</div>"
                    )
                else:
                    bubbles_html = ""
                    for m in thread:
                        is_me = m["sender_username"] == me
                        align = "flex-end" if is_me else "flex-start"
                        bg = "#2563eb" if is_me else "#f1f5f9"
                        color = "white" if is_me else "#1f2937"
                        sender_name = (
                            f"{m.get('sender_other_names') or ''} {m.get('sender_surname') or ''}".strip()
                            or m["sender_username"]
                        )
                        sender_label = (
                            ""
                            if is_me
                            else f"<div style='font-size:11px; color:#6b7280; margin-bottom:2px;'>{html.escape(sender_name)}</div>"
                        )
                        time_label = m["created_at"].strftime("%H:%M")
                        bubbles_html += (
                            f"<div style='display:flex; flex-direction:column; align-items:{align}; margin-bottom:10px;'>"
                            f"{sender_label}"
                            f"<div style='background:{bg}; color:{color}; padding:9px 13px; border-radius:14px; "
                            f"max-width:70%; font-size:14px; line-height:1.4;'>{html.escape(m['message'])}</div>"
                            f"<div style='font-size:10px; color:#9ca3af; margin-top:3px;'>{time_label}</div>"
                            f"</div>"
                        )

                st.html(
                    f"""
                    <div id="group-chat-thread-box" style='height:420px;
                         overflow-y:auto; display:flex; flex-direction:column; padding:4px 6px;'>
                        {bubbles_html}
                    </div>
                    """
                )
                last_id = thread[-1]["id"] if thread else 0
                components.html(
                    f"""
                    <script>
                    (function () {{
                        const scrollToBottom = () => {{
                            const box = window.parent.document.getElementById("group-chat-thread-box");
                            if (box) {{ box.scrollTop = box.scrollHeight; }}
                        }};
                        scrollToBottom();
                        setTimeout(scrollToBottom, 100);
                        setTimeout(scrollToBottom, 300);
                    }})();
                    </script>
                    <!-- last_id={last_id} -->
                    """,
                    height=0,
                )

                with st.form(key="group_chat_send_form", clear_on_submit=True):
                    fcol1, fcol2 = st.columns([5, 1])
                    fcol1.text_input(
                        "Message",
                        placeholder="Type a message…",
                        label_visibility="collapsed",
                        key="group_chat_draft",
                    )
                    sent = fcol2.form_submit_button("Send", use_container_width=True)
                    if sent:
                        text = st.session_state.get("group_chat_draft", "").strip()
                        if text:
                            send_group_chat_message(group_id, me, text)
                            st.rerun(scope="fragment")

            _render_group_thread(me, active_group["id"])

if isinstance(_dialog, tuple) and _dialog[0] == "add_members":
    _add_members_dialog(_dialog[1])