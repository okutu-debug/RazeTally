import streamlit as st
import streamlit.components.v1 as components


def clear_query_params_url():
    """Force the browser's address bar to drop query params after
    st.query_params.clear(). Without this, the address bar keeps showing
    the old "?action=id" string — so clicking the exact same row-action
    link twice in a row (e.g. toggling a checkbox back off) is a no-op,
    since browsers don't re-navigate to the URL already shown."""
    components.html(
        "<script>"
        "window.parent.history.replaceState(null, '', window.parent.location.pathname);"
        "</script>",
        height=0,
    )


def apply_theme():
    """Applies the shared page background + white card styling across all pages."""
    st.markdown(
        """
        <style>
        /* Page background */
        .stApp {
            background-color: #ebedee;
        }

        /* Card containers (targeted via st.container(key=...)) */
        div[class*="st-key-card"] {
            background-color: #ffffff;
            border-radius: 14px;
            padding: 1.5rem;
            margin-bottom: 1.25rem;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
            border: 1px solid rgba(0, 0, 0, 0.04);
        }

        /* Metric cards */
        div[data-testid="stMetric"] {
            background-color: #ffffff;
            border-radius: 12px;
            padding: 1rem 1rem 0.75rem 1rem;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
            border: 1px solid rgba(0, 0, 0, 0.04);
        }

        /* Tabs */
        div[data-testid="stTabs"] {
            background-color: #ffffff;
            border-radius: 14px;
            padding: 1.25rem;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
            border: 1px solid rgba(0, 0, 0, 0.04);
        }

        .block-container {
            padding-top: 2rem;
        }

        /* Primary buttons */
        button[kind="primary"], button[kind="primaryFormSubmit"] {
            background: linear-gradient(160deg, #152744 0%, #1e4a85 55%, #2471a3 100%) !important;
            border: none !important;
            color: white !important;
        }
        button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {
            background: linear-gradient(160deg, #0f1e33 0%, #183d70 55%, #1d608a 100%) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )