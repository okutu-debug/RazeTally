import base64
import hashlib
import html
import mimetypes
from datetime import datetime

import streamlit as st

from db import (
    add_feed_post_comment,
    add_feed_post_image,
    create_feed_post,
    delete_feed_post,
    delete_feed_post_comment,
    get_feed_post_image_bytes,
    list_feed_post_comments,
    list_feed_posts,
    save_feed_post_image_file,
    toggle_feed_post_like,
    update_feed_post,
    update_feed_post_comment,
)
from theme import apply_theme

apply_theme()

me = st.session_state.username

# ====================== DESIGN TOKENS ======================
# Grounded in the subject: an election-monitoring org's internal feed.
# Palette reads as "field ledger" — ink navy for authority, a ballot-green
# accent for verified/confirmed activity, warm amber reserved for anything
# that needs attention. A vertical rail turns the feed into an audit trail,
# not just a social wall.
INK = "#122540"
INK_SOFT = "#48607e"
PAPER = "#f6f5f1"
LINE = "#e4e1d8"
VERIFIED = "#0f7a5c"
VERIFIED_SOFT = "#e6f3ee"
AMBER = "#c17d1f"
AMBER_SOFT = "#faf1e0"

# Avatar background colors, cycled deterministically per-person so the same
# author always gets the same color across posts and comments.
AVATAR_PALETTE = ["0f7a5c", "122540", "c17d1f", "8a3b7c", "1f6fc1", "b23b3b", "2f7a7a", "6b5b1f"]

# ====================== CUSTOM CSS ======================
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Inter', sans-serif;
    }}

    .main .block-container {{
        padding-top: 2.25rem;
        max-width: 880px;
    }}

    /* ---- Page header ---- */
    .feed-eyebrow {{
        font-family: 'Space Grotesk', sans-serif;
        font-size: 0.72rem;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: {VERIFIED};
        font-weight: 600;
        margin-bottom: 0.35rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }}
    .feed-eyebrow .dot {{
        width: 7px; height: 7px; border-radius: 50%;
        background: {VERIFIED};
        box-shadow: 0 0 0 4px {VERIFIED_SOFT};
    }}
    .feed-title {{
        font-family: 'Space Grotesk', sans-serif;
        font-size: 2.1rem;
        font-weight: 700;
        color: {INK};
        margin: 0 0 0.2rem 0;
        letter-spacing: -0.02em;
    }}
    .feed-sub {{
        color: {INK_SOFT};
        font-size: 0.95rem;
        margin-bottom: 1.6rem;
    }}

    /* ---- Cards ---- */
    div[class*="st-key-create_post_card"] {{
        background-color: #ffffff !important;
        border-radius: 14px !important;
        padding: 1.85rem !important;
        border: 1px solid {LINE} !important;
        border-top: 3px solid {INK} !important;
        box-shadow: 0 1px 2px rgba(18,37,64,0.04);
        margin-bottom: 2.1rem;
    }}
    div[class*="st-key-post_card_"] {{
        background-color: #ffffff !important;
        border-radius: 14px !important;
        padding: 1.6rem 1.75rem !important;
        border: 1px solid {LINE} !important;
        box-shadow: 0 1px 2px rgba(18,37,64,0.04);
        margin-bottom: 1.4rem;
        transition: box-shadow 0.15s ease, border-color 0.15s ease;
    }}
    div[class*="st-key-post_card_"]:hover {{
        border-color: {VERIFIED} !important;
        box-shadow: 0 3px 12px rgba(18,37,64,0.08);
    }}

    .post-author {{
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 600;
        color: {INK};
        font-size: 1rem;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }}
    .verified-badge {{
        display: inline-flex;
        align-items: center;
        gap: 0.25rem;
        background: {VERIFIED_SOFT};
        color: {VERIFIED};
        font-size: 0.68rem;
        font-weight: 600;
        padding: 0.12rem 0.5rem;
        border-radius: 20px;
        letter-spacing: 0.02em;
    }}
    .post-meta {{
        color: {INK_SOFT};
        font-size: 0.8rem;
        margin-top: 0.05rem;
    }}
    .post-body {{
        color: #26364f;
        font-size: 0.98rem;
        line-height: 1.55;
        margin: 0.9rem 0 0.2rem 0;
    }}

    /* Avatars */
    div[class*="st-key-post_avatar_"] img {{
        border-radius: 50%;
        border: 2px solid {LINE};
    }}

    /* Section headers */
    .section-label {{
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 600;
        color: {INK};
        font-size: 1.05rem;
        margin: 0.2rem 0 1rem 0;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }}
    .section-count {{
        font-size: 0.78rem;
        color: {INK_SOFT};
        font-weight: 500;
    }}

    /* ---- Buttons ---- */
    .stButton>button {{
        border-radius: 9px;
        border: 1px solid {LINE};
        color: {INK};
        font-weight: 500;
        font-size: 0.85rem;
        background: {PAPER};
        transition: all 0.15s ease;
    }}
    .stButton>button:hover {{
        border-color: {VERIFIED};
        color: {VERIFIED};
        background: {VERIFIED_SOFT};
    }}
    .stFormSubmitButton>button {{
        border-radius: 9px;
        background: {INK} !important;
        border: none !important;
        font-weight: 600;
        letter-spacing: 0.01em;
    }}
    .stFormSubmitButton>button:hover {{
        background: {VERIFIED} !important;
    }}

    /* Text area */
    .stTextArea textarea {{
        border-radius: 10px;
        border: 1px solid {LINE};
        background: {PAPER};
        font-size: 0.95rem;
    }}
    .stTextArea textarea:focus {{
        border-color: {VERIFIED};
        box-shadow: 0 0 0 1px {VERIFIED};
    }}

    /* File uploader */
    [data-testid="stFileUploaderDropzone"] {{
        border-radius: 10px;
        border: 1.5px dashed {LINE};
        background: {PAPER};
    }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background: #ffffff;
        border-right: 1px solid {LINE};
    }}
    .sidebar-title {{
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 600;
        color: {INK};
        font-size: 1rem;
        margin-bottom: 0.3rem;
    }}
    .sidebar-caption {{
        color: {INK_SOFT};
        font-size: 0.8rem;
        margin-bottom: 1.1rem;
    }}

    /* Divider tone-down */
    hr {{ border-color: {LINE} !important; }}
</style>
""", unsafe_allow_html=True)


# ====================== HELPERS ======================
def time_ago(dt: datetime) -> str:
    """Render a relative timestamp, e.g. '2h ago', falling back to a formatted date."""
    if dt is None:
        return ""
    now = datetime.now()
    delta = now - dt
    seconds = delta.total_seconds()
    if seconds < 0:
        return dt.strftime("%d %b, %I:%M %p")
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 172800:
        return "Yesterday"
    return dt.strftime("%d %b, %I:%M %p")


def display_name(post: dict) -> str:
    name = f"{post.get('other_names') or ''} {post.get('surname') or ''}".strip()
    return name or post["author_username"]


def avatar_color(username: str) -> str:
    """Deterministic avatar background color for a username, stable across reruns."""
    digest = hashlib.md5(username.encode()).hexdigest()
    return AVATAR_PALETTE[int(digest, 16) % len(AVATAR_PALETTE)]


# ====================== HEADER ======================
st.markdown(
    "<h4 style='font-size:2.5rem !important; margin:0;'>Feeds</h4>",
    unsafe_allow_html=True,
)
st.caption(
    "Share updates, announcements, and keep your organization informed in real-time."
)

# ====================== CREATE POST ======================

with st.container(border=True, key="create_post_card"):
    col_a, col_b = st.columns([3, 11], vertical_alignment="center")
    with col_a:
        #st.image(f"https://ui-avatars.com/api/?name={me}&background=122540&color=fff&size=48", width=48)
        st.markdown("**Create a post**")

    with col_b:
        st.caption("Visible to everyone in your organization")

    with st.form("new_post", clear_on_submit=True):
        message = st.text_area(
            "Message",
            height=130,
            placeholder="Share an update, announcement, or ask for feedback...",
            label_visibility="collapsed"
        )

        uploaded_images = st.file_uploader(
            "Attach images",
            type=["jpg", "jpeg", "png"],
            accept_multiple_files=True
        )

        submitted = st.form_submit_button("Post update", use_container_width=True, type="primary")
        if submitted:
            if message.strip():
                post_id = create_feed_post(me, message.strip())
                for f in uploaded_images or []:
                    stored_name = save_feed_post_image_file(post_id, f.name, f.getvalue())
                    add_feed_post_image(post_id, stored_name, f.name)
                st.success("Post published to the organization feed.")
                st.rerun()
            else:
                st.warning("Write something before posting.")

# ====================== RECENT POSTS ======================
posts = list_feed_posts(viewer_username=me)

st.markdown(
    f'<div class="section-label">Recent activity '
    f'<span class="section-count">{len(posts)} updates</span></div>',
    unsafe_allow_html=True
)

for i, post in enumerate(posts):
    author = display_name(post)
    badge = post.get("position") or "Member"
    is_own_post = post["author_username"] == me
    editing_post_key = f"editing_post_{post['id']}"
    confirm_delete_post_key = f"confirm_delete_post_{post['id']}"

    with st.container(border=True, key=f"post_card_{post['id']}"):
        if is_own_post:
            col1, col2, col3 = st.columns([1, 7, 2], vertical_alignment="center")
        else:
            col1, col2 = st.columns([1, 8], vertical_alignment="center")
        with col1:
            avatar = f"https://ui-avatars.com/api/?name={author.replace(' ', '+')}&background={avatar_color(post['author_username'])}&color=fff&size=56"
            with st.container(key=f"post_avatar_{post['id']}"):
                st.image(avatar, width=56)
        with col2:
            st.markdown(
                f'<div class="post-author">{html.escape(author)} '
                f'<span class="verified-badge">✓ {html.escape(badge)}</span></div>'
                f'<div class="post-meta">{time_ago(post["created_at"])}</div>',
                unsafe_allow_html=True
            )
        if is_own_post:
            with col3:
                ec1, ec2 = st.columns(2)
                with ec1:
                    if st.button("✏️", key=f"edit_post_{post['id']}", use_container_width=True):
                        st.session_state[editing_post_key] = not st.session_state.get(editing_post_key, False)
                with ec2:
                    if st.button("🗑️", key=f"delete_post_{post['id']}", use_container_width=True):
                        st.session_state[confirm_delete_post_key] = True

        if st.session_state.get(confirm_delete_post_key, False):
            st.warning("Delete this post? This cannot be undone.")
            dc1, dc2 = st.columns(2)
            with dc1:
                if st.button("Yes, delete", key=f"confirm_delete_post_yes_{post['id']}",
                             use_container_width=True, type="primary"):
                    delete_feed_post(post["id"])
                    st.session_state.pop(confirm_delete_post_key, None)
                    st.rerun()
            with dc2:
                if st.button("Cancel", key=f"confirm_delete_post_no_{post['id']}", use_container_width=True):
                    st.session_state[confirm_delete_post_key] = False
                    st.rerun()

        if st.session_state.get(editing_post_key, False):
            with st.form(key=f"edit_post_form_{post['id']}"):
                new_message = st.text_area(
                    "Edit message", value=post["message"], label_visibility="collapsed",
                )
                sc1, sc2 = st.columns(2)
                save_clicked = sc1.form_submit_button("Save", use_container_width=True, type="primary")
                cancel_clicked = sc2.form_submit_button("Cancel", use_container_width=True)
            if save_clicked and new_message.strip():
                update_feed_post(post["id"], new_message.strip())
                st.session_state[editing_post_key] = False
                st.rerun()
            if cancel_clicked:
                st.session_state[editing_post_key] = False
                st.rerun()
        else:
            st.markdown(f'<div class="post-body">{html.escape(post["message"])}</div>', unsafe_allow_html=True)

        if post["images"]:
            cols = st.columns(min(3, len(post["images"])))
            for idx, img in enumerate(post["images"]):
                with cols[idx % len(cols)]:
                    result = get_feed_post_image_bytes(img["id"])
                    if result:
                        file_bytes, display_filename = result
                        mime = mimetypes.guess_type(display_filename)[0] or "image/jpeg"
                        b64 = base64.b64encode(file_bytes).decode()
                        st.markdown(
                            f'<div style="height:220px; border-radius:10px; overflow:hidden; '
                            f'border:1px solid {LINE}; margin-bottom:0.5rem;">'
                            f'<img src="data:{mime};base64,{b64}" '
                            f'style="width:100%; height:220px; object-fit:cover; display:block;">'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

        st.divider()

        liked = post["liked_by_viewer"]
        like_label = f"👍 Liked ({post['like_count']})" if liked else f"👍 Like ({post['like_count']})"
        comment_label = f"💬 Comment ({post['comment_count']})"

        r1, r2, r3, r4 = st.columns(4)
        with r1:
            if st.button(like_label, key=f"like_{post['id']}", use_container_width=True,
                         type="primary" if liked else "secondary"):
                toggle_feed_post_like(post["id"], me)
                st.rerun()
        with r2:
            comments_open = st.session_state.get(f"show_comments_{post['id']}", False)
            if st.button(comment_label, key=f"comment_{post['id']}", use_container_width=True,
                         type="primary" if comments_open else "secondary"):
                show_key = f"show_comments_{post['id']}"
                st.session_state[show_key] = not st.session_state.get(show_key, False)
        with r3:
            st.button("🔄 Share", key=f"share_{post['id']}", use_container_width=True)
        with r4:
            st.button("⭐ Save", key=f"save_{post['id']}", use_container_width=True)

        if st.session_state.get(f"show_comments_{post['id']}", False):
            for c in list_feed_post_comments(post["id"]):
                commenter = f"{c.get('other_names') or ''} {c.get('surname') or ''}".strip() or c["username"]
                commenter_avatar = f"https://ui-avatars.com/api/?name={commenter.replace(' ', '+')}&background={avatar_color(c['username'])}&color=fff&size=28"
                is_own_comment = c["username"] == me
                editing_comment_key = f"editing_comment_{c['id']}"

                if st.session_state.get(editing_comment_key, False):
                    with st.form(key=f"edit_comment_form_{c['id']}"):
                        ecc1, ecc2, ecc3 = st.columns([6, 1, 1])
                        new_comment_text = ecc1.text_input(
                            "Edit comment", value=c["comment"], label_visibility="collapsed",
                        )
                        save_c = ecc2.form_submit_button("Save", use_container_width=True)
                        cancel_c = ecc3.form_submit_button("Cancel", use_container_width=True)
                    if save_c and new_comment_text.strip():
                        update_feed_post_comment(c["id"], new_comment_text.strip())
                        st.session_state[editing_comment_key] = False
                        st.rerun()
                    if cancel_c:
                        st.session_state[editing_comment_key] = False
                        st.rerun()
                    continue

                if is_own_comment:
                    ccol1, ccol2, ccol3 = st.columns([8, 1, 1], vertical_alignment="center")
                else:
                    ccol1 = st.container()

                with ccol1:
                    st.markdown(
                        f'<div style="display:flex; align-items:flex-start; gap:0.55rem; margin:0.5rem 0;">'
                        f'<img src="{commenter_avatar}" width="28" height="28" '
                        f'style="border-radius:50%; border:2px solid {LINE}; flex-shrink:0;">'
                        f'<div style="padding:0.5rem 0.75rem; background:{PAPER}; '
                        f'border-radius:8px; font-size:0.88rem; flex:1;">'
                        f'<b>{html.escape(commenter)}</b> — {html.escape(c["comment"])}'
                        f'</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                if is_own_comment:
                    with ccol2:
                        if st.button("✏️", key=f"edit_comment_{c['id']}", use_container_width=True):
                            st.session_state[editing_comment_key] = True
                            st.rerun()
                    with ccol3:
                        if st.button("🗑️", key=f"delete_comment_{c['id']}", use_container_width=True):
                            delete_feed_post_comment(c["id"])
                            st.rerun()
            with st.form(key=f"comment_form_{post['id']}", clear_on_submit=True):
                fcol1, fcol2 = st.columns([5, 1])
                comment_text = fcol1.text_input(
                    "Comment", placeholder="Write a comment…", label_visibility="collapsed",
                )
                st.markdown("""
                <style>
                div[data-testid="stFormSubmitButton"] button {
                    color: #fff;
                }
                </style>
            """, unsafe_allow_html=True)
                comment_submitted = fcol2.form_submit_button("Send", use_container_width=True)
                if comment_submitted and comment_text.strip():
                    add_feed_post_comment(post["id"], me, comment_text.strip())
                    st.rerun()

if not posts:
    st.markdown(
        '<div style="text-align:center; color:#9ca3af; padding:2rem 0;">'
        'No activity yet. Be the first to post an update.</div>',
        unsafe_allow_html=True
    )

# ====================== SIDEBAR ======================
with st.sidebar:
    st.markdown('<div class="sidebar-title">Filters</div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-caption">Narrow the feed to what matters to you</div>', unsafe_allow_html=True)
    st.multiselect("Department", ["All", "Field Operations", "Tech", "Training"], default=["All"])
    st.slider("Last", 1, 30, 7, format="%d days")