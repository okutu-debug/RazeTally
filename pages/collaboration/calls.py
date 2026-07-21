import html
import json
import time

import streamlit as st
import streamlit.components.v1 as components

from db import (
    accept_call,
    add_ice_candidate,
    create_call,
    decline_call,
    end_call,
    get_active_call_for_user,
    get_incoming_call,
    list_ice_candidates,
    list_online_usernames,
    list_users,
    mark_call_missed,
)
from theme import apply_theme

apply_theme()

st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Calls</h4><hr>",
    unsafe_allow_html=True,
)

me = st.session_state.username

# Tells the app-wide incoming-call watcher (viz_app.py) that this page already
# handles ringing calls inline, so it should skip popping up its own dialog.
st.session_state["_on_calls_page"] = True

# ── Call-negotiation session state ──────────────────────────────────────────
# `active_call_id` is None until a DB row exists for the current call attempt
# (a caller has a brief "dialing" moment, generating a WebRTC offer in the
# browser, before that row is created — see the bridge-message handling below).
for key, default in [
    ("active_call_id", None),
    ("call_role", None),          # "caller" | "callee"
    ("call_other", None),         # the other party's username
    ("pending_outgoing", False),  # True while dialing, before the DB row exists
    ("dial_started_at", None),
    ("last_call_status", None),
    ("active_chat_user", None),   # reused as the selected person in the list
    ("pending_call_accept_id", None),  # set by the app-wide popup's Accept button
]:
    if key not in st.session_state:
        st.session_state[key] = default

RING_TIMEOUT_SECONDS = 30


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
    st.session_state.active_chat_user = username


def _reset_call_state():
    st.session_state.active_call_id = None
    st.session_state.call_role = None
    st.session_state.call_other = None
    st.session_state.pending_outgoing = False
    st.session_state.dial_started_at = None
    st.session_state.call_awaiting_answer = False


def _start_outgoing_call(other_username: str):
    _reset_call_state()
    st.session_state.call_role = "caller"
    st.session_state.call_other = other_username
    st.session_state.pending_outgoing = True
    st.session_state.dial_started_at = time.time()


online_usernames = list_online_usernames()
all_users = [u for u in list_users() if u["username"] != me and u["username"] in online_usernames]
all_users = sorted(all_users, key=_display_name)
by_username = {u["username"]: u for u in all_users}

if st.session_state.active_chat_user is None and all_users:
    st.session_state.active_chat_user = all_users[0]["username"]


# ── Bridge helper: pushes browser-generated SDP/ICE data into a hidden
# text_input so it lands in st.session_state on the next rerun. Plain
# components.html() has no return channel back to Python, so this uses the
# same "reach into window.parent.document" approach as the scroll-to-bottom
# trick in chats.py — it programmatically sets a native input's value and
# fires the events Streamlit listens for, then blurs it to commit the value. ──

def _webrtc_bridge_widget():
    with st.container(key="webrtc_bridge_wrap"):
        st.text_input("webrtc_bridge", key="webrtc_bridge", label_visibility="collapsed")
    st.html(
        """
        <style>
        div[class*="st-key-webrtc_bridge_wrap"] {
            position: absolute; width: 1px; height: 1px;
            overflow: hidden; opacity: 0; pointer-events: none;
        }
        </style>
        """
    )


def _process_bridge_message():
    """Consume whatever the browser last wrote into the hidden bridge input."""
    raw = st.session_state.get("webrtc_bridge", "")
    if not raw:
        return
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return

    role = msg.get("role")
    other = msg.get("other")
    if role != st.session_state.call_role or other != st.session_state.call_other:
        return  # stale message from a call we've already moved on from

    if msg.get("error"):
        st.session_state["_call_js_error"] = msg["error"]
        return

    # Caller: first time we see a generated offer, create the DB row.
    if role == "caller" and msg.get("offer") and st.session_state.active_call_id is None:
        call_id = create_call(me, other, msg["offer"])
        st.session_state.active_call_id = call_id
        st.session_state.pending_outgoing = False

    call_id = st.session_state.active_call_id
    if call_id is None:
        return

    # Callee: first time we see a generated answer, accept the call.
    if role == "callee" and msg.get("answer"):
        accept_call(call_id, msg["answer"])

    # Local ICE candidates trickle in — the bridge always carries the full
    # cumulative list, so only the new tail needs to be written.
    candidates = msg.get("candidates") or []
    sent_key = f"ice_sent_count_{call_id}"
    already_sent = st.session_state.get(sent_key, 0)
    for candidate_json in candidates[already_sent:]:
        add_ice_candidate(call_id, me, candidate_json)
    st.session_state[sent_key] = len(candidates)


def _webrtc_signaling_component(status: str, offer_sdp: str | None, answer_sdp: str | None):
    """Renders the invisible component that drives the actual WebRTC
    connection in the browser: gathers mic audio, negotiates the
    offer/answer, exchanges ICE candidates, and plays the remote audio."""
    call_id = st.session_state.active_call_id
    role = st.session_state.call_role
    other = st.session_state.call_other

    remote_candidates: list[str] = []
    if call_id is not None:
        recv_key = f"ice_recv_last_{call_id}"
        since_id = st.session_state.get(recv_key, 0)
        rows = list_ice_candidates(call_id, exclude_username=me, since_id=since_id)
        if rows:
            remote_candidates = [r["candidate"] for r in rows]
            st.session_state[recv_key] = rows[-1]["id"]

    payload = {
        "call_id": call_id,
        "role": role,
        "other": other,
        "status": status,
        "offer_sdp": offer_sdp,
        "answer_sdp": answer_sdp,
        "remote_candidates": remote_candidates,
    }

    components.html(
        f"""
        <script>
        (function () {{
            const data = {json.dumps(payload)};
            const w = window.parent;

            function setNativeValue(el, value) {{
                const proto = Object.getPrototypeOf(el);
                const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                desc.set.call(el, value);
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}

            function sendBridge(payload, attempt) {{
                attempt = attempt || 0;
                const wrap = w.document.querySelector('div[class*="st-key-webrtc_bridge_wrap"]');
                const input = wrap ? wrap.querySelector('input') : null;
                if (!input) {{
                    // The hidden bridge widget can be briefly absent from the DOM
                    // right as the fragment repaints (it's rebuilt on every 2s
                    // tick) — retry instead of silently dropping the message.
                    if (attempt < 50) {{
                        setTimeout(() => sendBridge(payload, attempt + 1), 100);
                    }} else {{
                        console.error('webrtc bridge input never became available');
                    }}
                    return;
                }}
                setNativeValue(input, JSON.stringify(payload));
                input.blur();
            }}

            function flush() {{
                if (!w.__callState) return;
                sendBridge({{
                    role: data.role,
                    other: data.other,
                    call_id: w.__callState.call_id || data.call_id || null,
                    offer: w.__callState.offer || null,
                    answer: w.__callState.answer || null,
                    candidates: w.__callState.localCandidates,
                }});
            }}

            function teardown() {{
                try {{ w.__callPC && w.__callPC.close(); }} catch (e) {{}}
                try {{ w.__callStream && w.__callStream.getTracks().forEach(t => t.stop()); }} catch (e) {{}}
                const audioEl = w.document.getElementById('call-remote-audio');
                if (audioEl) audioEl.remove();
                w.__callState = null;
                w.__callPC = null;
                w.__callStream = null;
            }}

            const switchingToDifferentCall = (
                w.__callState && data.call_id && w.__callState.call_id &&
                data.call_id !== w.__callState.call_id
            );
            const callOver = ['ended', 'declined', 'missed', 'idle'].includes(data.status);
            if (w.__callState && (switchingToDifferentCall || callOver)) {{
                teardown();
            }}
            if (callOver || !data.role) return;

            async function ensure() {{
                if (w.__callState && w.__callState.active) return;
                w.__callState = {{
                    call_id: data.call_id, active: true, remoteSet: false,
                    localCandidates: [], offer: null, answer: null,
                }};

                try {{
                    const pc = new RTCPeerConnection({{
                        iceServers: [{{ urls: 'stun:stun.l.google.com:19302' }}],
                    }});
                    w.__callPC = pc;

                    const stream = await navigator.mediaDevices.getUserMedia({{ audio: true }});
                    w.__callStream = stream;
                    stream.getTracks().forEach(t => pc.addTrack(t, stream));

                    pc.ontrack = (ev) => {{
                        let audioEl = w.document.getElementById('call-remote-audio');
                        if (!audioEl) {{
                            audioEl = w.document.createElement('audio');
                            audioEl.id = 'call-remote-audio';
                            audioEl.autoplay = true;
                            w.document.body.appendChild(audioEl);
                        }}
                        audioEl.srcObject = ev.streams[0];
                    }};

                    pc.onicecandidate = (ev) => {{
                        if (ev.candidate) {{
                            w.__callState.localCandidates.push(JSON.stringify(ev.candidate));
                            flush();
                        }}
                    }};

                    if (data.role === 'caller') {{
                        const offer = await pc.createOffer();
                        await pc.setLocalDescription(offer);
                        w.__callState.offer = JSON.stringify(offer);
                        flush();
                    }} else {{
                        await pc.setRemoteDescription(new RTCSessionDescription(JSON.parse(data.offer_sdp)));
                        w.__callState.remoteSet = true;
                        const answer = await pc.createAnswer();
                        await pc.setLocalDescription(answer);
                        w.__callState.answer = JSON.stringify(answer);
                        flush();
                    }}
                }} catch (e) {{
                    // Surface the failure back to Python (mic denied, no device,
                    // RTCPeerConnection error, etc.) instead of hanging silently
                    // on "Calling…" forever — see _process_bridge_message's
                    // "error" handling on the Python side.
                    console.error('Call setup failed:', e);
                    if (w.__callState) w.__callState.active = false;
                    sendBridge({{
                        role: data.role,
                        other: data.other,
                        call_id: data.call_id,
                        error: (e && e.message) ? e.message : String(e),
                    }});
                }}
            }}

            ensure().then(async () => {{
                if (!w.__callState) return;
                if (data.call_id) w.__callState.call_id = data.call_id;
                const pc = w.__callPC;
                if (!pc) return;

                if (data.role === 'caller' && data.answer_sdp && !w.__callState.remoteSet) {{
                    await pc.setRemoteDescription(new RTCSessionDescription(JSON.parse(data.answer_sdp)));
                    w.__callState.remoteSet = true;
                }}

                if (w.__callState.remoteSet && data.remote_candidates && data.remote_candidates.length) {{
                    for (const c of data.remote_candidates) {{
                        try {{ await pc.addIceCandidate(new RTCIceCandidate(JSON.parse(c))); }}
                        catch (e) {{ console.error('addIceCandidate failed:', e); }}
                    }}
                }}
            }});
        }})();
        </script>
        """,
        height=0,
    )


col_list, col_thread = st.columns([1, 2], gap="medium")

# ── User list ────────────────────────────────────────────────────────────────
with col_list:
    with st.container(key="card_chat_users"):
        st.text_input(
            "Search",
            placeholder="🔍 Search people",
            label_visibility="collapsed",
            key="chat_search",
        )

        st.html(
            """
            <style>
            div[class*="st-key-user_"] button {
                width: 100%;
                text-align: left;
                background: transparent;
                border: none;
                border-radius: 8px;
                padding: 10px 12px;
                color: #1f2937;
                font-weight: 500;
                justify-content: flex-start;
            }
            div[class*="st-key-user_"] button:hover {
                background: #f1f5f9;
                color: #1f2937;
            }
            div[class*="st-key-user_active"] button {
                background: #eff6ff !important;
                color: #1d4ed8 !important;
            }
            </style>
            """
        )

        search_term = st.session_state.get("chat_search", "").strip().lower()
        filtered = (
            [u for u in all_users if search_term in _display_name(u).lower()]
            if search_term
            else all_users
        )
        filtered = sorted(filtered, key=_display_name)

        if not all_users:
            st.caption("No one else is online right now.")
        elif not filtered:
            st.caption("No people match your search.")
        else:
            for u in filtered:
                is_active = u["username"] == st.session_state.active_chat_user
                name = _display_name(u)
                label = f"{_initials(name)}  {name}"
                key_prefix = "user_active" if is_active else f"user_{u['username']}"
                st.button(
                    label,
                    key=f"{key_prefix}_{u['username']}",
                    use_container_width=True,
                    on_click=_select_user,
                    args=(u["username"],),
                )


@st.fragment(run_every="2s")
def _render_call_panel():
    _process_bridge_message()

    js_error = st.session_state.pop("_call_js_error", None)
    if js_error:
        st.toast(f"Call failed: {js_error}")
        if st.session_state.active_call_id:
            end_call(st.session_state.active_call_id)
        _reset_call_state()

    # Detect a fresh incoming call, unless already busy with one.
    if st.session_state.active_call_id is None and not st.session_state.pending_outgoing:
        incoming = get_incoming_call(me)
        if incoming:
            st.session_state.active_call_id = incoming["id"]
            st.session_state.call_role = "callee"
            st.session_state.call_other = incoming["caller_username"]

    # If the user hit "Accept" on the app-wide incoming-call popup (which
    # navigated them here rather than negotiating WebRTC itself), treat that
    # as if they'd just clicked the in-page Accept button for this same call.
    if (
        st.session_state.active_call_id is not None
        and st.session_state.call_role == "callee"
        and st.session_state.pending_call_accept_id == st.session_state.active_call_id
    ):
        st.session_state.call_awaiting_answer = True
        st.session_state.pending_call_accept_id = None

    call = None
    if st.session_state.active_call_id is not None:
        call = get_active_call_for_user(me)
        if call is None or call["id"] != st.session_state.active_call_id:
            call = None  # the call we knew about is no longer active

    status = "idle"
    offer_sdp = answer_sdp = None
    if st.session_state.pending_outgoing and st.session_state.active_call_id is None:
        status = "dialing"
        if (
            st.session_state.dial_started_at
            and time.time() - st.session_state.dial_started_at > RING_TIMEOUT_SECONDS
        ):
            st.toast("No answer.")
            _reset_call_state()
            status = "idle"
    elif call is not None:
        status = call["status"]
        offer_sdp = call.get("offer_sdp")
        answer_sdp = call.get("answer_sdp")
        if status == "accepted":
            st.session_state.call_awaiting_answer = False
        if status in ("declined", "ended", "missed"):
            if st.session_state.last_call_status != status:
                st.toast({"declined": "Call declined.", "ended": "Call ended.", "missed": "Call missed."}[status])
            _reset_call_state()
            status = "idle"
        elif (
            status == "ringing"
            and st.session_state.call_role == "caller"
            and time.time() - call["created_at"].timestamp() > RING_TIMEOUT_SECONDS
        ):
            mark_call_missed(call["id"])
            st.toast("No answer.")
            _reset_call_state()
            status = "idle"
    st.session_state.last_call_status = status

    other_user = by_username.get(st.session_state.call_other) if st.session_state.call_other else None
    other_name = _display_name(other_user) if other_user else (st.session_state.call_other or "")

    with st.container(key="card_chat_thread"):
        if status == "idle":
            active_username = st.session_state.active_chat_user
            active_user = next((u for u in all_users if u["username"] == active_username), None)
            if active_user is None:
                st.markdown(
                    "<div style='display:flex; align-items:center; justify-content:center; "
                    "height:400px; color:#9ca3af; font-size:15px;'>"
                    "Select a person to start a call</div>",
                    unsafe_allow_html=True,
                )
            else:
                name = _display_name(active_user)
                subtitle = active_user.get("position") or active_user.get("role", "")
                st.markdown(
                    f"<div style='display:flex; flex-direction:column; align-items:center; "
                    f"justify-content:center; gap:14px; height:360px;'>"
                    f"<div style='width:72px; height:72px; border-radius:50%; background:#cbd5e1; "
                    f"color:#1f2937; display:flex; align-items:center; justify-content:center; "
                    f"font-weight:600; font-size:22px;'>{html.escape(_initials(name))}</div>"
                    f"<div style='text-align:center;'>"
                    f"<div style='font-weight:600; font-size:18px; color:#1f2937;'>{html.escape(name)}</div>"
                    f"<div style='font-size:13px; color:#9ca3af;'>{html.escape(subtitle)}</div>"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )
                if st.button("📞  Call", key="start_call_btn", use_container_width=True):
                    _start_outgoing_call(active_username)
                    st.rerun(scope="fragment")

        elif status == "dialing" or (status == "ringing" and st.session_state.call_role == "caller"):
            st.markdown(
                f"<div style='display:flex; flex-direction:column; align-items:center; "
                f"justify-content:center; gap:14px; height:360px;'>"
                f"<div style='width:72px; height:72px; border-radius:50%; background:#cbd5e1; "
                f"color:#1f2937; display:flex; align-items:center; justify-content:center; "
                f"font-weight:600; font-size:22px;'>{html.escape(_initials(other_name))}</div>"
                f"<div style='font-weight:600; font-size:18px; color:#1f2937;'>{html.escape(other_name)}</div>"
                f"<div style='color:#6b7280; font-size:14px;'>Calling…</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button("Cancel", key="cancel_call_btn", use_container_width=True):
                if st.session_state.active_call_id:
                    end_call(st.session_state.active_call_id)
                _reset_call_state()
                st.rerun(scope="fragment")

        elif (
            status == "ringing"
            and st.session_state.call_role == "callee"
            and st.session_state.get("call_awaiting_answer")
        ):
            st.markdown(
                f"<div style='display:flex; flex-direction:column; align-items:center; "
                f"justify-content:center; gap:14px; height:300px;'>"
                f"<div style='width:72px; height:72px; border-radius:50%; background:#cbd5e1; "
                f"color:#1f2937; display:flex; align-items:center; justify-content:center; "
                f"font-weight:600; font-size:22px;'>{html.escape(_initials(other_name))}</div>"
                f"<div style='font-weight:600; font-size:18px; color:#1f2937;'>{html.escape(other_name)}</div>"
                f"<div style='color:#6b7280; font-size:14px;'>Connecting…</div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        elif status == "ringing" and st.session_state.call_role == "callee":
            st.markdown(
                f"<div style='display:flex; flex-direction:column; align-items:center; "
                f"justify-content:center; gap:14px; height:300px;'>"
                f"<div style='width:72px; height:72px; border-radius:50%; background:#cbd5e1; "
                f"color:#1f2937; display:flex; align-items:center; justify-content:center; "
                f"font-weight:600; font-size:22px;'>{html.escape(_initials(other_name))}</div>"
                f"<div style='font-weight:600; font-size:18px; color:#1f2937;'>{html.escape(other_name)}</div>"
                f"<div style='color:#6b7280; font-size:14px;'>Incoming call…</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            bcol1, bcol2 = st.columns(2)
            if bcol1.button("✅ Accept", key="accept_call_btn", use_container_width=True):
                # The signaling component below generates the answer on the
                # next render (it needs offer_sdp, already available here);
                # nothing to do here except let status stay "ringing" until
                # the browser's generated answer flows back through the bridge.
                st.session_state.call_awaiting_answer = True
                st.rerun(scope="fragment")
            if bcol2.button("❌ Decline", key="decline_call_btn", use_container_width=True):
                decline_call(st.session_state.active_call_id)
                _reset_call_state()
                st.rerun(scope="fragment")

        elif status == "accepted":
            st.markdown(
                f"<div style='display:flex; flex-direction:column; align-items:center; "
                f"justify-content:center; gap:14px; height:360px;'>"
                f"<div style='width:72px; height:72px; border-radius:50%; background:#dcfce7; "
                f"color:#166534; display:flex; align-items:center; justify-content:center; "
                f"font-weight:600; font-size:22px;'>{html.escape(_initials(other_name))}</div>"
                f"<div style='font-weight:600; font-size:18px; color:#1f2937;'>{html.escape(other_name)}</div>"
                f"<div style='color:#16a34a; font-size:14px;'>🎙️ On call</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button("🔴  Hang up", key="hang_up_btn", use_container_width=True):
                end_call(st.session_state.active_call_id)
                _reset_call_state()
                st.rerun(scope="fragment")

    # The callee only starts generating an answer once they've hit Accept —
    # gate the WebRTC component so the browser doesn't start negotiating
    # (and asking for mic permission) before the user has actually accepted.
    should_run_webrtc = status == "accepted" or (
        status == "dialing" or (status == "ringing" and st.session_state.call_role == "caller")
    ) or (
        status == "ringing"
        and st.session_state.call_role == "callee"
        and st.session_state.get("call_awaiting_answer")
    )
    if should_run_webrtc:
        _webrtc_signaling_component(status, offer_sdp, answer_sdp)

    _webrtc_bridge_widget()


with col_thread:
    _render_call_panel()