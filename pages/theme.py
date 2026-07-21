import streamlit as st


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

        .block-container {
            padding-top: 2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )