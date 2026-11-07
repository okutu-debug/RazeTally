"""A file uploader that opens the phone's camera app directly.

Streamlit's own st.camera_input shows an in-page preview and grabs a frame
from it — low resolution, fixed focus, no flash — which is too rough for
reading handwritten vote counts off an election form. Instead this renders a
normal st.file_uploader and marks its <input type="file"> with
capture="environment", which tells mobile browsers to open the native camera
(back lens, full resolution, autofocus) instead of the file picker. Desktop
browsers ignore the attribute and show the normal file picker.

st.file_uploader has no option for that attribute, so it's set from a tiny
script that reaches into the parent page — the same window.parent approach
used in theme.py and pages/collaboration/calls.py.
"""

import streamlit as st
import streamlit.components.v1 as components

PHOTO_TYPES = ["jpg", "jpeg", "png", "webp"]


def camera_uploader(label: str, key: str, help: str | None = None):
    """st.file_uploader that opens the rear camera on phones. Returns the
    UploadedFile (or None), exactly like st.file_uploader."""
    photo = st.file_uploader(label, type=PHOTO_TYPES, key=key, help=help)
    components.html(
        f"""
        <script>
        const w = window.parent;
        const sel = 'div[class*="st-key-{key}"] input[type="file"]';
        const patch = () => w.document.querySelectorAll(sel).forEach((el) => {{
            if (el.getAttribute("capture") !== "environment") {{
                el.setAttribute("capture", "environment");
                el.setAttribute("accept", "image/*");
            }}
        }});
        patch();
        // Streamlit re-renders the uploader (e.g. after a photo is taken or
        // removed), which recreates the <input>; re-apply on every DOM change.
        // Replace any observer left by a previous run of this script, since
        // its iframe — and the function it calls — is gone after a rerun.
        const slot = "__razeCameraObs_{key}";
        if (w[slot]) w[slot].disconnect();
        w[slot] = new w.MutationObserver(patch);
        w[slot].observe(w.document.body, {{ childList: true, subtree: true }});
        </script>
        """,
        height=0,
    )
    return photo
