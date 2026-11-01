"""RazeTally Streamlit app — entry point."""

from dotenv import load_dotenv
load_dotenv()

import os

import streamlit as st
import streamlit.components.v1 as _components
import base64
from io import BytesIO
from PIL import Image
from auth import create_token, decode_token, is_revoked, revoke_token, verify_password
from db import decline_call, get_incoming_call, get_user, get_user_polling_stations, init_activities, init_applicant_documents, init_applications, init_calls, init_campaign_location_media, init_campaign_locations, init_campaign_materials, init_campaign_teams, init_candidates, init_chat_groups, init_chat_messages, init_contributions, init_demography, init_election_materials, init_election_teams, init_events, init_feed, init_interview_answers, init_interview_questions, init_job_descriptions, init_location_team, init_materials, init_opinion_polls, init_panel_assignments, init_parties, init_party_members, init_polling_stations, init_positions, init_revoked_tokens, init_team_assignments, init_user_documents, init_user_polling_stations, init_users, is_panelist, touch_presence

st.set_page_config(page_title="RazeTally", layout="wide", initial_sidebar_state="expanded")

_COOKIE        = "razetally_auth"
_COOKIE_DAYS   = 7
# Only mark the cookie Secure once served over HTTPS — a Secure cookie is
# silently dropped by browsers over plain http://, which would break local dev.
_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").strip().lower() == "true"


# ── Cookie helpers (synchronous — no JS timing issues) ────────────────────────

def _get_cookie_token() -> str | None:
    """Read the auth JWT from the HTTP request's Cookie header."""
    for part in st.context.headers.get("cookie", "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == _COOKIE:
            return value.strip()
    return None


def _set_cookie(token: str):
    """Write the auth cookie to the browser via a 0-height JS component."""
    max_age = _COOKIE_DAYS * 24 * 3600
    secure_attr = ";Secure" if _COOKIE_SECURE else ""
    _components.html(
        f"<script>document.cookie='{_COOKIE}={token};"
        f"path=/;max-age={max_age};SameSite=Strict{secure_attr}';</script>",
        height=0,
    )


def _remove_cookie():
    """Expire the auth cookie in the browser via a 0-height JS component."""
    _components.html(
        f"<script>document.cookie='{_COOKIE}=;"
        f"path=/;expires=Thu, 01 Jan 1970 00:00:00 GMT';</script>",
        height=0,
    )


def _restore_session() -> bool:
    """Try to restore session from the HTTP cookie. Always synchronous."""
    if st.session_state.get("authenticated"):
        return True
    token = _get_cookie_token()
    if not token or is_revoked(token):
        return False
    payload = decode_token(token)
    if payload:
        st.session_state.authenticated = True
        st.session_state.username = payload["sub"]
        st.session_state.role = payload["role"]
        st.session_state["_auth_token"] = token
        return True
    return False


def _get_image_base64(path, size=None):
    img = Image.open(path)
    if size:
        img = img.resize(size)
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()

def _show_login():
    img_b64 = _get_image_base64("./assets/images/logo_razetally_light.png", size=(400, 400))

    st.markdown("""
        <style>
        .stApp { background: #ebedee !important; }

        div[class*="st-key-login_left"] {
            background: linear-gradient(160deg, #152744 0%, #1e4a85 55%, #2471a3 100%);
            border-radius: 14px 0 0 14px;
            padding: 2rem 1.5rem !important;
        }
        div[class*="st-key-login_right"] {
            background: white;
            border-radius: 0 14px 14px 0;
            padding: 2rem 1.5rem !important;
        }

        /* Login button matches left panel */
        div[class*="st-key-login_right"] [data-testid="stFormSubmitButton"] button {
            background: linear-gradient(160deg, #152744 0%, #1e4a85 55%, #2471a3 100%) !important;
            border: none !important;
            color: white !important;
        }
        div[class*="st-key-login_right"] [data-testid="stFormSubmitButton"] button:hover {
            background: linear-gradient(160deg, #0f1e33 0%, #183d70 55%, #1d608a 100%) !important;
        }
        </style>
    """, unsafe_allow_html=True)

    _, center, _ = st.columns([1, 2.2, 1])
    with center:
        left_col, right_col = st.columns([1, 1.2])

        # ── Left: branding ────────────────────────────────────────────────
        with left_col:
            with st.container(key="login_left"):
                st.markdown(f"""
                    <div style="display:flex; flex-direction:column; align-items:center;
                                text-align:center; padding:0.5rem 0;">
                        <img src="data:image/png;base64,{img_b64}" width="90"
                             style="margin-bottom:1rem;">
                        <h2 style="color:white; margin:0 0 0.3rem; font-size:1.5rem;">RazeTally</h2>
                        <p style="color:rgba(255,255,255,0.65); font-size:0.72rem;
                                  letter-spacing:0.1em; text-transform:uppercase; margin:0 0 1.75rem;">
                            Tallying Results · Trusting Democracy
                        </p>
                        <div style="text-align:left; width:100%;">
                            <p style="color:rgba(255,255,255,0.85); margin:0.45rem 0; font-size:0.85rem;">
                                ✓ &nbsp;AI-powered form extraction</p>
                            <p style="color:rgba(255,255,255,0.85); margin:0.45rem 0; font-size:0.85rem;">
                                ✓ &nbsp;Real-time tally dashboards</p>
                            <p style="color:rgba(255,255,255,0.85); margin:0.45rem 0; font-size:0.85rem;">
                                ✓ &nbsp;Role-based access control</p>
                            <p style="color:rgba(255,255,255,0.85); margin:0.45rem 0; font-size:0.85rem;">
                                ✓ &nbsp;Transparent results tracking</p>
                        </div>
                    </div>
                """, unsafe_allow_html=True)

        # ── Right: login form ──────────────────────────────────────────────
        with right_col:
            with st.container(key="login_right"):
                st.markdown(
                    "<h3 style='text-align:center; margin:0.5rem 0 0.2rem;'>Welcome back</h3>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    "<p style='text-align:center; color:#64748b; margin:0 0 1.25rem;"
                    " font-size:0.88rem;'>Sign in to your account</p>",
                    unsafe_allow_html=True,
                )
                with st.form("login_form"):
                    username  = st.text_input("Username")
                    password  = st.text_input("Password", type="password")
                    submitted = st.form_submit_button("Login", type="primary", use_container_width=True)

            if submitted:
                user = get_user(username)
                if user and verify_password(password, user["password_hash"]):
                    token = create_token(user["username"], user["role"])
                    st.session_state.authenticated  = True
                    st.session_state.username       = user["username"]
                    st.session_state.role           = user["role"]
                    st.session_state["_auth_token"] = token
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
# ── Bootstrap ─────────────────────────────────────────────────────────────────
# Schema setup only needs to run once per server process — running it on every
# rerun opened ~30 DB connections before the login page could render.
@st.cache_resource(show_spinner="Starting up…")
def _bootstrap():
    init_demography()
    init_users()
    init_positions()
    init_team_assignments()
    init_panel_assignments()
    init_polling_stations()
    init_user_polling_stations()
    init_user_documents()
    init_applications()
    init_applicant_documents()
    init_party_members()
    init_parties()
    init_candidates()
    init_opinion_polls()
    init_contributions()
    init_revoked_tokens()
    init_job_descriptions()
    init_interview_questions()
    init_interview_answers()
    init_materials()
    init_campaign_teams()
    init_campaign_materials()
    init_campaign_locations()
    init_location_team()
    init_campaign_location_media()
    init_election_teams()
    init_election_materials()
    init_chat_messages()
    init_chat_groups()
    init_calls()
    init_events()
    init_activities()
    init_feed()


_bootstrap()
_restore_session()

if not st.session_state.get("authenticated"):
    st.markdown("<style>[data-testid='stSidebar']{display:none}</style>", unsafe_allow_html=True)
    _show_login()
    st.stop()

# Keep the cookie alive on every authenticated render
_set_cookie(st.session_state.get("_auth_token") or _get_cookie_token() or "")


@st.fragment(run_every="20s")
def _presence_heartbeat():
    """Reruns on its own timer (independent of user interaction) so a session
    still counts as online while the user is idly reading a page."""
    touch_presence(st.session_state.username)


_presence_heartbeat()


# ── Incoming-call popup (app-wide) ─────────────────────────────────────────────
# The Calls page (pages/collaboration/calls.py) has its own richer inline
# "Incoming call…" panel, so this global watcher stays out of the way while
# the user is already there — see the `_on_calls_page` flag it sets.

@st.dialog("Incoming call", dismissible=False)
def _incoming_call_dialog(call: dict):
    caller = call["caller_username"]
    caller_user = get_user(caller)
    name = (
        f"{caller_user.get('other_names') or ''} {caller_user.get('surname') or ''}".strip()
        if caller_user else ""
    ) or caller
    st.markdown(f"**{name}** is calling you…")
    accept_col, decline_col = st.columns(2)
    if accept_col.button("✅ Accept", use_container_width=True, key="global_accept_call"):
        st.session_state["pending_call_accept_id"] = call["id"]
        st.switch_page("pages/collaboration/calls.py")
    if decline_col.button("❌ Decline", use_container_width=True, key="global_decline_call"):
        decline_call(call["id"])
        st.rerun()


@st.fragment(run_every="2s")
def _incoming_call_watcher():
    if st.session_state.get("_on_calls_page"):
        return
    if st.session_state.get("active_call_id") is not None:
        return  # already mid-negotiation on a call elsewhere
    incoming = get_incoming_call(st.session_state.username)
    if incoming:
        _incoming_call_dialog(incoming)


st.session_state["_on_calls_page"] = False

# ── Global loading bar ────────────────────────────────────────────────────────
_components.html("""
<script>
(function () {
    const doc = window.parent.document;

    // Inject styles once
    if (!doc.getElementById('_raze_loader_style')) {
        const s = doc.createElement('style');
        s.id = '_raze_loader_style';
        s.textContent = `
            #_raze_loader {
                position: fixed;
                top: 0; left: 0;
                width: 100%;
                height: 3px;
                z-index: 999999;
                pointer-events: none;
                overflow: hidden;
                background: transparent;
            }
            #_raze_loader_bar {
                height: 100%;
                width: 40%;
                background: linear-gradient(90deg, #2563eb, #7c3aed, #db2777);
                border-radius: 0 2px 2px 0;
                position: absolute;
                left: -40%;
                animation: none;
            }
            #_raze_loader.active #_raze_loader_bar {
                animation: raze_slide 1.2s ease-in-out infinite;
            }
            @keyframes raze_slide {
                0%   { left: -40%; }
                100% { left: 100%; }
            }
        `;
        doc.head.appendChild(s);
    }

    // Create bar element once
    if (!doc.getElementById('_raze_loader')) {
        const wrap = doc.createElement('div');
        wrap.id = '_raze_loader';
        wrap.innerHTML = '<div id="_raze_loader_bar"></div>';
        doc.body.prepend(wrap);
    }

    // Toggle based on Streamlit status widget activity
    const toggle = () => {
        const loader = doc.getElementById('_raze_loader');
        if (!loader) return;
        const widget = doc.querySelector('[data-testid="stStatusWidget"]');
        const running = widget && widget.childElementCount > 0;
        loader.classList.toggle('active', running);
    };

    new MutationObserver(toggle)
        .observe(doc.body, { childList: true, subtree: true });
    toggle();
})();
</script>
""", height=0)

# ── App-wide chrome styling ───────────────────────────────────────────────────
st.markdown("""
    <style>
    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #152744 0%, #1e4a85 60%, #2471a3 100%) !important;
    }
    [data-testid="stSidebar"] * { color: rgba(255,255,255,0.9) !important; }

    [data-testid="stSidebarNavLink"] {
        border-radius: 8px !important;
        color: rgba(255,255,255,0.8) !important;
    }
    [data-testid="stSidebarNavLink"]:hover {
        background: rgba(255,255,255,0.12) !important;
        color: white !important;
    }
    [data-testid="stSidebarNavLink"][aria-selected="true"] {
        background: rgba(255,255,255,0.2) !important;
        color: white !important;
        font-weight: 600 !important;
    }
    [data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.15) !important; }
    [data-testid="stSidebar"] button {
        background: transparent !important;
        border: 1px solid rgba(255,255,255,0.35) !important;
        color: white !important;
    }
    [data-testid="stSidebar"] button:hover {
        background: rgba(255,255,255,0.1) !important;
        border-color: rgba(255,255,255,0.65) !important;
    }

    /* ── Sidebar width (only when expanded, so collapse still works) ── */
    [data-testid="stSidebar"][aria-expanded="true"] {
        width: 250px !important;
        min-width: 250px !important;
        max-width: 250px !important;
    }
    [data-testid="stSidebar"][aria-expanded="true"] > div {
        width: 250px !important;
        min-width: 250px !important;
    }
    [data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarContent"] {
        width: 250px !important;
    }
    [data-testid="stSidebar"][aria-expanded="false"] {
        width: 0 !important;
        min-width: 0 !important;
        max-width: 0 !important;
    }

    /* ── Sidebar nav: main section headers, single line ── */
    header[data-testid="stNavSectionHeader"] {
        margin-top: 1rem !important;
        height: auto !important;
        min-height: unset !important;
    }
    header[data-testid="stNavSectionHeader"] p {
        font-size: 0.92rem !important;
        font-weight: 600 !important;
        color: white !important;
        line-height: 1.3 !important;
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        max-width: none !important;
    }
    [data-testid="stSidebarNavLink"] p {
        white-space: nowrap !important;
        overflow: visible !important;
        text-overflow: clip !important;
        max-width: none !important;
    }

    /* ── Dashboard: standalone top-level page (first item, no section header) ── */
    [data-testid="stSidebarNav"] li:first-child [data-testid="stSidebarNavLink"] p,
    [data-testid="stSidebarNav"] > ul > li:first-child p,
    [data-testid="stSidebarNavLink"][href*="dashboard" i] p {
        font-size: 0.92rem !important;
        font-weight: 600 !important;
        color: white !important;
    }

    /* ── Sidebar nav: indent sub-items that follow a section header ── */
    header[data-testid="stNavSectionHeader"] ~ li [data-testid="stSidebarNavLink"] {
        padding-left: 2rem !important;
    }

    /* ── Top header bar ── */
    header[data-testid="stHeader"] {
        background: linear-gradient(90deg, #152744 0%, #2471a3 100%) !important;
    }
    header[data-testid="stHeader"] button,
    header[data-testid="stHeader"] a,
    header[data-testid="stHeader"] span { color: white !important; }
    header[data-testid="stHeader"] svg { fill: white !important; }

    /* ── Primary buttons (gradient throughout app) ── */
    button[kind="primary"], button[kind="primaryFormSubmit"] {
        background: linear-gradient(160deg, #152744 0%, #1e4a85 55%, #2471a3 100%) !important;
        border: none !important;
        color: white !important;
    }
    button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {
        background: linear-gradient(160deg, #0f1e33 0%, #183d70 55%, #1d608a 100%) !important;
    }
    </style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
role = st.session_state.role


@st.dialog("Confirm logout")
def _logout_dialog():
    st.write("Are you sure you want to log out?")
    col1, col2 = st.columns(2)
    if col1.button("Yes, logout", type="primary", use_container_width=True):
        token = st.session_state.get("_auth_token") or _get_cookie_token()
        if token:
            revoke_token(token)
        _remove_cookie()
        st.session_state.clear()
        st.rerun()
    if col2.button("Cancel", use_container_width=True):
        st.rerun()


# ── Top-right profile/logout (mirrors sidebar controls) ────────────────────────
with st.container(key="header_actions"):
    hcol1, hcol2 = st.columns(2, gap="small")
    with hcol1:
        if st.button("👤 Profile", key="header_profile_btn", use_container_width=True):
            st.switch_page("pages/profile.py")
    with hcol2:
        if st.button("🚪 Logout", key="header_logout_btn", use_container_width=True):
            _logout_dialog()

st.markdown("""
    <style>
    div[class*="st-key-header_actions"] {
        position: fixed;
        top: 0.55rem;
        right: 7.5rem;
        width: 12rem;
        z-index: 1000000;
    }
    div[class*="st-key-header_actions"] button {
        background: rgba(255,255,255,0.12) !important;
        border: 1px solid rgba(255,255,255,0.45) !important;
        color: white !important;
        border-radius: 999px !important;
        font-size: 0.8rem !important;
        padding: 0.25rem 0.6rem !important;
        white-space: nowrap !important;
    }
    div[class*="st-key-header_actions"] button:hover {
        background: rgba(255,255,255,0.25) !important;
        border-color: white !important;
    }

    /* On narrow/mobile viewports the sidebar becomes a full-width overlay
       drawer, which this fixed-position header bar would sit on top of —
       intercepting taps meant for the sidebar nav underneath it. Hide it
       there; Logout is already in the sidebar itself, and Profile is
       reachable via the "More" nav section. */
    @media (max-width: 768px) {
        div[class*="st-key-header_actions"] { display: none !important; }
    }
    </style>
""", unsafe_allow_html=True)

st.logo("./assets/images/logo_razetally_light22.png", size="large")
_components.html("""

""", height=0)

with st.sidebar:
    st.caption(f"**{st.session_state.username}** · {role}")
    if role == "admin":
        st.caption("📍 All polling stations")
    else:
        stations = get_user_polling_stations(st.session_state.username)
        if stations:
            def _esc(text):
                return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            items = "".join(
                f"<li>{_esc(s['polling_station_name'])} ({_esc(s['polling_station_code'])})</li>"
                for s in stations
            )
            st.markdown(
                "<div style='font-size:0.8rem;line-height:1.5;'>📍 Assigned polling stations:"
                "<ul style='margin:4px 0 0 1.1rem;padding:0 4px 0 0;max-height:160px;"
                "overflow-y:auto;'>"
                f"{items}</ul></div>",
                unsafe_allow_html=True,
            )
        else:
            st.caption("📍 No polling station assigned")
    if st.button("Logout", use_container_width=True):
        _logout_dialog()

# ── Navigation (role-based) ───────────────────────────────────────────────────
rest_pages = []

#if role in ("admin", "uploader"):
    #rest_pages.append(st.Page("pages/upload.py", title="Upload Form",))
    #rest_pages.append(st.Page("pages/manualCapture.py", title="Manual Capture", ))

if role == "admin":
    rest_pages.append(st.Page("pages/admin/parties.py", title="Parties", icon="🏳️"))
    rest_pages.append(st.Page("pages/admin/candidates.py", title="Candidates", icon="🧑‍💼"))
    rest_pages.append(st.Page("pages/admin/positions.py", title="Positions", icon="🧩"))
rest_pages.append(st.Page("pages/profile.py", title="My Profile", icon="🙍"))
pages = {"": [st.Page("pages/dashboard.py", title="Dashboard", icon="📊")]}

if role == "admin":
    pages["🗺️ Demography"] = [
        st.Page("pages/demography/counties.py",        title="  Counties", icon="🏛️"),
        st.Page("pages/demography/constituencies.py",  title="  Constituencies", icon="🏢"),
        st.Page("pages/demography/wards.py",           title="  Wards", icon="🏘️"),
        st.Page("pages/demography/pollingStations.py", title="  Polling Stations", icon="📍"),
    ]
    
    pages["🧑‍💼 Recruitment"] = [
        st.Page("pages/recruitment/job_descriptions.py",  title="Job Descriptions", icon="📝"),
        st.Page("pages/recruitment/applications.py",        title="Applications", icon="📄"),
        st.Page("pages/recruitment/panelists.py", title="Interview Panelists", icon="👨‍⚖️"),
        st.Page("pages/recruitment/interview_questions.py", title="Interview Questions", icon="❓"),
    ]
    
    pages["🧑‍🤝‍🧑 Membership & Funding"] = [
        st.Page("pages/membership/party_members.py",  title="Party Members", icon="🧑‍🤝‍🧑"),
        st.Page("pages/membership/funds.py",        title="Event Funding", icon="💰"),
        # st.Page("pages/membership/panelists.py", title="Interview Panelists", icon="👨‍⚖️"),
        # st.Page("pages/membership/interview_questions.py", title="Interview Questions", icon="❓"),
    ]

    pages["🎯 Event / Rally Mgt"] = [
         st.Page("pages/campaigns/campaign_team.py",title="Event Team", icon="🧑‍🤝‍🧑"),
         st.Page( "pages/campaigns/campaign_materials.py", title="Event  Materials", icon="📦"),
         st.Page("pages/campaigns/campaign_rallies.py", title="Events / Rallies", icon="🛣️"),
         st.Page("pages/campaigns/opinion_polls.py", title="Opinion Polls", icon="📊"),
         #st.Page("pages/campaigns/feeds.py", title="Feeds", icon="📰"),
    ]

    pages["🗳️ Election Mgt"] = [
    st.Page("pages/elections/elections_team.py", title="Election Team", icon="🧑‍💼"),
    st.Page("pages/elections/election_materials.py", title="Election Materials", icon="📦"),
    ]

pages.setdefault("🎯 Event / Rally Mgt", []).append(
    st.Page(
        "pages/campaigns/feeds.py",
        title="Feeds",
        icon="📰",
    )
)

pages[" 🗣️ Collaboration"] = [
    st.Page("pages/collaboration/events_calendar.py", title="Events Calendar", icon="📅"),
    st.Page("pages/collaboration/tasks_management.py", title="Activities & Tasks", icon="✅"),
    st.Page("pages/collaboration/chats.py",title="Chats", icon="💬"),
    st.Page("pages/collaboration/calls.py", title="Calls", icon="📞"),   
]

if role in ("admin", "uploader"):
    pages.setdefault("🗳️ Election Mgt", []).append( st.Page( "pages/elections/upload.py", title="Upload Form", icon="⬆️" ) )

if role == "admin":
    pages.setdefault("🗳️ Election Mgt", []).append( st.Page( "pages/elections/batch_upload.py", title="Batch Upload", icon="📤" ) )

if role == "admin" or is_panelist(st.session_state.username):
    pages.setdefault("🧑‍💼 Recruitment", []).append(st.Page("pages/recruitment/panel_interviews.py", title="My Interview Panel", icon="🗂️"))

pages["📁 More"] = rest_pages

_components.html(
    r"""
    <script>
    (function () {
        function getHeaders() {
            return Array.from(
                window.parent.document.querySelectorAll('header[data-testid="stNavSectionHeader"]')
            );
        }

        // Collect the <li> items that belong to a given section header
        // (they are siblings following the header, up to the next header).
        function itemsFor(header) {
            var items = [];
            var el = header.nextElementSibling;
            while (el && el.tagName !== 'HEADER') {
                if (el.tagName === 'LI') items.push(el);
                el = el.nextElementSibling;
            }
            return items;
        }

        function isOpen(header) {
            // Prefer an explicit aria-expanded attribute if the component sets one.
            var ariaExpanded = header.getAttribute('aria-expanded');
            if (ariaExpanded !== null) return ariaExpanded === 'true';

            var items = itemsFor(header);
            if (!items.length) return false;
            var el = items[0];
            return el.offsetParent !== null &&
                   window.getComputedStyle(el).display !== 'none';
        }

        // Try several signals to figure out if a nav link is the active/current page.
        function isActiveLink(link) {
            if (link.getAttribute('aria-selected') === 'true') return true;
            if (link.getAttribute('aria-current') === 'page') return true;
            var cls = (link.className || '').toString().toLowerCase();
            if (cls.indexOf('selected') !== -1 || cls.indexOf('active') !== -1) return true;
            try {
                var href = link.getAttribute('href') || '';
                var currentPath = window.parent.location.pathname;
                if (href && currentPath && currentPath.indexOf(href.replace(/^\//, '')) !== -1) {
                    return true;
                }
            } catch (e) { /* cross-origin or not ready yet — ignore */ }
            return false;
        }

        // Guard so our own programmatic clicks (used to force collapse/expand)
        // don't re-trigger the accordion listener and cause a cascade.
        var suppressAccordion = false;

        function collapse(header) {
            if (isOpen(header)) {
                suppressAccordion = true;
                header.click();
                suppressAccordion = false;
            }
        }

        function expand(header) {
            if (!isOpen(header)) {
                suppressAccordion = true;
                header.click();
                suppressAccordion = false;
            }
        }

        var didInitialOpen = false;
        var initialAttempts = 0;

        function tryInitialOpen(headers) {
            if (didInitialOpen) return;

            var activeHeader = null;
            headers.forEach(function (h) {
                var hasActive = itemsFor(h).some(function (li) {
                    var link = li.querySelector('[data-testid="stSidebarNavLink"]');
                    return link && isActiveLink(link);
                });
                if (hasActive) activeHeader = h;
            });

            initialAttempts++;
            if (activeHeader) {
                headers.forEach(function (h) {
                    if (h === activeHeader) expand(h);
                    else collapse(h);
                });
                didInitialOpen = true;
            } else if (initialAttempts > 60) {
                // Give up after ~9s (e.g. active page is Dashboard, which has no section).
                didInitialOpen = true;
            }
        }

        // Dashboard is a standalone top-level page with no section header of its
        // own, so it needs its own click listener to collapse every section.
        function getDashboardLink() {
            var byHref = window.parent.document.querySelector(
                '[data-testid="stSidebarNavLink"][href*="dashboard" i]'
            );
            if (byHref) return byHref;
            var nav = window.parent.document.querySelector('[data-testid="stSidebarNav"]');
            if (!nav) return null;
            var firstLi = nav.querySelector('li:first-child');
            return firstLi ? firstLi.querySelector('[data-testid="stSidebarNavLink"]') : null;
        }

        function init() {
            var headers = getHeaders();
            if (!headers.length) return;

            tryInitialOpen(headers);

            // Bind accordion behavior once per header: opening one collapses the rest.
            headers.forEach(function (h) {
                if (h.__accordionBound) return;
                h.__accordionBound = true;
                h.addEventListener('click', function () {
                    if (suppressAccordion) return;
                    setTimeout(function () {
                        getHeaders().forEach(function (other) {
                            if (other !== h) collapse(other);
                        });
                    }, 60);
                });
            });

            // Bind Dashboard click: collapse every section header.
            var dashLink = getDashboardLink();
            if (dashLink && !dashLink.__collapseBound) {
                dashLink.__collapseBound = true;
                dashLink.addEventListener('click', function () {
                    setTimeout(function () {
                        getHeaders().forEach(function (h) { collapse(h); });
                    }, 60);
                });
            }
        }

        var observer = new MutationObserver(init);
        observer.observe(window.parent.document.body, { childList: true, subtree: true });
        init();

        // Also retry on a short interval for the first couple seconds, in case
        // the active-page marker is applied slightly after the nav DOM appears.
        var pollCount = 0;
        var poll = setInterval(function () {
            init();
            pollCount++;
            if (pollCount > 60 || didInitialOpen) clearInterval(poll);
        }, 150);
    })();
    </script>
    """,
    height=0,
)

pg = st.navigation(pages)
pg.run()

# Runs after page content so `_on_calls_page` reflects whether pg.run() just
# rendered the Calls page (which sets that flag itself).
_incoming_call_watcher()